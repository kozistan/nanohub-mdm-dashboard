# Reports

Statistics and reporting features.

## Access

**Admin Panel > Reports** or `/admin/reports`

## Performance Optimizations

### Async Loading

Reports page uses asynchronous data loading for better responsiveness:

1. HTML page loads immediately (empty table with "Loading...")
2. Data fetched via AJAX from `/admin/api/reports/data`
3. Table populated after data arrives
4. Stats bar updated dynamically

**Benefits:**
- Page never "freezes" during data load
- Works smoothly even during bulk Update Inventory operations
- Retry button shown on network errors

### In-Memory Cache

Device data is cached in memory to avoid repeated JSON parsing:

| Parameter | Value |
|-----------|-------|
| TTL | 60 seconds |
| Max entries | 2000 devices |
| Location | `cache_utils.py` |

**Cached data per device:**
- `os_version`, `model`
- `is_supervised`, `is_encrypted`, `is_dep`
- `profile_check` (compliance result)
- `ddm_check` (DDM compliance result)

**Cache invalidation:**
- Automatic after 60 seconds
- On device data update (Update Inventory, device queries)
- On service restart

**Note:** `last_seen` and `status` are always fetched fresh from database.

## Filters

Reports page has two filter mechanisms:

### Stats Bar (Top)
Clickable statistics that act as quick filters:
- Click any stat number to filter devices by that criteria
- Examples: "Outdated OS", "Missing Profiles", "DEP devices"

### Filter Bar (Below Stats)
Two visible filters for common use:

| Filter | Description |
|--------|-------------|
| Manifest | Filter by device group |
| Search | Search hostname, serial, UUID |

**Note:** Other filters (OS, Supervised, Encrypted, etc.) are accessible via stats bar clicks.

## Pagination

- **50 rows per page** on all list views (devices, reports, VPP)
- Selection persists across pages for bulk operations

## Enrollment Types

Reports show enrollment type for each device based on MDM enrollment method:

| Type | Meaning |
|------|---------|
| **BYOD** | Personal device with managed Apple ID (IsUserEnrollment=True) |
| **DEP (User Approved)** | Apple Business Manager device, user approved MDM profile |
| **DEP (Not Approved)** | Apple Business Manager device, MDM not yet approved by user |
| **Manual (User Approved)** | Manually enrolled, user approved MDM profile |
| **Manual (Not Approved)** | Manually enrolled, MDM not yet approved |

**Technical details:**
- `IsUserEnrollment` - True only for BYOD User Enrollment (personal devices)
- `EnrolledViaDEP` - True for Apple Business Manager (ABM) devices
- `UserApprovedEnrollment` - True when user manually approves MDM profile on macOS

## Outdated Apps

Reports track outdated applications by comparing installed versions against expected versions:

**Data source:** `/opt/nanohub/data/apps_{os}_with_versions.json` (maintained by VPP sync)

**Display format:** `App Name: 1.0 → 2.0` (installed → expected)

**Note:** Only apps tracked in VPP are checked. Third-party apps not in VPP won't appear as outdated.

## CSV Export

Two export options available:

| Button | Description |
|--------|-------------|
| Export CSV | Export all devices matching current filters |
| Export Selected | Export only selected devices |

### CSV Columns (17 total)

| Column | Description |
|--------|-------------|
| Hostname | Device name |
| Serial | Hardware serial number |
| OS | macOS or iOS |
| Version | OS version number |
| Model | Device model |
| Manifest | Device group assignment |
| Enrollment Type | BYOD, DEP (User Approved/Not Approved), Manual (User Approved/Not Approved) |
| Supervised | Yes/No |
| Encrypted | Yes/No (FileVault/Data Protection) |
| Outdated OS | Yes/No |
| Outdated Apps | Semicolon-separated list: `App1: 1.0 → 2.0; App2: 3.1 → 3.2` |
| Profiles Status | Ratio: `5/6` (installed/required) |
| Missing Profiles | Semicolon-separated profile names |
| DDM Status | Ratio: `3/4` (active/required) |
| Missing DDM | Semicolon-separated declaration identifiers |
| Last Check-in | Timestamp of last MDM check-in |
| Status | Online/Active/Offline |

## Available Reports

### Device Statistics

| Metric | Description |
|--------|-------------|
| Total Devices | Count of enrolled devices |
| By OS | macOS vs iOS breakdown |
| By Manifest | Devices per group |
| Online/Offline | Current status distribution |

### OS Version Distribution

Breakdown of devices by operating system version:

- macOS versions (Ventura, Sonoma, Sequoia, etc.)
- iOS versions
- Devices needing updates

### Security Compliance

| Check | Description |
|-------|-------------|
| FileVault | Encryption enabled |
| Firewall | Firewall active |
| SIP | System Integrity Protection |
| Passcode | Passcode configured |

### DDM Compliance

| Column | Description |
|--------|-------------|
| DDM | Active/Total declarations (e.g., `4/4`) |
| Tooltip | Hover to see declaration details |
| Filter | Filter by DDM compliance status |

**Status icons in tooltip:**
- ✓ (green) = Active and valid
- ✗ (red) = Inactive or invalid

### Storage Analysis

- Total storage capacity
- Available space
- Devices with low storage (< 10%)

## Command History

**Admin Panel > History** or `/admin/history`

### Filters

| Filter | Options |
|--------|---------|
| Date Range | Today, 7 days, 30 days, custom |
| Device | Search by hostname/serial |
| User | Filter by admin user |
| Status | Success/Failure |
| Command | Filter by command type |

### Columns

| Column | Description |
|--------|-------------|
| Timestamp | When command was executed |
| User | Admin who ran command |
| Command | Command name |
| Device | Target device |
| Status | Success/Failure |
| Duration | Execution time |

### Details

Click any row to view:
- Full command parameters
- Response data
- Error messages (if failed)

## Export

Reports can be exported as:
- CSV for spreadsheet analysis
- JSON for programmatic use

## Database Queries

### Device Count by OS

```sql
SELECT os, COUNT(*) as count
FROM device_inventory
GROUP BY os;
```

### Recent Commands

```sql
SELECT
    timestamp,
    user,
    command_name,
    device_hostname,
    success
FROM command_history
ORDER BY timestamp DESC
LIMIT 100;
```

### Failed Commands

```sql
SELECT *
FROM command_history
WHERE success = 0
  AND timestamp > DATE_SUB(NOW(), INTERVAL 7 DAY)
ORDER BY timestamp DESC;
```

### Devices by Manifest

```sql
SELECT manifest, COUNT(*) as count
FROM device_inventory
GROUP BY manifest
ORDER BY count DESC;
```

## Audit Log

All admin actions logged to `admin_audit_log`:

```sql
SELECT
    timestamp,
    username,
    action,
    command,
    success
FROM admin_audit_log
ORDER BY timestamp DESC;
```

Also written to file: `/var/log/nanohub/admin_audit.log`
