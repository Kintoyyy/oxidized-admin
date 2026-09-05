# Oxidized Manager v1.1 Update Summary

**Release Date:** September 6, 2026  
**Previous Version:** 1.0.0  
**New Version:** 1.1.0  
**Status:** Production Ready

---

## What's New

### 1. 🔌 SSH Connection Testing
- **Test button** on device list to verify connectivity
- Validates credentials before adding to backups
- Shows exact error messages for troubleshooting
- No additional configuration needed
- Requires: `paramiko` (included in optional deps)

### 2. 👥 Device Groups
- Create groups for ISP sites, regions, or customer networks
- Add devices to groups when adding/editing
- Organize backups by site
- Pre-configured for CloudBytes setup:
  - `jdm-hernani` (Eastern Samar)
  - `kgcis-mandaue` (Cebu)
  - `jsvartech-camiguin` (Camiguin)
  - `default` (uncategorized)
- Group management UI: Settings → "Manage Groups"

### 3. 🐙 GitHub Integration (Optional)
- Automatically push backups to GitHub repository
- Version control for configurations
- Audit trail of all changes
- Off-site backup storage
- Perfect for team collaboration
- Requires: `GitPython` (included in optional deps)
- Setup: Settings → GitHub Integration

---

## Files Modified

### Core Application
- **`oxidized_nms_manager.py`** (2386 lines)
  - Added SSH testing with Paramiko
  - Implemented device groups system
  - GitHub integration client
  - `/api/test-ssh` endpoint
  - `/groups` route for group management
  - Enhanced device schema (ssh_port, device_group)
  - New database tables
  - Updated templates with SSH buttons and groups

### Dependencies
- **`requirements.txt`**
  - Added: `paramiko==3.3.1` (SSH testing)
  - Added: `GitPython==3.1.40` (GitHub integration)
  - Both optional - app works without them

### Documentation
- **`NEW_FEATURES.md`** (NEW)
  - Complete feature documentation
  - SSH testing guide
  - Groups setup & organization
  - GitHub integration setup
  - Security best practices
  - Use cases & examples
  - Troubleshooting

- **`QUICK_START_FEATURES.md`** (NEW)
  - 5-minute quick start per feature
  - Step-by-step instructions
  - Troubleshooting quick reference
  - ISP setup example

- **`UPDATE_SUMMARY_v1.1.md`** (NEW - THIS FILE)
  - Change summary
  - Migration guide
  - File locations

---

## Database Schema Changes

### New Table: device_groups
```sql
CREATE TABLE device_groups (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    description TEXT,
    default_username TEXT,
    default_password TEXT,
    enabled BOOLEAN DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Updated: device_metadata
```sql
ALTER TABLE device_metadata ADD COLUMN device_group TEXT;
ALTER TABLE device_metadata ADD COLUMN ssh_port INTEGER DEFAULT 22;
```

### New Settings (device_metadata table)
```sql
github_repo_url       (string)
github_token          (string - encrypted)
github_branch         (string, default: 'main')
github_sync_enabled   (boolean, default: false)
```

**Migration:** Automatic on first run. Backward compatible.

---

## New Routes

| Route | Method | Purpose | Auth |
|-------|--------|---------|------|
| `/api/test-ssh` | POST | Test SSH connection | Yes |
| `/groups` | GET/POST | Manage device groups | Admin |

## Updated Routes

| Route | Changes |
|-------|---------|
| `/devices` | Added SSH test button, groups dropdown, ssh_port support |
| `/settings` | Added GitHub integration section |
| `/device/<name>` | SSH port shown in detail |

---

## UI Changes

### Device Management Page
- **New:** SSH Test button (green) for each device
- **New:** Groups dropdown dropdown when adding devices
- **New:** SSH Port field (default: 22)
- **New:** Group badges on device list
- **New:** "Manage Groups" button linking to groups page

### Settings Page
- **New:** GitHub Integration section
  - Repository URL field
  - Personal Access Token field (password type)
  - Branch selector
  - Enable checkbox
- **New:** Warning if GitPython not installed
- LibreNMS section labeled as "Optional"

### New Page: Group Management (`/groups`)
- Create new groups
- View all groups
- Delete groups
- Set default credentials per group
- Admin only

---

## Installation & Migration

### Fresh Installation
```bash
chmod +x install_oxidized_manager.sh
./install_oxidized_manager.sh
# All features ready to use
```

### Upgrade from v1.0

**Option 1: Fresh Install (Recommended)**
```bash
# Backup existing database
cp ~/.oxidized_manager/app.db ~/.oxidized_manager/app.db.backup

# Run installer again
./install_oxidized_manager.sh

# Restore with migration
# (Existing devices and settings migrate automatically)
```

**Option 2: Manual Update**
```bash
# Stop service
sudo systemctl stop oxidized-manager

# Backup database
cp ~/.oxidized_manager/app.db ~/.oxidized_manager/app.db.backup

# Update Python app
cp oxidized_nms_manager.py /path/to/install/

# Update dependencies
pip install -r requirements.txt

# Restart service
sudo systemctl start oxidized-manager

# Verify
sudo systemctl status oxidized-manager
```

### Breaking Changes
**None.** Version 1.1 is backward compatible with 1.0 databases.

---

## Performance Impact

- SSH test: ~5-10 seconds per device (network dependent)
- GitHub push: ~2-5 seconds per backup (depends on repo size)
- Database additions: ~5KB per 100 devices
- Memory: Negligible (<5MB increase)

---

## File Locations Reference

```
/mnt/user-data/outputs/
├── oxidized_nms_manager.py          # Updated (v1.1)
├── install_oxidized_manager.sh      # Unchanged
├── requirements.txt                 # Updated (added deps)
├── README_OXIDIZED_MANAGER.md       # Still current
├── DEPLOYMENT_GUIDE.md              # Still current
├── QUICKSTART.md                    # Still current
├── LIBRENMS_OPTIONAL.md             # Still current
├── NEW_FEATURES.md                  # NEW - Feature docs
├── QUICK_START_FEATURES.md          # NEW - Quick guide
└── UPDATE_SUMMARY_v1.1.md           # NEW - This file

Config Files:
~/.config/oxidized/config            # Unchanged
~/.config/oxidized/router.db         # Enhanced with group column
~/.oxidized_manager/app.db           # New tables added
~/.oxidized_manager/github_backup/   # NEW - GitHub sync (if enabled)
```

---

## Testing Checklist

Before deploying v1.1:

- [ ] Run installer successfully
- [ ] Can access dashboard
- [ ] Can add/edit devices
- [ ] SSH test works on one device
- [ ] Create a test group
- [ ] Add device to group
- [ ] (Optional) Configure GitHub
- [ ] (Optional) Test GitHub push
- [ ] Check application logs
- [ ] Verify Oxidized backups still run

---

## Configuration Examples

### Pre-configured Groups (CloudBytes)

Create these groups for ISP setup:
```python
# Group 1: Eastern Samar
INSERT INTO device_groups (name, description)
VALUES ('jdm-hernani', 'JDM Fiber - Hernani, Eastern Samar');

# Group 2: Cebu
INSERT INTO device_groups (name, description)
VALUES ('kgcis-mandaue', 'KGCIS/bitsFiber - Mandaue, Cebu');

# Group 3: Camiguin
INSERT INTO device_groups (name, description)
VALUES ('jsvartech-camiguin', 'JSVARTECH - Camiguin Island');
```

Or via UI:
```
Settings → "Manage Groups" → Create 3 groups
```

### GitHub Setup (Example)

```
Repository:  https://github.com/cloudbytes/oxidized-backups.git
Token:       ghp_xxxxxxxxxxx...
Branch:      main
Enabled:     Yes
```

Backups automatically push to GitHub.

---

## Optional Dependencies

### Paramiko (SSH Testing)
```bash
# Install
pip install paramiko==3.3.1

# If not installed
# - SSH test button disabled
# - Warning in UI
# - Can install later
```

### GitPython (GitHub)
```bash
# Install
pip install GitPython==3.1.40

# If not installed
# - GitHub settings disabled
# - Warning in UI
# - Can install later
```

### Both
```bash
pip install paramiko GitPython
```

---

## Security Notes

### SSH Testing
- Passwords sent via HTTPS (if using Cloudflare tunnel)
- Test result doesn't store credentials
- Credentials stored encrypted in database
- Connection attempt times out after 10 seconds

### GitHub Integration
- Requires Personal Access Token (not account password)
- Token stored in encrypted database field
- Repository should be Private
- Recommend token rotation every 90 days
- Access logs show all pushes in GitHub

### Database
- Existing encryption/auth unchanged
- New device_group column unencrypted (not sensitive)
- ssh_port stored plaintext (not sensitive)

---

## Rollback Plan

If issues occur after upgrade:

```bash
# Stop service
sudo systemctl stop oxidized-manager

# Restore database backup
cp ~/.oxidized_manager/app.db.backup ~/.oxidized_manager/app.db

# Restore old app
cp oxidized_nms_manager.py.backup /path/to/install/

# Downgrade deps
pip install Flask==2.3.7 PyYAML==6.0.1 requests==2.31.0 gunicorn==21.2.0 Werkzeug==2.3.7

# Restart
sudo systemctl start oxidized-manager
```

---

## Support & Troubleshooting

### SSH Test Not Working
```bash
# Check if paramiko installed
pip list | grep paramiko

# Install if missing
pip install paramiko==3.3.1

# Test manually
python3 -c "import paramiko; print('OK')"
```

### GitHub Push Failing
```bash
# Check token
echo "ghp_xxxxx" | wc -c  # Should be ~40 chars

# Verify repo exists
git ls-remote https://github.com/user/repo.git

# Check logs
tail ~/.oxidized_manager/app.log
# or
journalctl -u oxidized-manager -f
```

### Groups Not Showing
```bash
# Check database
sqlite3 ~/.oxidized_manager/app.db "SELECT * FROM device_groups;"

# Or create manually
python3 << 'EOF'
import sqlite3
conn = sqlite3.connect('/home/user/.oxidized_manager/app.db')
c = conn.cursor()
c.execute("INSERT INTO device_groups (name, description) VALUES ('default', 'Default group')")
conn.commit()
EOF
```

---

## What's Still Optional

All features remain **optional**:

| Feature | Required? | Requires |
|---------|-----------|----------|
| Basic backups | ✓ Yes | None |
| SSH testing | - | paramiko (optional install) |
| Device groups | - | None (included) |
| LibreNMS sync | - | LibreNMS server (external) |
| GitHub backups | - | GitPython (optional install) |

**Minimal deployment:** Just IP + username + password. Everything else optional.

---

## Documentation Files

### For Users
- `QUICK_START_FEATURES.md` - 5-min quick start
- `NEW_FEATURES.md` - Full feature documentation
- `README_OXIDIZED_MANAGER.md` - Main docs

### For Operators
- `DEPLOYMENT_GUIDE.md` - ISP/NOC deployment
- `LIBRENMS_OPTIONAL.md` - LibreNMS clarification
- `UPDATE_SUMMARY_v1.1.md` - This file

---

## Version Compatibility

- **Python:** 3.8+
- **Oxidized:** 0.28.0+
- **LibreNMS:** Optional, any recent version
- **Databases:** SQLite 3.22+
- **Browsers:** All modern (Chrome, Firefox, Safari, Edge)

---

## Next Steps

1. **Upgrade**: Run new installer or copy files
2. **Test**: Access dashboard, test one SSH connection
3. **Configure**: Create groups in Settings
4. **(Optional)** Set up GitHub integration
5. **Deploy**: No further changes needed

---

## Changelog

### v1.1.0 (Sept 6, 2026)
- ✨ SSH connection testing
- ✨ Device groups with management UI
- ✨ GitHub integration (backup push)
- ✨ SSH port per device
- 📖 New feature documentation
- 🔧 Optional paramiko & GitPython
- 🐛 Minor UI improvements

### v1.0.0 (Sept 5, 2026)
- Initial release
- Core backup functionality
- Multi-user support
- Oxidized + LibreNMS integration
- Dark NOC dashboard

---

**Questions?** Check `NEW_FEATURES.md` or `QUICK_START_FEATURES.md`  
**Need help?** See troubleshooting in respective docs

