#!/bin/bash
# Server Security Hardening Script
# For Ubuntu 22.04+ / Debian 11+
#
# This script configures:
#   - UFW firewall
#   - Fail2Ban (SSH protection)
#   - Automatic security updates
#   - SSH hardening recommendations
#
# Usage:
#   sudo ./scripts/setup-server-security.sh
#
# WARNING: Review this script before running!
# Make sure you have SSH key access before disabling password authentication!

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Server Security Hardening${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   echo -e "${RED}ERROR: This script must be run as root${NC}"
   echo "Usage: sudo $0"
   exit 1
fi

# Confirmation
echo -e "${YELLOW}This script will:${NC}"
echo "  1. Configure UFW firewall (allow SSH, HTTP, HTTPS)"
echo "  2. Install and configure Fail2Ban"
echo "  3. Enable automatic security updates"
echo "  4. Show SSH hardening recommendations"
echo ""
read -p "Continue? (y/n): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted"
    exit 1
fi

# Step 1: Install required packages
echo ""
echo -e "${GREEN}[1/4] Installing security packages${NC}"
echo "------------------------------------"

apt update
apt install -y ufw fail2ban unattended-upgrades

echo -e "${GREEN}✓ Packages installed${NC}"

# Step 2: Configure UFW Firewall
echo ""
echo -e "${GREEN}[2/4] Configuring UFW Firewall${NC}"
echo "------------------------------------"

# Check if UFW is already enabled
if ufw status | grep -q "Status: active"; then
    echo -e "${YELLOW}UFW is already enabled${NC}"
    ufw status verbose
else
    # Configure firewall rules
    ufw default deny incoming
    ufw default allow outgoing

    # Allow SSH (CRITICAL - don't lock yourself out!)
    ufw allow 22/tcp comment 'SSH'

    # Allow HTTP and HTTPS
    ufw allow 80/tcp comment 'HTTP'
    ufw allow 443/tcp comment 'HTTPS'

    # Enable UFW
    echo -e "${YELLOW}Enabling UFW firewall...${NC}"
    ufw --force enable

    echo -e "${GREEN}✓ UFW configured and enabled${NC}"
fi

ufw status verbose

# Step 3: Configure Fail2Ban
echo ""
echo -e "${GREEN}[3/4] Configuring Fail2Ban${NC}"
echo "------------------------------------"

# Create local configuration
if [ ! -f /etc/fail2ban/jail.local ]; then
    cp /etc/fail2ban/jail.conf /etc/fail2ban/jail.local
fi

# Configure fail2ban for SSH protection
cat > /etc/fail2ban/jail.d/sshd.conf << 'EOF'
[sshd]
enabled = true
port = 22
filter = sshd
logpath = /var/log/auth.log
maxretry = 5
bantime = 1h
findtime = 10m
EOF

# Restart fail2ban
systemctl enable fail2ban
systemctl restart fail2ban

echo -e "${GREEN}✓ Fail2Ban configured${NC}"
echo ""
echo "Fail2Ban status:"
fail2ban-client status

# Step 4: Enable Automatic Security Updates
echo ""
echo -e "${GREEN}[4/4] Configuring Automatic Security Updates${NC}"
echo "------------------------------------"

# Configure unattended-upgrades
cat > /etc/apt/apt.conf.d/50unattended-upgrades << 'EOF'
Unattended-Upgrade::Allowed-Origins {
    "${distro_id}:${distro_codename}-security";
    "${distro_id}ESMApps:${distro_codename}-apps-security";
    "${distro_id}ESM:${distro_codename}-infra-security";
};

Unattended-Upgrade::AutoFixInterruptedDpkg "true";
Unattended-Upgrade::MinimalSteps "true";
Unattended-Upgrade::Remove-Unused-Dependencies "true";
Unattended-Upgrade::Automatic-Reboot "false";
EOF

# Enable automatic updates
cat > /etc/apt/apt.conf.d/20auto-upgrades << 'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Download-Upgradeable-Packages "1";
APT::Periodic::AutocleanInterval "7";
APT::Periodic::Unattended-Upgrade "1";
EOF

echo -e "${GREEN}✓ Automatic security updates enabled${NC}"

# SSH Hardening Recommendations
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Security Configuration Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "${YELLOW}SSH Hardening Recommendations:${NC}"
echo ""
echo "Edit /etc/ssh/sshd_config and ensure:"
echo "  PermitRootLogin no"
echo "  PasswordAuthentication no"
echo "  PubkeyAuthentication yes"
echo "  X11Forwarding no"
echo ""
echo -e "${RED}WARNING: Only disable PasswordAuthentication if you have SSH key access!${NC}"
echo ""
echo "After editing, restart SSH:"
echo "  sudo systemctl restart sshd"
echo ""

# Summary
echo -e "${GREEN}Summary:${NC}"
echo "  ✓ UFW firewall enabled (SSH, HTTP, HTTPS allowed)"
echo "  ✓ Fail2Ban protecting SSH (5 attempts, 1 hour ban)"
echo "  ✓ Automatic security updates enabled"
echo ""
echo "Check status:"
echo "  UFW:      sudo ufw status"
echo "  Fail2Ban: sudo fail2ban-client status"
echo "  Updates:  sudo unattended-upgrade --dry-run --debug"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "  1. Verify SSH key access works"
echo "  2. Harden SSH configuration (see recommendations above)"
echo "  3. Configure firewall for any additional ports you need"
echo "  4. Setup monitoring (optional)"
echo ""
