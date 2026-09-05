# Quick Start - SSH Testing, Groups & GitHub

## 1. SSH Connection Testing (2 min)

### Test a Device
```
Devices → Click "Test SSH" button on any device
```

Result shows:
- ✓ Success: Connected, credentials work
- ✗ Fail: Shows exact error (auth, timeout, etc.)

**That's it!** No setup needed.

---

## 2. Device Groups (5 min)

### Create Groups for Your ISP

```
Dashboard → Devices → "Manage Groups"
```

**Add Group:**
```
Name:     jdm-hernani
Desc:     JDM Fiber - Hernani site
Username: admin (optional)
Password: (optional)
```

Repeat for:
- `kgcis-mandaue` (Mandaue site)
- `jsvartech-camiguin` (Camiguin site)

### Add Device to Group

```
Devices → "+ Add Device"
Group: [select jdm-hernani]
Save
```

Done! Devices now organized by site.

---

## 3. GitHub Backup (5 min - if desired)

### Setup

#### Get Token (GitHub)
1. github.com → Settings → Developer settings → Personal tokens
2. "Generate new token (Classic)"
3. Tick `repo` checkbox
4. Copy token

#### Configure (Oxidized Manager)
```
Settings → GitHub Integration
URL:    https://github.com/yourname/oxidized-backups.git
Token:  [paste token here]
Branch: main
☑ Enable
Save
```

**Done!** Backups auto-push to GitHub.

### View Backups
```bash
git clone https://github.com/yourname/oxidized-backups.git
cd oxidized-backups
ls jdm-hernani/
# See all backups for that device
```

---

## SSH Testing - Troubleshooting

### "Paramiko not installed"
```bash
pip install paramiko
```

### Connection fails
Check:
1. IP address correct?
2. SSH port open (default 22)?
3. Username/password correct?
4. Firewall allowing access?

---

## Groups - Best Practices

### Organize by Site
```
jdm-hernani           → Eastern Samar ISP
kgcis-mandaue         → Cebu City ISP
jsvartech-camiguin    → Camiguin Island ISP
```

### Organize by Device Type
```
routers       → Core routers
switches      → Edge switches
firewalls     → Security devices
```

### Organize by Customer
```
customer-acme         → ACME Corp network
customer-initech      → Initech Corp network
```

Choose what makes sense for your NOC.

---

## GitHub - Best Practices

### Security
- [ ] Make repo **Private**
- [ ] Use **Personal Access Token** (not password)
- [ ] Give token **`repo` scope minimum**
- [ ] Rotate token every 90 days
- [ ] Don't share token!

### Naming
Keep configs organized:
```
oxidized-backups/
├── jdm-r1/       # Device name = folder
│   ├── 20260905_142030.conf
│   └── 20260905_141530.conf
└── kgcis-r1/
```

### Maintenance
```bash
# Clean old backups (keep last 30 days)
cd oxidized-backups
git rm jdm-r1/202605*.conf
git commit -m "Clean old backups"
git push
```

---

## All 3 Features Together

### Typical Workflow

1. **Create groups** (once)
   ```
   Settings → Groups → Add jdm-hernani, kgcis-mandaue, jsvartech-camiguin
   ```

2. **Add devices** (once per device)
   ```
   Devices → + Add Device
   Fill IP, user, pass, select group
   Click "Test SSH" → ✓ Confirmed
   Save Device
   ```

3. **Backups happen automatically**
   ```
   Oxidized backs up every hour
   GitHub auto-synced (if enabled)
   Dashboard shows status
   ```

4. **Monitor & troubleshoot**
   ```
   Test SSH anytime to verify connectivity
   View backups in GitHub
   Audit logs show changes
   ```

---

## Feature Quick Reference

| Feature | Access | Requires | Setup Time |
|---------|--------|----------|-----------|
| SSH Test | Devices page | paramiko | 1 min install |
| Groups | Devices → Manage Groups | none | 5 min |
| GitHub | Settings | GitPython | 5 min config |

---

## Minimal Setup (No Extras)

Want just basics?

1. Install normally
2. Add devices manually (IP, user, pass, group)
3. Done! Backups work.

LibreNMS, GitHub, SSH testing all optional.

---

## Full ISP Setup Example

### Your Network
```
Site 1: 10.25.1.1   (JDM Hernani)
Site 2: 10.36.0.1   (KGCIS Mandaue)
Site 3: 192.168.1.1 (JSVARTECH Camiguin)
```

### Setup Steps

1. **Create groups**
   ```
   Group: jdm-hernani
   Group: kgcis-mandaue
   Group: jsvartech-camiguin
   ```

2. **Add devices**
   ```
   10.25.1.1     → jdm-hernani      → Test SSH ✓
   10.36.0.1     → kgcis-mandaue    → Test SSH ✓
   192.168.1.1   → jsvartech-camiguin → Test SSH ✓
   ```

3. **Enable GitHub** (optional)
   ```
   Settings → GitHub Integration
   Repo URL + Token
   Enable
   ```

4. **Done!**
   ```
   Dashboard shows 3 devices
   Backups run hourly
   GitHub updated automatically
   ```

---

## Common Questions

**Q: Do I need GitHub?**  
A: No. Standalone backups work perfectly. GitHub is optional.

**Q: Do I need LibreNMS?**  
A: No. Standalone device management works. LibreNMS is optional.

**Q: Do I need SSH testing?**  
A: No. But it's useful for troubleshooting.

**Q: Can I add LibreNMS/GitHub later?**  
A: Yes. Settings → enable whenever you want.

**Q: How often do backups run?**  
A: Every hour. Configurable in Oxidized config.

**Q: Can I restore from GitHub?**  
A: Yes. GitHub stores full history.  
   ```bash
   git show jdm-r1/device.conf
   ```

**Q: Are credentials secure?**  
A: Passwords hashed in database. GitHub token in encrypted setting.

---

**Version 1.1** - All features ready to use!

