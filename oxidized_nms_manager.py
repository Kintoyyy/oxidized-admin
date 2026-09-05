#!/usr/bin/env python3
"""
Oxidized + LibreNMS Admin Manager
Professional NOC dashboard with device management, backups, and monitoring integration.
Includes auto-installer for Oxidized and full configuration management.
"""

import csv
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

import requests
import yaml
from flask import (
    Flask, Response, flash, jsonify, redirect, render_template_string,
    request, session, url_for
)
from werkzeug.security import check_password_hash, generate_password_hash

try:
    import paramiko
    HAS_PARAMIKO = True
except ImportError:
    HAS_PARAMIKO = False

try:
    from git import Repo
    HAS_GITPYTHON = True
except ImportError:
    HAS_GITPYTHON = False

# ============================================================================
# CONFIGURATION & SETUP
# ============================================================================

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'oxidized-nms-default-key-change-me')

CONFIG_DIR = Path(os.environ.get('OXIDIZED_CONFIG_DIR', Path.home() / '.config' / 'oxidized'))
DB_PATH = Path(os.environ.get('APP_DB_PATH', Path.home() / '.oxidized_manager' / 'app.db'))
BACKUP_DIR = DB_PATH.parent / 'backups'

# Ensure directories exist
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

OXIDIZED_CONFIG_PATH = CONFIG_DIR / 'config'
OXIDIZED_ROUTER_DB = CONFIG_DIR / 'router.db'
OXIDIZED_BACKUPS = CONFIG_DIR / 'repositories.default'

# ============================================================================
# DATABASE & INITIALIZATION
# ============================================================================

def init_db():
    """Initialize SQLite database with schema."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Users table
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        email TEXT,
        role TEXT DEFAULT 'operator',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_login TIMESTAMP
    )''')
    
    # Settings table
    c.execute('''CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT,
        value_type TEXT DEFAULT 'string',
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # Device groups table
    c.execute('''CREATE TABLE IF NOT EXISTS device_groups (
        id INTEGER PRIMARY KEY,
        name TEXT UNIQUE NOT NULL,
        description TEXT,
        default_username TEXT,
        default_password TEXT,
        enabled BOOLEAN DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # Device metadata table (extensions to router.db)
    c.execute('''CREATE TABLE IF NOT EXISTS device_metadata (
        device_ip TEXT PRIMARY KEY,
        device_name TEXT,
        device_group TEXT,
        librenms_device_id INTEGER,
        enabled BOOLEAN DEFAULT 1,
        tags TEXT,
        backup_enabled BOOLEAN DEFAULT 1,
        last_backup_at TIMESTAMP,
        backup_status TEXT DEFAULT 'pending',
        ssh_port INTEGER DEFAULT 22,
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # Audit log table
    c.execute('''CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY,
        user_id INTEGER,
        action TEXT NOT NULL,
        resource_type TEXT,
        resource_id TEXT,
        details TEXT,
        ip_address TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # Backup history table
    c.execute('''CREATE TABLE IF NOT EXISTS backup_history (
        id INTEGER PRIMARY KEY,
        device_ip TEXT NOT NULL,
        device_name TEXT,
        backup_file TEXT,
        file_hash TEXT,
        file_size INTEGER,
        status TEXT DEFAULT 'success',
        error_message TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    conn.commit()
    conn.close()

def get_setting(key, default=None):
    """Fetch a setting from database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    try:
        c.execute('SELECT value, value_type FROM settings WHERE key = ?', (key,))
        row = c.fetchone()
    except sqlite3.OperationalError:
        # settings table doesn't exist yet (DB not initialized) - nothing configured
        row = None
    conn.close()

    if not row:
        return default
    
    value = row['value']
    if row['value_type'] == 'json':
        return json.loads(value)
    elif row['value_type'] == 'int':
        return int(value)
    elif row['value_type'] == 'bool':
        return value.lower() in ('true', '1', 'yes')
    return value

def set_setting(key, value, value_type='string'):
    """Store a setting in database."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    if value_type == 'json':
        value = json.dumps(value)
    elif value_type == 'bool':
        value = 'true' if value else 'false'
    
    c.execute('''INSERT OR REPLACE INTO settings (key, value, value_type, updated_at)
                 VALUES (?, ?, ?, CURRENT_TIMESTAMP)''', (key, str(value), value_type))
    conn.commit()
    conn.close()

def log_audit(action, resource_type=None, resource_id=None, details=None):
    """Log an audit event."""
    user_id = session.get('user_id')
    ip = request.remote_addr
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''INSERT INTO audit_log (user_id, action, resource_type, resource_id, details, ip_address)
                 VALUES (?, ?, ?, ?, ?, ?)''',
              (user_id, action, resource_type, resource_id, details, ip))
    conn.commit()
    conn.close()

# ============================================================================
# SSH CONNECTION TESTING
# ============================================================================

def test_ssh_connection(host, username, password, port=22, timeout=10):
    """Test SSH connection to a device."""
    if not HAS_PARAMIKO:
        return {'status': 'error', 'message': 'Paramiko not installed. Run: pip install paramiko'}
    
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        ssh.connect(
            hostname=host,
            port=port,
            username=username,
            password=password,
            timeout=timeout,
            look_for_keys=False,
            allow_agent=False
        )
        
        # Test command
        stdin, stdout, stderr = ssh.exec_command('show version')
        output = stdout.read().decode('utf-8', errors='ignore')[:200]
        
        ssh.close()
        
        return {
            'status': 'success',
            'message': f'Connected successfully to {host}:{port}',
            'output': output
        }
    except paramiko.AuthenticationException:
        return {'status': 'error', 'message': 'Authentication failed - check username/password'}
    except paramiko.SSHException as e:
        return {'status': 'error', 'message': f'SSH error: {str(e)}'}
    except Exception as e:
        return {'status': 'error', 'message': f'Connection failed: {str(e)}'}

# ============================================================================
# GITHUB INTEGRATION (OPTIONAL)
# ============================================================================

class GitHubBackupClient:
    def __init__(self):
        self.enabled = False
        self.repo_url = get_setting('github_repo_url', '')
        self.branch = get_setting('github_branch', 'main')
        self.token = get_setting('github_token', '')
        self.local_path = Path.home() / '.oxidized_manager' / 'github_backup'
        
        if self.repo_url and self.token and HAS_GITPYTHON:
            self.enabled = True
    
    def init_repo(self):
        """Initialize Git repo if not exists."""
        if not self.enabled or not HAS_GITPYTHON:
            return False
        
        try:
            if not self.local_path.exists():
                # Clone repo
                auth_url = self.repo_url.replace('https://', f'https://{self.token}@')
                Repo.clone_from(auth_url, str(self.local_path), branch=self.branch)
            return True
        except Exception as e:
            print(f'GitHub repo init error: {e}')
            return False
    
    def push_backup(self, device_name, config_content):
        """Push backup to GitHub."""
        if not self.enabled or not HAS_GITPYTHON:
            return False
        
        try:
            if not self.init_repo():
                return False
            
            repo = Repo(str(self.local_path))
            
            # Create device directory
            device_dir = self.local_path / device_name
            device_dir.mkdir(exist_ok=True)
            
            # Write config
            config_file = device_dir / f'{datetime.now().strftime("%Y%m%d_%H%M%S")}.conf'
            config_file.write_text(config_content)
            
            # Commit and push
            repo.index.add([str(config_file)])
            repo.index.commit(f'Backup {device_name} at {datetime.now()}')
            repo.remotes.origin.push(self.branch)
            
            return True
        except Exception as e:
            print(f'GitHub push error: {e}')
            return False

github_client = GitHubBackupClient()

# ============================================================================
# OXIDIZED API INTEGRATION
# ============================================================================

OXIDIZED_API_URL = 'http://localhost:8888'

def get_oxidized_api_url():
    """Oxidized API base URL, as configured in Settings (falls back to the default)."""
    return get_setting('oxidized_api_url', OXIDIZED_API_URL)

def get_oxidized_nodes():
    """Fetch device list from Oxidized REST API (oxidized-web's /nodes.json)."""
    try:
        response = requests.get(f'{get_oxidized_api_url()}/nodes.json', timeout=5)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f'Oxidized API error: {e}')
        return []

def get_oxidized_node_config(node_name, group='default'):
    """Fetch a node's current config from Oxidized (triggers a live fetch over SSH)."""
    try:
        group_seg = f'{group}/' if group else ''
        response = requests.get(f'{get_oxidized_api_url()}/node/fetch/{group_seg}{node_name}.json', timeout=30)
        response.raise_for_status()
        lines = response.json()
        if isinstance(lines, list):
            return ''.join(lines)
        return str(lines)
    except Exception as e:
        print(f'Error fetching config: {e}')
        return None

def get_oxidized_node_history(node_name, group='default'):
    """Fetch a node's stored backup version history from Oxidized."""
    node_full = f'{group}/{node_name}' if group else node_name
    try:
        response = requests.get(
            f'{get_oxidized_api_url()}/node/version.json',
            params={'node_full': node_full}, timeout=5
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f'Error fetching history: {e}')
        return []

def get_oxidized_stats():
    """Fetch per-node run stats from Oxidized (oxidized-web's /nodes/stats.json)."""
    try:
        response = requests.get(f'{get_oxidized_api_url()}/nodes/stats.json', timeout=5)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f'Oxidized stats API error: {e}')
        return {}

def _stat_value(stats, *keys):
    """Return the first matching key's value from a stats dict, trying several
    likely spellings since Oxidized's exact stats schema isn't pinned down."""
    if not isinstance(stats, dict):
        return None
    for k in keys:
        if k in stats and stats[k] is not None:
            return stats[k]
    return None

# ============================================================================
# LIBRENMS API INTEGRATION
# ============================================================================

class LibreNMSClient:
    def __init__(self):
        self.base_url = get_setting('librenms_url', 'http://localhost')
        self.api_token = get_setting('librenms_token', '')
        self.enabled = self.api_token and self.base_url
    
    def get_devices(self):
        """Fetch devices from LibreNMS."""
        if not self.enabled:
            return []
        
        try:
            headers = {'X-Auth-Token': self.api_token}
            response = requests.get(
                f'{self.base_url}/api/v0/devices',
                headers=headers,
                timeout=10
            )
            response.raise_for_status()
            return response.json().get('devices', [])
        except Exception as e:
            print(f'LibreNMS error: {e}')
            return []
    
    def get_device(self, device_id):
        """Fetch single device from LibreNMS."""
        if not self.enabled:
            return None
        
        try:
            headers = {'X-Auth-Token': self.api_token}
            response = requests.get(
                f'{self.base_url}/api/v0/devices/{device_id}',
                headers=headers,
                timeout=10
            )
            response.raise_for_status()
            return response.json().get('devices', [{}])[0]
        except Exception as e:
            print(f'LibreNMS error: {e}')
            return None
    
    def get_alerts(self, device_id=None):
        """Fetch alerts from LibreNMS."""
        if not self.enabled:
            return []
        
        try:
            headers = {'X-Auth-Token': self.api_token}
            url = f'{self.base_url}/api/v0/alerts'
            if device_id:
                url += f'?device_id={device_id}'
            
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            return response.json().get('alerts', [])
        except Exception as e:
            print(f'LibreNMS error: {e}')
            return []

librenms = LibreNMSClient()

# ============================================================================
# YAML & ROUTER.DB HANDLING
# ============================================================================

def ruby_regexp_constructor(loader, node):
    """Handle !ruby/regexp tags in YAML."""
    return loader.construct_scalar(node)

yaml.SafeLoader.add_constructor("!ruby/regexp", ruby_regexp_constructor)

def read_oxidized_config():
    """Read Oxidized config YAML."""
    try:
        with open(OXIDIZED_CONFIG_PATH, 'r') as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}
    except yaml.YAMLError as e:
        print(f'YAML error: {e}')
        return {}

def write_oxidized_config(config):
    """Write Oxidized config YAML."""
    try:
        # Create backup
        if OXIDIZED_CONFIG_PATH.exists():
            backup = OXIDIZED_CONFIG_PATH.with_suffix(
                f'.{datetime.now().strftime("%Y%m%d_%H%M%S")}.bak'
            )
            shutil.copy2(OXIDIZED_CONFIG_PATH, backup)
        
        with open(OXIDIZED_CONFIG_PATH, 'w') as f:
            yaml.safe_dump(config, f, default_flow_style=False)
        
        log_audit('config_updated', 'oxidized_config')
        return True
    except Exception as e:
        print(f'Error writing config: {e}')
        return False

def read_router_db():
    """Read router.db CSV."""
    devices = []
    try:
        if OXIDIZED_ROUTER_DB.exists():
            with open(OXIDIZED_ROUTER_DB, 'r') as f:
                for row in csv.reader(f, delimiter=':'):
                    if len(row) >= 6:
                        devices.append({
                            'name': row[0],
                            'ip': row[1],
                            'model': row[2],
                            'username': row[3],
                            'password': row[4],
                            'group': row[5],
                            'enable': row[6] if len(row) > 6 else '',
                            'ssh_port': int(row[7]) if len(row) > 7 and row[7] else 22
                        })
    except Exception as e:
        print(f'Error reading router.db: {e}')
    return devices

def write_router_db(devices):
    """Write router.db CSV."""
    try:
        # Create backup
        if OXIDIZED_ROUTER_DB.exists():
            backup = OXIDIZED_ROUTER_DB.with_suffix(
                f'.{datetime.now().strftime("%Y%m%d_%H%M%S")}.bak'
            )
            shutil.copy2(OXIDIZED_ROUTER_DB, backup)
        
        with open(OXIDIZED_ROUTER_DB, 'w', newline='') as f:
            writer = csv.writer(f, delimiter=':')
            for dev in devices:
                writer.writerow([
                    dev['name'], dev['ip'], dev['model'],
                    dev['username'], dev['password'], dev['group'],
                    dev.get('enable', ''), dev.get('ssh_port', 22)
                ])
        
        log_audit('router_db_updated', 'router.db')
        return True
    except Exception as e:
        print(f'Error writing router.db: {e}')
        return False

# ============================================================================
# AUTHENTICATION & AUTHORIZATION
# ============================================================================

def create_user(username, password, email=None, role='operator'):
    """Create a user in database."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute('''INSERT INTO users (username, password_hash, email, role)
                     VALUES (?, ?, ?, ?)''',
                  (username, generate_password_hash(password), email, role))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def get_user(username):
    """Fetch user from database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE username = ?', (username,))
    row = c.fetchone()
    conn.close()
    return row

def login_user(username, password):
    """Verify credentials and set session."""
    user = get_user(username)
    if not user or not check_password_hash(user['password_hash'], password):
        return False
    
    session['user_id'] = user['id']
    session['username'] = user['username']
    session['role'] = user['role']
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?', (user['id'],))
    conn.commit()
    conn.close()
    
    return True

def requires_auth(f):
    """Decorator to require authentication."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def requires_admin(f):
    """Decorator to require admin role."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('role') != 'admin':
            flash('Admin access required', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated

# ============================================================================
# INSTALLER FUNCTIONS
# ============================================================================

def check_oxidized_installed():
    """Check if Oxidized is installed and running."""
    try:
        response = requests.get(f'{get_oxidized_api_url()}/nodes', timeout=2)
        return response.status_code == 200
    except:
        return False

def install_oxidized():
    """Install Oxidized on the system."""
    print('Installing Oxidized...')
    try:
        subprocess.run(['sudo', 'apt-get', 'update'], check=True, capture_output=True)
        subprocess.run([
            'sudo', 'apt-get', 'install', '-y',
            'ruby', 'ruby-dev', 'libsqlite3-dev', 'libssl-dev',
            'pkg-config', 'cmake', 'libssh2-1-dev', 'libicu-dev',
            'zlib1g-dev', 'libgpgme-dev'
        ], check=True, capture_output=True)
        
        subprocess.run(['sudo', 'gem', 'install', 'oxidized'], check=True, capture_output=True)
        subprocess.run(['sudo', 'gem', 'install', 'oxidized-web'], check=True, capture_output=True)
        subprocess.run(['sudo', 'gem', 'install', 'oxidized-script'], check=True, capture_output=True)
        
        return True
    except Exception as e:
        print(f'Oxidized installation failed: {e}')
        return False

def setup_oxidized_service():
    """Create systemd service for Oxidized."""
    service_content = '''[Unit]
Description=Oxidized Configuration Management
After=network.target

[Service]
Type=simple
User=oxidized
WorkingDirectory=/home/oxidized
ExecStart=/usr/local/bin/oxidized
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
'''
    
    try:
        service_path = Path('/etc/systemd/system/oxidized.service')
        subprocess.run(['sudo', 'tee', str(service_path)], input=service_content.encode(), check=True)
        subprocess.run(['sudo', 'systemctl', 'daemon-reload'], check=True)
        subprocess.run(['sudo', 'systemctl', 'enable', 'oxidized'], check=True)
        subprocess.run(['sudo', 'systemctl', 'start', 'oxidized'], check=True)
        return True
    except Exception as e:
        print(f'Service setup failed: {e}')
        return False

# ============================================================================
# ROUTES - AUTH
# ============================================================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if login_user(username, password):
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid credentials', 'danger')
    
    return render_template_string(LOGIN_TEMPLATE)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/setup', methods=['GET', 'POST'])
def setup():
    """Initial setup page."""
    if get_user('admin'):
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        username = request.form.get('username', 'admin')
        password = request.form.get('password')
        email = request.form.get('email')
        
        if len(password) < 8:
            flash('Password must be at least 8 characters', 'danger')
        elif create_user(username, password, email, 'admin'):
            # Create initial settings
            set_setting('app_name', 'Oxidized NMS Manager')
            set_setting('backup_retention_days', 30, 'int')
            set_setting('librenms_sync_enabled', False, 'bool')
            
            flash('Admin user created successfully. Please log in.', 'success')
            return redirect(url_for('login'))
        else:
            flash('User creation failed', 'danger')
    
    return render_template_string(SETUP_TEMPLATE)

# ============================================================================
# ROUTES - DASHBOARD
# ============================================================================

@app.route('/')
@requires_auth
def dashboard():
    """Main NOC dashboard."""
    oxidized_nodes = get_oxidized_nodes()
    oxidized_stats = get_oxidized_stats()

    # Enrich with metadata and LibreNMS data
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    devices = []
    for node in oxidized_nodes:
        c.execute('SELECT * FROM device_metadata WHERE device_ip = ?', (node.get('ip'),))
        meta = c.fetchone()
        node_stats = oxidized_stats.get(node.get('name'), {}) if isinstance(oxidized_stats, dict) else {}

        devices.append({
            'name': node.get('name'),
            'ip': node.get('ip'),
            'model': node.get('model'),
            'group': node.get('group') or 'default',
            'status': node.get('status'),
            'last_update': node.get('time'),
            'mtime': node.get('mtime'),
            'metadata': dict(meta) if meta else {},
            'total_failures': _stat_value(node_stats, 'total_failures', 'failures', 'fail_count'),
            'avg_run_time': _stat_value(node_stats, 'average_run_time', 'avg_run_time', 'avg_time'),
            'last_failure': _stat_value(node_stats, 'last_failure', 'last_fail'),
            'stats_raw': node_stats
        })
    conn.close()
    
    # Summary stats
    stats = {
        'total': len(devices),
        'healthy': sum(1 for d in devices if d['status'] == 'success'),
        'failed': sum(1 for d in devices if d['status'] == 'error'),
        'pending': sum(1 for d in devices if d['status'] not in ('success', 'error'))
    }
    
    return render_template_string(DASHBOARD_TEMPLATE, 
                                  devices=devices, 
                                  stats=stats,
                                  oxidized_api=f'{OXIDIZED_API_URL}/nodes')

@app.route('/api/devices')
@requires_auth
def api_devices():
    """REST API endpoint for device list."""
    oxidized_nodes = get_oxidized_nodes()
    return jsonify({'devices': oxidized_nodes})

def get_device_group(device_name):
    """Look up a device's group from router.db (falls back to 'default')."""
    for dev in read_router_db():
        if dev['name'] == device_name:
            return dev.get('group') or 'default'
    return 'default'

@app.route('/device/<device_name>')
@requires_auth
def device_detail(device_name):
    """View device details and config."""
    group = get_device_group(device_name)
    config = get_oxidized_node_config(device_name, group)
    history = get_oxidized_node_history(device_name, group)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT * FROM backup_history WHERE device_name = ? ORDER BY created_at DESC LIMIT 20',
              (device_name,))
    backups = [dict(row) for row in c.fetchall()]
    conn.close()

    return render_template_string(DEVICE_DETAIL_TEMPLATE,
                                  device_name=device_name,
                                  device_group=group,
                                  config=config,
                                  history=history,
                                  backups=backups)

@app.route('/device/<device_name>/config')
@requires_auth
def get_device_config(device_name):
    """Fetch device config (API endpoint)."""
    config = get_oxidized_node_config(device_name, get_device_group(device_name))
    if not config:
        return jsonify({'error': 'Config not found'}), 404
    return config, 200, {'Content-Type': 'text/plain'}

@app.route('/api/oxidized/fetch/<device_name>', methods=['POST'])
@requires_auth
def api_oxidized_fetch(device_name):
    """Trigger a live config fetch for a device (used by the 'Update Configuration' button)."""
    group = get_device_group(device_name)
    config = get_oxidized_node_config(device_name, group)
    if config is None:
        return jsonify({'status': 'error', 'message': 'Failed to fetch configuration from Oxidized'}), 500
    log_audit('device_config_updated', 'device', device_name)
    return jsonify({'status': 'success', 'message': 'Configuration updated', 'content': config})

@app.route('/api/oxidized/version-content')
@requires_auth
def api_oxidized_version_content():
    """Proxy: fetch a specific stored config version's raw content from Oxidized.
    Forwards whatever query params the caller sends straight through to
    oxidized-web's /node/version/view.json, since the exact set of fields
    (oid/epoch/num/group/node) is whatever that version's own history entry carried."""
    params = {k: v for k, v in request.args.items()}
    try:
        response = requests.get(f'{get_oxidized_api_url()}/node/version/view.json', params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        content = ''.join(data) if isinstance(data, list) else str(data)
        return jsonify({'status': 'success', 'content': content})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/oxidized/diff')
@requires_auth
def api_oxidized_diff():
    """Proxy: diff a stored version against the one immediately before it,
    via oxidized-web's /node/version/diffs. Forwards whatever params the
    caller sends (node/group/oid/epoch/num from that version's own history
    entry) and forces JSON output, since this route has no .json path form."""
    params = {k: v for k, v in request.args.items()}
    params['format'] = 'json'
    try:
        response = requests.get(f'{get_oxidized_api_url()}/node/version/diffs', params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        content = ''.join(data) if isinstance(data, list) else str(data)
        return jsonify({'status': 'success', 'content': content})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ============================================================================
# ROUTES - MANAGEMENT
# ============================================================================

@app.route('/api/test-ssh', methods=['POST'])
@requires_auth
def api_test_ssh():
    """Test SSH connection to a device."""
    host = request.form.get('host')
    username = request.form.get('username')
    password = request.form.get('password')
    port = int(request.form.get('port', 22))
    
    result = test_ssh_connection(host, username, password, port)
    log_audit('ssh_test', 'device', host, json.dumps(result))
    
    return jsonify(result)

@app.route('/groups', methods=['GET', 'POST'])
@requires_auth
@requires_admin
def manage_groups():
    """Manage device groups."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'add':
            name = request.form.get('name')
            description = request.form.get('description', '')
            default_username = request.form.get('default_username', '')
            default_password = request.form.get('default_password', '')
            
            try:
                c.execute('''INSERT INTO device_groups 
                             (name, description, default_username, default_password)
                             VALUES (?, ?, ?, ?)''',
                          (name, description, default_username, default_password))
                conn.commit()
                log_audit('group_created', 'group', name)
                flash(f'Group "{name}" created', 'success')
            except sqlite3.IntegrityError:
                flash('Group already exists', 'danger')
        
        elif action == 'delete':
            group_id = request.form.get('group_id')
            c.execute('SELECT name FROM device_groups WHERE id = ?', (group_id,))
            group = c.fetchone()
            if group:
                c.execute('DELETE FROM device_groups WHERE id = ?', (group_id,))
                conn.commit()
                log_audit('group_deleted', 'group', group['name'])
                flash(f'Group deleted', 'success')
        
        elif action == 'update':
            group_id = request.form.get('group_id')
            name = request.form.get('name')
            description = request.form.get('description', '')
            default_username = request.form.get('default_username', '')
            default_password = request.form.get('default_password', '')
            
            c.execute('''UPDATE device_groups 
                         SET name=?, description=?, default_username=?, default_password=?
                         WHERE id=?''',
                      (name, description, default_username, default_password, group_id))
            conn.commit()
            log_audit('group_updated', 'group', name)
            flash(f'Group updated', 'success')
    
    c.execute('SELECT * FROM device_groups ORDER BY name')
    groups = [dict(row) for row in c.fetchall()]
    conn.close()
    
    return render_template_string(GROUPS_MANAGEMENT_TEMPLATE, groups=groups)

@app.route('/devices', methods=['GET', 'POST'])
@requires_auth
def manage_devices():
    """Device management page."""
    devices = read_router_db()
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'add':
            new_device = {
                'name': request.form.get('name'),
                'ip': request.form.get('ip'),
                'model': request.form.get('model'),
                'username': request.form.get('username'),
                'password': request.form.get('password'),
                'group': request.form.get('group', 'default'),
                'ssh_port': int(request.form.get('ssh_port', 22)),
                'enable': request.form.get('enable', '')
            }
            devices.append(new_device)
            log_audit('device_added', 'device', new_device['name'])
        
        elif action == 'delete':
            ip = request.form.get('ip')
            devices = [d for d in devices if d['ip'] != ip]
            log_audit('device_deleted', 'device', ip)
        
        elif action == 'update':
            ip = request.form.get('ip')
            for dev in devices:
                if dev['ip'] == ip:
                    dev.update({
                        'name': request.form.get('name'),
                        'model': request.form.get('model'),
                        'username': request.form.get('username'),
                        'password': request.form.get('password'),
                        'group': request.form.get('group'),
                        'ssh_port': int(request.form.get('ssh_port', 22)),
                        'enable': request.form.get('enable', '')
                    })
                    log_audit('device_updated', 'device', ip)
        
        if write_router_db(devices):
            flash('Changes saved. Oxidized will pick up changes on next sync.', 'success')
        else:
            flash('Error saving changes', 'danger')
        
        return redirect(url_for('manage_devices'))
    
    # Get groups for dropdown
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT name FROM device_groups ORDER BY name')
    groups = [dict(row)['name'] for row in c.fetchall()]
    conn.close()
    
    return render_template_string(DEVICE_MANAGEMENT_TEMPLATE, devices=devices, groups=groups)

@app.route('/config', methods=['GET', 'POST'])
@requires_auth
@requires_admin
def manage_config():
    """Oxidized config management."""
    config = read_oxidized_config()
    
    if request.method == 'POST':
        if request.form.get('action') == 'update_yaml':
            try:
                new_config = yaml.safe_load(request.form.get('yaml_content'))
                if write_oxidized_config(new_config):
                    flash('Configuration saved successfully', 'success')
                    config = new_config
                else:
                    flash('Error saving configuration', 'danger')
            except yaml.YAMLError as e:
                flash(f'YAML error: {str(e)}', 'danger')
        
        return redirect(url_for('manage_config'))
    
    config_yaml = yaml.dump(config, default_flow_style=False)
    return render_template_string(CONFIG_MANAGEMENT_TEMPLATE, config=config, config_yaml=config_yaml)

@app.route('/api/oxidized/restart', methods=['POST'])
@requires_auth
@requires_admin
def api_oxidized_restart():
    """Restart the Oxidized systemd service."""
    try:
        result = subprocess.run(
            ['sudo', 'systemctl', 'restart', 'oxidized'],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            log_audit('oxidized_restart', 'oxidized')
            return jsonify({'status': 'success', 'message': 'Oxidized service restarted'})
        log_audit('oxidized_restart_failed', 'oxidized', details=result.stderr.strip())
        return jsonify({'status': 'error', 'message': result.stderr.strip() or 'Failed to restart Oxidized'}), 500
    except subprocess.TimeoutExpired:
        return jsonify({'status': 'error', 'message': 'Restart timed out'}), 500
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/oxidized/test', methods=['GET'])
@requires_auth
@requires_admin
def api_oxidized_test():
    """Debug: hit the Oxidized REST API directly and return the raw result."""
    url = f'{get_oxidized_api_url()}/nodes.json'
    result = {'url': url}
    start = datetime.now()
    try:
        response = requests.get(url, timeout=8)
        result['elapsed_ms'] = round((datetime.now() - start).total_seconds() * 1000, 1)
        result['status_code'] = response.status_code
        result['ok'] = response.status_code == 200
        result['body_preview'] = response.text[:2000]
        try:
            result['parsed_json'] = response.json()
        except Exception:
            result['parsed_json'] = None
    except requests.exceptions.ConnectionError as e:
        result['ok'] = False
        result['error'] = f'Connection error (nothing listening / refused?): {e}'
    except requests.exceptions.Timeout as e:
        result['ok'] = False
        result['error'] = f'Timed out: {e}'
    except Exception as e:
        result['ok'] = False
        result['error'] = f'{type(e).__name__}: {e}'
    return jsonify(result)

@app.route('/settings', methods=['GET', 'POST'])
@requires_auth
@requires_admin
def settings():
    """Application settings."""
    if request.method == 'POST':
        set_setting('app_name', request.form.get('app_name', 'Oxidized NMS Manager'))
        set_setting('librenms_url', request.form.get('librenms_url', ''))
        set_setting('librenms_token', request.form.get('librenms_token', ''))
        set_setting('librenms_sync_enabled', request.form.get('librenms_sync_enabled') == 'on', 'bool')
        set_setting('backup_retention_days', int(request.form.get('backup_retention_days', 30)), 'int')
        set_setting('oxidized_api_url', request.form.get('oxidized_api_url', OXIDIZED_API_URL))
        set_setting('github_repo_url', request.form.get('github_repo_url', ''))
        set_setting('github_token', request.form.get('github_token', ''))
        set_setting('github_branch', request.form.get('github_branch', 'main'))
        set_setting('github_sync_enabled', request.form.get('github_sync_enabled') == 'on', 'bool')
        
        log_audit('settings_updated', 'settings')
        flash('Settings saved successfully', 'success')
        
        # Reinitialize clients
        librenms.base_url = get_setting('librenms_url', 'http://localhost')
        librenms.api_token = get_setting('librenms_token', '')
        librenms.enabled = librenms.api_token and librenms.base_url
        
        github_client.repo_url = get_setting('github_repo_url', '')
        github_client.token = get_setting('github_token', '')
        github_client.branch = get_setting('github_branch', 'main')
        github_client.enabled = github_client.repo_url and github_client.token and HAS_GITPYTHON
        
        return redirect(url_for('settings'))
    
    settings_data = {
        'app_name': get_setting('app_name', 'Oxidized NMS Manager'),
        'librenms_url': get_setting('librenms_url', ''),
        'librenms_token': get_setting('librenms_token', ''),
        'librenms_sync_enabled': get_setting('librenms_sync_enabled', False),
        'backup_retention_days': get_setting('backup_retention_days', 30),
        'oxidized_api_url': get_setting('oxidized_api_url', OXIDIZED_API_URL),
        'github_repo_url': get_setting('github_repo_url', ''),
        'github_token': get_setting('github_token', ''),
        'github_branch': get_setting('github_branch', 'main'),
        'github_sync_enabled': get_setting('github_sync_enabled', False),
        'has_gitpython': HAS_GITPYTHON,
        'has_paramiko': HAS_PARAMIKO
    }
    
    oxidized_status = check_oxidized_installed()
    
    return render_template_string(SETTINGS_TEMPLATE, 
                                  settings=settings_data,
                                  oxidized_status=oxidized_status)

@app.route('/users', methods=['GET', 'POST'])
@requires_auth
@requires_admin
def manage_users():
    """User management."""
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'add':
            username = request.form.get('username')
            password = request.form.get('password')
            email = request.form.get('email')
            role = request.form.get('role', 'operator')
            
            if create_user(username, password, email, role):
                log_audit('user_created', 'user', username)
                flash(f'User {username} created', 'success')
            else:
                flash('User creation failed (duplicate username?)', 'danger')
        
        return redirect(url_for('manage_users'))
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT id, username, email, role, last_login FROM users')
    users = [dict(row) for row in c.fetchall()]
    conn.close()
    
    return render_template_string(USER_MANAGEMENT_TEMPLATE, users=users)

# ============================================================================
# ROUTES - LIBRENMS INTEGRATION
# ============================================================================

@app.route('/librenms/sync', methods=['POST'])
@requires_auth
@requires_admin
def librenms_sync():
    """Sync devices from LibreNMS to Oxidized router.db."""
    if not librenms.enabled:
        return jsonify({'error': 'LibreNMS not configured'}), 400
    
    devices = read_router_db()
    lnms_devices = librenms.get_devices()
    
    for lnms_dev in lnms_devices:
        ip = lnms_dev.get('ip', '')
        hostname = lnms_dev.get('hostname', '')
        sysDescr = lnms_dev.get('sysDescr', '')
        
        # Check if device already in router.db
        exists = any(d['ip'] == ip for d in devices)
        
        if not exists and ip:
            new_device = {
                'name': hostname or ip,
                'ip': ip,
                'model': 'unknown',  # Will be set by Oxidized discovery
                'username': 'admin',
                'password': '',
                'group': 'librenms-synced',
                'enable': ''
            }
            devices.append(new_device)
    
    if write_router_db(devices):
        log_audit('librenms_sync', 'device_list')
        return jsonify({'status': 'synced', 'count': len(devices)})
    
    return jsonify({'error': 'Sync failed'}), 500

@app.route('/librenms/alerts')
@requires_auth
def librenms_alerts():
    """View LibreNMS alerts for devices."""
    if not librenms.enabled:
        return jsonify({'error': 'LibreNMS not configured'}), 400
    
    alerts = librenms.get_alerts()
    return jsonify({'alerts': alerts})

# ============================================================================
# HTML TEMPLATES
# ============================================================================

# Shared shadcn-inspired design tokens + components, reused by every page.
BASE_CSS = '''
:root {
    --background: #09090b;
    --foreground: #fafafa;
    --card: #18181b;
    --border: #27272a;
    --input: #27272a;
    --ring: #60a5fa;
    --muted: #27272a;
    --muted-foreground: #a1a1aa;
    --primary: #fafafa;
    --primary-foreground: #18181b;
    --accent: #27272a;
    --destructive: #ef4444;
    --radius: 8px;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", Roboto, sans-serif;
    background: var(--background);
    color: var(--foreground);
    font-size: 14px;
    line-height: 1.5;
}
a { color: inherit; text-decoration: none; }
h1 { font-size: 20px; font-weight: 600; margin-bottom: 1.25rem; }
code, pre { font-family: ui-monospace, "SF Mono", Consolas, monospace; }

.topbar {
    position: sticky; top: 0; z-index: 20;
    display: flex; align-items: center; justify-content: space-between;
    height: 52px; padding: 0 1.25rem;
    background: rgba(9, 9, 11, 0.92);
    backdrop-filter: blur(8px);
    border-bottom: 1px solid var(--border);
}
.topbar .brand { font-weight: 600; font-size: 14px; display: flex; align-items: center; gap: 6px; }
.topbar nav { display: flex; align-items: center; gap: 2px; }
.topbar nav a {
    padding: 6px 10px; border-radius: var(--radius);
    font-size: 13px; color: var(--muted-foreground);
    transition: background .15s, color .15s;
}
.topbar nav a:hover { background: var(--accent); color: var(--foreground); }
.topbar nav a.active { background: var(--accent); color: var(--foreground); }
.topbar .right { display: flex; align-items: center; gap: 0.5rem; }

.page { max-width: 1280px; margin: 0 auto; padding: 1.5rem; }
.page-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 1.25rem; }
.page-header h1 { margin-bottom: 0; }

.btn {
    display: inline-flex; align-items: center; justify-content: center; gap: 6px;
    height: 32px; padding: 0 12px; border-radius: var(--radius);
    font-size: 13px; font-weight: 500; cursor: pointer;
    border: 1px solid transparent; background: var(--primary); color: var(--primary-foreground);
    transition: opacity .15s, background .15s; white-space: nowrap;
}
.btn:hover { opacity: .88; }
.btn:disabled { opacity: .5; cursor: default; }
.btn-outline { background: transparent; border-color: var(--border); color: var(--foreground); }
.btn-outline:hover { background: var(--accent); opacity: 1; }
.btn-ghost { background: transparent; color: var(--muted-foreground); }
.btn-ghost:hover { background: var(--accent); color: var(--foreground); opacity: 1; }
.btn-destructive { background: var(--destructive); color: #fff; }
.btn-sm { height: 28px; padding: 0 10px; font-size: 12px; }

.input, select, textarea, input[type], input:not([type]) {
    width: 100%; height: 32px; padding: 0 10px; border-radius: var(--radius);
    background: var(--background); border: 1px solid var(--input); color: var(--foreground);
    font-size: 13px;
}
textarea { height: auto; padding: 8px 10px; font-family: ui-monospace, monospace; }
input:focus, select:focus, textarea:focus {
    outline: none; border-color: var(--ring); box-shadow: 0 0 0 2px rgba(96, 165, 250, .25);
}
label { display: block; font-size: 12px; font-weight: 500; color: var(--muted-foreground); margin-bottom: 4px; }
.field { margin-bottom: 0.85rem; }
.help-text { color: var(--muted-foreground); font-size: 12px; margin-top: 4px; }

.card { background: var(--card); border: 1px solid var(--border); border-radius: calc(var(--radius) + 2px); }
.card-header { padding: 1rem 1.25rem; border-bottom: 1px solid var(--border); }
.card-title { font-size: 14px; font-weight: 600; }
.card-content { padding: 1.25rem; }

table.table { width: 100%; border-collapse: collapse; font-size: 13px; }
.card table.table { border: none; }
table.table th {
    text-align: left; padding: 8px 12px; font-size: 11px; font-weight: 600;
    text-transform: uppercase; letter-spacing: .03em; color: var(--muted-foreground);
    border-bottom: 1px solid var(--border);
}
table.table td { padding: 10px 12px; border-bottom: 1px solid var(--border); vertical-align: middle; }
table.table tbody tr:last-child td { border-bottom: none; }
table.table tbody tr:hover td { background: var(--accent); }
.table-wrap { background: var(--card); border: 1px solid var(--border); border-radius: calc(var(--radius) + 2px); overflow: hidden; overflow-x: auto; }
.table-wrap table.table { border: none; }

.badge {
    display: inline-flex; align-items: center; padding: 2px 8px; border-radius: 9999px;
    font-size: 11px; font-weight: 500; border: 1px solid var(--border); color: var(--muted-foreground);
    text-transform: capitalize;
}
.badge-success { color: #4ade80; border-color: rgba(34, 197, 94, .3); background: rgba(34, 197, 94, .1); }
.badge-destructive { color: #f87171; border-color: rgba(239, 68, 68, .3); background: rgba(239, 68, 68, .1); }
.badge-warning { color: #fbbf24; border-color: rgba(234, 179, 8, .3); background: rgba(234, 179, 8, .1); }

.alert { padding: 10px 14px; border-radius: var(--radius); font-size: 13px; border: 1px solid var(--border); margin-bottom: 1rem; }
.alert-success { color: #4ade80; border-color: rgba(34, 197, 94, .3); background: rgba(34, 197, 94, .08); }
.alert-danger { color: #f87171; border-color: rgba(239, 68, 68, .3); background: rgba(239, 68, 68, .08); }

.tabs { display: flex; gap: 0; border-bottom: 1px solid var(--border); margin-bottom: 1.25rem; }
.tab { padding: 8px 4px; margin-right: 1.25rem; background: none; border: none; color: var(--muted-foreground); font-size: 13px; cursor: pointer; border-bottom: 2px solid transparent; }
.tab:hover { color: var(--foreground); }
.tab.active { color: var(--foreground); border-bottom-color: var(--foreground); }
.tab-content { display: none; }
.tab-content.active { display: block; }

.stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 0.75rem; margin-bottom: 1.25rem; }
.stat-card { background: var(--card); border: 1px solid var(--border); border-radius: var(--radius); padding: 1rem; }
.stat-label { font-size: 11px; text-transform: uppercase; letter-spacing: .03em; color: var(--muted-foreground); margin-bottom: 6px; }
.stat-value { font-size: 24px; font-weight: 700; }

.code-viewer {
    background: #000; border: 1px solid var(--border); border-radius: var(--radius);
    padding: 1rem; font-size: 12px; white-space: pre-wrap; word-break: break-word;
    max-height: 600px; overflow: auto; color: #e4e4e7;
}

.muted { color: var(--muted-foreground); }
.flex { display: flex; align-items: center; gap: 0.5rem; }
.flex-between { display: flex; align-items: center; justify-content: space-between; }
.mb-2 { margin-bottom: 1rem; }
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 0.85rem; }
@media (max-width: 640px) { .grid-2 { grid-template-columns: 1fr; } }

.auth-shell {
    min-height: 100vh; display: flex; align-items: center; justify-content: center;
    background: radial-gradient(circle at top, #18181b, #09090b 60%); padding: 1rem;
}
.auth-card { width: 100%; max-width: 400px; }
.auth-logo { text-align: center; margin-bottom: 1.5rem; font-size: 15px; font-weight: 600; color: var(--muted-foreground); }
'''

def render_navbar(active):
    """Top navbar shared across all authenticated pages, with the current section highlighted."""
    def link(endpoint, label):
        cls = ' class="active"' if endpoint == active else ''
        return '<a' + cls + ' href="{{ url_for(\'' + endpoint + '\') }}">' + label + '</a>'
    links = (
        link('dashboard', 'Dashboard') +
        link('manage_devices', 'Devices') +
        link('manage_config', 'Config') +
        link('settings', 'Settings') +
        link('manage_users', 'Users')
    )
    return ('''<header class="topbar">
        <a class="brand" href="{{ url_for('dashboard') }}">Oxidized Manager</a>
        <nav>''' + links + '''</nav>
        <div class="right"><a class="btn btn-ghost btn-sm" href="{{ url_for('logout') }}">Logout</a></div>
    </header>
    ''')

LOGIN_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Login - Oxidized Manager</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .login-container {
            background: #1e293b;
            border: 1px solid #334155;
            border-radius: 12px;
            padding: 2rem;
            width: 100%;
            max-width: 400px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
        }
        .logo {
            text-align: center;
            margin-bottom: 2rem;
            font-size: 28px;
            font-weight: 700;
            background: linear-gradient(135deg, #3b82f6, #06b6d4);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        h1 {
            color: #f1f5f9;
            font-size: 24px;
            margin-bottom: 2rem;
            text-align: center;
        }
        .form-group {
            margin-bottom: 1.5rem;
        }
        label {
            display: block;
            color: #cbd5e1;
            font-size: 14px;
            font-weight: 500;
            margin-bottom: 0.5rem;
        }
        input {
            width: 100%;
            padding: 10px 12px;
            background: #0f172a;
            border: 1px solid #334155;
            border-radius: 6px;
            color: #f1f5f9;
            font-size: 14px;
        }
        input:focus {
            outline: none;
            border-color: #3b82f6;
            box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
        }
        button {
            width: 100%;
            padding: 10px;
            background: #2563eb;
            border: none;
            border-radius: 6px;
            color: white;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: background 0.2s;
        }
        button:hover {
            background: #1d4ed8;
        }
        .alert {
            padding: 12px;
            border-radius: 6px;
            margin-bottom: 1.5rem;
            font-size: 14px;
        }
        .alert-danger {
            background: rgba(239, 68, 68, 0.1);
            color: #f87171;
        }
    </style>
</head>
<body>
    <div class="login-container">
        <div class="logo">⚙️ Oxidized</div>
        <h1>Manager</h1>
        
        {% with messages = get_flashed_messages(category_filter=['danger']) %}
            {% if messages %}
                <div class="alert alert-danger">{{ messages[0] }}</div>
            {% endif %}
        {% endwith %}
        
        <form method="POST">
            <div class="form-group">
                <label>Username</label>
                <input type="text" name="username" required>
            </div>
            <div class="form-group">
                <label>Password</label>
                <input type="password" name="password" required>
            </div>
            <button type="submit">Sign in</button>
        </form>
    </div>
</body>
</html>'''

SETUP_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Setup - Oxidized Manager</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 1rem;
        }
        .setup-container {
            background: #1e293b;
            border: 1px solid #334155;
            border-radius: 12px;
            padding: 3rem 2rem;
            width: 100%;
            max-width: 500px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
        }
        h1 {
            color: #f1f5f9;
            font-size: 28px;
            margin-bottom: 1rem;
            background: linear-gradient(135deg, #3b82f6, #06b6d4);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .subtitle {
            color: #cbd5e1;
            font-size: 14px;
            margin-bottom: 2rem;
        }
        .form-group {
            margin-bottom: 1.5rem;
        }
        label {
            display: block;
            color: #cbd5e1;
            font-size: 13px;
            font-weight: 600;
            margin-bottom: 0.5rem;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        input {
            width: 100%;
            padding: 10px 12px;
            background: #0f172a;
            border: 1px solid #334155;
            border-radius: 6px;
            color: #f1f5f9;
            font-size: 14px;
        }
        input:focus {
            outline: none;
            border-color: #3b82f6;
            box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
        }
        button {
            width: 100%;
            padding: 12px;
            background: #2563eb;
            border: none;
            border-radius: 6px;
            color: white;
            font-size: 14px;
            font-weight: 700;
            cursor: pointer;
            transition: background 0.2s;
        }
        button:hover {
            background: #1d4ed8;
        }
        .help-text {
            color: #64748b;
            font-size: 12px;
            margin-top: 0.25rem;
        }
    </style>
</head>
<body>
    <div class="setup-container">
        <h1>Initial Setup</h1>
        <p class="subtitle">Create your admin account to get started</p>
        
        <form method="POST">
            <div class="form-group">
                <label>Admin Username</label>
                <input type="text" name="username" value="admin" required>
                <div class="help-text">You can change this after setup</div>
            </div>
            
            <div class="form-group">
                <label>Admin Password</label>
                <input type="password" name="password" placeholder="Min 8 characters" required minlength="8">
            </div>
            
            <div class="form-group">
                <label>Email Address</label>
                <input type="email" name="email" placeholder="admin@example.com">
            </div>
            
            <button type="submit">Create Admin Account</button>
        </form>
    </div>
</body>
</html>'''

DASHBOARD_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Dashboard - Oxidized Manager</title>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0f172a;
            color: #f1f5f9;
        }
        .navbar {
            background: #1e293b;
            border-bottom: 1px solid #334155;
            padding: 1rem 2rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .navbar h1 {
            font-size: 20px;
            background: linear-gradient(135deg, #3b82f6, #06b6d4);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .nav-links {
            display: flex;
            gap: 2rem;
        }
        .nav-links a {
            color: #cbd5e1;
            text-decoration: none;
            font-size: 14px;
            transition: color 0.2s;
        }
        .nav-links a:hover {
            color: #3b82f6;
        }
        .logout-btn {
            color: #ef4444;
            cursor: pointer;
        }
        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 2rem;
        }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1rem;
            margin-bottom: 2rem;
        }
        .stat-card {
            background: #1e293b;
            border: 1px solid #334155;
            border-radius: 8px;
            padding: 1.5rem;
            text-align: center;
        }
        .stat-label {
            color: #64748b;
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 0.5rem;
        }
        .stat-value {
            font-size: 32px;
            font-weight: 700;
            background: linear-gradient(135deg, #3b82f6, #06b6d4);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        table.devices-table {
            width: 100%;
            border-collapse: collapse;
            background: #1e293b;
            border: 1px solid #334155;
            border-radius: 8px;
            overflow: hidden;
        }
        table.devices-table th, table.devices-table td {
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #334155;
            font-size: 14px;
        }
        table.devices-table th {
            background: #334155;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            font-size: 12px;
        }
        table.devices-table tr:hover td {
            background: #26344a;
        }
        .device-ip {
            font-family: monospace;
            font-size: 12px;
            color: #64748b;
        }
        .status-badge {
            display: inline-block;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
        }
        .status-success {
            background: rgba(16, 185, 129, 0.1);
            color: #10b981;
        }
        .status-error {
            background: rgba(239, 68, 68, 0.1);
            color: #ef4444;
        }
        .status-pending {
            background: rgba(107, 114, 128, 0.1);
            color: #9ca3af;
        }
        .device-actions {
            margin-top: 1rem;
            display: flex;
            gap: 0.5rem;
        }
        .btn {
            padding: 6px 12px;
            border: 1px solid #334155;
            background: transparent;
            color: #3b82f6;
            border-radius: 4px;
            cursor: pointer;
            font-size: 12px;
            transition: all 0.2s;
        }
        .btn:hover {
            background: #334155;
        }
        .btn-primary {
            background: #2563eb;
            color: white;
            border-color: #2563eb;
        }
    </style>
</head>
<body>
    <div class="navbar">
        <h1>⚙️ Oxidized Manager</h1>
        <div class="nav-links">
            <a href="{{ url_for('manage_devices') }}">Devices</a>
            <a href="{{ url_for('manage_config') }}">Config</a>
            <a href="{{ url_for('settings') }}">Settings</a>
            <a href="{{ url_for('manage_users') }}">Users</a>
            <a href="{{ url_for('logout') }}" class="logout-btn">Logout</a>
        </div>
    </div>
    
    <div class="container">
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-label">Total Devices</div>
                <div class="stat-value">{{ stats.total }}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Healthy</div>
                <div class="stat-value" style="color: #10b981;">{{ stats.healthy }}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Pending</div>
                <div class="stat-value" style="color: #f59e0b;">{{ stats.pending }}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Failed</div>
                <div class="stat-value" style="color: #ef4444;">{{ stats.failed }}</div>
            </div>
        </div>
        
        <table class="devices-table">
            <thead>
                <tr>
                    <th>Name</th>
                    <th>Model</th>
                    <th>Group</th>
                    <th>Last Status</th>
                    <th>Last Update</th>
                    <th>Last Changed</th>
                    <th>Failures</th>
                    <th>Avg Run Time</th>
                    <th>Last Failure</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody>
                {% for device in devices %}
                <tr>
                    <td>
                        <div><strong>{{ device.name }}</strong></div>
                        <div class="device-ip">{{ device.ip }}</div>
                    </td>
                    <td>{{ device.model or '-' }}</td>
                    <td>{{ device.group or 'default' }}</td>
                    <td>
                        <span class="status-badge status-{{ device.status or 'pending' }}">
                            {{ device.status or 'unknown' }}
                        </span>
                    </td>
                    <td class="device-last-update" data-value="{{ device.last_update or '' }}">{{ device.last_update or 'never' }}</td>
                    <td title="{{ device.stats_raw|tojson }}">{{ device.mtime or 'unknown' }}</td>
                    <td title="{{ device.stats_raw|tojson }}">{{ device.total_failures if device.total_failures is not none else '-' }}</td>
                    <td title="{{ device.stats_raw|tojson }}">{{ device.avg_run_time if device.avg_run_time is not none else '-' }}</td>
                    <td title="{{ device.stats_raw|tojson }}">{{ device.last_failure if device.last_failure is not none else 'never' }}</td>
                    <td>
                        <a href="{{ url_for('device_detail', device_name=device.name) }}" class="btn">View</a>
                        <button type="button" class="btn" onclick="location.href='{{ url_for('manage_devices') }}';">Edit</button>
                        <button type="button" class="btn" id="update-btn-{{ loop.index0 }}" onclick="updateDeviceNow('{{ device.name }}', {{ loop.index0 }})">Update</button>
                        <span id="update-result-{{ loop.index0 }}" style="font-size: 12px; margin-left: 0.5rem;"></span>
                    </td>
                </tr>
                {% else %}
                <tr><td colspan="9">No devices found. Sync from LibreNMS or add one from the Devices page.</td></tr>
                {% endfor %}
            </tbody>
        </table>
    </div>

    <script>
    function updateDeviceNow(name, idx) {
        var btn = document.getElementById('update-btn-' + idx);
        var result = document.getElementById('update-result-' + idx);
        btn.disabled = true;
        result.style.color = '#cbd5e1';
        result.textContent = '⏳ updating...';

        fetch('/api/oxidized/fetch/' + encodeURIComponent(name), { method: 'POST' })
            .then(response => response.json().then(data => ({ ok: response.ok, data: data })))
            .then(({ ok, data }) => {
                if (ok && data.status === 'success') {
                    result.style.color = '#10b981';
                    result.textContent = '✓ updated';
                } else {
                    result.style.color = '#f87171';
                    result.textContent = '✗ ' + data.message;
                }
                btn.disabled = false;
            })
            .catch(err => {
                result.style.color = '#f87171';
                result.textContent = '✗ ' + err;
                btn.disabled = false;
            });
    }
    </script>
</body>
</html>'''

DEVICE_DETAIL_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Device - Oxidized Manager</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0f172a;
            color: #f1f5f9;
        }
        .navbar {
            background: #1e293b;
            border-bottom: 1px solid #334155;
            padding: 1rem 2rem;
        }
        .navbar a {
            color: #3b82f6;
            text-decoration: none;
        }
        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 2rem;
        }
        h1 {
            margin-bottom: 2rem;
            background: linear-gradient(135deg, #3b82f6, #06b6d4);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .tabs {
            display: flex;
            gap: 1rem;
            border-bottom: 1px solid #334155;
            margin-bottom: 2rem;
        }
        .tab {
            padding: 1rem;
            background: none;
            border: none;
            color: #cbd5e1;
            cursor: pointer;
            font-size: 14px;
            border-bottom: 2px solid transparent;
            transition: all 0.2s;
        }
        .tab.active {
            color: #3b82f6;
            border-bottom-color: #3b82f6;
        }
        .tab-content {
            display: none;
        }
        .tab-content.active {
            display: block;
        }
        .config-viewer {
            background: #1e293b;
            border: 1px solid #334155;
            border-radius: 8px;
            padding: 1.5rem;
            font-family: monospace;
            font-size: 12px;
            white-space: pre-wrap;
            word-break: break-word;
            overflow-x: auto;
            max-height: 600px;
            overflow-y: auto;
            color: #e2e8f0;
            line-height: 1.5;
        }
        .backup-item {
            background: #1e293b;
            border: 1px solid #334155;
            border-radius: 8px;
            padding: 1rem;
            margin-bottom: 1rem;
        }
        .backup-date {
            color: #64748b;
            font-size: 12px;
        }
        .btn {
            padding: 8px 14px;
            background: #2563eb;
            color: white;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            font-size: 13px;
        }
        .btn:hover {
            background: #1d4ed8;
        }
        .btn:disabled {
            opacity: 0.6;
            cursor: default;
        }
        table.versions-table {
            width: 100%;
            border-collapse: collapse;
            background: #1e293b;
            border: 1px solid #334155;
            border-radius: 8px;
            overflow: hidden;
        }
        table.versions-table th, table.versions-table td {
            padding: 10px 12px;
            text-align: left;
            border-bottom: 1px solid #334155;
            font-size: 13px;
        }
        table.versions-table th {
            background: #334155;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            font-size: 11px;
        }
        .action-btn {
            padding: 5px 10px;
            background: transparent;
            border: 1px solid #334155;
            color: #3b82f6;
            border-radius: 4px;
            cursor: pointer;
            font-size: 12px;
        }
        .action-btn:hover {
            background: #334155;
        }
        #version-content {
            display: none;
            margin-top: 1rem;
            background: #0f172a;
            border: 1px solid #334155;
            border-radius: 8px;
            padding: 1.5rem;
            font-family: monospace;
            font-size: 12px;
            white-space: pre-wrap;
            word-break: break-all;
            max-height: 500px;
            overflow-y: auto;
            color: #e2e8f0;
        }
        .diff-picker {
            background: #1e293b;
            border: 1px solid #334155;
            border-radius: 8px;
            padding: 1rem 1.25rem;
            margin-top: 1.5rem;
        }
        .diff-picker select {
            padding: 6px 10px;
            background: #0f172a;
            border: 1px solid #334155;
            border-radius: 6px;
            color: #f1f5f9;
            font-size: 13px;
            min-width: 220px;
        }
        #diff-content {
            display: none;
            margin-top: 1rem;
        }
        .diff-pane {
            background: #0f172a;
            border: 1px solid #334155;
            border-radius: 8px;
            padding: 1rem;
            font-family: monospace;
            font-size: 12px;
            white-space: pre-wrap;
            word-break: break-all;
            max-height: 600px;
            overflow-y: auto;
            color: #e2e8f0;
        }
        .diff-add {
            background: rgba(16, 185, 129, 0.15);
            color: #6ee7b7;
        }
        .diff-remove {
            background: rgba(239, 68, 68, 0.15);
            color: #fca5a5;
        }
    </style>
</head>
<body>
    <div class="navbar">
        <a href="{{ url_for('dashboard') }}">← Back to Dashboard</a>
    </div>

    <div class="container">
        <h1>{{ device_name }}</h1>

        <div class="tabs">
            <button class="tab active" onclick="showTab('config')">Config</button>
            <button class="tab" onclick="showTab('history')">Versions</button>
            <button class="tab" onclick="showTab('backups')">Backups</button>
        </div>

        <div id="config" class="tab-content active">
            <div style="margin-bottom: 1rem; display: flex; align-items: center; gap: 1rem;">
                <button class="btn" id="update-config-btn" onclick="updateConfig()">Update Configuration</button>
                <button class="btn" onclick="rawView('config-viewer', '{{ device_name }}.conf')">Raw</button>
                <button class="btn" onclick="downloadContent('config-viewer', '{{ device_name }}.conf')">Download</button>
                <span id="update-config-result" style="font-size: 13px;"></span>
            </div>
            <div class="config-viewer" id="config-viewer">{{ config or 'No configuration found' }}</div>
        </div>

        <div id="history" class="tab-content">
            <table class="versions-table">
                <thead>
                    <tr><th>Version</th><th>Date</th><th>Actions</th></tr>
                </thead>
                <tbody>
                {% for v in history %}
                    <tr>
                        <td>{{ v.num if v.num is defined else loop.index }}</td>
                        <td class="version-date" data-epoch="{{ v.epoch if v.epoch is defined else '' }}">
                            {{ v.epoch if v.epoch is defined else (v.date if v.date is defined else '-') }}
                        </td>
                        <td>
                            <button class="action-btn" onclick='viewVersion({{ v|tojson }})'>View</button>
                        </td>
                    </tr>
                {% else %}
                    <tr><td colspan="3">No version history yet</td></tr>
                {% endfor %}
                </tbody>
            </table>
            <div id="version-content"></div>
            <div>
                <div id="version-content-actions" style="display: none; margin-top: 0.5rem;">
                    <button class="btn" onclick="rawView('version-content', '{{ device_name }}-version.conf')">Raw</button>
                    <button class="btn" onclick="downloadContent('version-content', '{{ device_name }}-version.conf')">Download</button>
                </div>
            </div>

            <div class="diff-picker">
                <h3 style="font-size: 14px; margin-bottom: 0.75rem;">Compare Versions</h3>
                <div style="display: flex; gap: 1rem; align-items: flex-end; flex-wrap: wrap;">
                    <div>
                        <label style="display:block; font-size:12px; color:#94a3b8; margin-bottom:4px;">Version</label>
                        <select id="diff-select-a"></select>
                    </div>
                    <div>
                        <label style="display:block; font-size:12px; color:#94a3b8; margin-bottom:4px;">Compared against</label>
                        <select id="diff-select-b"></select>
                    </div>
                    <button class="btn" onclick="compareDiffs()">Get Diffs</button>
                </div>
            </div>

            <div id="diff-content">
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1rem;">
                    <div>
                        <div id="diff-label-old" style="font-size: 12px; color: #94a3b8; margin-bottom: 0.4rem;"></div>
                        <div class="diff-pane" id="diff-old"></div>
                    </div>
                    <div>
                        <div id="diff-label-new" style="font-size: 12px; color: #94a3b8; margin-bottom: 0.4rem;"></div>
                        <div class="diff-pane" id="diff-new"></div>
                    </div>
                </div>
            </div>
        </div>

        <div id="backups" class="tab-content">
            {% for backup in backups %}
            <div class="backup-item">
                <div class="backup-date">{{ backup.created_at }}</div>
                <div>Status: {{ backup.status }}</div>
                <div>Size: {{ backup.file_size }} bytes</div>
            </div>
            {% else %}
            <div style="color: #64748b;">No local backup records yet</div>
            {% endfor %}
        </div>
    </div>

    <script>
    function showTab(tabName) {
        document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
        document.querySelectorAll('.tab').forEach(el => el.classList.remove('active'));
        document.getElementById(tabName).classList.add('active');
        event.target.classList.add('active');
    }

    function updateConfig() {
        var btn = document.getElementById('update-config-btn');
        var result = document.getElementById('update-config-result');
        var viewer = document.getElementById('config-viewer');
        btn.disabled = true;
        result.style.color = '#cbd5e1';
        result.textContent = '⏳ Fetching latest config from device...';

        fetch('{{ url_for("api_oxidized_fetch", device_name=device_name) }}', { method: 'POST' })
            .then(response => response.json().then(data => ({ ok: response.ok, data: data })))
            .then(({ ok, data }) => {
                if (ok && data.status === 'success') {
                    result.style.color = '#10b981';
                    result.textContent = '✓ ' + data.message;
                    viewer.textContent = data.content || 'No configuration found';
                } else {
                    result.style.color = '#f87171';
                    result.textContent = '✗ ' + data.message;
                }
                btn.disabled = false;
            })
            .catch(err => {
                result.style.color = '#f87171';
                result.textContent = '✗ ' + err;
                btn.disabled = false;
            });
    }

    function versionParams(v) {
        var params = new URLSearchParams();
        params.append('node', {{ device_name|tojson }});
        params.append('group', {{ device_group|tojson }});
        Object.keys(v).forEach(function(k) {
            if (v[k] !== null && v[k] !== undefined) params.append(k, v[k]);
        });
        return params;
    }

    function viewVersion(v) {
        document.getElementById('diff-content').style.display = 'none';
        var out = document.getElementById('version-content');
        var actions = document.getElementById('version-content-actions');
        out.style.display = 'block';
        out.textContent = 'Loading...';
        actions.style.display = 'none';

        fetch('{{ url_for("api_oxidized_version_content") }}?' + versionParams(v).toString())
            .then(response => response.json())
            .then(data => {
                out.textContent = data.status === 'success' ? data.content : ('Error: ' + data.message);
                if (data.status === 'success') actions.style.display = 'block';
            })
            .catch(err => { out.textContent = 'Request failed: ' + err; });
    }

    var HISTORY = {{ history|tojson }};

    function versionLabel(v, idx) {
        var num = (v && v.num !== undefined) ? v.num : (idx + 1);
        var when = (v && v.epoch !== undefined) ? new Date(parseFloat(v.epoch) * 1000).toLocaleString()
                 : (v && v.date !== undefined ? v.date : '');
        return 'Version ' + num + (when ? ' - ' + when : '');
    }

    function initDiffPickers() {
        var a = document.getElementById('diff-select-a');
        var b = document.getElementById('diff-select-b');
        HISTORY.forEach(function(v, idx) {
            var optA = document.createElement('option');
            optA.value = idx;
            optA.textContent = versionLabel(v, idx);
            a.appendChild(optA);
            b.appendChild(optA.cloneNode(true));
        });
        if (HISTORY.length > 0) a.value = 0;
        if (HISTORY.length > 1) b.value = 1;
    }
    initDiffPickers();

    function renderSideBySide(diffText) {
        var lines = diffText.split('\\n');
        var oldLines = [], newLines = [];
        lines.forEach(function(line) {
            if (line.startsWith('+') && !line.startsWith('+++')) {
                newLines.push(line);
            } else if (line.startsWith('-') && !line.startsWith('---')) {
                oldLines.push(line);
            } else {
                newLines.push(line);
                oldLines.push(line);
            }
        });
        var i = 0;
        while (i <= Math.max(oldLines.length, newLines.length)) {
            if (i > Math.min(oldLines.length, newLines.length)) break;
            var oldLine = oldLines[i], newLine = newLines[i];
            var oldRemoved = oldLine !== undefined && oldLine.startsWith('-') && !oldLine.startsWith('---');
            var newAdded = newLine !== undefined && newLine.startsWith('+') && !newLine.startsWith('+++');
            if (oldRemoved && !newAdded) {
                newLines.splice(i, 0, '');
            } else if (!oldRemoved && newAdded) {
                oldLines.splice(i, 0, '');
            }
            i++;
        }

        function fill(container, arr) {
            container.innerHTML = '';
            arr.forEach(function(line) {
                var div = document.createElement('div');
                if (line.startsWith('+') && !line.startsWith('+++')) div.className = 'diff-add';
                else if (line.startsWith('-') && !line.startsWith('---')) div.className = 'diff-remove';
                div.textContent = line || '\\u00A0';
                container.appendChild(div);
            });
        }
        fill(document.getElementById('diff-old'), oldLines);
        fill(document.getElementById('diff-new'), newLines);
    }

    function compareDiffs() {
        var a = document.getElementById('diff-select-a');
        var b = document.getElementById('diff-select-b');
        if (a.value === '' || b.value === '') return;
        var idxA = parseInt(a.value, 10), idxB = parseInt(b.value, 10);
        var vA = HISTORY[idxA], vB = HISTORY[idxB];

        document.getElementById('version-content').style.display = 'none';
        document.getElementById('version-content-actions').style.display = 'none';

        var out = document.getElementById('diff-content');
        out.style.display = 'block';
        document.getElementById('diff-label-old').textContent = versionLabel(vB, idxB) + ' (compared against)';
        document.getElementById('diff-label-new').textContent = versionLabel(vA, idxA) + ' (selected)';
        document.getElementById('diff-old').textContent = 'Loading...';
        document.getElementById('diff-new').textContent = '';

        var params = versionParams(vA);
        if (vB && vB.oid !== undefined && vB.oid !== null) params.append('oid2', vB.oid);

        fetch('{{ url_for("api_oxidized_diff") }}?' + params.toString())
            .then(response => response.json())
            .then(data => {
                if (data.status !== 'success') {
                    document.getElementById('diff-old').textContent = 'Error: ' + data.message;
                    document.getElementById('diff-new').textContent = '';
                    return;
                }
                renderSideBySide(data.content);
            })
            .catch(err => {
                document.getElementById('diff-old').textContent = 'Request failed: ' + err;
            });
    }

    function rawView(elementId, filename) {
        var text = document.getElementById(elementId).textContent;
        var blob = new Blob([text], { type: 'text/plain' });
        var url = URL.createObjectURL(blob);
        window.open(url, '_blank');
        setTimeout(function() { URL.revokeObjectURL(url); }, 30000);
    }

    function downloadContent(elementId, filename) {
        var text = document.getElementById(elementId).textContent;
        var blob = new Blob([text], { type: 'text/plain' });
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        setTimeout(function() { URL.revokeObjectURL(url); }, 30000);
    }

    document.querySelectorAll('.version-date').forEach(function(el) {
        var epoch = el.getAttribute('data-epoch');
        if (epoch && !isNaN(parseFloat(epoch))) {
            var d = new Date(parseFloat(epoch) * 1000);
            if (!isNaN(d.getTime())) el.textContent = d.toLocaleString();
        }
    });
    </script>
</body>
</html>'''

DEVICE_MANAGEMENT_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Device Management - Oxidized Manager</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0f172a;
            color: #f1f5f9;
        }
        .navbar {
            background: #1e293b;
            border-bottom: 1px solid #334155;
            padding: 1rem 2rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .navbar a {
            color: #3b82f6;
            text-decoration: none;
        }
        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 2rem;
        }
        .controls {
            display: flex;
            gap: 1rem;
            margin-bottom: 2rem;
        }
        .btn {
            padding: 10px 16px;
            background: #2563eb;
            color: white;
            border: none;
            border-radius: 6px;
            cursor: pointer;
        }
        .btn:hover {
            background: #1d4ed8;
        }
        .btn-secondary {
            background: #1e293b;
            border: 1px solid #334155;
            color: #cbd5e1;
            padding: 8px 12px;
            font-size: 12px;
        }
        .btn-secondary:hover {
            background: #334155;
        }
        .form-section {
            background: #1e293b;
            padding: 1.5rem;
            border-radius: 8px;
            margin-bottom: 2rem;
            border: 1px solid #334155;
        }
        input, select {
            padding: 8px 12px;
            background: #0f172a;
            border: 1px solid #334155;
            border-radius: 4px;
            color: #f1f5f9;
            margin-bottom: 0.5rem;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            background: #1e293b;
            border: 1px solid #334155;
            border-radius: 8px;
            overflow: hidden;
        }
        th, td {
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #334155;
            font-size: 14px;
        }
        th {
            background: #334155;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            font-size: 12px;
        }
        tr:hover {
            background: #334155;
        }
        .action-btn {
            padding: 6px 12px;
            margin-right: 0.5rem;
            background: transparent;
            border: 1px solid #334155;
            color: #3b82f6;
            border-radius: 4px;
            cursor: pointer;
            font-size: 12px;
        }
        .action-btn:hover {
            background: #334155;
        }
        .action-btn.test {
            color: #10b981;
        }
        .action-btn.delete {
            color: #ef4444;
        }
        .test-result {
            display: none;
        }
        .test-result.show {
            display: table-row;
        }
        .test-result td {
            padding: 10px 12px;
            font-size: 12px;
            text-align: center;
        }
        .test-result.success {
            background: rgba(16, 185, 129, 0.1);
            color: #10b981;
        }
        .test-result.error {
            background: rgba(239, 68, 68, 0.1);
            color: #f87171;
        }
        .group-badge {
            background: #334155;
            padding: 4px 8px;
            border-radius: 3px;
            font-size: 12px;
        }
    </style>
</head>
<body>
    <div class="navbar">
        <h2>Device Management</h2>
        <div>
            <button class="btn btn-secondary" onclick="location.href='{{ url_for('manage_groups') }}'">Manage Groups</button>
            <a href="{{ url_for('dashboard') }}" style="margin-left: 1rem;">← Back</a>
        </div>
    </div>
    
    <div class="container">
        <div class="controls">
            <button class="btn" onclick="showAddForm()">+ Add Device</button>
        </div>
        
        <div id="add-form" class="form-section" style="display: none;">
            <h3 id="form-title" style="margin-bottom: 1rem;">Add New Device</h3>
            <form method="POST" id="device-form">
                <input type="hidden" name="action" id="form-action" value="add">
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin-bottom: 1rem;">
                    <input type="text" name="name" id="field-name" placeholder="Device Name" required>
                    <input type="text" name="ip" id="field-ip" placeholder="IP Address (10.25.1.1)" required>
                    <input type="text" name="model" id="field-model" placeholder="Model (RouterOS, Cisco IOS, JunOS)">
                    <input type="text" name="username" id="field-username" placeholder="SSH Username">
                    <input type="password" name="password" id="field-password" placeholder="SSH Password">
                    <select name="group" id="field-group" required>
                        {% for g in groups %}
                        <option value="{{ g }}">{{ g }}</option>
                        {% else %}
                        <option value="default">default</option>
                        {% endfor %}
                    </select>
                    <input type="number" name="ssh_port" id="field-ssh_port" placeholder="SSH Port" value="22" min="1" max="65535">
                </div>
                <div style="display: flex; gap: 0.5rem;">
                    <button type="submit" class="btn">Save Device</button>
                    <button type="button" class="btn btn-secondary" onclick="hideForm()">Cancel</button>
                </div>
            </form>
        </div>
        
        <table>
            <thead>
                <tr>
                    <th>Name</th>
                    <th>IP</th>
                    <th>Model</th>
                    <th>Group</th>
                    <th>Port</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody>
                {% for device in devices %}
                <tr>
                    <td><strong>{{ device.name }}</strong></td>
                    <td><code style="font-size: 11px;">{{ device.ip }}</code></td>
                    <td>{{ device.model or '-' }}</td>
                    <td><span class="group-badge">{{ device.group }}</span></td>
                    <td>{{ device.get('ssh_port', 22) }}</td>
                    <td>
                        <button class="action-btn test" onclick="testSSH('{{ device.name }}', '{{ device.ip }}', '{{ device.username }}', '{{ device.password }}', {{ device.get('ssh_port', 22) }})">Test SSH</button>
                        <button class="action-btn" onclick='editDevice({{ device|tojson }})'>Edit</button>
                        <form method="POST" style="display: inline;">
                            <input type="hidden" name="action" value="delete">
                            <input type="hidden" name="ip" value="{{ device.ip }}">
                            <button type="submit" class="action-btn delete" onclick="return confirm('Delete device?')">Delete</button>
                        </form>
                    </td>
                </tr>
                <tr id="test-result-{{ loop.index0 }}" class="test-result">
                    <td colspan="6"></td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
    
    <script>
    function resetForm() {
        document.getElementById('device-form').reset();
        document.getElementById('form-action').value = 'add';
        document.getElementById('field-ip').readOnly = false;
        document.getElementById('form-title').textContent = 'Add New Device';
    }

    function showAddForm() {
        var form = document.getElementById('add-form');
        if (form.style.display === 'none') {
            resetForm();
            form.style.display = 'block';
        } else {
            form.style.display = 'none';
        }
    }

    function hideForm() {
        document.getElementById('add-form').style.display = 'none';
    }

    function editDevice(device) {
        document.getElementById('form-action').value = 'update';
        document.getElementById('form-title').textContent = 'Edit Device: ' + device.name;
        document.getElementById('field-name').value = device.name || '';
        document.getElementById('field-ip').value = device.ip || '';
        document.getElementById('field-ip').readOnly = true;
        document.getElementById('field-model').value = device.model || '';
        document.getElementById('field-username').value = device.username || '';
        document.getElementById('field-password').value = device.password || '';
        document.getElementById('field-group').value = device.group || 'default';
        document.getElementById('field-ssh_port').value = device.ssh_port || 22;
        var form = document.getElementById('add-form');
        form.style.display = 'block';
        form.scrollIntoView({ behavior: 'smooth' });
    }

    function testSSH(name, ip, username, password, port) {
        var idx = Array.from(document.querySelectorAll('[id^="test-result-"]')).length - 1;
        var resultRow = document.querySelector('[id="test-result-' + (Array.from(document.querySelectorAll('[id^="test-result-"]')).indexOf(document.getElementById('test-result-' + idx))) + '"]') || 
                        document.getElementById('test-result-0');
        
        // Find the correct result row by searching for the one after the device row
        var deviceRows = document.querySelectorAll('tbody tr');
        var resultRowIdx = 0;
        for (var i = 0; i < deviceRows.length; i++) {
            if (deviceRows[i].textContent.includes(name)) {
                resultRowIdx = i + 1;
                break;
            }
        }
        resultRow = document.querySelectorAll('tbody tr')[resultRowIdx];
        
        if (!resultRow) resultRow = document.getElementById('test-result-0');
        
        resultRow.classList.add('show');
        resultRow.innerHTML = '<td colspan="6" style="text-align: center; color: #cbd5e1;">⏳ Testing SSH connection...</td>';
        
        var formData = new FormData();
        formData.append('host', ip);
        formData.append('username', username);
        formData.append('password', password);
        formData.append('port', port);
        
        fetch('{{ url_for("api_test_ssh") }}', {
            method: 'POST',
            body: formData
        })
        .then(response => response.json())
        .then(data => {
            var html = '<td colspan="6">';
            if (data.status === 'success') {
                html += '<strong style="color: #10b981;">✓ ' + name + ':</strong> ' + data.message;
                resultRow.className = 'test-result show success';
            } else {
                html += '<strong style="color: #f87171;">✗ ' + name + ':</strong> ' + data.message;
                resultRow.className = 'test-result show error';
            }
            html += '</td>';
            resultRow.innerHTML = html;
            
            setTimeout(() => {
                resultRow.classList.remove('show');
            }, 6000);
        })
        .catch(error => {
            resultRow.innerHTML = '<td colspan="6" style="color: #f87171;"><strong>✗ Error:</strong> ' + error + '</td>';
            resultRow.className = 'test-result show error';
        });
    }
    </script>
</body>
</html>'''

CONFIG_MANAGEMENT_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Config Management - Oxidized Manager</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0f172a;
            color: #f1f5f9;
        }
        .navbar {
            background: #1e293b;
            border-bottom: 1px solid #334155;
            padding: 1rem 2rem;
            display: flex;
            justify-content: space-between;
        }
        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 2rem;
        }
        textarea {
            width: 100%;
            height: 600px;
            background: #0f172a;
            color: #e2e8f0;
            border: 1px solid #334155;
            border-radius: 8px;
            padding: 1rem;
            font-family: monospace;
            font-size: 12px;
            margin-bottom: 1rem;
        }
        .btn {
            padding: 10px 16px;
            background: #2563eb;
            color: white;
            border: none;
            border-radius: 6px;
            cursor: pointer;
        }
    </style>
</head>
<body>
    <div class="navbar">
        <h2>Oxidized Configuration</h2>
        <a href="{{ url_for('dashboard') }}">← Back</a>
    </div>
    
    <div class="container">
        <form method="POST">
            <input type="hidden" name="action" value="update_yaml">
            <textarea name="yaml_content" required>{{ config_yaml }}</textarea>
            <button type="submit" class="btn">Save Configuration</button>
        </form>
    </div>
</body>
</html>'''

SETTINGS_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Settings - Oxidized Manager</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0f172a;
            color: #f1f5f9;
        }
        .navbar {
            background: #1e293b;
            border-bottom: 1px solid #334155;
            padding: 1rem 2rem;
            display: flex;
            justify-content: space-between;
        }
        .container {
            max-width: 800px;
            margin: 0 auto;
            padding: 2rem;
        }
        .form-group {
            margin-bottom: 1.5rem;
        }
        label {
            display: block;
            color: #cbd5e1;
            font-size: 14px;
            font-weight: 600;
            margin-bottom: 0.5rem;
        }
        input, select {
            width: 100%;
            padding: 10px 12px;
            background: #1e293b;
            border: 1px solid #334155;
            border-radius: 6px;
            color: #f1f5f9;
            font-size: 14px;
        }
        input:focus, select:focus {
            outline: none;
            border-color: #3b82f6;
            box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
        }
        .checkbox-group {
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }
        .checkbox-group input {
            width: auto;
        }
        .btn {
            padding: 10px 16px;
            background: #2563eb;
            color: white;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            font-size: 14px;
        }
        .btn:hover {
            background: #1d4ed8;
        }
        .status {
            padding: 12px;
            border-radius: 6px;
            margin-bottom: 1rem;
            font-size: 14px;
        }
        .status-success {
            background: rgba(16, 185, 129, 0.1);
            color: #10b981;
            border: 1px solid rgba(16, 185, 129, 0.2);
        }
        .status-error {
            background: rgba(239, 68, 68, 0.1);
            color: #f87171;
            border: 1px solid rgba(239, 68, 68, 0.2);
        }
        .section {
            background: #1e293b;
            border: 1px solid #334155;
            border-radius: 8px;
            padding: 1.5rem;
            margin-bottom: 2rem;
        }
        .section h2 {
            font-size: 16px;
            margin-bottom: 1rem;
            color: #e2e8f0;
        }
        .btn-secondary {
            background: #1e293b;
            border: 1px solid #334155;
            color: #cbd5e1;
            padding: 10px 16px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 14px;
        }
        .btn-secondary:hover {
            background: #334155;
        }
        .btn-secondary:disabled {
            opacity: 0.6;
            cursor: default;
        }
    </style>
</head>
<body>
    <div class="navbar">
        <h2>Settings</h2>
        <a href="{{ url_for('dashboard') }}">← Back</a>
    </div>

    <div class="container">
        {% if oxidized_status %}
        <div class="status status-success">✓ Oxidized API is running and reachable</div>
        {% else %}
        <div class="status status-error">✗ Oxidized API is not reachable. Please check your installation.</div>
        {% endif %}

        <div style="margin-bottom: 1rem; display: flex; align-items: center; gap: 1rem; flex-wrap: wrap;">
            <button type="button" class="btn-secondary" id="restart-oxidized-btn" onclick="restartOxidized()">Restart Oxidized Service</button>
            <button type="button" class="btn-secondary" id="test-oxidized-btn" onclick="testOxidized()">Test Oxidized Connection</button>
            <span id="restart-oxidized-result" style="font-size: 13px;"></span>
        </div>
        <pre id="test-oxidized-result" style="display: none; background: #0f172a; border: 1px solid #334155; border-radius: 6px; padding: 1rem; margin-bottom: 1.5rem; font-size: 12px; white-space: pre-wrap; word-break: break-all; max-height: 400px; overflow: auto;"></pre>

        <form method="POST">
            <div class="section">
                <h2>Application Settings</h2>
                <div class="form-group">
                    <label>Application Name</label>
                    <input type="text" name="app_name" value="{{ settings.app_name }}">
                </div>
                <div class="form-group">
                    <label>Backup Retention (days)</label>
                    <input type="number" name="backup_retention_days" value="{{ settings.backup_retention_days }}" min="1">
                </div>
                <div class="form-group">
                    <label>Oxidized API URL</label>
                    <input type="text" name="oxidized_api_url" value="{{ settings.oxidized_api_url }}">
                </div>
            </div>
            
            <div class="section">
                <h2>LibreNMS Integration (Optional)</h2>
                <div class="form-group">
                    <label>LibreNMS URL</label>
                    <input type="text" name="librenms_url" placeholder="http://librenms.example.com" value="{{ settings.librenms_url }}">
                </div>
                <div class="form-group">
                    <label>LibreNMS API Token</label>
                    <input type="password" name="librenms_token" placeholder="Your API token here" value="{{ settings.librenms_token }}">
                </div>
                <div class="form-group checkbox-group">
                    <input type="checkbox" name="librenms_sync_enabled" id="librenms_sync" {% if settings.librenms_sync_enabled %}checked{% endif %}>
                    <label for="librenms_sync" style="margin: 0;">Enable automatic device sync from LibreNMS</label>
                </div>
            </div>
            
            <div class="section">
                <h2>GitHub Integration (Optional)</h2>
                {% if not settings.has_gitpython %}
                <div style="background: rgba(239, 68, 68, 0.1); border: 1px solid rgba(239, 68, 68, 0.2); color: #f87171; padding: 12px; border-radius: 6px; margin-bottom: 1rem;">
                    ⚠ GitPython not installed. Run: <code>pip install GitPython</code>
                </div>
                {% endif %}
                <div class="form-group">
                    <label>GitHub Repository URL</label>
                    <input type="text" name="github_repo_url" placeholder="https://github.com/user/oxidized-backups.git" value="{{ settings.github_repo_url }}">
                </div>
                <div class="form-group">
                    <label>GitHub Personal Access Token</label>
                    <input type="password" name="github_token" placeholder="Your GitHub token here" value="{{ settings.github_token }}">
                </div>
                <div class="form-group">
                    <label>GitHub Branch</label>
                    <input type="text" name="github_branch" placeholder="main" value="{{ settings.github_branch }}">
                </div>
                <div class="form-group checkbox-group">
                    <input type="checkbox" name="github_sync_enabled" id="github_sync" {% if settings.github_sync_enabled %}checked{% endif %} {% if not settings.has_gitpython %}disabled{% endif %}>
                    <label for="github_sync" style="margin: 0;">Push backups to GitHub</label>
                </div>
            </div>
            
            <button type="submit" class="btn">Save Settings</button>
        </form>
    </div>

    <script>
    function restartOxidized() {
        var btn = document.getElementById('restart-oxidized-btn');
        var result = document.getElementById('restart-oxidized-result');
        btn.disabled = true;
        result.style.color = '#cbd5e1';
        result.textContent = '⏳ Restarting...';

        fetch('{{ url_for("api_oxidized_restart") }}', { method: 'POST' })
            .then(response => response.json().then(data => ({ ok: response.ok, data: data })))
            .then(({ ok, data }) => {
                if (ok && data.status === 'success') {
                    result.style.color = '#10b981';
                    result.textContent = '✓ ' + data.message + ' - reloading...';
                    setTimeout(() => location.reload(), 2000);
                } else {
                    result.style.color = '#f87171';
                    result.textContent = '✗ ' + data.message;
                    btn.disabled = false;
                }
            })
            .catch(err => {
                result.style.color = '#f87171';
                result.textContent = '✗ ' + err;
                btn.disabled = false;
            });
    }

    function testOxidized() {
        var btn = document.getElementById('test-oxidized-btn');
        var out = document.getElementById('test-oxidized-result');
        btn.disabled = true;
        out.style.display = 'block';
        out.style.color = '#cbd5e1';
        out.textContent = 'Testing...';

        fetch('{{ url_for("api_oxidized_test") }}')
            .then(response => response.json())
            .then(data => {
                out.style.color = data.ok ? '#10b981' : '#f87171';
                out.textContent = JSON.stringify(data, null, 2);
                btn.disabled = false;
            })
            .catch(err => {
                out.style.color = '#f87171';
                out.textContent = 'Request failed: ' + err;
                btn.disabled = false;
            });
    }
    </script>
</body>
</html>'''

GROUPS_MANAGEMENT_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Group Management - Oxidized Manager</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0f172a;
            color: #f1f5f9;
        }
        .navbar {
            background: #1e293b;
            border-bottom: 1px solid #334155;
            padding: 1rem 2rem;
            display: flex;
            justify-content: space-between;
        }
        .container {
            max-width: 900px;
            margin: 0 auto;
            padding: 2rem;
        }
        .form-section {
            background: #1e293b;
            border: 1px solid #334155;
            border-radius: 8px;
            padding: 1.5rem;
            margin-bottom: 2rem;
        }
        input, textarea {
            padding: 8px 12px;
            background: #0f172a;
            border: 1px solid #334155;
            border-radius: 4px;
            color: #f1f5f9;
            margin-bottom: 0.5rem;
            width: 100%;
        }
        .btn {
            padding: 10px 16px;
            background: #2563eb;
            color: white;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            margin-bottom: 1rem;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            background: #1e293b;
            border: 1px solid #334155;
            border-radius: 8px;
        }
        th, td {
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #334155;
        }
        th {
            background: #334155;
            font-weight: 600;
        }
        .action-btn {
            padding: 6px 12px;
            margin-right: 0.5rem;
            background: transparent;
            border: 1px solid #334155;
            color: #3b82f6;
            border-radius: 4px;
            cursor: pointer;
            font-size: 12px;
        }
    </style>
</head>
<body>
    <div class="navbar">
        <h2>Device Groups</h2>
        <a href="{{ url_for('dashboard') }}">← Back</a>
    </div>
    
    <div class="container">
        <div class="form-section">
            <h3 style="margin-bottom: 1rem;">Create New Group</h3>
            <form method="POST">
                <input type="hidden" name="action" value="add">
                <input type="text" name="name" placeholder="Group Name" required>
                <textarea name="description" placeholder="Description (optional)" rows="2"></textarea>
                <input type="text" name="default_username" placeholder="Default Username (optional)">
                <input type="password" name="default_password" placeholder="Default Password (optional)">
                <button type="submit" class="btn">Create Group</button>
            </form>
        </div>
        
        <table>
            <thead>
                <tr>
                    <th>Group Name</th>
                    <th>Description</th>
                    <th>Default User</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody>
                {% for group in groups %}
                <tr>
                    <td><strong>{{ group.name }}</strong></td>
                    <td>{{ group.description or '-' }}</td>
                    <td>{{ group.default_username or '-' }}</td>
                    <td>
                        <form method="POST" style="display: inline;">
                            <input type="hidden" name="action" value="delete">
                            <input type="hidden" name="group_id" value="{{ group.id }}">
                            <button type="submit" class="action-btn" onclick="return confirm('Delete group?')">Delete</button>
                        </form>
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</body>
</html>'''

USER_MANAGEMENT_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>User Management - Oxidized Manager</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0f172a;
            color: #f1f5f9;
        }
        .navbar {
            background: #1e293b;
            border-bottom: 1px solid #334155;
            padding: 1rem 2rem;
            display: flex;
            justify-content: space-between;
        }
        .container {
            max-width: 900px;
            margin: 0 auto;
            padding: 2rem;
        }
        .btn {
            padding: 10px 16px;
            background: #2563eb;
            color: white;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            margin-bottom: 1rem;
        }
        .form-section {
            background: #1e293b;
            border: 1px solid #334155;
            border-radius: 8px;
            padding: 1.5rem;
            margin-bottom: 2rem;
        }
        input {
            padding: 8px 12px;
            background: #0f172a;
            border: 1px solid #334155;
            border-radius: 4px;
            color: #f1f5f9;
            margin-right: 0.5rem;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            background: #1e293b;
            border: 1px solid #334155;
            border-radius: 8px;
        }
        th, td {
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #334155;
        }
        th {
            background: #334155;
            font-weight: 600;
        }
    </style>
</head>
<body>
    <div class="navbar">
        <h2>User Management</h2>
        <a href="{{ url_for('dashboard') }}">← Back</a>
    </div>
    
    <div class="container">
        <div class="form-section">
            <h3 style="margin-bottom: 1rem;">Create New User</h3>
            <form method="POST">
                <input type="hidden" name="action" value="add">
                <input type="text" name="username" placeholder="Username" required>
                <input type="password" name="password" placeholder="Password" required>
                <input type="email" name="email" placeholder="Email">
                <select name="role">
                    <option value="operator">Operator</option>
                    <option value="admin">Admin</option>
                </select>
                <button type="submit" class="btn">Add User</button>
            </form>
        </div>
        
        <table>
            <thead>
                <tr>
                    <th>Username</th>
                    <th>Email</th>
                    <th>Role</th>
                    <th>Last Login</th>
                </tr>
            </thead>
            <tbody>
                {% for user in users %}
                <tr>
                    <td>{{ user.username }}</td>
                    <td>{{ user.email or '-' }}</td>
                    <td><strong>{{ user.role }}</strong></td>
                    <td>{{ user.last_login or 'Never' }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</body>
</html>'''

# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    init_db()
    
    # Check if admin user exists, show setup if not
    if not get_user('admin'):
        print('=' * 60)
        print('Oxidized + LibreNMS Manager - Initial Setup')
        print('=' * 60)
        print('Navigate to http://localhost:5000/setup to complete setup')
        print('=' * 60)
    
    app.run(
        host='0.0.0.0',
        port=int(os.environ.get('PORT', 5000)),
        debug=os.environ.get('DEBUG', 'False').lower() == 'true'
    )
