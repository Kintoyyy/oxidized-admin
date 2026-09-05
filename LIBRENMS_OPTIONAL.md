# Oxidized + LibreNMS Manager - LibreNMS is OPTIONAL

## Important Clarification

**The application is a complete, standalone backup solution.**

LibreNMS integration is an **optional feature** for convenience only.

---

## What Works WITHOUT LibreNMS

✓ All core features:
- Device inventory management (add/edit/delete)
- Automatic config backups (every hour)
- Backup history and restore
- Config editing and YAML management
- Multi-user support with roles
- Audit logging
- REST API
- Role-based access control
- Systemd service
- Dark NOC dashboard

---

## What LibreNMS Adds (OPTIONAL)

**Only these features require LibreNMS:**
- Auto-sync devices from LibreNMS inventory
- Pull active alerts from LibreNMS
- Auto-map LibreNMS device IDs

**You can still:**
- Add devices manually (takes 30 seconds per device)
- Manage credentials
- See backups
- View device status
- All without LibreNMS

---

## Installation (No LibreNMS Needed)

```bash
./install_oxidized_manager.sh

# Just press Enter when asked about LibreNMS
# Or leave settings blank
# App works perfectly standalone
```

---

## Standalone Workflow

1. **Add devices manually** (one-time setup)
   - Click "Devices" → "+ Add Device"
   - Enter: name, IP, model, username, password
   - Click "Save Device"

2. **Backups happen automatically**
   - Every hour Oxidized pulls configs via SSH
   - Dashboard shows status in real-time
   - History tracked with timestamps

3. **Manage configs**
   - Click any device to view config
   - Edit YAML if needed
   - Restore from backup history
   - View who changed what (audit log)

---

## When to Add LibreNMS Later (Optional)

LibreNMS integration is useful if:
- You already have LibreNMS running
- You want automatic device discovery
- You have 50+ devices to manage
- You want to sync alerts

But **not required** for backup functionality.

---

## If You Don't Have LibreNMS

**You still get:**
- Professional NOC dashboard
- Complete backup management
- Multi-user access
- Config history
- Audit trails
- REST API

Just add devices manually once and you're done.

---

## Quick Comparison

| Feature | Without LibreNMS | With LibreNMS |
|---------|-----------------|--------------|
| Add devices | Manual | Auto-sync |
| View backups | ✓ | ✓ |
| Manage configs | ✓ | ✓ |
| Restore configs | ✓ | ✓ |
| Multi-user | ✓ | ✓ |
| Audit log | ✓ | ✓ |
| See device alerts | - | ✓ |
| Auto device discovery | - | ✓ |

---

## Installation Choices

### Option A: Standalone (No Dependencies)
```bash
./install_oxidized_manager.sh
# Skip all LibreNMS prompts
# Add devices manually
# Done!
```

### Option B: With LibreNMS (Later)
```bash
# First: Install and use standalone
./install_oxidized_manager.sh

# Later: Configure LibreNMS when ready
# Settings → LibreNMS URL + API Token
# Devices → Sync from LibreNMS
# Optional feature added
```

---

## What You Actually Get (Standalone)

1. **Oxidized Manager Flask App** (5000)
   - Professional dashboard
   - Device management UI
   - Config editor
   - Multi-user interface

2. **Oxidized Backup Engine** (8080)
   - Automatic device config backup
   - SSH/Telnet discovery
   - Git storage of backups
   - Backup history

3. **SQLite Database**
   - Users and access control
   - Device metadata
   - Backup history
   - Audit logs

4. **Systemd Service**
   - Auto-start on boot
   - Service management
   - Log collection

---

## File Size Without LibreNMS

The application is still:
- **50KB** of Python code (oxidized_nms_manager.py)
- **15KB** installer script
- **~2MB** when installed with venv

LibreNMS integration code: ~10% of application, easily ignored if unused.

---

## For Your ISP Setup

**Standalone** (CloudBytes Configuration):
```
Oxidized Manager (CT 106)
├── Device 1: 10.25.1.1 (JDM Hernani)
├── Device 2: 10.36.0.1 (KGCIS Mandaue)
├── Device 3: router (JSVARTECH Camiguin)
└── All backups in ~/.config/oxidized/repositories.default/

Access via:
- http://10.98.0.106:5000 (internal)
- https://nms-manager.cloudbytes.ph (via Cloudflare)
```

Works perfectly without LibreNMS.

---

## Common Questions

**Q: Do I need LibreNMS installed?**  
A: No. Standalone backups work without it.

**Q: Can I add LibreNMS later?**  
A: Yes. Settings tab lets you enable it anytime.

**Q: Can I use this if I'm not using LibreNMS?**  
A: Absolutely! That's the main use case.

**Q: How do I add devices without LibreNMS?**  
A: Click "Devices" → "+ Add Device" → Fill in details

**Q: What if LibreNMS breaks or goes down?**  
A: Oxidized Manager still works. It just can't sync devices.

**Q: Is LibreNMS sync automatic?**  
A: Only if you enable it. Default is off.

---

## Summary

**Oxidized Manager is a complete, standalone application.**

You get:
- ✓ Professional backup platform
- ✓ Multi-user NOC dashboard
- ✓ Automatic device backups
- ✓ Config management
- ✓ Audit logging
- ✓ REST API

LibreNMS is **optional convenience**, not required.

---

## Installation (Truly Simple)

```bash
chmod +x install_oxidized_manager.sh
./install_oxidized_manager.sh

# Answer prompts (or just press Enter)
# App ready at http://localhost:5000
# Add devices manually
# Start backing up
# Done!
```

No other systems needed.

---

**Version**: 1.0.0 (Standalone Ready)  
**LibreNMS Support**: Optional  
**Core Features**: Complete  
