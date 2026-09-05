#!/usr/bin/env python3
"""
Oxidized + LibreNMS Admin Manager
Professional NOC dashboard with device management, backups, and monitoring integration.
Includes auto-installer for Oxidized and full configuration management.
"""

import csv
import json
import os
import re
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
# OXIDIZED SUPPORTED MODELS
# (vendor, OS/product label, oxidized model identifier)
# https://github.com/ytti/oxidized/blob/master/docs/Model-Notes.md
# ============================================================================

MODEL_CHOICES = [
    ('-generic-', 'Cisco-like', 'defacto'),
    ('6WIND', 'VSR', 'sixwind'),
    ('A10 Networks', 'ACOS', 'acos'),
    ('Accedian', 'AEN', 'aen'),
    ('Acme Packet', 'ACMEPACKET', 'acmepacket'),
    ('AddPack', 'AddPack', 'addpack'),
    ('Adtran', 'Total Access (AOS)', 'adtran'),
    ('ADVA', 'ADVA', 'adva'),
    ('Alcatel-Lucent', 'AOS', 'aos'),
    ('Alcatel-Lucent', 'AOS7', 'aos7'),
    ('Alcatel-Lucent', 'ISAM', 'isam'),
    ('Alcatel-Lucent', 'SR OS (Formerly TiMOS)', 'sros'),
    ('Alcatel-Lucent', 'Wireless', 'aosw'),
    ('Allied Telesis', 'Alliedware Plus', 'awplus'),
    ('Allied Telesis', 'AT-8000S, AT-8000GS series', 'powerconnect'),
    ('Alvarion', 'BreezeACCESS', 'alvarion'),
    ('APC', 'AOS', 'apcaos'),
    ('Arbor Networks', 'ArbOS', 'arbos'),
    ('Arista', 'EOS', 'eos'),
    ('Arris', 'C4CMTS', 'c4cmts'),
    ('Aruba', 'AOS-CX', 'aoscx'),
    ('Aruba', 'AOSW', 'aosw'),
    ('Aruba', 'ArubaInstant', 'arubainstant'),
    ('Asterfusion', 'AsterNOS', 'asternos'),
    ('AudioCodes', 'AudioCodes', 'audiocodes'),
    ('AudioCodes', 'MediaPack MP-1xx, Mediant1000', 'audiocodesmp'),
    ('Avaya', 'VOSS', 'voss'),
    ('Avaya', 'BOSS', 'boss'),
    ('BDCOM', 'S2200/S2500/S2900 series', 'bdcom'),
    ('Brocade', 'FabricOS', 'fabricos'),
    ('Brocade', 'Enhanced Fabric OS', 'efos'),
    ('Brocade', 'FastIron', 'fastiron'),
    ('Brocade', 'IronWare', 'ironware'),
    ('Brocade', 'NOS', 'nos'),
    ('Brocade', 'Vyatta', 'vyatta'),
    ('Brocade', '6910', 'br6910'),
    ('Brocade', 'SLX-OS', 'slxos'),
    ('Calix', 'AXOS', 'axos'),
    ('Cambium', 'PMP450 Series', 'cambium'),
    ('Cambium', 'ePMP Series', 'cambiumepmp'),
    ('Casa', 'Casa', 'casa'),
    ('Centec Networks', 'CNOS', 'cnos'),
    ('Check Point', 'GaiaOS', 'gaiaos'),
    ('Ciena', 'SAOS', 'saos'),
    ('Ciena', 'SAOS10', 'saos10'),
    ('Cisco', 'ACSW', 'acsw'),
    ('Cisco', 'AireOS', 'aireos'),
    ('Cisco', 'ASA', 'asa'),
    ('Cisco', 'AsyncOS', 'asyncos'),
    ('Cisco', 'CatOS', 'catos'),
    ('Cisco', 'Catalyst Express', 'ciscoce'),
    ('Cisco', 'ExaLink Fusion (Nexus 3550-F)', 'exalink'),
    ('Cisco', 'FireLinuxOS', 'firelinuxos'),
    ('Cisco', 'IOS', 'ios'),
    ('Cisco', 'IOSXR', 'iosxr'),
    ('Cisco', 'NGA', 'cisconga'),
    ('Cisco', 'NXOS', 'nxos'),
    ('Cisco', 'SMA', 'ciscosma'),
    ('Cisco', 'SMB (Nikola series)', 'ciscosmb'),
    ('Cisco', 'UCS', 'ucs'),
    ('Cisco', 'Viptela', 'viptela'),
    ('Cisco', 'VPN3000', 'ciscovpn3k'),
    ('Citrix', 'NetScaler (Virtual Appliance)', 'netscaler'),
    ('Coriant (former Tellabs)', 'TMOS (8800)', 'corianttmos'),
    ('Coriant (former Tellabs)', '8600', 'coriant8600'),
    ('Coriant (former Tellabs)', 'Groove', 'coriantgroove'),
    ('ComNet', 'Microsemi Switch', 'comnetms'),
    ('Comtrol', 'RocketLinx', 'comtrol'),
    ('Cumulus', 'Linux', 'cumulus'),
    ('DataCom', 'DmSwitch 3000', 'datacom'),
    ('DCN', 'DCN', 'ios'),
    ('DELL', 'PowerConnect', 'powerconnect'),
    ('DELL', 'AOSW', 'aosw'),
    ('DELL', 'DellX', 'dellx'),
    ('DELL', 'EMC Networking OS6', 'os6'),
    ('DELL', 'EMC Networking OS10', 'os10'),
    ('D-Link', 'D-Link', 'dlink'),
    ('D-Link', 'D-Link Cisco-like CLI', 'dlinknextgen'),
    ('Eaton', 'Gigabit Network Card', 'eatonnetwork'),
    ('ECI Telecom', 'ECIapollo', 'eciapollo'),
    ('EdgeCore', 'ECS3510, ES3526XA-V2, ES3528M', 'edgecos'),
    ('Eltex', 'Eltex', 'eltex'),
    ('Ericsson/Redback', 'IPOS (former SEOS)', 'ipos'),
    ('Ericsson/Redback', 'Minilink 6600', 'ml66'),
    ('Extreme Networks', 'Enterasys B/C-Series', 'enterasys'),
    ('Extreme Networks', 'Enterasys 800-Series', 'enterasys800'),
    ('Extreme Networks', 'WM', 'mtrlrfs'),
    ('Extreme Networks', 'XOS, ExtremeWare', 'xos'),
    ('F5', 'F5OS', 'tmos'),
    ('F5', 'TMOS', 'tmos'),
    ('Fiberstore (fs.com)', 'S3400', 'fsos'),
    ('Fiberstore (fs.com)', 'S3800', 'gcombnps'),
    ('Fiberstore (fs.com)', 'S3900', 'edgecos'),
    ('Fiberstore (fs.com)', 'S3900-R', 'bdcom'),
    ('Fiberstore (fs.com)', 'S5800, S5850', 'cnos'),
    ('Firebrick', 'FBxxxx', 'firebrick'),
    ('Force10', 'DNOS', 'dnos'),
    ('Force10', 'FTOS', 'ftos'),
    ('Fortinet', 'FortiGate', 'fortigate'),
    ('Fortinet', 'FortiOS', 'fortios'),
    ('Fortinet', 'FortiWLC', 'fortiwlc'),
    ('Fujitsu', 'PRIMERGY Blade switch 1/10Gbe', 'fujitsupy'),
    ('Fujitsu', '1FINITY Switches', 'onefinity'),
    ('Garderos', 'GRS', 'garderos'),
    ('GCOM Technologies', 'Broadband Network Platform Software', 'gcombnps'),
    ('Grandstream Networks', 'GSX', 'grandstream'),
    ('Grandstream Networks', 'HT8xx', 'grandstream'),
    ('Hatteras', 'Hatteras', 'hatteras'),
    ('Hillstone Networks', 'StoneOS', 'stoneos'),
    ('Hirschmann', 'Classic', 'hirschmann'),
    ('Hirschmann', 'HiOS', 'hios'),
    ('HP', 'Comware (HP A-series, H3C, 3Com)', 'comware'),
    ('HP', 'Procurve', 'procurve'),
    ('HP', 'BladeSystem (Onboard Administrator)', 'hpebladesystem'),
    ('HP', 'MSA', 'hpemsa'),
    ('HP', 'MSM (Wireless Controller)', 'hpmsm'),
    ('HP', 'H3C S6520X', 'h3c'),
    ('Huawei', 'VRP', 'vrp'),
    ('Huawei', 'SmartAX series', 'smartax'),
    ('Icotera', '6400 series', 'icotera'),
    ('Ingate', 'SIParator/Firewalls', 'ingate'),
    ('IP Infusion', 'OcNOS', 'ocnos'),
    ('Ivanti', 'Ivanti Connect Secure (ICS)', 'ivanti'),
    ('Juniper', 'JunOS', 'junos'),
    ('Juniper', 'ScreenOS (Netscreen)', 'screenos'),
    ('LANCOM Systems', 'LCOS', 'lancom'),
    ('Lenovo', 'Lenovo Network OS', 'lenovonos'),
    ('Linksys', 'SRW', 'linksyssrw'),
    ('Linuxgeneric', 'CentOS', 'linuxgeneric'),
    ('Mellanox', 'MLNX-OS', 'mlnxos'),
    ('Mellanox', 'Voltaire', 'voltaire'),
    ('Mikrotik', 'RouterOS', 'routeros'),
    ('Mikrotik', 'SwOS and SwOS Lite', 'swos'),
    ('Mimosa', 'Mimosa (B11)', 'mimosab11'),
    ('Motorola', 'RFS', 'mtrlrfs'),
    ('MRV', 'MasterOS', 'masteros'),
    ('MRV', 'FiberDriver', 'fiberdriver'),
    ('NEC', 'NEC IX', 'necix'),
    ('Netgate', 'TNSR', 'tnsr'),
    ('Netgear', 'Netgear switches', 'netgear'),
    ('Netonix', 'WISP Switch', 'netonix'),
    ('Nokia (formerly Alcatel-Lucent)', 'SR OS (TiMOS)', 'sros'),
    ('Nokia (formerly Alcatel-Lucent)', 'SR OS Model-Driven CLI (7705/7210/7450/7750/7950/NSP)', 'srosmd'),
    ('OneAccess', 'OneOS', 'oneos'),
    ('OneAccess', 'TDRE', 'tdre'),
    ('OpenBSD', 'OpenBSD', 'openbsd'),
    ('Opengear', 'Opengear', 'opengear'),
    ('OpenWRT', 'OpenWRT', 'openwrt'),
    ('OPNsense', 'OPNsense', 'opnsense'),
    ('Palo Alto', 'PanOS API', 'panos_api'),
    ('Palo Alto', 'PanOS', 'panos'),
    ('Perle', 'IOLAN Console Servers', 'perle'),
    ('PLANET', 'SG/SGS Switches', 'planet'),
    ('pfSense', 'pfSense', 'pfsense'),
    ('Pure Storage', 'PurityOS', 'purityos'),
    ('Radware', 'AlteonOS', 'alteonos'),
    ('Raisecom', 'Raisecom', 'raisecom'),
    ('Riverbed', 'SteelHead', 'riverbed'),
    ('Ruijie Networks', 'RGOS', 'rgos'),
    ('QTECH', 'QSW-2800/3400/3450/3500', 'qtech'),
    ('Quanta', 'Quanta / VxWorks 6.6', 'quantaos'),
    ('Siklu', 'EtherHaul', 'siklu'),
    ('Siklu', 'Multihaul TG', 'siklumhtg'),
    ('Seiko Solutions', 'SmartCS, SmartCS mini', 'smartcs'),
    ('SmartByte', 'LT-S8228G series', 'smartbyte'),
    ('SonicWALL', 'SonicOS', 'sonicos'),
    ('SONiC', 'Enterprise SONiC', 'enterprise_sonic'),
    ('SNR', 'SNR-S300G, S2xxx, S3xxx, S4xxx', 'dcnos'),
    ('Speedtouch', 'Thomson Speedtouch', 'speedtouch'),
    ('Supermicro', 'SSE-G2252, G2252P', 'edgecos'),
    ('Supermicro', 'SSE-G48-TG4, G24-TG4', 'aricentiss'),
    ('Supermicro', 'SSE-X24S, X24SR, X3348S/SR/T/TR', 'aricentiss'),
    ('Supermicro', 'SBM-GEM-X2C, GEM-X2C+, GEM-X3S+, XEM-X10SM', 'aricentiss'),
    ('Symantec', 'Blue Coat ProxySG / SGOS', 'sgos'),
    ('Telco Systems', 'T-Marc 3306', 'telco'),
    ('Trango Systems', 'Trango', 'trango'),
    ('TrueNAS', 'TrueNAS', 'truenas'),
    ('TPLink', 'TPLink', 'tplink'),
    ('TPLink', 'DeltaStream GPON OLT', 'tplink'),
    ('TPLink', 'TL-SL5428', 'edgecos'),
    ('TPLink', 'TL-SL3428', 'powerconnect'),
    ('Ubiquiti', 'AirOS', 'airos'),
    ('Ubiquiti', 'Edgeos', 'edgeos'),
    ('Ubiquiti', 'EdgeSwitch', 'edgeswitch'),
    ('Ubiquiti', 'AirFiber', 'airfiber'),
    ('Ubiquiti', 'UnifiAP', 'unifiap'),
    ('Uplink', 'EP4440-DP', 'EP4440'),
    ('VMWare', 'NSX Edge (configuration)', 'nsxconfig'),
    ('VMWare', 'NSX Edge (firewall rules)', 'nsxfirewall'),
    ('VMWare', 'NSX Distributed Firewall', 'nsxdfw'),
    ('VSOL', 'GPON OLT', 'vsololt'),
    ('VYOS Networks', 'VYOS', 'vyos'),
    ('Watchguard', 'Fireware OS', 'firewareos'),
    ('Waystream (PacketFront)', 'iBOS', 'ibos'),
    ('Westell', 'Westell 8178G, Westell 8266G', 'weos'),
    ('Yadro', 'KornfeldOS', 'kornfeldos'),
    ('YAMAHA', 'NVR/RTX Series', 'yamaha'),
    ('Zhone', 'Zhone (OLT and MX)', 'zhoneolt'),
    ('ZPE', 'Nodegrid OS', 'nodegrid'),
    ('ZTE', 'C300&C320 OLT', 'zteolt'),
    ('Zyxel', 'ZyNOS', 'zynos'),
    ('Zyxel', 'ZyNOS GS-series variant', 'zynosgs'),
    ('Zyxel', 'ZyNOS ADSL', 'zynosadsl'),
    ('Zyxel', 'ZyNOS CLI (DSLAMs)', 'zynoscli'),
    ('Zyxel', 'ZyNOS MGS series', 'zynosmgs'),
    ('Zyxel', 'NDMS', 'ndms'),
    ('Zyxel', '1308', 'zy1308'),
]

def get_model_groups():
    """MODEL_CHOICES grouped by vendor, preserving order, for a grouped <select>."""
    groups = []
    current_vendor = None
    current_options = None
    for vendor, os_label, model in MODEL_CHOICES:
        if vendor != current_vendor:
            current_vendor = vendor
            current_options = []
            groups.append((vendor, current_options))
        current_options.append((os_label, model))
    return groups

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

def trigger_oxidized_update(node_name, group='default'):
    """Queue a node for immediate re-fetch by Oxidized (matches the native 'Update configuration'
    action, which hits /node/next/<group>/<node> — it just queues the job on Oxidized's own
    scheduler and returns right away, unlike /node/fetch which blocks on a live SSH connection)."""
    try:
        group_seg = f'{group}/' if group else ''
        response = requests.get(f'{get_oxidized_api_url()}/node/next/{group_seg}{node_name}.json', timeout=10)
        response.raise_for_status()
        return True
    except Exception as e:
        print(f'Error triggering update: {e}')
        return False

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

# oxidized-web's /nodes/stats.json is broken in the versions we've tested against -
# it serializes each node's Oxidized::Node::Stats object with Ruby's default
# to-string representation (e.g. "#<Oxidized::Node::Stats:0x...>") instead of real
# fields, since that class doesn't implement JSON serialization. The plain HTML
# page (/nodes/stats, no .json) renders the real numbers directly in its table, so
# we parse that instead.
OXIDIZED_STATS_ROW_RE = re.compile(
    r"<tr[^>]*>\s*"
    r"<td>([^<]*)</td>\s*"           # name
    r"<td>([^<]*)</td>\s*"           # total runs
    r"<td>([^<]*)</td>\s*"           # total failures
    r"<td>([^<]*)</td>\s*"           # failure rate
    r"<td>([^<]*)</td>\s*"           # average run time
    r"<td>.*?<div class='([^']*)'.*?</td>\s*"           # last status
    r"<td class='time' epoch='([^']*)'>([^<]*)</td>\s*"  # last update
    r"<td class='time' epoch='([^']*)'>([^<]*)</td>\s*"  # last failure
    r"</tr>",
    re.DOTALL
)

def get_oxidized_stats():
    """Fetch per-node run stats by parsing Oxidized's /nodes/stats HTML page."""
    try:
        response = requests.get(f'{get_oxidized_api_url()}/nodes/stats', timeout=5)
        response.raise_for_status()
        html = response.text
    except Exception as e:
        print(f'Oxidized stats error: {e}')
        return {}

    stats = {}
    for m in OXIDIZED_STATS_ROW_RE.finditer(html):
        (name, total_runs, total_failures, failure_rate, avg_run_time, last_status,
         _last_update_epoch, last_update, _last_failure_epoch, last_failure) = m.groups()
        stats[name.strip()] = {
            'total_runs': total_runs.strip(),
            'total_failures': total_failures.strip(),
            'failure_rate': failure_rate.strip(),
            'avg_run_time': avg_run_time.strip(),
            'last_status': last_status.strip(),
            'last_update': last_update.strip(),
            'last_failure': last_failure.strip(),
        }
    return stats

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
        node_stats = oxidized_stats.get(node.get('name'), {})

        devices.append({
            'name': node.get('name'),
            'ip': node.get('ip'),
            'model': node.get('model'),
            'group': node.get('group') or 'default',
            'status': node.get('status'),
            'last_update': node.get('time'),
            'mtime': node.get('mtime'),
            'metadata': dict(meta) if meta else {},
            'total_failures': node_stats.get('total_failures'),
            'failure_rate': node_stats.get('failure_rate'),
            'avg_run_time': node_stats.get('avg_run_time'),
            'last_failure': node_stats.get('last_failure')
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
    """Queue an immediate re-fetch for a device via Oxidized (matches the native
    'Update configuration' action, which hits /node/next — this just queues the job
    on Oxidized's own scheduler and returns right away; it does not hand back the
    fetched content, since the actual SSH pull happens asynchronously)."""
    group = get_device_group(device_name)
    ok = trigger_oxidized_update(device_name, group)
    device_ip = next((d['ip'] for d in read_router_db() if d['name'] == device_name), None)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if not ok:
        c.execute('''INSERT INTO backup_history (device_ip, device_name, status, error_message)
                     VALUES (?, ?, 'error', 'Failed to queue update with Oxidized')''',
                  (device_ip, device_name))
        conn.commit()
        conn.close()
        return jsonify({'status': 'error', 'message': 'Failed to queue update with Oxidized'}), 500

    c.execute('''INSERT INTO backup_history (device_ip, device_name, status)
                 VALUES (?, ?, 'queued')''', (device_ip, device_name))
    conn.commit()
    conn.close()

    log_audit('device_update_requested', 'device', device_name)
    return jsonify({'status': 'success', 'message': 'Update queued. Oxidized will fetch it shortly.'})

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
    
    # Get groups (and their default credentials, for autofill) for the dropdown
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT name, default_username, default_password FROM device_groups ORDER BY name')
    group_rows = [dict(row) for row in c.fetchall()]
    conn.close()

    groups = [g['name'] for g in group_rows]
    group_defaults = {
        g['name']: {'username': g['default_username'] or '', 'password': g['default_password'] or ''}
        for g in group_rows
    }

    return render_template_string(DEVICE_MANAGEMENT_TEMPLATE, devices=devices, groups=groups,
                                  model_groups=get_model_groups(), group_defaults=group_defaults)

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

.shell { display: flex; min-height: 100vh; align-items: stretch; }
.sidebar {
    width: 208px; flex-shrink: 0;
    background: var(--card); border-right: 1px solid var(--border);
    display: flex; flex-direction: column;
    padding: 0.85rem 0.6rem;
    position: sticky; top: 0; height: 100vh; overflow-y: auto;
}
.sidebar .brand {
    font-weight: 600; font-size: 13px; padding: 4px 8px 14px;
    color: var(--foreground); display: block;
}
.sidebar nav { display: flex; flex-direction: column; gap: 2px; flex: 1; }
.sidebar nav a {
    padding: 7px 9px; border-radius: var(--radius);
    font-size: 13px; color: var(--muted-foreground);
    transition: background .15s, color .15s;
}
.sidebar nav a:hover { background: var(--accent); color: var(--foreground); }
.sidebar nav a.active { background: var(--accent); color: var(--foreground); font-weight: 500; }
.sidebar .bottom { padding-top: 0.6rem; margin-top: 0.6rem; border-top: 1px solid var(--border); }
.sidebar .bottom a {
    display: block; padding: 7px 9px; border-radius: var(--radius);
    font-size: 13px; color: var(--muted-foreground);
}
.sidebar .bottom a:hover { background: var(--accent); color: var(--foreground); }

.main { flex: 1; min-width: 0; }
.page { max-width: 1280px; margin: 0 auto; padding: 1.5rem; }
.page-full { max-width: none; padding: 1.5rem; }
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

def render_sidebar(active):
    """Left sidebar shared across all authenticated pages, with the current section highlighted."""
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
    return ('''<aside class="sidebar">
        <a class="brand" href="{{ url_for('dashboard') }}">Oxidized Manager</a>
        <nav>''' + links + '''</nav>
        <div class="bottom"><a href="{{ url_for('logout') }}">Logout</a></div>
    </aside>
    ''')

LOGIN_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Login - Oxidized Manager</title>
    <style>''' + BASE_CSS + '''</style>
</head>
<body>
<div class="auth-shell">
    <div class="auth-card card">
        <div class="card-content">
            <div class="auth-logo">Oxidized Manager</div>

            {% with messages = get_flashed_messages(category_filter=['danger']) %}
                {% if messages %}
                    <div class="alert alert-danger">{{ messages[0] }}</div>
                {% endif %}
            {% endwith %}

            <form method="POST">
                <div class="field">
                    <label>Username</label>
                    <input type="text" name="username" required>
                </div>
                <div class="field">
                    <label>Password</label>
                    <input type="password" name="password" required>
                </div>
                <button type="submit" class="btn" style="width: 100%;">Sign in</button>
            </form>
        </div>
    </div>
</div>
</body>
</html>'''

SETUP_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Setup - Oxidized Manager</title>
    <style>''' + BASE_CSS + '''</style>
</head>
<body>
<div class="auth-shell">
    <div class="auth-card card" style="max-width: 440px;">
        <div class="card-content">
            <h1 style="margin-bottom: 0.35rem;">Initial Setup</h1>
            <p class="muted" style="font-size: 13px; margin-bottom: 1.5rem;">Create your admin account to get started</p>

            <form method="POST">
                <div class="field">
                    <label>Admin Username</label>
                    <input type="text" name="username" value="admin" required>
                    <div class="help-text">You can change this after setup</div>
                </div>

                <div class="field">
                    <label>Admin Password</label>
                    <input type="password" name="password" placeholder="Min 8 characters" required minlength="8">
                </div>

                <div class="field">
                    <label>Email Address</label>
                    <input type="email" name="email" placeholder="admin@example.com">
                </div>

                <button type="submit" class="btn" style="width: 100%;">Create Admin Account</button>
            </form>
        </div>
    </div>
</div>
</body>
</html>'''

DASHBOARD_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Dashboard - Oxidized Manager</title>
    <style>''' + BASE_CSS + '''
    </style>
</head>
<body>
<div class="shell">
''' + render_sidebar('dashboard') + '''
<main class="main"><div class="page">
    <div class="stats-grid">
        <div class="stat-card">
            <div class="stat-label">Total Devices</div>
            <div class="stat-value">{{ stats.total }}</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Healthy</div>
            <div class="stat-value" style="color: #4ade80;">{{ stats.healthy }}</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Pending</div>
            <div class="stat-value" style="color: #fbbf24;">{{ stats.pending }}</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Failed</div>
            <div class="stat-value" style="color: #f87171;">{{ stats.failed }}</div>
        </div>
    </div>

    <div class="table-wrap">
        <table class="table">
            <thead>
                <tr>
                    <th>Name</th>
                    <th>Model</th>
                    <th>Group</th>
                    <th>Last Status</th>
                    <th>Last Update</th>
                    <th>Last Changed</th>
                    <th>Failures</th>
                    <th>Failure Rate</th>
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
                        <div class="muted" style="font-family: ui-monospace, monospace; font-size: 12px;">{{ device.ip }}</div>
                    </td>
                    <td>{{ device.model or '-' }}</td>
                    <td>{{ device.group or 'default' }}</td>
                    <td>
                        <span class="badge {{ 'badge-success' if device.status == 'success' else ('badge-destructive' if device.status == 'error' else 'badge-warning') }}">
                            {{ device.status or 'unknown' }}
                        </span>
                    </td>
                    <td>{{ device.last_update or 'never' }}</td>
                    <td>{{ device.mtime or 'unknown' }}</td>
                    <td>{{ device.total_failures if device.total_failures is not none else '-' }}</td>
                    <td>{{ device.failure_rate if device.failure_rate is not none else '-' }}</td>
                    <td>{{ device.avg_run_time if device.avg_run_time is not none else '-' }}</td>
                    <td>{{ device.last_failure if device.last_failure is not none else 'never' }}</td>
                    <td>
                        <div class="flex">
                            <a href="{{ url_for('device_detail', device_name=device.name) }}" class="btn btn-outline btn-sm">View</a>
                            <button type="button" class="btn btn-outline btn-sm" id="update-btn-{{ loop.index0 }}" onclick="updateDeviceNow('{{ device.name }}', {{ loop.index0 }})">Update</button>
                        </div>
                        <span id="update-result-{{ loop.index0 }}" style="font-size: 12px;"></span>
                    </td>
                </tr>
                {% else %}
                <tr><td colspan="11">No devices found. Sync from LibreNMS or add one from the Devices page.</td></tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</div></main>
</div>

    <script>
    function updateDeviceNow(name, idx) {
        var btn = document.getElementById('update-btn-' + idx);
        var result = document.getElementById('update-result-' + idx);
        btn.disabled = true;
        result.style.color = '#cbd5e1';
        result.textContent = '⏳ queuing...';

        fetch('/api/oxidized/fetch/' + encodeURIComponent(name), { method: 'POST' })
            .then(response => response.json().then(data => ({ ok: response.ok, data: data })))
            .then(({ ok, data }) => {
                if (ok && data.status === 'success') {
                    result.style.color = '#10b981';
                    result.textContent = '✓ queued';
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
    <title>{{ device_name }} - Oxidized Manager</title>
    <style>''' + BASE_CSS + '''
        .diff-add { background: rgba(16, 185, 129, 0.15); color: #6ee7b7; }
        .diff-remove { background: rgba(239, 68, 68, 0.15); color: #fca5a5; }
        #version-content, #diff-content { display: none; margin-top: 1rem; }
        .diff-picker select { min-width: 220px; }
        #config-viewer, #version-content, #diff-old, #diff-new {
            height: calc(100vh - 260px);
            max-height: none;
        }
    </style>
</head>
<body>
<div class="shell">
''' + render_sidebar('manage_devices') + '''
<main class="main"><div class="page-full">
    <div class="page-header">
        <h1>{{ device_name }}</h1>
        <a class="btn btn-outline btn-sm" href="{{ url_for('manage_devices') }}">Back to Devices</a>
    </div>

    <div class="tabs">
        <button class="tab active" onclick="showTab('config')">Config</button>
        <button class="tab" onclick="showTab('history')">Versions</button>
        <button class="tab" onclick="showTab('backups')">Backups</button>
    </div>

    <div id="config" class="tab-content active">
        <div class="flex mb-2">
            <button class="btn" id="update-config-btn" onclick="updateConfig()">Update Configuration</button>
            <button class="btn btn-outline" onclick="rawView('config-viewer', '{{ device_name }}.conf')">Raw</button>
            <button class="btn btn-outline" onclick="downloadContent('config-viewer', '{{ device_name }}.conf')">Download</button>
            <span id="update-config-result" style="font-size: 13px;"></span>
        </div>
        <div class="code-viewer" id="config-viewer">{{ config or 'No configuration found' }}</div>
    </div>

    <div id="history" class="tab-content">
        <div class="table-wrap">
            <table class="table">
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
                            <button class="btn btn-outline btn-sm" onclick='viewVersion({{ v|tojson }})'>View</button>
                        </td>
                    </tr>
                {% else %}
                    <tr><td colspan="3">No version history yet</td></tr>
                {% endfor %}
                </tbody>
            </table>
        </div>
        <div class="code-viewer" id="version-content"></div>
        <div id="version-content-actions" class="flex" style="display: none; margin-top: 0.5rem;">
            <button class="btn btn-outline btn-sm" onclick="rawView('version-content', '{{ device_name }}-version.conf')">Raw</button>
            <button class="btn btn-outline btn-sm" onclick="downloadContent('version-content', '{{ device_name }}-version.conf')">Download</button>
        </div>

        <div class="card" style="margin-top: 1.5rem;">
            <div class="card-header"><div class="card-title">Compare Versions</div></div>
            <div class="card-content">
                <div style="display: flex; gap: 1rem; align-items: flex-end; flex-wrap: wrap;">
                    <div class="field" style="margin-bottom:0;">
                        <label>Version</label>
                        <select id="diff-select-a"></select>
                    </div>
                    <div class="field" style="margin-bottom:0;">
                        <label>Compared against</label>
                        <select id="diff-select-b"></select>
                    </div>
                    <button class="btn" onclick="compareDiffs()">Get Diffs</button>
                </div>
            </div>
        </div>

        <div id="diff-content">
            <div class="grid-2">
                <div>
                    <div id="diff-label-old" class="muted" style="font-size: 12px; margin-bottom: 0.4rem;"></div>
                    <div class="code-viewer" id="diff-old"></div>
                </div>
                <div>
                    <div id="diff-label-new" class="muted" style="font-size: 12px; margin-bottom: 0.4rem;"></div>
                    <div class="code-viewer" id="diff-new"></div>
                </div>
            </div>
        </div>
    </div>

    <div id="backups" class="tab-content">
        {% for backup in backups %}
        <div class="card flex-between" style="padding: 1rem; margin-bottom: 0.75rem;">
            <div>
                <div class="muted" style="font-size: 12px;">{{ backup.created_at }}</div>
                <div>Status: <span class="badge {{ 'badge-success' if backup.status == 'success' else ('badge-warning' if backup.status == 'queued' else 'badge-destructive') }}">{{ backup.status }}</span></div>
                {% if backup.file_size %}
                <div class="muted" style="font-size: 12px;">Size: {{ backup.file_size }} bytes</div>
                {% endif %}
                {% if backup.error_message %}
                <div class="muted" style="font-size: 12px;">{{ backup.error_message }}</div>
                {% endif %}
            </div>
            <a class="btn btn-outline btn-sm" href="{{ url_for('get_device_config', device_name=device_name) }}" download="{{ device_name }}.conf" title="Downloads the device's current config (this app doesn't store a separate copy per backup entry)">Download</a>
        </div>
        {% else %}
        <div class="muted">No backups logged yet through this app. Click "Update Configuration" on the Config tab to trigger one - Oxidized's own scheduled backups show up under Versions instead.</div>
        {% endfor %}
    </div>
</div></main>
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
        btn.disabled = true;
        result.style.color = '#cbd5e1';
        result.textContent = '⏳ Queuing update with Oxidized...';

        fetch('{{ url_for("api_oxidized_fetch", device_name=device_name) }}', { method: 'POST' })
            .then(response => response.json().then(data => ({ ok: response.ok, data: data })))
            .then(({ ok, data }) => {
                if (ok && data.status === 'success') {
                    result.style.color = '#10b981';
                    result.textContent = '✓ ' + data.message + ' Reload this page in a few seconds to see the fetched config.';
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
    <style>''' + BASE_CSS + '''
        .test-result { display: none; }
        .test-result.show { display: table-row; }
        .test-result td { padding: 10px 12px; font-size: 12px; text-align: center; }
        .test-result.success { background: rgba(34, 197, 94, 0.1); color: #4ade80; }
        .test-result.error { background: rgba(239, 68, 68, 0.1); color: #f87171; }
    </style>
</head>
<body>
<div class="shell">
''' + render_sidebar('manage_devices') + '''
<main class="main"><div class="page">
    <div class="page-header">
        <h1>Device Management</h1>
        <div class="flex">
            <button class="btn btn-outline btn-sm" onclick="location.href='{{ url_for('manage_groups') }}'">Manage Groups</button>
            <button class="btn btn-sm" onclick="showAddForm()">+ Add Device</button>
        </div>
    </div>

    <div id="add-form" class="card mb-2" style="display: none;">
        <div class="card-header"><div class="card-title" id="form-title">Add New Device</div></div>
        <div class="card-content">
            <form method="POST" id="device-form">
                <input type="hidden" name="action" id="form-action" value="add">
                <div class="grid-2 mb-2">
                    <div class="field">
                        <label>Device Name</label>
                        <input type="text" name="name" id="field-name" placeholder="Device Name" required>
                    </div>
                    <div class="field">
                        <label>IP Address</label>
                        <input type="text" name="ip" id="field-ip" placeholder="10.25.1.1" required>
                    </div>
                    <div class="field">
                        <label>Model</label>
                        <select name="model" id="field-model">
                            <option value="">-- Select Model --</option>
                            {% for vendor, options in model_groups %}
                            <optgroup label="{{ vendor }}">
                                {% for os_label, model in options %}
                                <option value="{{ model }}">{{ os_label }} ({{ model }})</option>
                                {% endfor %}
                            </optgroup>
                            {% endfor %}
                        </select>
                    </div>
                    <div class="field">
                        <label>SSH Username</label>
                        <input type="text" name="username" id="field-username" placeholder="SSH Username">
                    </div>
                    <div class="field">
                        <label>SSH Password</label>
                        <input type="password" name="password" id="field-password" placeholder="SSH Password">
                    </div>
                    <div class="field">
                        <label>Group</label>
                        <select name="group" id="field-group" required onchange="applyGroupDefaults()">
                            {% for g in groups %}
                            <option value="{{ g }}">{{ g }}</option>
                            {% else %}
                            <option value="default">default</option>
                            {% endfor %}
                        </select>
                    </div>
                    <div class="field">
                        <label>SSH Port</label>
                        <input type="number" name="ssh_port" id="field-ssh_port" placeholder="22" value="22" min="1" max="65535">
                    </div>
                </div>
                <div class="flex">
                    <button type="submit" class="btn">Save Device</button>
                    <button type="button" class="btn btn-outline" onclick="hideForm()">Cancel</button>
                </div>
            </form>
        </div>
    </div>

    <div class="table-wrap">
        <table class="table">
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
                    <td><span class="badge">{{ device.group }}</span></td>
                    <td>{{ device.get('ssh_port', 22) }}</td>
                    <td>
                        <button class="btn btn-outline btn-sm" onclick="testSSH('{{ device.name }}', '{{ device.ip }}', '{{ device.username }}', '{{ device.password }}', {{ device.get('ssh_port', 22) }})">Test SSH</button>
                        <button class="btn btn-outline btn-sm" onclick='editDevice({{ device|tojson }})'>Edit</button>
                        <form method="POST" style="display: inline;">
                            <input type="hidden" name="action" value="delete">
                            <input type="hidden" name="ip" value="{{ device.ip }}">
                            <button type="submit" class="btn btn-outline btn-sm" style="color: #f87171;" onclick="return confirm('Delete device?')">Delete</button>
                        </form>
                    </td>
                </tr>
                <tr id="test-result-{{ loop.index0 }}" class="test-result">
                    <td colspan="6"></td>
                </tr>
                {% else %}
                <tr><td colspan="6">No devices yet. Click "+ Add Device" to add one.</td></tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</div></main>
</div>

    <script>
    var GROUP_DEFAULTS = {{ group_defaults|tojson }};

    function applyGroupDefaults() {
        var groupName = document.getElementById('field-group').value;
        var defaults = GROUP_DEFAULTS[groupName];
        if (!defaults) return;
        var usernameField = document.getElementById('field-username');
        var passwordField = document.getElementById('field-password');
        if (defaults.username) usernameField.value = defaults.username;
        if (defaults.password) passwordField.value = defaults.password;
    }

    function resetForm() {
        document.getElementById('device-form').reset();
        document.getElementById('form-action').value = 'add';
        document.getElementById('field-ip').readOnly = false;
        document.getElementById('form-title').textContent = 'Add New Device';
        applyGroupDefaults();
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
    <style>''' + BASE_CSS + '''
        textarea { height: 75vh; font-size: 13px; }
    </style>
</head>
<body>
<div class="shell">
''' + render_sidebar('manage_config') + '''
<main class="main"><div class="page-full">
    <div class="page-header">
        <h1>Oxidized Configuration</h1>
    </div>

    <form method="POST">
        <input type="hidden" name="action" value="update_yaml">
        <textarea name="yaml_content" required class="mb-2">{{ config_yaml }}</textarea>
        <button type="submit" class="btn">Save Configuration</button>
    </form>
</div></main>
</div>
</body>
</html>'''

SETTINGS_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Settings - Oxidized Manager</title>
    <style>''' + BASE_CSS + '''</style>
</head>
<body>
<div class="shell">
''' + render_sidebar('settings') + '''
<main class="main"><div class="page" style="max-width: 760px;">
    <div class="page-header"><h1>Settings</h1></div>

    {% if oxidized_status %}
    <div class="alert alert-success">Oxidized API is running and reachable</div>
    {% else %}
    <div class="alert alert-danger">Oxidized API is not reachable. Please check your installation.</div>
    {% endif %}

    <div class="flex mb-2" style="flex-wrap: wrap;">
        <button type="button" class="btn btn-outline btn-sm" id="restart-oxidized-btn" onclick="restartOxidized()">Restart Oxidized Service</button>
        <button type="button" class="btn btn-outline btn-sm" id="test-oxidized-btn" onclick="testOxidized()">Test Oxidized Connection</button>
        <span id="restart-oxidized-result" style="font-size: 13px;"></span>
    </div>
    <pre id="test-oxidized-result" class="code-viewer mb-2" style="display: none; max-height: 400px;"></pre>

    <form method="POST">
        <div class="card mb-2">
            <div class="card-header"><div class="card-title">Application Settings</div></div>
            <div class="card-content">
                <div class="field">
                    <label>Application Name</label>
                    <input type="text" name="app_name" value="{{ settings.app_name }}">
                </div>
                <div class="field">
                    <label>Backup Retention (days)</label>
                    <input type="number" name="backup_retention_days" value="{{ settings.backup_retention_days }}" min="1">
                </div>
                <div class="field">
                    <label>Oxidized API URL</label>
                    <input type="text" name="oxidized_api_url" value="{{ settings.oxidized_api_url }}">
                </div>
            </div>
        </div>

        <div class="card mb-2">
            <div class="card-header"><div class="card-title">LibreNMS Integration (Optional)</div></div>
            <div class="card-content">
                <div class="field">
                    <label>LibreNMS URL</label>
                    <input type="text" name="librenms_url" placeholder="http://librenms.example.com" value="{{ settings.librenms_url }}">
                </div>
                <div class="field">
                    <label>LibreNMS API Token</label>
                    <input type="password" name="librenms_token" placeholder="Your API token here" value="{{ settings.librenms_token }}">
                </div>
                <div class="flex" style="margin-bottom: 0;">
                    <input type="checkbox" name="librenms_sync_enabled" id="librenms_sync" style="width: auto;" {% if settings.librenms_sync_enabled %}checked{% endif %}>
                    <label for="librenms_sync" style="margin: 0;">Enable automatic device sync from LibreNMS</label>
                </div>
            </div>
        </div>

        <div class="card mb-2">
            <div class="card-header"><div class="card-title">GitHub Integration (Optional)</div></div>
            <div class="card-content">
                {% if not settings.has_gitpython %}
                <div class="alert alert-danger">GitPython not installed. Run: <code>pip install GitPython</code></div>
                {% endif %}
                <div class="field">
                    <label>GitHub Repository URL</label>
                    <input type="text" name="github_repo_url" placeholder="https://github.com/user/oxidized-backups.git" value="{{ settings.github_repo_url }}">
                </div>
                <div class="field">
                    <label>GitHub Personal Access Token</label>
                    <input type="password" name="github_token" placeholder="Your GitHub token here" value="{{ settings.github_token }}">
                </div>
                <div class="field">
                    <label>GitHub Branch</label>
                    <input type="text" name="github_branch" placeholder="main" value="{{ settings.github_branch }}">
                </div>
                <div class="flex" style="margin-bottom: 0;">
                    <input type="checkbox" name="github_sync_enabled" id="github_sync" style="width: auto;" {% if settings.github_sync_enabled %}checked{% endif %} {% if not settings.has_gitpython %}disabled{% endif %}>
                    <label for="github_sync" style="margin: 0;">Push backups to GitHub</label>
                </div>
            </div>
        </div>

        <button type="submit" class="btn">Save Settings</button>
    </form>
</div></main>
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
    <style>''' + BASE_CSS + '''</style>
</head>
<body>
<div class="shell">
''' + render_sidebar('manage_devices') + '''
<main class="main"><div class="page" style="max-width: 900px;">
    <div class="page-header">
        <h1>Device Groups</h1>
        <a class="btn btn-outline btn-sm" href="{{ url_for('manage_devices') }}">Back to Devices</a>
    </div>

    <div class="card mb-2">
        <div class="card-header"><div class="card-title">Create New Group</div></div>
        <div class="card-content">
            <form method="POST">
                <input type="hidden" name="action" value="add">
                <div class="field">
                    <label>Group Name</label>
                    <input type="text" name="name" placeholder="Group Name" required>
                </div>
                <div class="field">
                    <label>Description</label>
                    <textarea name="description" placeholder="Description (optional)" rows="2"></textarea>
                </div>
                <div class="field">
                    <label>Default Username</label>
                    <input type="text" name="default_username" placeholder="Default Username (optional)">
                </div>
                <div class="field">
                    <label>Default Password</label>
                    <input type="password" name="default_password" placeholder="Default Password (optional)">
                </div>
                <button type="submit" class="btn">Create Group</button>
            </form>
        </div>
    </div>

    <div class="table-wrap">
        <table class="table">
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
                            <button type="submit" class="btn btn-outline btn-sm" onclick="return confirm('Delete group?')">Delete</button>
                        </form>
                    </td>
                </tr>
                {% else %}
                <tr><td colspan="4">No groups yet.</td></tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</div></main>
</div>
</body>
</html>'''

USER_MANAGEMENT_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>User Management - Oxidized Manager</title>
    <style>''' + BASE_CSS + '''</style>
</head>
<body>
<div class="shell">
''' + render_sidebar('manage_users') + '''
<main class="main"><div class="page" style="max-width: 900px;">
    <div class="page-header"><h1>User Management</h1></div>

    <div class="card mb-2">
        <div class="card-header"><div class="card-title">Create New User</div></div>
        <div class="card-content">
            <form method="POST">
                <input type="hidden" name="action" value="add">
                <div class="grid-2">
                    <div class="field">
                        <label>Username</label>
                        <input type="text" name="username" placeholder="Username" required>
                    </div>
                    <div class="field">
                        <label>Password</label>
                        <input type="password" name="password" placeholder="Password" required>
                    </div>
                    <div class="field">
                        <label>Email</label>
                        <input type="email" name="email" placeholder="Email">
                    </div>
                    <div class="field">
                        <label>Role</label>
                        <select name="role">
                            <option value="operator">Operator</option>
                            <option value="admin">Admin</option>
                        </select>
                    </div>
                </div>
                <button type="submit" class="btn">Add User</button>
            </form>
        </div>
    </div>

    <div class="table-wrap">
        <table class="table">
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
                    <td><span class="badge">{{ user.role }}</span></td>
                    <td>{{ user.last_login or 'Never' }}</td>
                </tr>
                {% else %}
                <tr><td colspan="4">No users found.</td></tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</div></main>
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
