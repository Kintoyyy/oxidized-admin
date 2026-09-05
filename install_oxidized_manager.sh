#!/bin/bash

# Oxidized + LibreNMS Manager Installer
# Comprehensive setup script with Oxidized installation, venv, dependencies,
# database initialization, systemd service creation, and firewall config

set -e

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

if [ "$EUID" -eq 0 ]; then
    error "This script should NOT be run as root. Please run as your normal user with sudo privileges."
fi

info "Checking system requirements..."

# OS Check
if ! grep -q 'Ubuntu\|Debian' /etc/os-release; then
    error "This script only supports Ubuntu/Debian. Please install manually on other systems."
fi

OS_VERSION=$(lsb_release -rs)
info "Detected: Ubuntu/Debian $OS_VERSION"

# Python check
if ! command -v python3 &> /dev/null; then
    error "Python3 is not installed. Please install it first: sudo apt-get install python3 python3-pip"
fi

PYTHON_VERSION=$(python3 --version | cut -d ' ' -f 2)
info "Python version: $PYTHON_VERSION"

# Sudo check
if ! sudo -n true 2>/dev/null; then
    info "This installation requires sudo password. You will be prompted to enter it."
    sudo -v
fi

# ============================================================================
# USER INPUT
# ============================================================================

section "Configuration"

read -p "Enter installation directory (default: ~/oxidized-manager): " INSTALL_DIR
INSTALL_DIR=${INSTALL_DIR:-$HOME/oxidized-manager}

read -p "Enter config directory (default: ~/.config/oxidized): " CONFIG_DIR
CONFIG_DIR=${CONFIG_DIR:-$HOME/.config/oxidized}

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

info "Installation directory: $INSTALL_DIR"
info "Config directory: $CONFIG_DIR"
info "Application port: $APP_PORT"
info "Admin username: $ADMIN_USERNAME"

# ============================================================================
# SYSTEM DEPENDENCIES
# ============================================================================

section "Installing System Dependencies"

info "Updating package lists..."
sudo apt-get update -qq

info "Installing dependencies (this may take a few minutes)..."
sudo apt-get install -y \
    python3-dev \
    python3-venv \
    python3-pip \
    git \
    curl \
    wget \
    gunicorn \
    ufw \
    ruby \
    ruby-dev \
    libsqlite3-dev \
    libssl-dev \
    pkg-config \
    cmake \
    libssh2-1-dev \
    libicu-dev \
    zlib1g-dev \
    libgpgme-dev

info "✓ System dependencies installed"

# ============================================================================
# SETUP DIRECTORIES
# ============================================================================

section "Setting Up Directories"

mkdir -p "$INSTALL_DIR"
mkdir -p "$CONFIG_DIR"
mkdir -p "$HOME/.oxidized_manager"

info "Directories created"

# ============================================================================
# OXIDIZED INSTALLATION CHECK
# ============================================================================

section "Checking Oxidized Installation"

if command -v oxidized &> /dev/null; then
    info "✓ Oxidized is already installed"
    oxidized --version
else
    warn "Oxidized not found. Installing..."
    
    sudo gem install oxidized oxidized-web oxidized-script || warn "Oxidized installation had issues but continuing"
    
    # Initialize Oxidized config if not present
    if [ ! -f "$CONFIG_DIR/config" ]; then
        info "Creating Oxidized config directory..."
        mkdir -p "$CONFIG_DIR"
        
        # Create minimal config
        cat > "$CONFIG_DIR/config" << 'EOF'
---
username: admin
password: password
interval: 3600
use_syslog: false
log: $HOME/.config/oxidized/logs

source:
  default: csv

csv:
  file: $HOME/.config/oxidized/router.db
  delimiter: ":"

output:
  default: git

git:
  repo: $HOME/.config/oxidized/repositories.default/.git

groups:
  default:
    username: admin
    password: password
EOF
        info "Created minimal Oxidized config"
    fi
    
    # Create router.db if not present
    if [ ! -f "$CONFIG_DIR/router.db" ]; then
        touch "$CONFIG_DIR/router.db"
        info "Created router.db"
    fi
fi

# ============================================================================
# PYTHON VIRTUAL ENVIRONMENT
# ============================================================================

section "Setting Up Python Virtual Environment"

info "Creating virtual environment..."
python3 -m venv "$INSTALL_DIR/venv"

source "$INSTALL_DIR/venv/bin/activate"

info "Upgrading pip..."
pip install --upgrade pip setuptools wheel -q

# ============================================================================
# PYTHON DEPENDENCIES
# ============================================================================

section "Installing Python Dependencies"

info "Installing Flask and dependencies..."
pip install -q \
    Flask==2.3.0 \
    PyYAML==6.0 \
    requests==2.31.0 \
    gunicorn==21.0.0 \
    Werkzeug==2.3.0

info "✓ Python dependencies installed"

# ============================================================================
# DOWNLOAD APPLICATION
# ============================================================================

section "Installing Application"

# If running from current directory, copy the app
if [ -f "oxidized_nms_manager.py" ]; then
    cp oxidized_nms_manager.py "$INSTALL_DIR/"
    info "Application copied"
else
    error "oxidized_nms_manager.py not found in current directory"
fi

# ============================================================================
# DATABASE INITIALIZATION
# ============================================================================

section "Initializing Database"

cd "$INSTALL_DIR"

# Create Python script to init DB and create admin
cat > init_app.py << 'PYEOF'
import sys
sys.path.insert(0, '.')

from oxidized_nms_manager import init_db, create_user
import os

os.environ['OXIDIZED_CONFIG_DIR'] = os.path.expanduser('~/.config/oxidized')
os.environ['APP_DB_PATH'] = os.path.expanduser('~/.oxidized_manager/app.db')

init_db()
print("✓ Database initialized")

username = sys.argv[1] if len(sys.argv) > 1 else 'admin'
password = sys.argv[2] if len(sys.argv) > 2 else 'admin'
email = sys.argv[3] if len(sys.argv) > 3 else 'admin@localhost'

if create_user(username, password, email, 'admin'):
    print(f"✓ Admin user '{username}' created")
else:
    print(f"⚠ User '{username}' may already exist")
PYEOF

source venv/bin/activate
python3 init_app.py "$ADMIN_USERNAME" "$ADMIN_PASSWORD" "$ADMIN_EMAIL"
rm init_app.py

# ============================================================================
# SYSTEMD SERVICE
# ============================================================================

section "Creating Systemd Service"

SERVICE_CONTENT="[Unit]
Description=Oxidized + LibreNMS Manager
After=network.target

[Service]
Type=notify
User=$USER
WorkingDirectory=$INSTALL_DIR
Environment=\"PATH=$INSTALL_DIR/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\"
Environment=\"OXIDIZED_CONFIG_DIR=$CONFIG_DIR\"
Environment=\"APP_DB_PATH=$HOME/.oxidized_manager/app.db\"
Environment=\"PORT=$APP_PORT\"
ExecStart=$INSTALL_DIR/venv/bin/gunicorn --workers 4 --bind 0.0.0.0:$APP_PORT --timeout 60 oxidized_nms_manager:app
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"

echo "$SERVICE_CONTENT" | sudo tee /etc/systemd/system/oxidized-manager.service > /dev/null
info "Service file created"

info "Reloading systemd..."
sudo systemctl daemon-reload

info "Enabling service..."
sudo systemctl enable oxidized-manager.service

# ============================================================================
# FIREWALL CONFIGURATION
# ============================================================================

section "Firewall Configuration"

if sudo ufw status | grep -q "Status: active"; then
    info "UFW is active. Adding firewall rule for port $APP_PORT..."
    sudo ufw allow "$APP_PORT/tcp"
    info "✓ Firewall rule added"
else
    warn "UFW is not active. You may need to manually allow port $APP_PORT"
fi

# ============================================================================
# START SERVICE
# ============================================================================

section "Starting Service"

info "Starting oxidized-manager..."
sudo systemctl start oxidized-manager.service

sleep 2

if sudo systemctl is-active --quiet oxidized-manager.service; then
    info "✓ Service started successfully"
else
    warn "Service may have failed to start. Check logs:"
    warn "  sudo journalctl -u oxidized-manager -n 50"
fi

# Verify port is listening
if netstat -tuln 2>/dev/null | grep -q ":$APP_PORT" || \
   ss -tuln 2>/dev/null | grep -q ":$APP_PORT"; then
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
echo "               (or http://\$YOUR_IP:$APP_PORT from another machine)"
echo ""
echo "Login:"
echo "  Username: $ADMIN_USERNAME"
echo "  Password: (the one you entered during setup)"
echo ""
echo "Configuration:"
echo "  Oxidized config: $CONFIG_DIR"
echo "  App database:    $HOME/.oxidized_manager/app.db"
echo "  App directory:   $INSTALL_DIR"
echo ""
echo "Service Management:"
echo "  Start:    sudo systemctl start oxidized-manager"
echo "  Stop:     sudo systemctl stop oxidized-manager"
echo "  Status:   sudo systemctl status oxidized-manager"
echo "  Logs:     sudo journalctl -u oxidized-manager -f"
echo ""
echo "Quick Setup Next Steps:"
echo "  1. Open http://localhost:$APP_PORT in your browser"
echo "  2. Log in with your admin credentials"
echo "  3. Go to Settings → configure LibreNMS API (optional)"
echo "  4. Add devices via Devices tab or sync from LibreNMS"
echo "  5. Configure Oxidized in Settings if needed"
echo ""
echo "For Oxidized itself:"
echo "  - Config: $CONFIG_DIR/config"
echo "  - Router database: $CONFIG_DIR/router.db"
echo "  - Backups: $CONFIG_DIR/repositories.default"
echo ""
echo "Documentation: https://github.com/ytti/oxidized"
echo ""
