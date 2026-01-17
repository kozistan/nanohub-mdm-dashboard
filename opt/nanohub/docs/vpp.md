# VPP - Volume Purchase Program

Manage Apple Business Manager app licenses and deployments.

## Overview

The VPP Panel provides:

- Token status and expiration monitoring
- License overview (total, assigned, available)
- Visual app browser with icons
- Direct install/remove to devices
- Automatic app updates

## Access

**Admin Panel > VPP** or `/admin/vpp`

## Features

### Token Management

- VPP token status display
- Expiration warnings (30 days before)
- Token loaded from `/opt/nanohub/environment.sh`

### License Overview

| Metric | Description |
|--------|-------------|
| Total Apps | Number of apps in VPP account |
| Total Licenses | Sum of all licenses |
| Assigned | Licenses currently in use |
| Available | Licenses available for assignment |

### App Browser

- App icons fetched from iTunes API
- Filter by platform (iOS/macOS)
- Search by app name
- Low license alerts (< 5 available)

### Actions

| Action | Description |
|--------|-------------|
| Install | Push app to selected devices |
| Remove | Remove app from devices |
| Refresh | Update license counts from Apple |

## VPP Updates Dashboard

**Admin Panel > VPP > Updates** or `/admin/vpp/updates`

Automatic app version management:

1. **Check Updates** - Compare installed vs expected versions
2. **Apply Updates** - Queue InstallApplication commands
3. **Refresh Apps** - Request fresh app list from devices
4. **Manage Apps** - Edit managed apps manifest

### Managed Apps Manifest

JSON files defining expected app versions:

```
/opt/nanohub/data/apps_ios.json
/opt/nanohub/data/apps_macos.json
```

Example:
```json
{
  "com.microsoft.Outlook": "3.45.0",
  "com.microsoft.Word": "2.78",
  "us.zoom.xos": "5.17.0"
}
```

### Filters

- **OS** - macOS or iOS only
- **Manifest** - Device group filter
- **Search** - Device name search

### Automation

Cron script for automated updates:

```bash
/opt/nanohub/tools/api/commands/update_vpp_from_db
```

Runs daily at 03:00 (Mon-Fri) with Telegram reporting.

## Database

VPP data is cached in `device_details.apps_data`:

```sql
SELECT
    uuid,
    JSON_EXTRACT(apps_data, '$[*].name') as apps,
    apps_updated_at
FROM device_details
WHERE apps_data IS NOT NULL;
```

## Troubleshooting

### Token Issues

```bash
# Check token in environment
grep VPP_TOKEN /opt/nanohub/environment.sh

# Test VPP API
curl -H "Authorization: Bearer $VPP_TOKEN" \
  https://vpp.itunes.apple.com/mdm/v2/assets
```

### App Not Installing

1. Check device has available license
2. Verify device is online
3. Check Command History for errors
4. Ensure app is compatible with device OS version
