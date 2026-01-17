# Reports

Statistics and reporting features.

## Access

**Admin Panel > Reports** or `/admin/reports`

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
