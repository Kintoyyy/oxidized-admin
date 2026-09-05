#!/bin/bash

# Oxidized + LibreNMS Manager Installer
# Installs Oxidized (as a dedicated 'oxidized' system user), then installs
# the Flask admin page on top of it. Must be run as root.

set -e

# Prevent apt/needrestart from popping up interactive (whiptail) dialogs
# that take over the terminal mid-install (looks like the screen "clears").
export DEBIAN_FRONTEND=noninteractive
export NEEDRESTART_MODE=a
export NEEDRESTART_SUSPEND=1

# ============================================================================
# COLOR DEFINITIONS
# ============================================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info() { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }
section() { echo -e "\n${BLUE}=== $1 ===${NC}\n"; }

# ============================================================================
# PRE-FLIGHT CHECKS
# ============================================================================

section "Pre-flight Checks"

if [ "$EUID" -ne 0 ]; then
    error "This script must be run as root, e.g.: sudo ./install_oxidized_manager.sh"
fi

info "Checking system requirements..."

if ! grep -q 'Ubuntu\|Debian' /etc/os-release; then
    error "This script only supports Ubuntu/Debian. Please install manually on other systems."
fi

OS_VERSION=$(lsb_release -rs)
info "Detected: Ubuntu/Debian $OS_VERSION"

# ============================================================================
# USER INPUT
# ============================================================================

section "Configuration"

read -p "Enter admin page install directory (default: /home/oxidized/oxidized-manager): " INSTALL_DIR
INSTALL_DIR=${INSTALL_DIR:-/home/oxidized/oxidized-manager}

read -p "Enter Oxidized config directory (default: /home/oxidized/.config/oxidized): " CONFIG_DIR
CONFIG_DIR=${CONFIG_DIR:-/home/oxidized/.config/oxidized}

read -p "Enter application port (default: 5000): " APP_PORT
APP_PORT=${APP_PORT:-5000}

read -p "Enter admin username (default: admin): " ADMIN_USERNAME
ADMIN_USERNAME=${ADMIN_USERNAME:-admin}

read -s -p "Enter admin password (min 8 characters): " ADMIN_PASSWORD
echo
while [ ${#ADMIN_PASSWORD} -lt 8 ]; do
    warn "Password must be at least 8 characters"
    read -s -p "Enter admin password: " ADMIN_PASSWORD
    echo
done

read -p "Enter admin email (default: admin@localhost): " ADMIN_EMAIL
ADMIN_EMAIL=${ADMIN_EMAIL:-admin@localhost}

info "Admin page install directory: $INSTALL_DIR"
info "Oxidized config directory:    $CONFIG_DIR"
info "Application port:             $APP_PORT"
info "Admin username:                $ADMIN_USERNAME"

# ============================================================================
# DETECT EXISTING OXIDIZED INSTALLATION
# ============================================================================

section "Checking for Existing Oxidized Installation"

INSTALL_OXIDIZED=true

if command -v oxidized &> /dev/null; then
    CURRENT_VERSION=$(oxidized --version 2>/dev/null || echo "unknown")
    info "Oxidized is already installed (version: $CURRENT_VERSION)"
    echo ""
    echo "  [s] Skip  - leave the existing install as-is (default)"
    echo "  [n] Nuke  - uninstall and reinstall the oxidized gems fresh"
    echo "              (existing device configs/backups under $CONFIG_DIR are kept)"
    echo "  [c] Cancel - exit without changing anything"
    read -p "Choice [s/n/c]: " OXIDIZED_CHOICE
    OXIDIZED_CHOICE=${OXIDIZED_CHOICE:-s}

    case "$OXIDIZED_CHOICE" in
        [Cc]*)
            error "Installation cancelled by user."
            ;;
        [Nn]*)
            info "Nuking existing oxidized gems (backups/config will be preserved)..."
            gem uninstall oxidized oxidized-web oxidized-script -a -x -I || warn "Some gems may not have been installed; continuing"
            INSTALL_OXIDIZED=true
            ;;
        *)
            info "Skipping Oxidized installation, keeping existing setup."
            INSTALL_OXIDIZED=false
            ;;
    esac
else
    info "Oxidized not found. It will be installed."
fi

# ============================================================================
# SYSTEM DEPENDENCIES (ADMIN PAGE)
# ============================================================================

section "Installing System Dependencies"

info "Updating package lists..."
apt-get update -qq

info "Installing base dependencies (this may take a few minutes)..."
apt-get install -y \
    python3-dev \
    python3-venv \
    python3-pip \
    git \
    curl \
    wget \
    gunicorn \
    ufw

info "Base dependencies installed"

# ============================================================================
# OXIDIZED INSTALLATION (AS ROOT, DEDICATED 'oxidized' SYSTEM USER)
# ============================================================================

if [ "$INSTALL_OXIDIZED" = true ]; then
    section "Setting Up Oxidized System User"

    if id -u oxidized &> /dev/null; then
        info "System user 'oxidized' already exists"
    else
        info "Creating system user 'oxidized'..."
        adduser --disabled-password --gecos "" oxidized
    fi

    info "Granting passwordless sudo to 'oxidized' (via /etc/sudoers.d/oxidized)..."
    SUDOERS_TMP=$(mktemp)
    echo "oxidized ALL=(ALL) NOPASSWD:ALL" > "$SUDOERS_TMP"
    if visudo -cf "$SUDOERS_TMP" &> /dev/null; then
        install -m 0440 -o root -g root "$SUDOERS_TMP" /etc/sudoers.d/oxidized
        info "Sudoers rule installed"
    else
        warn "Generated sudoers file failed validation; skipping sudoers setup"
    fi
    rm -f "$SUDOERS_TMP"

    section "Installing Oxidized Build Dependencies"

    apt install software-properties-common -y

    apt install libssh2-1-dev -y

    apt install ruby ruby-dev libsqlite3-dev libssl-dev pkg-config cmake libssh2-1-dev libicu-dev zlib1g-dev g++ libyaml-dev -y

    apt install libgpgme-dev -y

    info "Build dependencies installed"

    section "Installing Oxidized Gems"

    gem install oxidized
    gem install oxidized-web
    gem install oxidized-script

    info "Verifying installation as 'oxidized' user..."
    if su - oxidized -c "oxidized -v" &> /dev/null; then
        OX_VERSION=$(su - oxidized -c "oxidized -v")
        info "✓ Oxidized installed: $OX_VERSION"
    else
        warn "Could not verify oxidized as the 'oxidized' user. Check the gem install output above."
    fi
else
    section "Skipping Oxidized Installation"
    info "Using existing Oxidized installation"

    if ! id -u oxidized &> /dev/null; then
        warn "'oxidized' system user does not exist yet, but Oxidized is installed elsewhere."
        warn "The admin page will still be configured to run as 'oxidized'; create the user manually if needed:"
        warn "  sudo adduser --disabled-password --gecos \"\" oxidized"
    fi
fi

# ============================================================================
# OXIDIZED CONFIGURATION
# ============================================================================

section "Configuring Oxidized"

mkdir -p "$CONFIG_DIR"

if [ ! -f "$CONFIG_DIR/config" ]; then
    info "Creating minimal Oxidized config..."
    cat > "$CONFIG_DIR/config" << EOF
---
username: admin
password: password
interval: 3600
use_syslog: false
log: $CONFIG_DIR/logs

source:
  default: csv

csv:
  file: $CONFIG_DIR/router.db
  delimiter: ":"

output:
  default: git

git:
  repo: $CONFIG_DIR/repositories.default/.git

groups:
  default:
    username: admin
    password: password

rest: 0.0.0.0:8888
EOF
    info "Created $CONFIG_DIR/config"
else
    info "Existing Oxidized config found, leaving it untouched"
fi

if [ ! -f "$CONFIG_DIR/router.db" ]; then
    touch "$CONFIG_DIR/router.db"
    info "Created $CONFIG_DIR/router.db"
fi

if id -u oxidized &> /dev/null; then
    chown -R oxidized:oxidized "$(dirname "$CONFIG_DIR")" 2>/dev/null || chown -R oxidized:oxidized "$CONFIG_DIR"
fi

# ============================================================================
# OXIDIZED SYSTEMD SERVICE
# ============================================================================

if [ "$INSTALL_OXIDIZED" = true ] && id -u oxidized &> /dev/null; then
    section "Creating Oxidized Systemd Service"

    OXIDIZED_BIN=$(su - oxidized -c "command -v oxidized" 2>/dev/null || echo "/usr/local/bin/oxidized")

    cat > /etc/systemd/system/oxidized.service << EOF
[Unit]
Description=Oxidized Network Device Configuration Backup Tool
After=network.target

[Service]
Type=simple
User=oxidized
Group=oxidized
Environment="HOME=/home/oxidized"
WorkingDirectory=/home/oxidized
ExecStart=$OXIDIZED_BIN
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable oxidized.service
    systemctl restart oxidized.service
    sleep 2

    if systemctl is-active --quiet oxidized.service; then
        info "✓ oxidized.service started successfully"
    else
        warn "oxidized.service may have failed to start. Check: sudo journalctl -u oxidized -n 50"
    fi
fi

# ============================================================================
# SECURE OXIDIZED WEB GUI (OPTIONAL NGINX REVERSE PROXY + BASIC AUTH)
# ============================================================================

section "Secure Oxidized Web GUI"

NGINX_PROXY_ENABLED=false

read -p "Put the Oxidized web GUI (port 8888) behind an Nginx reverse proxy with password protection? [y/N]: " SETUP_NGINX
if [[ "$SETUP_NGINX" =~ ^[Yy] ]]; then
    NGINX_PROXY_ENABLED=true

    info "Installing Nginx and Apache utils..."
    apt install nginx apache2-utils -y

    read -p "Enter a username for the Oxidized web GUI (default: oxidized): " PROXY_USER
    PROXY_USER=${PROXY_USER:-oxidized}

    read -s -p "Enter a password for '$PROXY_USER': " PROXY_PASS
    echo
    while [ ${#PROXY_PASS} -lt 6 ]; do
        warn "Password must be at least 6 characters"
        read -s -p "Enter a password for '$PROXY_USER': " PROXY_PASS
        echo
    done

    info "Creating password file..."
    echo "$PROXY_PASS" | htpasswd -ci /etc/nginx/.htpasswd "$PROXY_USER"

    info "Writing Nginx reverse proxy config..."
    cat > /etc/nginx/sites-available/oxidized << 'EOF'
server {
    listen 80;
    server_name _;

    location / {
        auth_basic "Oxidized Access";
        auth_basic_user_file /etc/nginx/.htpasswd;

        proxy_pass http://localhost:8888;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF

    ln -sf /etc/nginx/sites-available/oxidized /etc/nginx/sites-enabled/oxidized

    if [ -f /etc/nginx/sites-enabled/default ]; then
        rm -f /etc/nginx/sites-enabled/default
        info "Removed default Nginx site"
    fi

    info "Testing Nginx configuration..."
    nginx -t

    systemctl restart nginx
    systemctl enable nginx
    info "✓ Nginx reverse proxy configured on port 80"

    info "Restricting Oxidized to listen on localhost only..."
    if grep -q '^rest:' "$CONFIG_DIR/config"; then
        sed -i 's/^rest:.*/rest: localhost:8888/' "$CONFIG_DIR/config"
    else
        echo 'rest: localhost:8888' >> "$CONFIG_DIR/config"
    fi
    systemctl restart oxidized.service
    info "✓ Oxidized now only reachable via the Nginx proxy (http://<host>/, user: $PROXY_USER)"
else
    info "Skipping Nginx setup. Oxidized web GUI stays reachable directly on port 8888."
fi

# ============================================================================
# PYTHON VIRTUAL ENVIRONMENT (ADMIN PAGE, AS 'oxidized' USER)
# ============================================================================

section "Setting Up Admin Page"

mkdir -p "$INSTALL_DIR"
mkdir -p /home/oxidized/.oxidized_manager

REPO_URL="https://github.com/Kintoyyy/oxidized-admin.git"
APP_SRC_DIR="$(pwd)"
CLONE_DIR=""

if [ ! -f "$APP_SRC_DIR/oxidized_nms_manager.py" ]; then
    warn "oxidized_nms_manager.py not found in current directory, cloning $REPO_URL..."
    CLONE_DIR=$(mktemp -d /tmp/oxidized-admin.XXXXXX)
    git clone --depth 1 "$REPO_URL" "$CLONE_DIR"
    APP_SRC_DIR="$CLONE_DIR"
fi

if [ ! -f "$APP_SRC_DIR/oxidized_nms_manager.py" ]; then
    error "oxidized_nms_manager.py not found, even after cloning $REPO_URL"
fi

cp "$APP_SRC_DIR/oxidized_nms_manager.py" "$INSTALL_DIR/"

if [ -f "$APP_SRC_DIR/requirements.txt" ]; then
    cp "$APP_SRC_DIR/requirements.txt" "$INSTALL_DIR/"
fi

if [ -n "$CLONE_DIR" ]; then
    rm -rf "$CLONE_DIR"
fi

if id -u oxidized &> /dev/null; then
    chown -R oxidized:oxidized "$INSTALL_DIR" /home/oxidized/.oxidized_manager
    RUN_AS_OXIDIZED=true
else
    warn "'oxidized' user not available; installing admin page to run as root instead"
    RUN_AS_OXIDIZED=false
fi

info "Creating virtual environment..."
if [ "$RUN_AS_OXIDIZED" = true ]; then
    su - oxidized -c "python3 -m venv '$INSTALL_DIR/venv'"
    su - oxidized -c "'$INSTALL_DIR/venv/bin/pip' install --upgrade pip setuptools wheel -q"
else
    python3 -m venv "$INSTALL_DIR/venv"
    "$INSTALL_DIR/venv/bin/pip" install --upgrade pip setuptools wheel -q
fi

info "Installing Python dependencies..."
if [ "$RUN_AS_OXIDIZED" = true ]; then
    if [ -f "$INSTALL_DIR/requirements.txt" ]; then
        su - oxidized -c "'$INSTALL_DIR/venv/bin/pip' install -q -r '$INSTALL_DIR/requirements.txt'"
    else
        su - oxidized -c "'$INSTALL_DIR/venv/bin/pip' install -q Flask==2.3.3 PyYAML==6.0.1 requests==2.31.0 gunicorn==21.2.0 Werkzeug==2.3.7"
    fi
else
    if [ -f "$INSTALL_DIR/requirements.txt" ]; then
        "$INSTALL_DIR/venv/bin/pip" install -q -r "$INSTALL_DIR/requirements.txt"
    else
        "$INSTALL_DIR/venv/bin/pip" install -q Flask==2.3.3 PyYAML==6.0.1 requests==2.31.0 gunicorn==21.2.0 Werkzeug==2.3.7
    fi
fi

info "✓ Python dependencies installed"

# ============================================================================
# DATABASE INITIALIZATION
# ============================================================================

section "Initializing Database"

cat > "$INSTALL_DIR/init_app.py" << 'PYEOF'
import sys
sys.path.insert(0, '.')

from oxidized_nms_manager import init_db, create_user
import os

init_db()
print("Database initialized")

username = sys.argv[1] if len(sys.argv) > 1 else 'admin'
password = sys.argv[2] if len(sys.argv) > 2 else 'admin'
email = sys.argv[3] if len(sys.argv) > 3 else 'admin@localhost'

if create_user(username, password, email, 'admin'):
    print(f"Admin user '{username}' created")
else:
    print(f"User '{username}' may already exist")
PYEOF

if [ "$RUN_AS_OXIDIZED" = true ]; then
    chown oxidized:oxidized "$INSTALL_DIR/init_app.py"
    su - oxidized -c "cd '$INSTALL_DIR' && OXIDIZED_CONFIG_DIR='$CONFIG_DIR' APP_DB_PATH='/home/oxidized/.oxidized_manager/app.db' '$INSTALL_DIR/venv/bin/python3' init_app.py '$ADMIN_USERNAME' '$ADMIN_PASSWORD' '$ADMIN_EMAIL'"
else
    (cd "$INSTALL_DIR" && OXIDIZED_CONFIG_DIR="$CONFIG_DIR" APP_DB_PATH="/home/oxidized/.oxidized_manager/app.db" "$INSTALL_DIR/venv/bin/python3" init_app.py "$ADMIN_USERNAME" "$ADMIN_PASSWORD" "$ADMIN_EMAIL")
fi

rm -f "$INSTALL_DIR/init_app.py"

# ============================================================================
# ADMIN PAGE SYSTEMD SERVICE
# ============================================================================

section "Creating Admin Page Systemd Service"

SERVICE_USER="oxidized"
if [ "$RUN_AS_OXIDIZED" != true ]; then
    SERVICE_USER="root"
fi

cat > /etc/systemd/system/oxidized-manager.service << EOF
[Unit]
Description=Oxidized Manager Admin Page
After=network.target oxidized.service

[Service]
Type=notify
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$INSTALL_DIR
Environment="PATH=$INSTALL_DIR/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
Environment="OXIDIZED_CONFIG_DIR=$CONFIG_DIR"
Environment="APP_DB_PATH=/home/oxidized/.oxidized_manager/app.db"
Environment="PORT=$APP_PORT"
ExecStart=$INSTALL_DIR/venv/bin/gunicorn --workers 4 --bind 0.0.0.0:$APP_PORT --timeout 60 oxidized_nms_manager:app
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

info "Service file created"

systemctl daemon-reload
systemctl enable oxidized-manager.service

# ============================================================================
# FIREWALL CONFIGURATION
# ============================================================================

section "Firewall Configuration"

if ufw status | grep -q "Status: active"; then
    info "UFW is active. Adding firewall rules..."
    ufw allow "$APP_PORT/tcp"
    if [ "$NGINX_PROXY_ENABLED" = true ]; then
        ufw allow 80/tcp
        info "✓ Firewall rules added for $APP_PORT (admin page) and 80 (Oxidized web GUI via Nginx)"
    else
        ufw allow 8888/tcp
        info "✓ Firewall rules added for $APP_PORT (admin page) and 8888 (Oxidized web GUI)"
    fi
else
    warn "UFW is not active. You may need to manually allow port $APP_PORT (and 80, or 8888 if not using Nginx)"
fi

# ============================================================================
# START SERVICE
# ============================================================================

section "Starting Admin Page Service"

systemctl start oxidized-manager.service
sleep 2

if systemctl is-active --quiet oxidized-manager.service; then
    info "✓ oxidized-manager service started successfully"
else
    warn "Service may have failed to start. Check logs:"
    warn "  sudo journalctl -u oxidized-manager -n 50"
fi

if netstat -tuln 2>/dev/null | grep -q ":$APP_PORT" || ss -tuln 2>/dev/null | grep -q ":$APP_PORT"; then
    info "✓ Port $APP_PORT is listening"
else
    warn "Port $APP_PORT is not listening yet. Give it a moment to start."
fi

# ============================================================================
# SETUP COMPLETE
# ============================================================================

section "Installation Complete!"

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║         Oxidized + LibreNMS Manager Successfully Installed     ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
echo "Web Interface: http://localhost:$APP_PORT"
echo ""
echo "Login:"
echo "  Username: $ADMIN_USERNAME"
echo "  Password: (the one you entered during setup)"
echo ""
echo "Configuration:"
echo "  Oxidized config: $CONFIG_DIR"
echo "  App database:    /home/oxidized/.oxidized_manager/app.db"
echo "  App directory:   $INSTALL_DIR"
echo "  Runs as user:    $SERVICE_USER"
echo ""
echo "Service Management:"
echo "  Admin page - Start:  sudo systemctl start oxidized-manager"
echo "  Admin page - Logs:   sudo journalctl -u oxidized-manager -f"
echo "  Oxidized   - Start:  sudo systemctl start oxidized"
echo "  Oxidized   - Logs:   sudo journalctl -u oxidized -f"
echo ""
if [ "$NGINX_PROXY_ENABLED" = true ]; then
echo "Oxidized Web GUI (behind Nginx, password protected):"
echo "  URL:      http://<this-host>/"
echo "  Username: $PROXY_USER"
echo ""
else
echo "Oxidized Web GUI: http://localhost:8888 (not password protected)"
echo ""
fi
echo "Quick Setup Next Steps:"
echo "  1. Open http://localhost:$APP_PORT in your browser"
echo "  2. Log in with your admin credentials"
echo "  3. Go to Settings → configure LibreNMS API (optional)"
echo "  4. Add devices via Devices tab or sync from LibreNMS"
echo ""
echo "Documentation: https://github.com/ytti/oxidized"
echo ""
