# Device Inventory

Manage and view all enrolled MDM devices.

## Device List

**Admin Panel > Devices** or `/admin/devices`

### Columns

| Column | Description |
|--------|-------------|
| Select | Checkbox for bulk operations |
| Status | Online/Active/Offline indicator |
| Hostname | Device name (click for detail) |
| Serial | Hardware serial number |
| OS | macOS or iOS |
| Manifest | Device group assignment |
| Last Seen | Last MDM check-in time |

### Status Indicators

| Status | Color | Meaning |
|--------|-------|---------|
| Online | Green | Seen within 15 minutes |
| Active | Yellow | Seen within 60 minutes |
| Offline | Gray | Not seen for 60+ minutes |

### Filters

- **OS** - macOS, iOS, or All
- **Manifest** - Device group filter
- **Search** - Hostname, serial, or UUID

## Device Detail

Click device hostname to open detail page: `/admin/device/<uuid>`

### Tabs

| Tab | Content |
|-----|---------|
| Info | Basic device information |
| Hardware | Model, storage, battery |
| Security | FileVault, Firewall, SIP status |
| Profiles | Installed configuration profiles |
| Apps | Installed applications |
| History | Command history for this device |

### Quick Actions

- **Lock** - Lock device immediately
- **Restart** - Restart device
- **Erase** - Factory reset (confirmation required)

## Device Manager

Add, update, or remove devices from inventory.

### Add Device

Required fields:
- UUID (from MDM enrollment)
- Serial number
- OS type (macOS/iOS)
- Hostname

Optional:
- Manifest assignment
- Account status
- DEP enrollment flag

### Update Device

Modify device properties:
- Hostname
- Manifest assignment
- Account status

### Delete Device

Remove device from inventory database.

**Note:** This does not unenroll the device from MDM.

## Database

Devices are stored in `device_inventory`:

```sql
SELECT
    uuid,
    serial,
    hostname,
    os,
    manifest,
    updated_at
FROM device_inventory
ORDER BY hostname;
```

### Cached Data

Device details cached in `device_details`:

```sql
SELECT
    d.hostname,
    dd.hardware_updated_at,
    dd.security_updated_at,
    dd.apps_updated_at
FROM device_inventory d
LEFT JOIN device_details dd ON d.uuid = dd.uuid;
```

## Inventory Updates

### Manual Update

**Admin Panel > Commands > Device Control > Update Inventory**

Filters:
- OS (macOS/iOS)
- Manifest
- Last Updated (24h, 7 days, never)

### Automatic Update

Daily cron at 14:00:

```bash
/opt/nanohub/tools/inventory_update.py
```

Updates all devices with:
- Hardware info (DeviceInformation)
- Security info (SecurityInfo)
- Profiles (ProfileList)
- Apps (InstalledApplicationList)

## Bulk Operations

1. Select devices using checkboxes
2. Or use "Select All" / "Select Filtered"
3. Execute command from dropdown
4. View progress and results

### Multi-Page Selection

Device selection persists across pagination. Selected device count shown in header.
