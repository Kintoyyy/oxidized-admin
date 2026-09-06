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
# BANNER
# ============================================================================

echo -e "${BLUE}"
echo "============================================================"
echo "  Oxidized Manager Installer"
echo "  https://github.com/Kintoyyy/oxidized-admin"
echo "============================================================"
echo -e "${NC}"

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

SERVER_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
SERVER_IP=${SERVER_IP:-127.0.0.1}
info "Detected server IP: $SERVER_IP"

# ============================================================================
# USER INPUT
# ============================================================================

section "Configuration"

read -p "Enter admin page install directory (default: /home/oxidized/oxidized-manager): " INSTALL_DIR
INSTALL_DIR=${INSTALL_DIR:-/home/oxidized/oxidized-manager}

read -p "Enter Oxidized config directory (default: /home/oxidized/.config/oxidized): " CONFIG_DIR
CONFIG_DIR=${CONFIG_DIR:-/home/oxidized/.config/oxidized}

APP_PORT=5000

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
info "Application port:             $APP_PORT (internal; reachable via Nginx on port 80)"
info "Admin username:                $ADMIN_USERNAME"

# ============================================================================
# DETECT EXISTING OXIDIZED INSTALLATION
# ============================================================================

section "Checking for Existing Oxidized Installation"

INSTALL_OXIDIZED=true
NUKE_OXIDIZED=false

if command -v oxidized &> /dev/null; then
    CURRENT_VERSION=$(oxidized --version 2>/dev/null || echo "unknown")
    info "Oxidized is already installed (version: $CURRENT_VERSION)"
    echo ""
    echo "  [s] Skip  - leave the existing install as-is (default)"
    echo "  [n] Nuke  - uninstall and reinstall the oxidized gems fresh, and"
    echo "              regenerate $CONFIG_DIR/config (the old one is backed up first)"
    echo "              (device backups/router.db under $CONFIG_DIR are kept)"
    echo "  [c] Cancel - exit without changing anything"
    read -p "Choice [s/n/c]: " OXIDIZED_CHOICE
    OXIDIZED_CHOICE=${OXIDIZED_CHOICE:-s}

    case "$OXIDIZED_CHOICE" in
        [Cc]*)
            error "Installation cancelled by user."
            ;;
        [Nn]*)
            info "Nuking existing oxidized gems (backups/router.db will be preserved)..."
            gem uninstall oxidized oxidized-web oxidized-script -a -x -I || warn "Some gems may not have been installed; continuing"
            INSTALL_OXIDIZED=true
            NUKE_OXIDIZED=true
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
    if sudo -u oxidized -H bash -c "oxidized -v" &> /dev/null; then
        OX_VERSION=$(sudo -u oxidized -H bash -c "oxidized -v")
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
mkdir -p "$CONFIG_DIR/logs"

if [ -f "$CONFIG_DIR/config" ] && [ "$NUKE_OXIDIZED" = true ]; then
    CONFIG_BACKUP="$CONFIG_DIR/config.bak.$(date +%Y%m%d%H%M%S)"
    cp "$CONFIG_DIR/config" "$CONFIG_BACKUP"
    info "Backed up existing config to $CONFIG_BACKUP"
    rm -f "$CONFIG_DIR/config"
fi

if [ ! -f "$CONFIG_DIR/config" ]; then
    info "Creating Oxidized config..."
    cat > "$CONFIG_DIR/config" << EOF
---
username: admin
password: password
log: $CONFIG_DIR/logs/oxidized.log
rest: 127.0.0.1:8888
resolve_dns: false
interval: 3600
use_syslog: false
debug: false
run_once: false
threads: 30
use_max_threads: false
timeout: 20
timelimit: 300
retries: 3
prompt: !ruby/regexp /^([\w.@-]+[#>]\s?)\$/
next_adds_job: false
vars: {}
groups:
  default:
    username: admin
    password: password
group_map: {}
models: {}
pid: "$CONFIG_DIR/pid"
extensions:
  oxidized-web:
    load: true
    host: 0.0.0.0
    port: 8888
crash:
  directory: "$CONFIG_DIR/crashes"
  hostnames: false
stats:
  history_size: 10
input:
  default: ssh
  debug: false
  ssh:
    secure: false
  ftp:
    passive: true
  utf8_encoded: true
output:
  default: git
  git:
    single_repo: true
    user: Oxidized
    email: oxidized@localhost
    repo: $CONFIG_DIR/repositories.default/.git
source:
  default: csv
  csv:
    file: $CONFIG_DIR/router.db
    delimiter: ":"
    map:
      name: 0
      ip: 1
      model: 2
      username: 3
      password: 4
      group: 5
model_map:
  juniper: junos
  cisco: ios
  mikrotik: routeros
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

    OXIDIZED_BIN=$(sudo -u oxidized -H bash -c "command -v oxidized" 2>/dev/null || echo "/usr/local/bin/oxidized")

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
# LIBRENMS DIRECT REST ACCESS
# ============================================================================

section "LibreNMS Direct REST Access"

info "This is separate from the LibreNMS sync toggle in the admin page's own"
info "Settings page -- it's for LibreNMS's own built-in Oxidized widget, which"
info "connects to Oxidized's REST API directly from the LibreNMS host."

LIBRENMS_NEEDS_REST=false
LIBRENMS_IP=""

read -p "Does LibreNMS need direct network access to Oxidized's REST API (port 8888)? [y/N]: " LIBRENMS_REST_ACCESS
if [[ "$LIBRENMS_REST_ACCESS" =~ ^[Yy] ]]; then
    LIBRENMS_NEEDS_REST=true
    read -p "Enter the LibreNMS server's IP address (blank = allow from any host): " LIBRENMS_IP
fi

# ============================================================================
# RESTRICT/BIND OXIDIZED'S REST/WEB INTERFACE
# ============================================================================

if [ "$LIBRENMS_NEEDS_REST" = true ]; then
    section "Binding Oxidized for LibreNMS Access"
    REST_BIND_ADDR="$SERVER_IP"
    info "Oxidized's REST/web interface will be reachable at $SERVER_IP:8888 for LibreNMS."
else
    section "Restricting Oxidized to Localhost"
    REST_BIND_ADDR="127.0.0.1"
    info "The admin page always talks to Oxidized over localhost, so its REST/web"
    info "interface never needs to be reachable from outside this host directly."
fi

if [ -f "$CONFIG_DIR/config" ]; then
    # Oxidized's core (lib/oxidized/core.rb) checks for a top-level "rest:"
    # key FIRST -- if present at all, it is used verbatim as the bind
    # address/port and "extensions.oxidized-web.host"/"port" are ignored
    # entirely (that extension only reads a "listen" key, never "host", so
    # a "host:" key there is always a silent no-op). So "rest:" is the only
    # thing that actually needs to change here.
    if grep -q '^rest:' "$CONFIG_DIR/config"; then
        sed -i -E "s/^rest:.*/rest: $REST_BIND_ADDR:8888/" "$CONFIG_DIR/config"
    elif grep -qE '^\s*oxidized-web:\s*$' "$CONFIG_DIR/config"; then
        if grep -qE '^\s*listen:' "$CONFIG_DIR/config"; then
            sed -i -E "s/^(\s*)listen:.*/\1listen: $REST_BIND_ADDR/" "$CONFIG_DIR/config"
        else
            sed -i -E "/^\s*oxidized-web:\s*\$/a\\    listen: $REST_BIND_ADDR" "$CONFIG_DIR/config"
        fi
    else
        echo "rest: $REST_BIND_ADDR:8888" >> "$CONFIG_DIR/config"
    fi

    if systemctl list-unit-files oxidized.service &> /dev/null; then
        systemctl restart oxidized.service
        sleep 2
        info "Verifying Oxidized's bind address..."
        if (ss -tlnp 2>/dev/null || netstat -tlnp 2>/dev/null) | grep ":8888" | grep -qE '0\.0\.0\.0|\*:8888|:::8888'; then
            warn "Oxidized is listening on ALL interfaces (0.0.0.0:8888) instead of just $REST_BIND_ADDR."
            warn "It may have been re-saved with a different bind address afterwards (e.g. via the admin page's Config editor)."
            warn "Check: grep -E 'rest:|listen:' $CONFIG_DIR/config"
        else
            info "✓ Oxidized's REST/web interface is bound to $REST_BIND_ADDR:8888"
        fi
    else
        warn "oxidized.service not found; restart Oxidized manually for this change to take effect."
    fi
else
    warn "$CONFIG_DIR/config not found; skipping bind-address configuration."
fi

# ============================================================================
# NGINX REVERSE PROXY
# ============================================================================

section "Nginx Reverse Proxy"

NGINX_ADMIN_ENABLED=false
NGINX_OXIDIZED_EXPOSED=false

read -p "Set up Nginx as a reverse proxy for the admin page on port 80? [Y/n]: " SETUP_NGINX_ADMIN
SETUP_NGINX_ADMIN=${SETUP_NGINX_ADMIN:-y}
if [[ "$SETUP_NGINX_ADMIN" =~ ^[Yy] ]]; then
    NGINX_ADMIN_ENABLED=true

    info "Installing Nginx..."
    apt install nginx -y

    info "Writing Nginx config for the admin page (port 80 -> 127.0.0.1:$APP_PORT)..."
    cat > /etc/nginx/sites-available/oxidized-admin << EOF
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:$APP_PORT;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF

    ln -sf /etc/nginx/sites-available/oxidized-admin /etc/nginx/sites-enabled/oxidized-admin

    if [ -f /etc/nginx/sites-enabled/default ]; then
        rm -f /etc/nginx/sites-enabled/default
        info "Removed default Nginx site"
    fi

    if [ "$LIBRENMS_NEEDS_REST" = true ]; then
        info "Skipping Nginx exposure for the Oxidized web GUI -- port 8888 on $SERVER_IP is already bound directly for LibreNMS's REST access."
        SETUP_NGINX_OXIDIZED="n"
    else
        read -p "Also expose the Oxidized web GUI externally, on port 8888, password protected? [y/N]: " SETUP_NGINX_OXIDIZED
    fi
    if [[ "$SETUP_NGINX_OXIDIZED" =~ ^[Yy] ]]; then
        NGINX_OXIDIZED_EXPOSED=true

        info "Installing Apache utils (for htpasswd)..."
        apt install apache2-utils -y

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

        info "Writing Nginx config for the Oxidized web GUI (port 8888 on $SERVER_IP)..."
        # Oxidized itself is bound to 127.0.0.1:8888 (see above), so Nginx can
        # bind that same port number on the host's own IP without a conflict --
        # a wildcard "listen 8888;" would instead clash with that loopback bind.
        cat > /etc/nginx/sites-available/oxidized-web << EOF
server {
    listen $SERVER_IP:8888;
    server_name _;

    location / {
        auth_basic "Oxidized Access";
        auth_basic_user_file /etc/nginx/.htpasswd;

        proxy_pass http://127.0.0.1:8888;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF

        ln -sf /etc/nginx/sites-available/oxidized-web /etc/nginx/sites-enabled/oxidized-web
    fi

    info "Testing Nginx configuration..."
    nginx -t

    systemctl restart nginx
    systemctl enable nginx
    info "✓ Nginx configured: port 80 -> admin page"
    if [ "$NGINX_OXIDIZED_EXPOSED" = true ]; then
        info "✓ Oxidized web GUI exposed at http://$SERVER_IP:8888/ (user: $PROXY_USER)"
    fi
else
    info "Skipping Nginx setup. Admin page stays reachable directly on port $APP_PORT."
fi

# ============================================================================
# PYTHON VIRTUAL ENVIRONMENT (ADMIN PAGE, AS 'oxidized' USER)
# ============================================================================

section "Setting Up Admin Page"

mkdir -p "$INSTALL_DIR"
mkdir -p /home/oxidized/.oxidized_manager

REPO_URL="https://github.com/Kintoyyy/oxidized-admin.git"
CLONE_DIR=$(mktemp -d /tmp/oxidized-admin.XXXXXX)

info "Pulling latest admin page source from $REPO_URL..."
git clone --depth 1 "$REPO_URL" "$CLONE_DIR"

if [ ! -f "$CLONE_DIR/oxidized_nms_manager.py" ]; then
    rm -rf "$CLONE_DIR"
    error "oxidized_nms_manager.py not found after cloning $REPO_URL"
fi

info "Replacing admin page files in $INSTALL_DIR..."
cp -f "$CLONE_DIR/oxidized_nms_manager.py" "$INSTALL_DIR/"

if [ -f "$CLONE_DIR/requirements.txt" ]; then
    cp -f "$CLONE_DIR/requirements.txt" "$INSTALL_DIR/"
fi

if compgen -G "$CLONE_DIR/*.html" > /dev/null; then
    cp -f "$CLONE_DIR"/*.html "$INSTALL_DIR/"
fi

rm -rf "$CLONE_DIR"

if id -u oxidized &> /dev/null; then
    chown -R oxidized:oxidized "$INSTALL_DIR" /home/oxidized/.oxidized_manager
    RUN_AS_OXIDIZED=true
else
    warn "'oxidized' user not available; installing admin page to run as root instead"
    RUN_AS_OXIDIZED=false
fi

info "Creating virtual environment..."
if [ "$RUN_AS_OXIDIZED" = true ]; then
    sudo -u oxidized -H bash -c "python3 -m venv '$INSTALL_DIR/venv'"
    sudo -u oxidized -H bash -c "'$INSTALL_DIR/venv/bin/pip' install --upgrade pip setuptools wheel -q"
else
    python3 -m venv "$INSTALL_DIR/venv"
    "$INSTALL_DIR/venv/bin/pip" install --upgrade pip setuptools wheel -q
fi

info "Installing Python dependencies..."
if [ "$RUN_AS_OXIDIZED" = true ]; then
    if [ -f "$INSTALL_DIR/requirements.txt" ]; then
        sudo -u oxidized -H bash -c "'$INSTALL_DIR/venv/bin/pip' install -q -r '$INSTALL_DIR/requirements.txt'"
    else
        sudo -u oxidized -H bash -c "'$INSTALL_DIR/venv/bin/pip' install -q Flask==2.3.3 PyYAML==6.0.1 requests==2.31.0 gunicorn==21.2.0 Werkzeug==2.3.7"
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
    sudo -u oxidized -H bash -c "cd '$INSTALL_DIR' && OXIDIZED_CONFIG_DIR='$CONFIG_DIR' APP_DB_PATH='/home/oxidized/.oxidized_manager/app.db' '$INSTALL_DIR/venv/bin/python3' init_app.py '$ADMIN_USERNAME' '$ADMIN_PASSWORD' '$ADMIN_EMAIL'"
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
    RULES_ADDED="$APP_PORT (admin page, direct)"
    if [ "$NGINX_ADMIN_ENABLED" = true ]; then
        ufw allow 80/tcp
        RULES_ADDED="$RULES_ADDED, 80 (admin page via Nginx)"
    fi
    if [ "$NGINX_OXIDIZED_EXPOSED" = true ]; then
        ufw allow 8888/tcp
        RULES_ADDED="$RULES_ADDED, 8888 (Oxidized web GUI via Nginx)"
    elif [ "$LIBRENMS_NEEDS_REST" = true ]; then
        if [ -n "$LIBRENMS_IP" ]; then
            ufw allow from "$LIBRENMS_IP" to any port 8888 proto tcp
            RULES_ADDED="$RULES_ADDED, 8888 from $LIBRENMS_IP only (LibreNMS REST access)"
        else
            ufw allow 8888/tcp
            RULES_ADDED="$RULES_ADDED, 8888 open to any host (LibreNMS REST access)"
        fi
    fi
    info "✓ Firewall rules added: $RULES_ADDED"
else
    warn "UFW is not active. You may need to manually allow port $APP_PORT (and 80 if using Nginx)"
fi

# ============================================================================
# START SERVICE
# ============================================================================

section "Starting Admin Page Service"

systemctl restart oxidized-manager.service
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
if [ "$NGINX_ADMIN_ENABLED" = true ]; then
echo "Web Interface: http://$SERVER_IP/  (via Nginx, port 80)"
echo "                http://$SERVER_IP:$APP_PORT/  (direct)"
else
echo "Web Interface: http://$SERVER_IP:$APP_PORT/"
fi
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
if [ "$NGINX_OXIDIZED_EXPOSED" = true ]; then
echo "Oxidized Web GUI (behind Nginx, password protected):"
echo "  URL:      http://$SERVER_IP:8888/"
echo "  Username: $PROXY_USER"
echo ""
elif [ "$LIBRENMS_NEEDS_REST" = true ]; then
echo "Oxidized REST API (for LibreNMS's built-in widget, unauthenticated):"
echo "  URL:      http://$SERVER_IP:8888/"
if [ -n "$LIBRENMS_IP" ]; then
echo "  Allowed:  $LIBRENMS_IP only"
else
echo "  Allowed:  any host (no IP restriction set)"
fi
echo ""
else
echo "Oxidized Web GUI: not publicly exposed (bound to 127.0.0.1:8888, used internally by the admin page)"
echo ""
fi
echo "Quick Setup Next Steps:"
echo "  1. Open the Web Interface URL above in your browser"
echo "  2. Log in with your admin credentials"
echo "  3. Go to Settings → configure LibreNMS API (optional)"
echo "  4. Add devices via Devices tab or sync from LibreNMS"
echo ""
echo "Project:     https://github.com/Kintoyyy/oxidized-admin"
echo "Credits:     https://github.com/ytti/oxidized + https://github.com/ytti/oxidized-web"
echo "Inspired by: https://github.com/MrMime71/oxidized-configuration-manager-v1"
echo ""
