# Docker Secrets Setup

This directory contains example secret files for production deployment using Docker Compose secrets.

## Quick Start

1. **Copy example files to create actual secrets:**
   ```bash
   cp -r docker/config/secrets.example docker/config/secrets
   ```

2. **Edit secret files with your actual credentials:**
   ```bash
   # Edit each file with your real values
   nano docker/config/secrets/supabase_url
   nano docker/config/secrets/supabase_anon_key
   nano docker/config/secrets/supabase_service_key
   ```

3. **Protect your secrets:**
   - The `secrets/` directory is already in `.gitignore`
   - Never commit actual secret files to git
   - Consider using `chmod 600 secrets/*` to restrict file permissions

4. **Start production services:**
   ```bash
   cd docker/compose
   docker compose -f docker-compose.prod.yml up -d
   ```

## How It Works

Docker Compose mounts secret files at `/run/secrets/<secret_name>` inside containers:

- `/run/secrets/supabase_url`
- `/run/secrets/supabase_anon_key`
- `/run/secrets/supabase_service_key`

The application automatically:
1. Checks if `/run/secrets/<secret_name>` exists
2. Reads the secret value from the file
3. Falls back to environment variables if secret file doesn't exist

See: https://docs.docker.com/compose/how-tos/use-secrets/

## Secret Files Format

Each secret file should contain **only** the secret value (no quotes, no extra lines):

```bash
# ✅ CORRECT
https://your-project.supabase.co

# ❌ WRONG
SUPABASE_URL=https://your-project.supabase.co

# ❌ WRONG
"https://your-project.supabase.co"
```

## Alternative: External Secrets (Docker Swarm)

If deploying with Docker Swarm, you can use external secrets instead of files:

```bash
# Create secrets in Swarm
echo "https://your-project.supabase.co" | docker secret create supabase_url -
echo "your-anon-key" | docker secret create supabase_anon_key -
echo "your-service-key" | docker secret create supabase_service_key -

# Update docker-compose.prod.yml to use external secrets:
# secrets:
#   supabase_url:
#     external: true
#   supabase_anon_key:
#     external: true
#   supabase_service_key:
#     external: true
```

## Security Best Practices

1. **Never commit actual secrets** - The `secrets/` directory is gitignored
2. **Use strong permissions** - `chmod 600 docker/config/secrets/*`
3. **Rotate regularly** - Change secrets every 90 days
4. **Limit access** - Only give credentials to services that need them
5. **Monitor usage** - Check Supabase logs for suspicious activity

## Troubleshooting

### Secrets not being read

1. Check file exists: `ls -la docker/config/secrets/`
2. Check file permissions: Should be readable by Docker
3. Check file content: `cat docker/config/secrets/supabase_url` (no quotes, no extra lines)
4. Check logs: `docker compose -f docker-compose.prod.yml logs api_1`

### Permission denied errors

```bash
# Fix permissions
chmod 600 docker/config/secrets/*
chown $(whoami):$(whoami) docker/config/secrets/*
```
