# CLI Scripts & Tools

Command-line tools for automation and maintenance.

## Directory Structure

```
/opt/nanohub/
├── tools/
│   ├── api/commands/      # MDM command scripts
│   ├── inventory_update.py
│   └── queue_cleanup.py   # MDM queue maintenance
├── ddm/scripts/           # DDM management
└── backend_api/
    ├── manage_roles.py    # User role management
    ├── nanohub_admin_core.py  # Admin panel routes (main)
    └── nanohub_admin/     # Modular admin package
        ├── __init__.py    # Package init, register_routes()
        ├── core.py        # Shared functions (device data, audit, VPP)
        ├── commands.py    # Command execution (execute_*)
        ├── profiles.py    # Profile management routes
        ├── utils.py       # Decorators (login_required, admin_required)
        └── routes/        # Route blueprints
            ├── settings.py
            ├── reports.py
            ├── vpp.py
            ├── devices.py # Device list & detail
            ├── ddm.py
            └── help.py
```

## Backend API Architecture

The admin panel is organized into modular components:

| Module | Lines | Description |
|--------|-------|-------------|
| `nanohub_admin_core.py` | ~380 | Main routes (/, /command, /execute, /history) |
| `nanohub_admin/core.py` | ~1290 | Shared functions (device data, audit, VPP, webhooks) |
| `nanohub_admin/commands.py` | ~3040 | All execute_* command handlers |
| `nanohub_admin/profiles.py` | ~650 | Profile management page and API |
| `nanohub_admin/routes/devices.py` | ~1700 | Device list and detail pages |

### Key Functions by Module

**core.py:**
- `get_device_info_for_uuid()`, `get_device_detail()`, `get_devices_full()`
- `execute_device_query()`, `validate_device_access()`
- `audit_log()`, `get_vpp_token()`, `fetch_vpp_assets()`

**commands.py:**
- `execute_command()` - main command dispatcher
- `execute_bulk_command()` - parallel execution
- `execute_device_add/update/delete()` - device CRUD
- `execute_manage_*()` - profiles, DDM, VPP, etc.

**profiles.py:**
- `/profiles` page with required profiles management
- `/api/profiles`, `/api/required-profiles` APIs

## MDM Command Scripts

Location: `/opt/nanohub/tools/api/commands/`

### Device Information

```bash
# Get device info
./device_info <UDID>

# Security info
./security_info <UDID>

# Profile list
./profile_list <UDID>

# Installed apps
./installed_apps <UDID>
```

### Device Control

```bash
# Lock device
./lock_device <UDID>

# Restart device
./restart_device <UDID>

# Erase device (caution!)
./erase_device <UDID>
```

### Profiles

```bash
# Install profile
./install_profile <UDID> <profile_path>

# Remove profile
./remove_profile <UDID> <profile_identifier>
```

### VPP/Apps

```bash
# Install VPP app
./install_app <UDID> <adam_id>

# Update apps from database
./update_vpp_from_db
```

### Bulk Operations

```bash
# System report (all devices)
./system_report

# Full system report
./system_report_full
```

## Inventory Update

```bash
/opt/nanohub/tools/inventory_update.py
```

Updates all devices with:
- DeviceInformation
- SecurityInfo
- ProfileList
- InstalledApplicationList

### Usage

```bash
cd /opt/nanohub/tools
source /opt/nanohub/venv/bin/activate
python inventory_update.py
```

### Cron Schedule

Runs twice daily (11:00 and 22:00, Mon-Fri):

```cron
0 11,22 * * 1-5 /opt/nanohub/venv/bin/python /opt/nanohub/tools/inventory_update.py >> /var/log/nanohub/inventory_update.log 2>&1
```

**Schedule rationale:**
- **11:00** - Morning update (fresh data for afternoon)
- **22:00** - Evening update (fresh data for next morning)
- **Mon-Fri only** - No updates on weekends (devices mostly offline)

**Note:** Reduced from every 2 hours to 2× daily to minimize load during work hours.

## Queue Cleanup

```bash
/opt/nanohub/tools/queue_cleanup.py
```

Cleans up processed commands from NanoMDM `enrollment_queue` table to prevent queue buildup.

### Cleanup Rules

| Status | Retention | Reason |
|--------|-----------|--------|
| Acknowledged | 1 hour | Command completed successfully |
| Error | 1 hour | Command failed |
| CommandFormatError | 1 hour | Invalid command format |
| NotNow | 5 days | Device busy, may retry |
| No response | 14 days | Device offline too long |

### Usage

```bash
cd /opt/nanohub/tools
source /opt/nanohub/venv/bin/activate

# Dry run (show what would be deleted)
python queue_cleanup.py --dry-run

# Actual cleanup
python queue_cleanup.py
```

### Cron Schedule

Runs daily at 03:00:

```cron
0 3 * * * /opt/nanohub/venv/bin/python /opt/nanohub/tools/queue_cleanup.py >> /var/log/nanohub/queue_cleanup.log 2>&1
```

**Note:** NanoMDM does not automatically clean the queue. Without this script, the `enrollment_queue` table grows indefinitely with processed commands.

## DDM Scripts

Location: `/opt/nanohub/ddm/scripts/`

```bash
# Upload all declarations
./ddm-upload-declarations.sh

# Create sets
./ddm-create-sets.sh

# Assign device to set
./ddm-assign-device.sh <UDID> <set-name>

# Force sync
./ddm-force-sync.sh <UDID>

# Status check
./ddm-status.sh all|declarations|sets|device <UDID>

# Bulk assign
./ddm-bulk-assign.sh <set-name> <UDID1> <UDID2> ...
```

## User Role Management

```bash
cd /opt/nanohub/backend_api
source /opt/nanohub/venv/bin/activate

# List roles
python manage_roles.py list

# Add role
python manage_roles.py add <username> <role>

# Add with manifest filter
python manage_roles.py add <username> restricted-admin --manifest "site-%"

# Remove role
python manage_roles.py remove <username>

# Deactivate user
python manage_roles.py deactivate <username>
```

## Environment Setup

Most scripts require environment variables:

```bash
source /opt/nanohub/environment.sh
```

Or activate venv:

```bash
source /opt/nanohub/venv/bin/activate
```

## Webhook Handler

```bash
# Start webhook server (development)
cd /home/microm/nanohub/webhook
source venv/bin/activate
python webhook.py

# Production: systemd service
systemctl status nanohub-webhook
systemctl restart nanohub-webhook
```

## Logs

```bash
# Webhook log
tail -f /var/log/nanohub/webhook.log

# Admin audit log
tail -f /var/log/nanohub/admin_audit.log

# Service logs
journalctl -u nanohub-web -f
journalctl -u nanohub-webhook -f
journalctl -u mdm-flask-api -f
```

## Systemd Services

| Service | Description | Port |
|---------|-------------|------|
| nanohub | NanoMDM server (Docker) | 9004 |
| nanohub-web | Flask web frontend | 9007 |
| nanohub-webhook | Webhook handler | 5001 |
| mdm-flask-api | Legacy API | 9006 |

```bash
# Status
systemctl status nanohub nanohub-web nanohub-webhook

# Restart all
systemctl restart nanohub nanohub-web nanohub-webhook

# Logs
journalctl -u <service> -f
```
