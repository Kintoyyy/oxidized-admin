# Oxidized Manager v1.1 - New Features

## 1. SSH Connection Testing 🔌

### Overview
Test SSH connectivity to devices directly from the UI before adding them to Oxidized backups.

### How It Works

1. **Open Device Management**
   - Dashboard → "Devices" in the navbar
   - Or directly: http://localhost:5000/devices

2. **Test SSH Connection**
   - Scroll to any device in the list
   - Click the green **"Test SSH"** button
   - System tests connection with credentials
   - Result appears below the device row

3. **What Gets Tested**
   - ✓ Network connectivity to host:port
   - ✓ SSH authentication (username/password)
   - ✓ Command execution (basic `show version`)
   - ✓ Connection timeout handling

### Result Indicators

**✓ Success (Green)**
```
✓ Connected successfully to 10.25.1.1:22
```

**✗ Error (Red)**
```
✗ Authentication failed - check username/password
✗ Connection failed: Connection refused
✗ SSH error: Unable to negotiate
```

### Requirements

SSH testing requires **Paramiko** (included in optional deps):
```bash
pip install paramiko==3.3.1
```

### Use Cases

- Verify credentials before adding device
- Troubleshoot connection issues
- Test after changing firewall rules
- Validate SSH port configuration
- Batch test multiple devices

---

## 2. Device Groups 👥

### Overview
Organize devices into logical groups (ISP sites, regions, customer networks, etc.).

### Group Management

**Access Groups Page:**
- Dashboard → "Manage Groups" button (Device Management page)
- Or directly: http://localhost:5000/groups
- Admin only

### Create a Group

```
Group Name:           jdm-hernani
Description:          JDM Fiber - Hernani, Eastern Samar
Default Username:     admin
Default Password:     [leave blank for per-device]
```

### Pre-configured Groups (Examples)

Your ISP setup could use:
```
jdm-hernani        → JDM Fiber (Hernani, Eastern Samar)
kgcis-mandaue      → KGCIS/bitsFiber (Mandaue, Cebu)
jsvartech-camiguin → JSVARTECH (Camiguin)
default            → Uncategorized devices
```

### Adding Devices to Groups

When adding a device:
1. Click **"+ Add Device"**
2. Fill in IP, username, password, etc.
3. Select **Group** dropdown
4. Choose: `jdm-hernani`, `kgcis-mandaue`, etc.
5. Click **Save Device**

### Features

- **Group-level defaults**: Set default SSH credentials per group
- **Organization**: Filter/find devices by site
- **Multi-site management**: Separate backups by ISP/location
- **Access control**: (v1.2+) Restrict user access per group

### Database Schema

```sql
CREATE TABLE device_groups (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    description TEXT,
    default_username TEXT,
    default_password TEXT,
    enabled BOOLEAN DEFAULT 1,
    created_at TIMESTAMP
);
```

### API Integration

Devices in `router.db` now include:
```csv
name:ip:model:username:password:group:enable:ssh_port
R1-JDM:10.25.1.1:RouterOS:admin:pass123:jdm-hernani:yes:22
R1-KGCIS:10.36.0.1:RouterOS:admin:pass456:kgcis-mandaue:yes:22
```

---

## 3. GitHub Integration (Optional) 🐙

### Overview
Automatically push configuration backups to a GitHub repository for:
- Version control
- Audit trail
- Off-site storage
- Easy rollback
- Team collaboration

### Setup

#### Step 1: Create GitHub Repo
```bash
# Create new repo on GitHub
# Example: https://github.com/yourorg/oxidized-backups
# Set to Private for security
```

#### Step 2: Generate GitHub Token
1. GitHub → Settings → Developer settings → Personal access tokens
2. Generate new token (Classic)
3. Scopes needed:
   - `repo` (full control)
   - `read:user`
4. Copy token (save securely!)

#### Step 3: Configure in Oxidized Manager
1. Navigate to **Settings** (admin only)
2. Scroll to **GitHub Integration** section
3. Fill in:
   ```
   GitHub Repository URL:  https://github.com/yourorg/oxidized-backups.git
   GitHub Personal Token:  ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   GitHub Branch:          main
   Enable Push:            ☑ Push backups to GitHub
   ```
4. Click **Save Settings**

### What Gets Backed Up

Each device's configs are stored in GitHub as:
```
oxidized-backups/
├── jdm-r1/
│   ├── 20260905_142030.conf
│   ├── 20260905_140000.conf
│   └── 20260905_133015.conf
├── kgcis-r1/
│   ├── 20260905_143000.conf
│   └── 20260905_130000.conf
└── jsvartech-router/
    └── 20260905_144500.conf
```

### Automatic Pushes

When **GitHub Integration** is enabled:
- Each new backup is pushed to GitHub
- Commit message: `Backup {device_name} at {timestamp}`
- Branch: `main` (configurable)
- Automatic timestamp tagging

### Commit Example

```
Commit: 1a2b3c4d5e6f
Author: oxidized-manager
Message: Backup jdm-r1 at 2026-09-05 14:30:45
Files changed: 1
Insertions: +125 lines of config
```

### Requirements

GitHub integration requires **GitPython** (optional dependency):
```bash
pip install GitPython==3.1.40
```

If not installed:
- GitHub section shows warning in Settings
- Feature can be installed later with `pip install GitPython`

### Security Considerations

⚠️ **Token Security**
- Use **Personal Access Token**, not account password
- Use **read:repo** scope minimum (not admin)
- Store token securely (not in code/configs)
- Rotate token regularly (every 90 days recommended)
- Consider using Secrets Manager for production

⚠️ **Repository Security**
- Make GitHub repo **Private**
- Don't expose configs publicly
- Review access permissions
- Enable 2FA on GitHub account

### Use Cases

**Version Control**
```bash
git log --oneline oxidized-backups/
# See history of all config changes
```

**Config Comparison**
```bash
git diff HEAD~1 jdm-r1/latest.conf
# Compare configs between backups
```

**Rollback** (manual)
```bash
git show HEAD~5:jdm-r1/config.conf
# Restore old configuration
```

**Audit Trail**
```bash
git log -p jdm-r1/
# Full audit of who changed what and when
```

**Team Collaboration**
- Share backup repo with team
- Everyone can view configs
- Audit trail of changes
- No additional tools needed

### API Integration

Disabled by default. Configure in Settings → GitHub Integration:
```python
set_setting('github_repo_url', 'https://github.com/user/repo.git')
set_setting('github_token', 'ghp_xxx')
set_setting('github_sync_enabled', True, 'bool')
```

### Troubleshooting

**Error: Repository not found**
- Check URL is correct
- Verify token has `repo` access
- Ensure repository is accessible

**Error: Authentication failed**
- Verify GitHub token is valid
- Check token hasn't expired
- Regenerate token if needed

**Commits not appearing**
- Check GitHub branch (default: `main`)
- Verify `github_sync_enabled` is True
- Check application logs for errors

### GitHub Actions Integration (Optional)

Once backups are in GitHub, you can use GitHub Actions:

```yaml
name: Config Change Notification
on:
  push:
    paths:
      - 'oxidized-backups/**/*.conf'
jobs:
  notify:
    runs-on: ubuntu-latest
    steps:
      - name: Notify on config change
        run: |
          echo "Device config updated!"
          # Send Slack/email notification
```

---

## Feature Matrix

| Feature | Standalone | With LibreNMS | With GitHub |
|---------|-----------|--------------|------------|
| Backup devices | ✓ | ✓ | ✓ |
| Manage groups | ✓ | ✓ | ✓ |
| Test SSH | ✓ | ✓ | ✓ |
| Auto-sync devices | - | ✓ | ✓ |
| Version control | - | - | ✓ |
| Audit trail | ✓ | ✓ | ✓ |
| Multi-user | ✓ | ✓ | ✓ |

---

## Installation Changes

### Updated requirements.txt

```
Flask==2.3.7
PyYAML==6.0.1
requests==2.31.0
gunicorn==21.2.0
Werkzeug==2.3.7
paramiko==3.3.1         # NEW - SSH testing
GitPython==3.1.40       # NEW - GitHub integration
```

### Installation (No Changes Required)

Same process:
```bash
./install_oxidized_manager.sh
# SSH testing and GitHub ready to use
# LibreNMS still optional
```

### Optional: Install After Setup

```bash
# Add SSH testing
pip install paramiko==3.3.1

# Add GitHub integration
pip install GitPython==3.1.40

# Both
pip install paramiko GitPython
```

---

## Database Updates

New tables added on init:

```sql
-- Device groups
CREATE TABLE device_groups (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    description TEXT,
    default_username TEXT,
    default_password TEXT,
    enabled BOOLEAN DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Updated device metadata
ALTER TABLE device_metadata ADD COLUMN device_group TEXT;
ALTER TABLE device_metadata ADD COLUMN ssh_port INTEGER DEFAULT 22;
```

Backward compatible: Existing databases upgraded automatically on first run.

---

## Configuration Guide

### Complete settings.json (All Features)

```python
# LibreNMS (optional)
set_setting('librenms_url', 'http://10.98.0.1')
set_setting('librenms_token', 'xxx')
set_setting('librenms_sync_enabled', True, 'bool')

# GitHub (optional)
set_setting('github_repo_url', 'https://github.com/cloudbytes/oxidized-backups.git')
set_setting('github_token', 'ghp_xxx')
set_setting('github_branch', 'main')
set_setting('github_sync_enabled', True, 'bool')

# App settings
set_setting('app_name', 'CloudBytes NOC')
set_setting('backup_retention_days', 30, 'int')
set_setting('oxidized_api_url', 'http://localhost:8080/api')
```

---

## Roadmap (v1.2+)

- [ ] Config diff viewer in UI
- [ ] Email notifications on backup failure
- [ ] Slack webhook integration
- [ ] LDAP/Active Directory auth
- [ ] Role-based group access
- [ ] Scheduled backup reports
- [ ] Mobile app support
- [ ] Backup compression
- [ ] S3 storage backend
- [ ] Config search/diff
- [ ] Backup frequency per device

---

## Support

For issues:
1. Check logs: `journalctl -u oxidized-manager -f`
2. Test SSH manually: `ssh -v user@10.x.x.x`
3. Verify GitHub token: GitHub → Settings → Personal tokens
4. Check application logs in `~/.oxidized_manager/`

---

**Version**: 1.1.0  
**Release**: September 2026  
**Status**: Production Ready

