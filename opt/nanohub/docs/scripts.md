# CLI Scripts & Tools

Command-line tools for automation and maintenance.

## Directory Structure

```
/opt/nanohub/
├── tools/
│   ├── api/commands/      # MDM command scripts
│   └── inventory_update.py
├── ddm/scripts/           # DDM management
└── backend_api/
    └── manage_roles.py    # User role management
```

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

Daily at 14:00:

```cron
0 14 * * * /opt/nanohub/venv/bin/python /opt/nanohub/tools/inventory_update.py
```

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
