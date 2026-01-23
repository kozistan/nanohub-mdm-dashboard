# Declarative Device Management (DDM)

DDM is Apple's modern device management approach that runs parallel to traditional MDM. Devices apply configurations autonomously based on declarations.

## Architecture

```
┌─────────────────┐                              ┌─────────────────┐
│  JSON Files     │  ──── Import/Add ────────>  │   NanoHUB DB    │
│  (declarations/)│                              │ (ddm_declarations)
└─────────────────┘                              └────────┬────────┘
                                                          │
                                                   auto-upload
                                                          │
                                                          v
                                                 ┌─────────────────┐
                                                 │   KMFDDM        │
                                                 │   (DDM Engine)  │
                                                 └────────┬────────┘
                                                          │
                                                          v
                                                 ┌─────────────────┐
                                                 │    Devices      │
                                                 │ (via NanoMDM)   │
                                                 └─────────────────┘
```

**Data flow:**
- JSON files on disk = PRIMARY SOURCE
- NanoHUB DB = metadata + payload copy
- KMFDDM = auto-synced (upload on add, delete on remove)

## Hierarchy

1. **Declarations** - Individual configuration policies (JSON files)
2. **Sets** - Groups of declarations assigned together
3. **Required Sets** - Manifest+OS assignments (which sets apply to which devices)
4. **Enrollments** - Device assignments to sets

## Admin Panel - DDM Page

### Declarations Tab

Manage individual DDM declarations:

| Action | Description |
|--------|-------------|
| **Add Declaration** | Create new declaration manually (identifier, type, JSON payload) - auto-uploads to KMFDDM |
| **Import from Files** | Import JSON files from `/opt/nanohub/ddm/declarations/` - auto-uploads to KMFDDM |
| **Remove** | Remove declaration from database AND KMFDDM server |

**Table columns:** Identifier, Type, Payload (preview), Updated At

**Note:** Declarations are automatically uploaded to KMFDDM server when added or imported. No manual upload needed.

### Sets Tab

Manage declaration groups:

| Action | Description |
|--------|-------------|
| **Create Set** | Create new set with selected declarations |
| **Edit Set** | Modify set name, description, or declarations |
| **Remove** | Remove set from database |

**Table columns:** Set Name, Description, Declarations (count), Updated At

### Required Sets Tab

Assign DDM sets to manifests (device groups):

| Action | Description |
|--------|-------------|
| **Assign Set** | Assign DDM set to manifest + OS combination |
| **Remove** | Remove assignment |

**Table columns:** Manifest, OS, DDM Set, Actions

## Device Detail - DDM Tab

View DDM status for individual device:

| Column | Description |
|--------|-------------|
| **Identifier** | Declaration identifier |
| **Active** | ✓ = declaration is active on device |
| **Valid** | ✓ = declaration is valid (no errors) |
| **Server Token** | Token from server |
| **Updated** | Last update timestamp |

**Badge colors:**
- Green ✓ = Active and valid
- Red ✗ = Inactive or invalid

## Reports - DDM Column

DDM compliance column shows:
- **Format:** `active/total` (e.g., `4/4`)
- **Tooltip:** Lists all declarations with status icons
- **Filter:** Filter by DDM compliance status
- **CSV Export:** Included in exports

## Available Declaration Types

| Type | Description | Platform |
|------|-------------|----------|
| `com.apple.configuration.passcode.settings` | Passcode requirements | macOS, iOS |
| `com.apple.configuration.softwareupdate.settings` | Software update policy | macOS, iOS |
| `com.apple.configuration.screensharing.host.settings` | Screen sharing | macOS |
| `com.apple.management.organization-info` | Organization info | macOS, iOS |
| `com.apple.activation.simple` | Activation declaration | macOS, iOS |

**Note:** FileVault and Firewall are NOT available as DDM - use traditional MDM profiles.

## Directory Structure

```
/opt/nanohub/ddm/
├── declarations/           # DDM declaration JSON files (PRIMARY SOURCE)
│   ├── com.company.ddm.activation.ios.json
│   ├── com.company.ddm.activation.macos.json
│   ├── com.company.ddm.org-info.json
│   ├── com.company.ddm.passcode.json
│   ├── com.company.ddm.screensharing.json
│   ├── com.company.ddm.softwareupdate.ios.json
│   └── com.company.ddm.softwareupdate.macos.json
└── scripts/                # Management scripts
    ├── ddm-upload-declarations.sh
    ├── ddm-create-sets.sh
    ├── ddm-assign-device.sh
    ├── ddm-bulk-assign.sh
    ├── ddm-force-sync.sh
    └── ddm-status.sh
```

**Note:** Sets are defined in the database only (not as files). Declarations on disk are the primary source.

## Declaration JSON Format

```json
{
    "Type": "com.apple.configuration.passcode.settings",
    "Identifier": "com.company.ddm.passcode",
    "Payload": {
        "MinimumLength": 6,
        "RequireAlphanumeric": false
    }
}
```

## Workflow

1. **Import declarations** - Import JSON files from `/opt/nanohub/ddm/declarations/` (auto-uploads to KMFDDM)
2. **Create sets** - Group declarations by purpose (e.g., ios-default, macos-tech) in Sets tab
3. **Assign to manifests** - In Required Sets tab, assign sets to manifest+OS
4. **Devices sync** - Devices receive declarations based on their manifest

**Note:** Declarations are automatically uploaded to KMFDDM server when imported or added. No manual upload step needed.

## CLI Scripts

```bash
# Upload all declarations
/opt/nanohub/ddm/scripts/ddm-upload-declarations.sh

# Create sets from definition files
/opt/nanohub/ddm/scripts/ddm-create-sets.sh

# Assign set to device
/opt/nanohub/ddm/scripts/ddm-assign-device.sh <UDID> <set-name>

# Force device to sync DDM
/opt/nanohub/ddm/scripts/ddm-force-sync.sh <UDID>

# View status
/opt/nanohub/ddm/scripts/ddm-status.sh all|declarations|sets|device <UDID>
```

## Database Tables

### NanoHUB Database (nanohub)

```sql
-- Declarations (with full payload)
SELECT id, identifier, type, payload, server_token, uploaded, updated_at
FROM ddm_declarations;

-- Sets (metadata only)
SELECT id, name, description, updated_at FROM ddm_sets;

-- Set-declaration mappings
SELECT set_id, declaration_id FROM ddm_set_declarations;

-- Required sets (manifest assignments)
SELECT manifest, os, set_id FROM ddm_required_sets;

-- Cached DDM data (device_details)
SELECT uuid, ddm_data, ddm_updated_at FROM device_details;
```

### KMFDDM Database (kmfddm)

```sql
-- Declarations on KMFDDM server
SELECT identifier, type, payload, server_token FROM declarations;

-- Sets on KMFDDM server
SELECT identifier FROM sets;

-- Set-declaration mappings
SELECT set_identifier, declaration_identifier FROM set_declarations;

-- Device-set assignments
SELECT id, set_identifier FROM enrollment_sets;

-- Declaration status from devices
SELECT enrollment_id, declaration_identifier, active, valid, server_token
FROM status_declarations;
```

## Verifying on Client

```bash
# Check MDM enrollment
profiles status -type enrollment

# View DDM logs
log show --predicate 'eventMessage CONTAINS "declaration"' --last 1h

# Check specific declaration
log show --predicate 'eventMessage CONTAINS "passcode"' --last 1h
```

**Note:** DDM declarations don't appear in `profiles show` - they're processed directly by system services.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Declarations not showing in KMFDDM | Check `uploaded` column in `ddm_declarations` - should be 1 |
| Device shows 0 declarations | Verify manifest assignment in Required Sets tab |
| Valid = No | Check declaration JSON syntax in source file |
| Reports show 0/0 | Click "Refresh Data" to update cache |
| Import failed | Check JSON file format and permissions in `/opt/nanohub/ddm/declarations/` |
| Remove failed | Check KMFDDM server connectivity and API key |
