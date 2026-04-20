# Deployment Scripts

Helper scripts for deploying SaaSForge to production. These are **reference scripts** - review and customize before running!

## Available Scripts

### 🔒 `setup-server-security.sh`

Hardens server security (Ubuntu/Debian).

**What it does:**
- Configures UFW firewall (SSH, HTTP, HTTPS)
- Installs and configures Fail2Ban (SSH brute-force protection)
- Enables automatic security updates
- Provides SSH hardening recommendations

**Usage:**
```bash
# Run on a fresh server
sudo ./scripts/setup-server-security.sh
```

**Run this FIRST** before deploying your application.

---

### 🚀 `deploy-production.sh`

Deploys the application to production.

**What it does:**
- Copies Docker secrets from examples
- Prompts you to configure secrets
- Validates environment configuration
- Builds and starts production services

**Usage:**
```bash
# From project root
./scripts/deploy-production.sh
```

**Prerequisites:**
- Server security configured
- DNS pointing to server
- SSL certificates obtained
- Docker installed

---

## Important Notes

⚠️ **These scripts are REFERENCE implementations**

- Review each script before running
- Customize for your infrastructure
- Test in a staging environment first
- Keep backups of your configuration

📚 **Full documentation:** `docs/DEPLOYMENT.md`

## Manual Deployment (Recommended)

For production deployments, we recommend **manual execution** following the deployment guide rather than running scripts blindly.

**Why?**
- Understand each step
- Customize for your needs
- Catch issues early
- Learn your infrastructure

**Read:** `docs/DEPLOYMENT.md` for step-by-step instructions.

## Script Safety

These scripts:
- ✅ Exit on errors (`set -e`)
- ✅ Require confirmation before running
- ✅ Check prerequisites
- ✅ Provide colored output for clarity
- ✅ Show what they're doing

But they:
- ❌ Don't handle all edge cases
- ❌ Might not fit your exact setup
- ❌ Assume Ubuntu/Debian environment
- ❌ Can't replace understanding

## Customization

Feel free to modify these scripts for your needs:

```bash
# Copy script and customize
cp scripts/deploy-production.sh scripts/my-deploy.sh
nano scripts/my-deploy.sh

# Add your custom steps
# Modify for your infrastructure
# Add additional checks
```

## Getting Help

If deployment fails:

1. **Check logs:**
   ```bash
   docker compose -f docker/compose/docker-compose.prod.yml logs
   ```

2. **Verify secrets:**
   ```bash
   ls -la docker/config/secrets/
   cat docker/config/secrets/supabase_url  # Should not be empty
   ```

3. **Check services:**
   ```bash
   docker ps
   ```

4. **Read documentation:**
   - `docs/DEPLOYMENT.md` - Full deployment guide
   - `docker/config/secrets.example/README.md` - Secrets setup
   - `docker/config/nginx/ssl/README.md` - SSL setup

## Alternative Deployment Methods

**Docker Swarm:**
- Use external secrets instead of file-based
- Scale services with `docker service scale`
- See Docker Swarm documentation

**Kubernetes:**
- Convert docker-compose to k8s manifests
- Use k8s secrets instead of Docker secrets
- See Kubernetes documentation

**PaaS Platforms (Heroku, Fly.io, Railway):**
- Set environment variables via platform UI
- Use platform's secret management
- No Docker secrets needed

## Contributing

Found an issue or improvement?
- Open an issue
- Submit a pull request
- Share your deployment experience

---

**Remember:** Scripts are helpers, not replacements for understanding your infrastructure.

Read. Understand. Deploy. 🚀
