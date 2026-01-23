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

| Filter | Options | Description |
|--------|---------|-------------|
| Search | Text input | Hostname, serial, or UUID |
| OS | All / macOS / iOS | Operating system type |
| Status | All / Online / Active / Offline | Device check-in status |
| Supervised | All / Yes / No | MDM supervision status |
| Encrypted | All / Yes / No | FileVault/encryption status |
| Outdated | All / Yes / No | OS version outdated |
| Manifest | Dropdown | Device group assignment |

All filters work client-side on loaded data for instant filtering.

### Pagination

- **50 rows per page** on device list
- Selection persists across pages for bulk operations
- Table scrolls within fixed viewport (page header/filters stay visible)

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
| DDM | Declarative Device Management status |
| History | Command history for this device |

### Tab Pagination

Tabs with large data sets (Profiles, Apps, DDM) use pagination:
- **50 items per page**
- Pagination controls at bottom of each tab
- Tables scroll within tab container

### Profiles Tab

Shows installed configuration profiles on the device:

| Column | Description |
|--------|-------------|
| # | Row number |
| Name | Profile display name |
| Identifier | Profile bundle identifier |
| Status | Managed or Installed |

**DDM Profiles:** DDM declarations that appear in ProfileList are marked with a purple **DDM** badge. These profiles have:
- Identifier starting with `com.apple.RemoteManagement.*`
- Status = "Installed" (not managed by traditional MDM)
- Decoded DDM identifier shown instead of the cryptic base64 string

**Note:** DDM profiles appear in both Profiles tab (with badge) and DDM tab (with active/valid status).

### DDM Tab

Shows DDM declaration status for the device:

| Column | Description |
|--------|-------------|
| Identifier | Declaration identifier |
| Active | ✓ = declaration is active |
| Valid | ✓ = declaration is valid |
| Server Token | Token from KMFDDM server |
| Updated | Last update timestamp |

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
    dd.profiles_updated_at,
    dd.apps_updated_at,
    dd.ddm_updated_at
FROM device_inventory d
LEFT JOIN device_details dd ON d.uuid = dd.uuid;
```

**Cached columns:**
- `hardware_data` - DeviceInformation response
- `security_data` - SecurityInfo response
- `profiles_data` - ProfileList response
- `apps_data` - InstalledApplicationList response
- `ddm_data` - DDM declaration status from status_declarations

## Inventory Updates

### Manual Update

**Admin Panel > Commands > Device Control > Update Inventory**

Filters:
- OS (macOS/iOS)
- Manifest
- Last Updated (24h, 7 days, never)

### Automatic Update

Cron schedule (11:00 and 22:00, Mon-Fri):

```bash
0 11,22 * * 1-5 /opt/nanohub/tools/inventory_update.py >> /var/log/nanohub/inventory_update.log 2>&1
```

Updates all devices with:
- Hardware info (DeviceInformation)
- Security info (SecurityInfo)
- Profiles (ProfileList)
- Apps (InstalledApplicationList)

### In-Memory Cache

Processed device data is cached in memory for faster page loads:

- **TTL:** 60 seconds
- **Invalidation:** Automatic on device update
- **Cached:** os_version, model, supervised, encrypted, DEP, profile compliance

See [Reports > Performance Optimizations](reports.md#performance-optimizations) for details.

## Bulk Operations

1. Select devices using checkboxes
2. Or use "Select All" / "Select Filtered"
3. Execute command from dropdown
4. View progress and results

### Multi-Page Selection

Device selection persists across pagination. Selected device count shown in header.
