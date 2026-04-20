# SSL/TLS Certificates Setup

This directory contains SSL/TLS certificates for the production nginx reverse proxy.

## Required Files

Place your SSL certificate files in this directory:

- `server.crt` - SSL certificate (public) - full chain including intermediate certificates
- `server.key` - Private key (keep secure!)

## Development

For local development, you can:

1. **Skip SSL entirely** (use HTTP only)
   - Comment out the HTTPS server block in `nginx.prod.conf`
   - Or use the development environment which doesn't require nginx

2. **Use self-signed certificates** (browser will show warnings)
   ```bash
   cd template/docker/config/nginx/ssl
   openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
     -keyout server.key \
     -out server.crt \
     -subj "/C=US/ST=State/L=City/O=Organization/CN=localhost"
   ```

## Production

### Option 1: Let's Encrypt (Recommended)

Let's Encrypt provides free SSL certificates with automatic renewal.

#### Step 1: Install Certbot

```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install certbot

# macOS
brew install certbot
```

#### Step 2: Generate Certificate

```bash
# Replace api.prod.example.com with your actual domain
sudo certbot certonly --standalone -d api.prod.example.com

# Certificate will be generated at:
# /etc/letsencrypt/live/api.prod.example.com/fullchain.pem
# /etc/letsencrypt/live/api.prod.example.com/privkey.pem
```

#### Step 3: Copy Certificates

```bash
# Copy to nginx SSL directory
sudo cp /etc/letsencrypt/live/api.prod.example.com/fullchain.pem \
  /path/to/template/docker/config/nginx/ssl/server.crt

sudo cp /etc/letsencrypt/live/api.prod.example.com/privkey.pem \
  /path/to/template/docker/config/nginx/ssl/server.key

# Set appropriate permissions
sudo chmod 644 server.crt
sudo chmod 600 server.key
```

#### Step 4: Setup Auto-Renewal

Let's Encrypt certificates expire every 90 days. Setup automatic renewal:

```bash
# Test renewal
sudo certbot renew --dry-run

# Add to crontab for automatic renewal
sudo crontab -e

# Add this line (runs daily at midnight, renews if needed, restarts nginx)
0 0 * * * certbot renew --quiet --deploy-hook "cd /path/to/project && docker compose -f docker-compose.prod.yml restart nginx"
```

### Option 2: Commercial Certificate (e.g., DigiCert, Comodo)

If you purchased an SSL certificate:

1. **Download your certificate files** from your provider
   - You'll typically get: certificate file, private key, and intermediate certificates

2. **Combine certificate with intermediate certificates** (if separate)
   ```bash
   cat your_certificate.crt intermediate.crt > server.crt
   ```

3. **Copy files to this directory**
   ```bash
   cp path/to/fullchain.crt server.crt
   cp path/to/private.key server.key
   chmod 644 server.crt
   chmod 600 server.key
   ```

### Option 3: Cloudflare (Proxy Mode)

If using Cloudflare in proxy mode:

1. **Use Cloudflare Origin Certificate**
   - Generate in Cloudflare dashboard: SSL/TLS → Origin Server → Create Certificate
   - Download both certificate and private key
   - Copy to this directory as `server.crt` and `server.key`

2. **Configure Cloudflare SSL Mode**
   - Set to "Full (strict)" in Cloudflare dashboard
   - This encrypts traffic between Cloudflare and your origin server

## Security Best Practices

1. **Never commit `server.key` to git**
   - The `.gitignore` file in this directory excludes `*.key` files
   - Keep your private key secure and encrypted

2. **Use strong key sizes**
   - Minimum 2048-bit RSA keys
   - Preferably 4096-bit for production

3. **Enable OCSP stapling**
   - Already configured in `nginx.prod.conf`
   - Improves performance and privacy

4. **Monitor certificate expiration**
   - Set up alerts 30 days before expiration
   - Use monitoring tools like SSL Labs

5. **Test your SSL configuration**
   - Use [SSL Labs Server Test](https://www.ssllabs.com/ssltest/)
   - Aim for an A+ rating

## Verification

After setting up certificates, verify your configuration:

```bash
# Test nginx configuration
docker compose -f docker-compose.prod.yml exec nginx nginx -t

# Check certificate details
openssl x509 -in server.crt -text -noout

# Check certificate and key match
openssl x509 -noout -modulus -in server.crt | openssl md5
openssl rsa -noout -modulus -in server.key | openssl md5
# The MD5 hashes should match
```

## Troubleshooting

### Certificate/Key Mismatch
```
nginx: [emerg] SSL_CTX_use_PrivateKey_file() failed
```
**Solution**: Ensure the certificate and private key match (see verification above)

### Permission Denied
```
nginx: [emerg] cannot load certificate
```
**Solution**: Check file permissions
```bash
chmod 644 server.crt
chmod 600 server.key
```

### Certificate Chain Issues
```
SSL certificate problem: unable to get local issuer certificate
```
**Solution**: Ensure `server.crt` includes the full certificate chain (intermediate + root certificates)

## Additional Resources

- [Let's Encrypt Documentation](https://letsencrypt.org/docs/)
- [Certbot Documentation](https://certbot.eff.org/)
- [Mozilla SSL Configuration Generator](https://ssl-config.mozilla.org/)
- [SSL Labs Server Test](https://www.ssllabs.com/ssltest/)
