# Oxidized + LibreNMS Manager

A NOC dashboard for managing [Oxidized](https://github.com/ytti/oxidized) configuration backups, with optional [LibreNMS](https://www.librenms.org) device sync, backup history, and multi-user support.

## Features

- Real-time device status via the Oxidized REST API
- Config backup, editing, and restore with retention policy
- Device inventory with grouping (organize by site/customer)
- SSH connection testing before adding a device (requires `paramiko`)
- Optional GitHub push for off-site backups + version control (requires `GitPython`)
- Optional LibreNMS integration — auto-sync devices, pull alerts (the app is fully standalone without it)
- Multi-user support with roles (admin/operator) and audit logging
- REST API for integrations

## Requirements

- Ubuntu 22.04+ / Debian 11+
- Python 3.8+
- Oxidized 0.28.0+ (the installer sets this up if it's missing)

## Installation

```bash
git clone https://github.com/Kintoyyy/oxidized-admin
cd oxidized-admin
chmod +x install_oxidized_manager.sh
./install_oxidized_manager.sh
```

You'll be prompted for the install directory, config directory, port, and admin username/password/email. The script installs system dependencies, Oxidized (if not already present), a Python venv, initializes the database, creates a systemd service, and starts it.

Open `http://localhost:5000` and log in with the admin credentials you set.

### Manual install

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 oxidized_nms_manager.py
```

## Configuration

Environment variables (set in the systemd unit or shell):

```bash
OXIDIZED_CONFIG_DIR   # default: ~/.config/oxidized
APP_DB_PATH           # default: ~/.oxidized_manager/app.db
APP_NAME              # default: "Oxidized Manager"
PORT                  # default: 5000
SECRET_KEY            # set a real value in production
DEBUG                 # default: False
```

- **LibreNMS (optional):** Settings → enter LibreNMS URL + API token → enable sync. Devices can also always be added manually.
- **GitHub backups (optional):** Settings → GitHub Integration → repo URL + personal access token (`repo` scope) + branch → enable.
- **Device groups:** Settings → Manage Groups → create groups to organize devices, with optional default credentials per group.

## Usage

- **Dashboard** — device status and backup metrics
- **Devices** — add/edit/delete devices, Test SSH, assign to a group
- **Configuration** — edit the Oxidized `config` YAML (auto-backed up before saving)
- **Settings** — LibreNMS, GitHub, backup retention, API keys
- **Users** — manage accounts and view the audit log

### API

```bash
curl -u admin:password http://localhost:5000/api/devices
curl -u admin:password http://localhost:5000/device/<name>/config
curl -u admin:password http://localhost:5000/librenms/alerts
curl -u admin:password -X POST http://localhost:5000/api/test-ssh
```

## Service management

```bash
sudo systemctl start|stop|restart|status oxidized-manager
sudo journalctl -u oxidized-manager -f
```

## Production notes

- Set a real `SECRET_KEY`: `export SECRET_KEY="$(openssl rand -hex 32)"`
- Put it behind HTTPS (nginx reverse proxy or a Cloudflare Tunnel)
- Use a strong admin password and restrict the firewall to known IPs
- Rotate LibreNMS/GitHub tokens periodically — never commit them to git

## Troubleshooting

**Service won't start**
```bash
sudo journalctl -u oxidized-manager -n 100
sudo lsof -i :5000              # port already in use?
```

**Can't reach the Oxidized API**
```bash
sudo systemctl status oxidized
curl http://localhost:8080/api/nodes
```

**LibreNMS sync failing**
```bash
curl -H "X-Auth-Token: YOUR_TOKEN" http://<librenms-host>/api/v0/devices
```

**SSH test button disabled** → `pip install paramiko`

**GitHub integration disabled** → `pip install GitPython`

**Database issues**
```bash
sqlite3 ~/.oxidized_manager/app.db "SELECT COUNT(*) FROM device_metadata;"
rm ~/.oxidized_manager/app.db   # resets all app data — last resort
```

## Uninstall

```bash
sudo systemctl stop oxidized-manager
sudo systemctl disable oxidized-manager
sudo rm /etc/systemd/system/oxidized-manager.service
rm -rf ~/oxidized-manager ~/.oxidized_manager ~/.config/oxidized   # also deletes data
```

## License

MIT
