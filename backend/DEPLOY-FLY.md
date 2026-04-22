# Deploy Receipt API to Fly.io

One-time setup + every-deploy checklist. Assumes `flyctl` is installed (`brew
install flyctl`) and you're logged in (`flyctl auth login`).

## 1. Create the app + volume (one-time)

```bash
cd backend

# Create the Fly app (name must be globally unique — swap if taken).
flyctl apps create receipt-api --org personal

# Persistent volume for SQLite. 3 GB is plenty for ~10M events.
flyctl volumes create receipt_data --region cdg --size 3
```

## 2. Push secrets (one-time, update when rotating)

```bash
# Auth
flyctl secrets set AUTH_JWT_SECRET="$(openssl rand -base64 48)"

# Supabase — copy from your local .env
flyctl secrets set \
  SUPABASE_URL="https://ozgnzurxuudzpsyrlnbj.supabase.co" \
  SUPABASE_ANON_KEY="<anon>" \
  SUPABASE_SERVICE_ROLE_KEY="<service-role>"

# Stripe — LIVE keys, not test. Create a new webhook endpoint at
# https://dashboard.stripe.com/webhooks pointing to
# https://receipt-api.fly.dev/api/v1/billing/webhook and paste its signing
# secret below.
flyctl secrets set \
  STRIPE_API_KEY="sk_live_..." \
  STRIPE_WEBHOOK_SECRET="whsec_..." \
  STRIPE_PRO_PRICE_ID="price_..." \
  STRIPE_PRO_ANNUAL_PRICE_ID="price_..." \
  STRIPE_TEAM_PRICE_ID="price_..." \
  STRIPE_TEAM_ANNUAL_PRICE_ID="price_..." \
  STRIPE_PORTAL_CONFIG_ID="bpc_..."

# Sentry (optional but recommended)
flyctl secrets set SENTRY_DSN="https://...@sentry.io/..."

# GitHub OAuth (if enabled) — same values as the Supabase provider config
flyctl secrets set GITHUB_OAUTH_CLIENT_ID="Iv1..." GITHUB_OAUTH_CLIENT_SECRET="..."
```

## 3. Deploy

```bash
flyctl deploy --remote-only
```

`--remote-only` builds on Fly's builder VM — no local Docker needed.

## 4. Verify

```bash
flyctl status
flyctl logs -i <machine-id>          # live tail
curl https://receipt-api.fly.dev/health
curl https://receipt-api.fly.dev/api/docs
```

## 5. Post-deploy (Stripe portal config — LIVE mode)

The `features[subscription_update][products]` field is dropped by Stripe's
API in both test and live mode — must be set via Dashboard. Open
https://dashboard.stripe.com/settings/billing/portal and add the Pro + Team
products (monthly + annual prices) to the portal configuration referenced by
`STRIPE_PORTAL_CONFIG_ID`.

## Backup strategy

SQLite lives on a single Fly volume — snapshots are automatic (daily, 5-day
retention) via Fly. For stronger guarantees we can layer litestream later
(streams WAL to S3 every few seconds). Skip until we have paying customers.

## Schema migrations

`db.py::init_db()` runs PRAGMA introspection + ALTERs on every boot. Safe to
deploy schema changes the same way we ship code — no separate migration step.
Supabase Postgres migrations are applied through the dashboard or the
Supabase MCP `apply_migration` tool.

## Rollback

```bash
flyctl releases                      # list recent deploys
flyctl deploy --image <prior-image>  # re-run any past build
```
