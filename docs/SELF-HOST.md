# Self-hosting Yoru

Deploy Yoru inside your own infrastructure — your Supabase project, your
servers, your domain. You keep the data, your team signs in against your
identity system, no payloads leave your network. Nothing to buy; the AGPL
license is all you need.

> **Scope**: this guide covers the single-company self-host path (your own
> Supabase + one backend box + a static frontend). A bare-metal zero-
> dependency path — Postgres instead of Supabase, GoTrue instead of the
> Supabase auth API — lands in Phase G. If you need it today, reach out
> and we'll pair on it.

---

## What you get vs. the Cloud tier

| Feature | Cloud (yoru.sh) | Self-host |
| --- | --- | --- |
| Session capture + red flags + A–F scoring | ✓ | ✓ |
| Multi-agent support (Claude Code today, Cursor/Aider coming) | ✓ | ✓ |
| Workspaces + GitHub routing + route\_rules escape hatch | ✓ | ✓ |
| Trail export + webhook dispatch | ✓ | ✓ |
| Email templates (welcome / password-reset / invite / alert) | ✓ | ✓ |
| **Plan & billing logic** | Stripe gated | All users default to Org — everything unlocked |
| **Ops burden** | Zero (we run it) | You run the backend + Supabase + DNS |

Same source, same features. The only difference is who runs the infra.

---

## Prerequisites

- A **Supabase project** you control (Supabase Cloud or self-hosted Supabase).
  Free tier is fine to start; switch to Pro when you cross the free limits.
- A **server or Fly.io / Render / Railway app** for the FastAPI backend.
  ~512 MB RAM is enough for v0.
- A **static host** (Vercel, Netlify, Cloudflare Pages, nginx) for the
  React dashboard.
- An **SMTP provider** (Resend, Postmark, Mailgun, your corporate SMTP).
  Optional if you skip welcome / invite mails.
- A **domain** with DNS control (three subdomains — e.g. `yoru.acme.com`,
  `api.yoru.acme.com`, `app.yoru.acme.com` — or a single subdomain with
  sub-paths, your call).
- **Docker** on the backend box, and `psql` / Supabase CLI locally for the
  initial schema bootstrap.

---

## 1. Bootstrap the Supabase schema

The Yoru backend expects ~14 tables in `public` plus a handful of RPCs,
views, and RLS policies. Apply them to your empty Supabase project:

```bash
# One-shot: export Yoru Cloud's schema into a portable SQL file, then
# run it against your project. The dump contains public schema only —
# auth.* is already present in every Supabase project.

# Fastest path — use the Supabase CLI linked against your own project:
supabase link --project-ref <your-project-ref>
supabase db push   # if you cloned this repo, the migrations under
                   # backend/migrations/ will apply in order

# Or, if you prefer one-file: concatenate and run
cat backend/migrations/*.sql | psql "postgresql://postgres:<pwd>@<your-project>.supabase.co:5432/postgres"
```

The repo ships these migrations:

| File | Purpose |
| --- | --- |
| `organizations_schema.sql` | Multi-tenant orgs + membership + RLS |
| `user_groups_schema.sql` | Role-based access (admin / member / viewer) |
| `subscriptions_schema.sql` | Plans + features + user_grants overrides |
| `invitations_schema.sql` | Signed invite links |
| `notifications_schema.sql` | In-app notifications |
| `webhooks_schema.sql` | Outbound webhook subscriptions |
| `rate_limit_feature.sql` | Per-plan event rate limits |
| `performance_optimization_views.sql` | `user_subscription_details` view |
| `route_rules_schema.sql` | Workspace routing escape hatch |
| `welcome_email_sent_at.sql` | Email idempotency column |

After migrations, insert seed plans if your project doesn't already have them:

```sql
INSERT INTO public.plans (name, price, billing_period, is_active) VALUES
  ('Free', 0,  'monthly', true),
  ('Pro',  9,  'monthly', true),
  ('Team', 19, 'monthly', true),
  ('Org',  99, 'monthly', true)
ON CONFLICT (name) DO NOTHING;
```

### Default new signups to Org (self-host only)

On Cloud, new users land on Free and upgrade via Stripe. Self-hosters have
no billing, so we default everyone to Org. Add this trigger to your SB:

```sql
-- Replace the Cloud's default-Free trigger with a default-Org one.
CREATE OR REPLACE FUNCTION public._selfhost_default_org_subscription()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_plan_id uuid;
BEGIN
    SELECT id INTO v_plan_id FROM public.plans
     WHERE name = 'Org' AND is_active = true LIMIT 1;
    IF v_plan_id IS NOT NULL THEN
        INSERT INTO public.subscriptions (user_id, plan_id, status, start_date)
        VALUES (NEW.id, v_plan_id, 'active', NOW());
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS _ensure_personal_org_per_user ON auth.users;
CREATE TRIGGER _selfhost_default_org_on_signup
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public._selfhost_default_org_subscription();
```

Every user signing up will now land on Org active with all features unlocked.

---

## 2. Configure Supabase Auth

Cloud uses Supabase Auth for email/password + GitHub OAuth; you do the same.

**Email/password** works out of the box, nothing to configure.

**GitHub OAuth** (optional but strongly recommended for dev teams):

1. Create a GitHub OAuth App at https://github.com/settings/applications/new
   - Homepage URL: `https://app.yoru.acme.com`
   - Authorization callback URL: **your Supabase project's** GitHub callback —
     shown in the Supabase dashboard under Auth → Providers → GitHub
2. In Supabase dashboard → Auth → Providers → **GitHub** → paste the
   `client_id` + `client_secret` → toggle Enabled.
3. Auth → URL Configuration:
   - Site URL: `https://app.yoru.acme.com`
   - Redirect URLs (add both):
     - `https://api.yoru.acme.com/api/v1/auth/github/callback`
     - `http://localhost:8000/api/v1/auth/github/callback` (for local dev)

---

## 3. Deploy the backend

### Environment variables

The backend is a single FastAPI app in `backend/`. Copy `backend/.env.example`
to `.env` and fill in:

```bash
# --- Core ---
APP_ENV=production
ENVIRONMENT=production
AUTH_JWT_SECRET=<openssl rand -base64 48>
APP_URL=https://app.yoru.acme.com
API_URL=https://api.yoru.acme.com
CORS_ALLOWED_ORIGINS=https://app.yoru.acme.com,https://yoru.acme.com
COOKIE_SECURE=true
COOKIE_SAMESITE=none
COOKIE_DOMAIN=.yoru.acme.com
FRONTEND_ORIGIN=https://app.yoru.acme.com

# --- Supabase ---
SUPABASE_URL=https://<your-project>.supabase.co
SUPABASE_ANON_KEY=<anon key>
SUPABASE_SERVICE_ROLE_KEY=<service role key>

# --- Data ---
RECEIPT_DB_URL=sqlite:////data/receipt.db   # local SQLite, persist the volume

# --- Email (skip the whole block if you don't want welcome / invite mails) ---
EMAIL_PROVIDER=smtp
EMAIL_BRAND_NAME=Yoru
EMAIL_COMPANY_ADDRESS="Acme, Paris"
EMAIL_SUPPORT_EMAIL=yoru@acme.com
SMTP_HOST=smtp.resend.com
SMTP_PORT=465
SMTP_USERNAME=resend
SMTP_PASSWORD=<re_... token>
SMTP_FROM_EMAIL=yoru@acme.com
SMTP_FROM_NAME=Yoru
SMTP_USE_TLS=true

# --- Stripe (LEAVE EMPTY for self-host) ---
# Backend detects empty STRIPE_API_KEY and falls back to mock mode:
# - BillingPage hides the "Upgrade" + "Manage subscription" buttons
# - /billing/checkout-session and /billing/portal-session return a graceful
#   mock URL instead of a 502
STRIPE_API_KEY=
STRIPE_WEBHOOK_SECRET=
STRIPE_PRO_PRICE_ID=
STRIPE_PRO_ANNUAL_PRICE_ID=
STRIPE_TEAM_PRICE_ID=
STRIPE_TEAM_ANNUAL_PRICE_ID=
STRIPE_PORTAL_CONFIG_ID=

# --- GitHub OAuth (client_id/secret already live in your Supabase dashboard;
# these two are only needed if you expose a legacy device-flow — optional) ---
GITHUB_OAUTH_CLIENT_ID=
GITHUB_OAUTH_CLIENT_SECRET=
```

### Build + run

Docker (recommended — same image we ship to Cloud):

```bash
cd backend
docker build -t yoru-backend:latest .
docker run -d \
  --name yoru-backend \
  --env-file .env \
  -p 8002:8002 \
  -v /srv/yoru-data:/data \
  --restart unless-stopped \
  yoru-backend:latest
```

The backend exposes `:8002` — put any TLS-terminating proxy in front of it
(Caddy / nginx / Traefik). The `/data` volume holds the SQLite DB where
session events are written; back it up with your normal snapshot rotation.

Health check: `curl https://api.yoru.acme.com/health` → `200`.

---

## 4. Deploy the frontend + marketing

Both are Vite apps. Build once, serve the `dist/` folder from anywhere.

```bash
# Dashboard
cd frontend
cp .env.example .env.production
# edit .env.production:
#   VITE_API_URL=https://api.yoru.acme.com/api/v1
#   VITE_MARKETING_URL=https://yoru.acme.com
#   VITE_SUPABASE_URL=https://<your-project>.supabase.co
#   VITE_SUPABASE_ANON_KEY=<anon>
npm install
npm run build
# serve dist/ from Vercel / nginx / Cloudflare Pages / …

# Marketing (optional — if you don't want a public landing page, skip it)
cd ../marketing
npm install
npm run build
```

If you use nginx, mount `dist/` as the web root and add SPA fallback:

```nginx
location / {
    try_files $uri /index.html;
}
```

---

## 5. Configure the CLI to talk to your backend

Users of your self-hosted instance install the public CLI from PyPI and
point it at your server:

```bash
pip install yoru-cli
yoru init --server https://api.yoru.acme.com
```

The browser will open on `https://app.yoru.acme.com/cli/pair?code=…` for
approval. From there the CLI writes `~/.config/yoru/config.json` with
your server URL and a paired token. Everything else — Claude Code hooks,
event ingest, dashboard polling — works identically to Cloud.

If you run an air-gapped environment where PyPI isn't reachable, mirror
the wheel from `pip download yoru-cli` into your internal PyPI index and
install from there.

---

## 6. Verification checklist

Run through these after the first deploy; they confirm the full stack:

- [ ] `curl https://api.yoru.acme.com/health` returns `200`
- [ ] Sign up a first account on `https://app.yoru.acme.com/signup`
- [ ] DB check: that user has a row in `public.subscriptions` with
      `plan_name = 'Org'`, `status = 'active'` (the self-host trigger fired)
- [ ] `GET /api/v1/me/subscription` returns `{ plan_name: "Org", features: { … } }`
- [ ] "Continue with GitHub" on /signin completes → lands on /welcome
- [ ] `yoru init --server https://api.yoru.acme.com` pairs cleanly
- [ ] Run `claude` in any git repo → a tool call appears in the dashboard
      within ~5 s
- [ ] Drop a known-secret pattern in a Bash tool call (e.g.
      `echo AKIAIOSFODNN7EXAMPLE`) → the session shows a `[secret]` red flag
- [ ] `/settings/billing` shows "Org" and hides the Upgrade buttons
      (because `STRIPE_API_KEY` is empty)
- [ ] Welcome email lands in the new user's inbox (if SMTP is configured)

All green → you're live.

---

## Upgrading

Yoru ships continuously on Cloud. Self-host tracks behind by choice — pin
a Docker tag (`yoru-backend:v0.5.0`) and upgrade on your cadence.

```bash
# Pull the new image, restart, let init_db() auto-apply SQLite migrations
docker pull ghcr.io/helios-code/yoru-backend:latest
docker stop yoru-backend && docker rm yoru-backend
docker run -d --name yoru-backend --env-file .env -p 8002:8002 \
  -v /srv/yoru-data:/data --restart unless-stopped \
  ghcr.io/helios-code/yoru-backend:latest
```

Schema changes in `public.*` (Supabase) occasionally need a manual
migration run. Watch the release notes; we tag breaking migrations with a
🚨 and ship a `supabase db push`-compatible file.

---

## Security notes

- **AGPL-3.0**: modifying the backend and exposing it to *other organizations*
  triggers the AGPL's distribution clause — you must offer source to
  those users. Internal single-org use is unrestricted. (The CLI is MIT
  and carries no such obligation.)
- **Secrets hygiene**: `AUTH_JWT_SECRET`, `SUPABASE_SERVICE_ROLE_KEY`, and
  `SMTP_PASSWORD` never need to reach any client. Pin them to the backend
  process only.
- **Cookie domain**: the `COOKIE_DOMAIN` env is what lets the dashboard at
  `app.yoru.acme.com` read the CSRF cookie set by `api.yoru.acme.com`.
  If you use a single subdomain for both (same origin), leave it unset.
- **RLS**: every `public.*` table has RLS policies. The backend mediates
  all writes, but a leaked anon key will still only expose what a user's
  own row grants.

---

## When to reach out

Open an issue on `github.com/helios-code/overnight-saas` for:

- A migration that fails on your Supabase (we'll ship a fix)
- A feature you want gated behind a plan that isn't (we'll land an override)
- Bare-metal self-host help (Postgres + GoTrue instead of Supabase) —
  Phase G, but real customers unblock it

Or email `hello@yoru.sh` for private / enterprise conversations.
