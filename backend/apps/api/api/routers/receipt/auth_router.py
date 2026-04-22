"""Receipt v0 — hook-token auth router.

Endpoints:
  - POST   /auth/hook-token              mint a new rcpt_* token (unauth in v0)
  - GET    /auth/hook-tokens             list caller's tokens (bearer required)
  - DELETE /auth/hook-token/{id}         soft-revoke caller's token
  - POST   /auth/logout                  revoke bearer (wave-14 C3)
  - POST   /auth/refresh                 rotate refresh token (wave-48 C1)
  - POST   /auth/password-reset-request  issue a reset token (wave-14 C4, flag-gated)
  - POST   /auth/password-reset-confirm  consume a reset token (wave-14 C4, flag-gated)

Contract: vault/BACKEND-API-V0.md §4.6–§4.8, vault/AUTH-V0.md §1(a),
vault/AUTH-HARDENING-V1.md §1/§3/§4/§6.
Token storage: raw token returned once on mint, sha256 hash persisted.
"""
from __future__ import annotations

import hashlib
import logging
import os
import secrets
import uuid
from datetime import UTC, timedelta

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import update as sa_update
from sqlmodel import Session as DBSession
from sqlmodel import select

import json

from apps.api.api.dependencies.auth import SESSION_COOKIE_NAME

from .auth_sessions_model import AuthSession
from .db import get_session
from .deps import _naive_utc_now, require_current_user
from .email.welcome import send_welcome_email
from .models import (
    CliToken,
    DeviceAuthorization,
    DeviceCodeApproveIn,
    DeviceCodePollIn,
    DeviceCodePollOut,
    DeviceCodeStartIn,
    DeviceCodeStartOut,
    HookTokenListItem,
    HookTokenMintIn,
    HookTokenMintOut,
    PasswordResetConfirmIn,
    PasswordResetConfirmOut,
    PasswordResetRequestIn,
    PasswordResetRequestOut,
    PasswordResetToken,
    ServiceTokenCreateIn,
    ServiceTokenCreateOut,
    ServiceTokenListItem,
    User,
    WelcomeEmailOut,
)

# Backward-compat alias — auth_router still references `HookToken` in many
# places (mint + list + revoke). Keep both names resolving to the same model
# until Phase B cleanup pass.
HookToken = CliToken

# Idempotency window for /auth/welcome-email — second call inside this
# window after a successful send is a no-op (returns sent=False with the
# original timestamp). Matches the wave-54 task brief acceptance criteria.
_WELCOME_EMAIL_DEDUPE_WINDOW = timedelta(minutes=5)

_TOKEN_PREFIX = "rcpt_"           # legacy prefix — still accepted on read
_USER_TOKEN_PREFIX = "rcpt_u_"    # Phase B: new user-scoped tokens
_SERVICE_TOKEN_PREFIX = "rcpt_s_" # Phase B: new org/service tokens
_BEARER_PREFIX = "Bearer "
_RESET_TOKEN_PREFIX = "rcpt_reset_"
_RESET_TOKEN_TTL = timedelta(hours=1)

# Device-code pairing (receipt init) — RFC 8628 inspired.
_DEVICE_CODE_TTL = timedelta(minutes=10)
_DEVICE_POLL_INTERVAL = 2  # seconds
_USER_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no O/0/I/1 ambiguity


def _gen_user_code() -> str:
    """Generate a human-typeable code like 'ABCD-EFGH' from an unambiguous
    alphabet (no 0/O, 1/I). ~32^8 = 10^12 combinations — the short TTL +
    one-shot approval makes brute-force infeasible."""
    raw = "".join(secrets.choice(_USER_CODE_ALPHABET) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"

# AUTH-HARDENING-V1 §2 — split access/refresh lifetimes.
_ACCESS_TTL = timedelta(minutes=15)
_REFRESH_TTL = timedelta(days=30)
_JWT_ALGO = "HS256"
_REFRESH_COOKIE = "refresh_token"
_DEV_JWT_SECRET = "dev-only-unsafe-change-me"

_logger = logging.getLogger(__name__)

# Warn once at import when the JWT secret is unset — tests and local dev fall
# back to a known-unsafe constant. Prod MUST set AUTH_JWT_SECRET.
if not os.environ.get("AUTH_JWT_SECRET"):
    _logger.warning(
        "AUTH_JWT_SECRET unset — access tokens will be signed with the "
        "dev-only fallback secret. Do NOT deploy this way."
    )


def _jwt_secret() -> str:
    return os.environ.get("AUTH_JWT_SECRET") or _DEV_JWT_SECRET


def _hash_refresh(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _epoch(dt) -> int:
    """Convert a naive-UTC datetime to an integer epoch second."""
    return int(dt.replace(tzinfo=UTC).timestamp())


# Future-complete email body. Delivery is deferred (wave-14 C4 ships plumbing
# only); wiring Resend/Supabase is tracked in vault/audits/auth-password-reset-design.md.
PASSWORD_RESET_EMAIL_TEMPLATE = """\
Subject: Reset your Receipt password

Hi,

We received a request to reset the password for the Receipt account
tied to this email address. If you didn't ask for this, you can ignore
this message.

To set a new password, open this link within the next hour:

    {reset_link}

The link can be used once. After that, request a new one if you still
need to reset.

— Receipt
"""


def _password_reset_enabled() -> bool:
    """Feature flag for wave-14 C4 reset plumbing.

    Env-driven (mirrors the `RATELIMIT_ENABLED` pattern in
    `api/core/ratelimit.py`), default false. When false, both reset
    endpoints 404 so the route surface is indistinguishable from an
    unknown path (no information leak about the feature's existence).
    """
    v = os.environ.get("AUTH_PASSWORD_RESET_ENABLED", "").strip().lower()
    return v in ("1", "true", "yes", "on")


class AuthRouter:
    """Hook-token lifecycle (mint / list / revoke)."""

    def __init__(self) -> None:
        self.router = APIRouter(prefix="/auth", tags=["receipt:auth"])
        self._setup_routes()

    def get_router(self) -> APIRouter:
        return self.router

    def _setup_routes(self) -> None:
        self.router.post(
            "/hook-token",
            response_model=HookTokenMintOut,
            status_code=status.HTTP_201_CREATED,
        )(self.mint_token)
        self.router.get(
            "/hook-tokens",
            response_model=list[HookTokenListItem],
        )(self.list_tokens)
        self.router.delete(
            "/hook-token/{token_id}",
            status_code=status.HTTP_204_NO_CONTENT,
            response_model=None,
        )(self.revoke_token)
        self.router.post(
            "/device-code",
            response_model=DeviceCodeStartOut,
            status_code=status.HTTP_201_CREATED,
        )(self.device_code_start)
        self.router.post(
            "/device-code/poll",
            response_model=DeviceCodePollOut,
        )(self.device_code_poll)
        self.router.post(
            "/device-code/approve",
            status_code=status.HTTP_204_NO_CONTENT,
            response_model=None,
        )(self.device_code_approve)
        self.router.post(
            "/service-token",
            response_model=ServiceTokenCreateOut,
            status_code=status.HTTP_201_CREATED,
        )(self.create_service_token)
        self.router.get(
            "/service-tokens",
            response_model=list[ServiceTokenListItem],
        )(self.list_service_tokens)
        self.router.delete(
            "/service-token/{token_id}",
            status_code=status.HTTP_204_NO_CONTENT,
            response_model=None,
        )(self.revoke_service_token)
        self.router.post(
            "/logout",
            status_code=status.HTTP_204_NO_CONTENT,
            response_model=None,
        )(self.logout)
        self.router.post(
            "/refresh",
            response_model=None,
        )(self.refresh)
        self.router.post(
            "/password-reset-request",
            response_model=PasswordResetRequestOut,
            status_code=status.HTTP_202_ACCEPTED,
        )(self.password_reset_request)
        self.router.post(
            "/password-reset-confirm",
            response_model=PasswordResetConfirmOut,
        )(self.password_reset_confirm)
        self.router.post(
            "/welcome-email",
            response_model=WelcomeEmailOut,
        )(self.welcome_email)

    def mint_token(
        self,
        body: HookTokenMintIn,
        db: DBSession = Depends(get_session),
        current_user: str = Depends(require_current_user),
    ) -> HookTokenMintOut:
        """Create a new hook-token for the authenticated caller. Raw value
        is returned **once**; only the sha256 hash is persisted.

        v1 hardening: the `user` in `body` is IGNORED. Identity is taken
        from the session cookie (Supabase JWT) or bearer. Previously this
        endpoint was unauth and trusted body.user — see wave-XX CVE note.
        """
        raw = _USER_TOKEN_PREFIX + secrets.token_urlsafe(24)
        token_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        row = CliToken(
            id=uuid.uuid4().hex,
            user=current_user,
            token_hash=token_hash,
            token_type="user",
            minted_by_user_id=current_user,
            label=body.label,
            created_at=_naive_utc_now(),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return HookTokenMintOut(token=raw, user_id=row.id, user=row.user)

    # ---------- Device-code flow (receipt init) ----------

    def device_code_start(
        self,
        body: DeviceCodeStartIn,
        request: Request,
        db: DBSession = Depends(get_session),
    ) -> DeviceCodeStartOut:
        """CLI entry-point — unauth. Mints a pending device_code / user_code
        pair, TTL 10min. The CLI polls `/device-code/poll` until a user
        approves the pairing from an authenticated browser.
        """
        device_code = secrets.token_urlsafe(32)
        device_code_hash = hashlib.sha256(device_code.encode("utf-8")).hexdigest()

        # Retry on user_code collision — 32^8 space, collisions realistically
        # only happen with concurrent issuance + active rows.
        user_code = ""
        for _ in range(5):
            candidate = _gen_user_code()
            existing = db.exec(
                select(DeviceAuthorization).where(
                    DeviceAuthorization.user_code == candidate,
                    DeviceAuthorization.status == "pending",
                )
            ).first()
            if existing is None:
                user_code = candidate
                break
        if not user_code:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="could not allocate a free user_code — retry",
            )

        now = _naive_utc_now()
        row = DeviceAuthorization(
            id=uuid.uuid4().hex,
            device_code_hash=device_code_hash,
            user_code=user_code,
            status="pending",
            label=body.label,
            created_at=now,
            expires_at=now + _DEVICE_CODE_TTL,
        )
        db.add(row)
        db.commit()

        origin = os.environ.get("FRONTEND_ORIGIN", "").rstrip("/") or str(
            request.base_url
        ).rstrip("/")
        verification_uri = f"{origin}/cli/pair"
        return DeviceCodeStartOut(
            device_code=device_code,
            user_code=user_code,
            verification_uri=verification_uri,
            verification_uri_complete=f"{verification_uri}?code={user_code}",
            expires_in=int(_DEVICE_CODE_TTL.total_seconds()),
            interval=_DEVICE_POLL_INTERVAL,
        )

    def device_code_poll(
        self,
        body: DeviceCodePollIn,
        db: DBSession = Depends(get_session),
    ) -> DeviceCodePollOut:
        """CLI poll — unauth. Returns the minted hook-token the first time
        an approved row is seen, then transitions it to `consumed`.
        """
        device_code_hash = hashlib.sha256(body.device_code.encode("utf-8")).hexdigest()
        row = db.exec(
            select(DeviceAuthorization).where(
                DeviceAuthorization.device_code_hash == device_code_hash,
            )
        ).first()
        if row is None:
            # Don't leak whether the code ever existed — report expired.
            return DeviceCodePollOut(status="expired")

        now = _naive_utc_now()
        row.last_polled_at = now

        if row.expires_at < now and row.status == "pending":
            row.status = "expired"
            db.add(row)
            db.commit()
            return DeviceCodePollOut(status="expired")

        if row.status == "pending":
            db.add(row)
            db.commit()
            return DeviceCodePollOut(status="pending")

        if row.status == "approved":
            # Read-once: reveal the raw token, transition to consumed.
            # The raw token was returned by /approve; we persist only a
            # short-lived opaque blob alongside the row — but to keep the
            # design stateless for the token itself, /approve stores the
            # raw token on the row in `token_hash` column transiently via
            # a separate one-shot field. Simplest: re-mint here on first
            # poll-after-approve, binding to the captured user.
            #
            # Implementation: approve() saved the raw token into the
            # in-memory consumable slot via a separate cache; since we have
            # no Redis, we instead mint ON approve and stash the raw token
            # on the row via a new column. To avoid a schema migration we
            # use a convention: when status='approved', the `token_hash`
            # column holds the *raw* token prefixed with '!' (never hashed
            # that way elsewhere) — on first read we hash + overwrite.
            raw = row.token_hash or ""
            if raw.startswith("!"):
                raw_token = raw[1:]
                row.token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
                row.status = "consumed"
                row.consumed_at = now
                db.add(row)
                db.commit()
                return DeviceCodePollOut(status="approved", token=raw_token)
            # Already consumed by an earlier poll — treat as denied so the
            # CLI stops polling (it already got its token once).
            return DeviceCodePollOut(status="denied")

        # consumed / denied / expired
        return DeviceCodePollOut(status=row.status)

    def device_code_approve(
        self,
        body: DeviceCodeApproveIn,
        db: DBSession = Depends(get_session),
        current_user: str = Depends(require_current_user),
    ) -> JSONResponse:
        """Browser endpoint — authed (cookie + CSRF). User types `user_code`,
        confirms, and we bind the pending row to their identity + mint the
        hook-token. Token raw value is NOT returned here — the CLI picks it
        up on its next poll.
        """
        row = db.exec(
            select(DeviceAuthorization).where(
                DeviceAuthorization.user_code == body.user_code.strip().upper(),
            )
        ).first()
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="unknown pairing code",
            )

        now = _naive_utc_now()
        if row.status != "pending":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"code is {row.status}",
            )
        if row.expires_at < now:
            row.status = "expired"
            db.add(row)
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="code has expired — re-run `receipt init`",
            )

        raw_token = _USER_TOKEN_PREFIX + secrets.token_urlsafe(24)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        hook_row = CliToken(
            id=uuid.uuid4().hex,
            user=current_user,
            token_hash=token_hash,
            token_type="user",
            minted_by_user_id=current_user,
            label=row.label or "cli-pair",
            created_at=now,
        )
        db.add(hook_row)

        # Stash raw on the pairing row with a '!' sentinel so the CLI poll
        # can read it once, then hash+overwrite. See device_code_poll comment.
        # (Event scoping to orgs is resolved server-side via route_rules at
        # ingest time — the token itself has no scope.)
        row.status = "approved"
        row.user = current_user
        row.token_hash = "!" + raw_token
        row.approved_at = now
        db.add(row)
        db.commit()

        _logger.info(
            "device_code.approved user=%s label=%s user_code=%s",
            current_user, row.label, body.user_code,
        )
        return JSONResponse(status_code=status.HTTP_204_NO_CONTENT, content=None)

    def list_tokens(
        self,
        db: DBSession = Depends(get_session),
        current_user: str = Depends(require_current_user),
    ) -> list[HookTokenListItem]:
        """List the caller's USER tokens (not service tokens — those live
        under /auth/service-tokens, scoped to an org and admin-managed)."""
        rows = db.exec(
            select(CliToken)
            .where(
                CliToken.user == current_user,
                CliToken.token_type != "service",
            )
            .order_by(CliToken.created_at.desc())
        ).all()
        return [HookTokenListItem.model_validate(r.model_dump()) for r in rows]

    def revoke_token(
        self,
        token_id: str,
        db: DBSession = Depends(get_session),
        current_user: str = Depends(require_current_user),
    ) -> None:
        """Soft-revoke: set `revoked_at = now()`.

        Per AUTH-V0 §1(a): 401 when the token belongs to a different user
        (not 404 — spec is explicit), 404 when token_id is unknown,
        idempotent 204 when already revoked.
        """
        row = db.get(HookToken, token_id)
        if row is None:
            raise HTTPException(status_code=404, detail="token not found")
        if row.user != current_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="token does not belong to caller",
            )
        if row.revoked_at is None:
            row.revoked_at = _naive_utc_now()
            db.add(row)
            db.commit()
        return None

    # ---------- Service tokens (Phase B — headless/CI/fleet) ----------

    def _require_dashboard_jwt(self, request: Request) -> str:
        """Admin endpoints require a dashboard session (Supabase JWT via cookie).
        CLI bearer tokens are rejected — you manage tokens from the UI, not
        from another CLI."""
        jwt = request.cookies.get(SESSION_COOKIE_NAME)
        if not jwt:
            raise HTTPException(
                status_code=401,
                detail="Sign in to the dashboard to manage service tokens",
            )
        return jwt

    def _require_org_admin(self, request: Request, org_id: str) -> str:
        """Raise 403 unless the caller (via Supabase JWT cookie) is owner or
        admin of the org. Returns the caller's user email for audit trail."""
        jwt = self._require_dashboard_jwt(request)
        from libs.supabase.supabase import SupabaseManager
        supabase = SupabaseManager(access_token=jwt)
        try:
            user_resp = supabase.client.auth.get_user(jwt)
        except Exception as exc:
            raise HTTPException(status_code=401, detail="Invalid session") from exc
        if not user_resp or not user_resp.user:
            raise HTTPException(status_code=401, detail="Invalid session")
        caller_id = user_resp.user.id
        caller_email = user_resp.user.email or caller_id

        try:
            memberships = supabase.query_records(
                "organization_members",
                filters={"org_id": org_id, "user_id": caller_id},
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail="membership lookup failed") from exc
        if not memberships:
            raise HTTPException(
                status_code=403,
                detail="You are not a member of this organization",
            )
        role = memberships[0].get("role")
        if role not in ("owner", "admin"):
            raise HTTPException(
                status_code=403,
                detail="Owner or admin role required to manage service tokens",
            )
        return caller_email

    def _org_default_workspace_id(self, org_id: str) -> str:
        """Resolve the 'Default' workspace id of an org for service-token
        backward-compat: existing API contract accepts `org_id` but new DB
        column is `workspace_id`. We look up the default workspace row via
        Supabase PostgREST (RLS will enforce the caller's membership)."""
        import httpx
        supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
        anon = os.environ.get("SUPABASE_ANON_KEY", "")
        resp = httpx.get(
            f"{supabase_url}/rest/v1/workspaces",
            headers={"apikey": anon, "Authorization": f"Bearer {anon}"},
            params={"select": "id", "org_id": f"eq.{org_id}", "slug": "eq.default", "deleted_at": "is.null"},
            timeout=5.0,
        )
        resp.raise_for_status()
        rows = resp.json() or []
        if not rows:
            raise HTTPException(status_code=404, detail="organization has no default workspace")
        return rows[0]["id"]

    def create_service_token(
        self,
        body: ServiceTokenCreateIn,
        request: Request,
        db: DBSession = Depends(get_session),
    ) -> ServiceTokenCreateOut:
        """Mint a long-lived token bound to an organization's default workspace.
        Admin-only. Raw token returned **once**. Phase W7 will refactor this
        to take a `workspace_id` directly.
        """
        caller_email = self._require_org_admin(request, body.org_id)
        workspace_id = self._org_default_workspace_id(body.org_id)

        raw = _SERVICE_TOKEN_PREFIX + secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        scopes_json = json.dumps(body.scopes or ["events:write"])
        now = _naive_utc_now()
        row = CliToken(
            id=uuid.uuid4().hex,
            user=f"service:{body.org_id}",  # synthetic, not a real human
            token_hash=token_hash,
            token_type="service",
            workspace_id=workspace_id,
            minted_by_user_id=caller_email,
            label=body.label,
            scopes=scopes_json,
            created_at=now,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        _logger.info(
            "service_token.created org=%s ws=%s by=%s label=%s",
            body.org_id, workspace_id, caller_email, body.label,
        )
        return ServiceTokenCreateOut(
            token=raw,
            id=row.id,
            org_id=body.org_id,
            label=row.label or "",
            created_at=row.created_at,
        )

    def list_service_tokens(
        self,
        org_id: str,
        request: Request,
        db: DBSession = Depends(get_session),
    ) -> list[ServiceTokenListItem]:
        """List service tokens for an org (admin-only). Never leaks `token_hash`."""
        self._require_org_admin(request, org_id)
        workspace_id = self._org_default_workspace_id(org_id)
        rows = db.exec(
            select(CliToken)
            .where(CliToken.token_type == "service", CliToken.workspace_id == workspace_id)
            .order_by(CliToken.created_at.desc())
        ).all()
        items: list[ServiceTokenListItem] = []
        for r in rows:
            try:
                scopes = json.loads(r.scopes) if r.scopes else None
            except Exception:
                scopes = None
            items.append(ServiceTokenListItem(
                id=r.id,
                org_id=org_id,
                label=r.label,
                machine_hostname=r.machine_hostname,
                scopes=scopes,
                created_at=r.created_at,
                last_used_at=r.last_used_at,
                revoked_at=r.revoked_at,
                minted_by_user_id=r.minted_by_user_id,
            ))
        return items

    def revoke_service_token(
        self,
        token_id: str,
        request: Request,
        db: DBSession = Depends(get_session),
    ) -> None:
        row = db.get(CliToken, token_id)
        if row is None or row.token_type != "service" or not row.workspace_id:
            raise HTTPException(status_code=404, detail="service token not found")
        # Look up the org for this workspace so we can admin-check.
        import httpx
        supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
        anon = os.environ.get("SUPABASE_ANON_KEY", "")
        ws_resp = httpx.get(
            f"{supabase_url}/rest/v1/workspaces",
            headers={"apikey": anon, "Authorization": f"Bearer {anon}"},
            params={"select": "org_id,owner_user_id", "id": f"eq.{row.workspace_id}"},
            timeout=5.0,
        )
        ws_resp.raise_for_status()
        ws_rows = ws_resp.json() or []
        if not ws_rows:
            raise HTTPException(status_code=404, detail="workspace not found")
        org_id = ws_rows[0].get("org_id")
        if org_id:
            self._require_org_admin(request, org_id)
        # If the service token is scoped to a personal workspace (future Phase G),
        # we'd gate on ownership — not a current flow.
        if row.revoked_at is None:
            row.revoked_at = _naive_utc_now()
            db.add(row)
            db.commit()
        return None

    def logout(
        self,
        authorization: str | None = Header(default=None),
        db: DBSession = Depends(get_session),
    ) -> None:
        """Revoke the bearer in the Authorization header.

        Stamps `revoked_at` on the matching `hook_tokens` row. 401 when the
        header is missing, malformed, or the token is unknown / already
        revoked — matches AUTH-V0 posture and prevents replay after logout.
        """
        if authorization is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="authorization required",
            )
        if not authorization.startswith(_BEARER_PREFIX):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid authorization scheme",
            )
        token = authorization[len(_BEARER_PREFIX):].strip()
        if not token.startswith(_TOKEN_PREFIX):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid token format",
            )
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        row = db.exec(
            select(HookToken).where(
                HookToken.token_hash == token_hash,
                HookToken.revoked_at.is_(None),  # type: ignore[union-attr]
            )
        ).first()
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid or revoked token",
            )
        row.revoked_at = _naive_utc_now()
        db.add(row)
        db.commit()
        return None

    async def refresh(
        self,
        request: Request,
        db: DBSession = Depends(get_session),
    ):
        """Rotate a refresh token (AUTH-HARDENING-V1 §3/§4).

        Cookie first, JSON body (`{"refresh_token": ...}`) second.
        - unknown hash             -> 401 `{"error": "auth_unknown"}`
        - expired-not-revoked      -> 401 `{"error": "auth_expired"}` (family untouched)
        - revoked (REUSE)          -> 401 `{"error": "auth_revoked"}` + revoke every
                                      live sibling in the family + WARN log
        - valid                    -> 200 with new access JWT + new refresh token,
                                      refresh cookie rotated, old row stamped
                                      `last_used_at` then `revoked_at`
        """
        raw = request.cookies.get(_REFRESH_COOKIE)
        if not raw:
            try:
                body = await request.json()
            except Exception:
                body = None
            if isinstance(body, dict):
                val = body.get("refresh_token")
                if isinstance(val, str) and val:
                    raw = val

        if not raw:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"error": "auth_unknown"},
            )

        presented_hash = _hash_refresh(raw)
        row = db.exec(
            select(AuthSession).where(
                AuthSession.refresh_token_hash == presented_hash
            )
        ).first()
        if row is None:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"error": "auth_unknown"},
            )

        ip = request.client.host if request.client else None
        ua = (request.headers.get("user-agent") or "")[:256]

        # §4 reuse detection — presented a row that was already consumed.
        if row.revoked_at is not None:
            family_id = row.family_id
            user_email = row.user_email
            now = _naive_utc_now()
            db.execute(
                sa_update(AuthSession)
                .where(AuthSession.family_id == family_id)
                .where(AuthSession.revoked_at.is_(None))
                .values(revoked_at=now)
            )
            db.commit()
            _logger.warning(
                "event=refresh_family_reuse family_id=%s user_email=%s ip=%s ua=%s",
                family_id, user_email, ip, ua,
            )
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"error": "auth_revoked"},
            )

        now = _naive_utc_now()
        if row.expires_at <= now:
            # Stale cookie — do NOT revoke the family (§4 edge case).
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"error": "auth_expired"},
            )

        # §3 rotation-on-use: mint new token + row, stamp old row, single txn.
        new_raw = secrets.token_urlsafe(32)
        new_hash = _hash_refresh(new_raw)
        new_id = uuid.uuid4().hex
        new_row = AuthSession(
            id=new_id,
            user_email=row.user_email,
            refresh_token_hash=new_hash,
            issued_at=now,
            expires_at=now + _REFRESH_TTL,
            family_id=row.family_id,
            parent_token_hash=presented_hash,
            ip=ip,
            user_agent=ua,
        )
        row.last_used_at = now
        row.revoked_at = now
        db.add(row)
        db.add(new_row)
        db.commit()

        access_exp = now + _ACCESS_TTL
        access_token = jwt.encode(
            {
                "sub": row.user_email,
                "sid": new_id,
                "iat": _epoch(now),
                "exp": _epoch(access_exp),
            },
            _jwt_secret(),
            algorithm=_JWT_ALGO,
        )

        response = JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "access_token": access_token,
                "refresh_token": new_raw,
                "expires_in": int(_ACCESS_TTL.total_seconds()),
                "token_type": "bearer",
            },
        )
        response.set_cookie(
            key=_REFRESH_COOKIE,
            value=new_raw,
            max_age=int(_REFRESH_TTL.total_seconds()),
            httponly=True,
            samesite="lax",
            secure=False,  # dev — TLS termination handles secure=True in prod
        )
        return response

    def password_reset_request(
        self,
        body: PasswordResetRequestIn,
        db: DBSession = Depends(get_session),
    ) -> PasswordResetRequestOut:
        """Issue a single-use, 1-hour reset token for `body.email`.

        Flag-gated: when `AUTH_PASSWORD_RESET_ENABLED` is unset/false, 404 so
        the endpoint is indistinguishable from an unknown path. When on, the
        raw token is logged to stderr with a `[DEV-ONLY …]` prefix (email
        delivery is out of scope for wave-14 — see the design note at
        vault/audits/auth-password-reset-design.md). Only the sha256 hash of
        the token is persisted.
        """
        if not _password_reset_enabled():
            raise HTTPException(status_code=404, detail="Not Found")

        raw = _RESET_TOKEN_PREFIX + secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        now = _naive_utc_now()
        row = PasswordResetToken(
            id=uuid.uuid4().hex,
            user_email=body.email,
            token_hash=token_hash,
            issued_at=now,
            expires_at=now + _RESET_TOKEN_TTL,
        )
        db.add(row)
        db.commit()

        # Dev-only surface so local testing works without an SMTP pipeline.
        # Replace with real delivery once the follow-up ticket lands (see
        # vault/audits/auth-password-reset-design.md §Follow-up).
        print(
            f"[DEV-ONLY password-reset link] email={body.email} token={raw}",
            flush=True,
        )
        return PasswordResetRequestOut(sent=True)

    def welcome_email(
        self,
        db: DBSession = Depends(get_session),
        current_user: str = Depends(require_current_user),
    ) -> WelcomeEmailOut:
        """Fire the welcome / install-snippet email for the caller.

        Idempotent: the second call within `_WELCOME_EMAIL_DEDUPE_WINDOW`
        returns `sent=False` with the original `welcome_email_sent_at` and
        does NOT re-send. Lazily upserts the `users` row keyed by email.

        The frontend calls this once after first sign-in (Supabase magic-link
        provides email → bearer; bearer scopes the call to the caller, so no
        cross-user concern). Stub vs SMTP delivery is decided inside
        `send_welcome_email` based on `SMTP_HOST` env.
        """
        now = _naive_utc_now()
        row = db.get(User, current_user)
        if (
            row is not None
            and row.welcome_email_sent_at is not None
            and (now - row.welcome_email_sent_at) < _WELCOME_EMAIL_DEDUPE_WINDOW
        ):
            return WelcomeEmailOut(
                sent=False,
                user_email=current_user,
                welcome_email_sent_at=row.welcome_email_sent_at,
            )

        send_welcome_email(current_user)

        if row is None:
            row = User(email=current_user, welcome_email_sent_at=now)
        else:
            row.welcome_email_sent_at = now
        db.add(row)
        db.commit()
        return WelcomeEmailOut(
            sent=True,
            user_email=current_user,
            welcome_email_sent_at=now,
        )

    def password_reset_confirm(
        self,
        body: PasswordResetConfirmIn,
        db: DBSession = Depends(get_session),
    ) -> PasswordResetConfirmOut:
        """Consume a reset token and mark it used.

        Flag-gated identically to request. 401 on expired / already-used /
        unknown-hash. On success the token is stamped `used_at = now()` and
        we return a known-string body that flags the incomplete storage path
        (Receipt has no password column on users today — follow-up ticket).
        """
        if not _password_reset_enabled():
            raise HTTPException(status_code=404, detail="Not Found")

        token_hash = hashlib.sha256(body.token.encode("utf-8")).hexdigest()
        now = _naive_utc_now()
        row = db.exec(
            select(PasswordResetToken).where(
                PasswordResetToken.token_hash == token_hash,
            )
        ).first()
        if row is None or row.used_at is not None or row.expires_at < now:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid or expired reset token",
            )

        row.used_at = now
        db.add(row)
        db.commit()

        # TODO(wave-follow-up): once the user model grows a `password_hash`
        # column, hash `body.new_password` (argon2id — product-lead to confirm)
        # and persist here. Tracked in vault/audits/auth-password-reset-design.md.
        _logger.warning(
            "password-reset confirm accepted but password storage not yet "
            "implemented (user_email=%s)",
            row.user_email,
        )
        return PasswordResetConfirmOut(
            reset="accepted-but-password-storage-not-implemented",
        )
