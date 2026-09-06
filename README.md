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

The installer must be run as root — it creates a dedicated `oxidized` system user, installs Oxidized under it, and then installs the admin page.

```bash
git clone https://github.com/Kintoyyy/oxidized-admin
cd oxidized-admin
chmod +x install_oxidized_manager.sh
sudo ./install_oxidized_manager.sh
```

Or, without cloning first:

```bash
sudo bash -c "$(curl -fsSL https://raw.githubusercontent.com/Kintoyyy/oxidized-admin/refs/heads/main/install_oxidized_manager.sh)"
```

You'll be prompted for the admin page install directory, Oxidized config directory, and admin username/password/email (the admin page always runs on port 5000 internally). The script then:

1. Detects any existing Oxidized install — you can **skip** it (leave as-is), **nuke** it (reinstall the gems fresh, keeping existing backups/config), or cancel.
2. If installing, creates the `oxidized` system user, grants it passwordless sudo, installs build dependencies, and installs the `oxidized`/`oxidized-web`/`oxidized-script` gems.
3. Sets up an `oxidized.service` systemd unit running as that user, and restricts Oxidized's REST/web interface (port 8888) to `127.0.0.1` — the admin page always talks to it over localhost, so it's never exposed by default (see [Securing the Oxidized Web GUI](#securing-the-oxidized-web-gui) to expose it deliberately).
4. Optionally installs Nginx as a reverse proxy for the **admin page** on port 80 (recommended — lets you reach it at `http://<host>/` instead of `http://<host>:5000`), and separately offers to expose the Oxidized web GUI itself on port 8888, either behind Nginx with basic auth for browser access, or bound directly for LibreNMS's built-in Oxidized widget (which talks to Oxidized's REST API directly and doesn't support basic auth).
5. Always does a fresh `git clone` of this repo and overwrites the admin page files (`oxidized_nms_manager.py`, `requirements.txt`, any `.html` templates) in the install directory, initializes the database, and sets up the `oxidized-manager.service` systemd unit.

That last step means **re-running the installer is also how you update the admin page** — it always pulls the latest code from git and replaces what's deployed, regardless of local edits. The Oxidized config file itself is left alone unless you choose "Nuke".

Open `http://<host>/` (or `http://<host>:5000` if you skipped the Nginx step) and log in with the admin credentials you set.

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
OXIDIZED_CONFIG_DIR   # default: /home/oxidized/.config/oxidized
APP_DB_PATH           # default: /home/oxidized/.oxidized_manager/app.db
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
sudo systemctl start|stop|restart|status oxidized-manager   # admin page
sudo systemctl start|stop|restart|status oxidized           # backup engine
sudo journalctl -u oxidized-manager -f
sudo journalctl -u oxidized -f
```

## Production notes

- Set a real `SECRET_KEY`: `export SECRET_KEY="$(openssl rand -hex 32)"`
- Put it behind HTTPS (nginx reverse proxy or a Cloudflare Tunnel)
- Use a strong admin password and restrict the firewall to known IPs
- Rotate LibreNMS/GitHub tokens periodically — never commit them to git

### Securing the Oxidized Web GUI

By default the installer binds Oxidized's own web GUI/API (port 8888) to `127.0.0.1` — it's never reachable from outside the host, since the admin page always talks to it over localhost. Port 80 is reserved for the admin page itself (via Nginx).

If you need Oxidized's web GUI reachable from elsewhere, the installer can put it behind Nginx on port 8888 (bound to the server's own IP, not `0.0.0.0`, so it doesn't collide with Oxidized's own loopback bind on the same port number), with basic auth required by default. LibreNMS's built-in Oxidized widget talks to the REST API directly and doesn't support basic auth, so if you say it needs access, the installer additionally allowlists just its IP to skip the password (`satisfy any` + `allow <ip>; deny all;`) — everyone else still needs one.

To set this up by hand instead of re-running the installer:

```bash
sudo apt install nginx apache2-utils -y
sudo htpasswd -c /etc/nginx/.htpasswd oxidized   # -c only on the first user

sudo tee /etc/nginx/sites-available/oxidized-web > /dev/null << 'EOF'
server {
    listen <server-ip>:8888;
    server_name _;

    location / {
        # Omit these three lines if LibreNMS doesn't need unauthenticated access
        satisfy any;
        allow <librenms-ip>;
        deny all;

        auth_basic "Oxidized Access";
        auth_basic_user_file /etc/nginx/.htpasswd;

        proxy_pass http://127.0.0.1:8888;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF
sudo ln -sf /etc/nginx/sites-available/oxidized-web /etc/nginx/sites-enabled/oxidized-web
sudo nginx -t && sudo systemctl restart nginx
sudo ufw allow 8888/tcp   # if UFW is active
```

## Troubleshooting

**Service won't start**
```bash
sudo journalctl -u oxidized-manager -n 100
sudo lsof -i :5000              # port already in use?
```

**Can't reach the Oxidized API**
```bash
sudo systemctl status oxidized
sudo journalctl -u oxidized -n 50
curl http://localhost:8888/nodes.json
```

**LibreNMS sync failing**
```bash
curl -H "X-Auth-Token: YOUR_TOKEN" http://<librenms-host>/api/v0/devices
```

**SSH test button disabled** → `pip install paramiko`

**GitHub integration disabled** → `pip install GitPython`

**Database issues**
```bash
sudo sqlite3 /home/oxidized/.oxidized_manager/app.db "SELECT COUNT(*) FROM device_metadata;"
sudo rm /home/oxidized/.oxidized_manager/app.db   # resets all app data — last resort
```

## Uninstall

```bash
sudo systemctl stop oxidized-manager oxidized
sudo systemctl disable oxidized-manager oxidized
sudo rm /etc/systemd/system/oxidized-manager.service /etc/systemd/system/oxidized.service
sudo rm /etc/sudoers.d/oxidized
sudo systemctl daemon-reload

# If you set up the Nginx proxy:
sudo rm -f /etc/nginx/sites-enabled/oxidized /etc/nginx/sites-available/oxidized /etc/nginx/.htpasswd
sudo systemctl restart nginx

# Also deletes all device backups/config and the oxidized user's data:
sudo deluser --remove-home oxidized
```

## License

MIT
