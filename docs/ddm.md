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

## Declaration Types and Activation Rules

### Three Declaration Types

| Type Prefix | Name | StandardConfigurations | Example |
|-------------|------|------------------------|---------|
| `com.apple.activation.*` | Activation | N/A (defines StandardConfigurations) | `com.apple.activation.simple` |
| `com.apple.configuration.*` | Configuration | **MUST be listed** to apply | `com.apple.configuration.passcode.settings` |
| `com.apple.management.*` | Management | **NOT needed** (auto-applies via set) | `com.apple.management.organization-info` |

### How Activation Works

The **activation declaration** controls which configuration declarations are applied to the device. Its `StandardConfigurations` array lists the identifiers of config declarations that should be active.

Example activation payload:
```json
{
    "Type": "com.apple.activation.simple",
    "Identifier": "com.sloto.ddm.activation.macos-karlin",
    "Payload": {
        "StandardConfigurations": [
            "com.sloto.ddm.passcode",
            "com.sloto.ddm.softwareupdate.macos",
            "com.sloto.ddm.status-subscriptions"
        ]
    }
}
```

**Key Rules:**
- Config declarations (`com.apple.configuration.*`) **MUST** be in `StandardConfigurations` to apply
- Management declarations (`com.apple.management.*`) **auto-apply** via set assignment - no need to list them
- Each set should have exactly ONE activation declaration

### Set Editor Warnings

When editing a set, the UI shows type hints and warnings:

| Badge | Meaning |
|-------|---------|
| `(activation)` | This is an activation declaration |
| `(config)` | This is a configuration declaration |
| `(mgmt)` | This is a management declaration |
| **no activation** | No activation selected in set - config declarations won't work |
| **not in activation** | This config is not in the selected activation's StandardConfigurations |

## Complete Workflow: Adding New Config Declaration

### Step 1: Create Declaration

1. Go to **DDM** → **Declarations** tab
2. Click **Add Declaration** or **Import from Files**
3. Fill in identifier, type, and payload JSON
4. Click **Save** (auto-uploads to KMFDDM)

### Step 2: Update Activation

1. Find the appropriate activation declaration (e.g., `com.sloto.ddm.activation.macos-karlin`)
2. Click **View** to open it
3. Add your new declaration identifier to the `StandardConfigurations` array in Payload
4. Click **Save**
5. Click **Upload** to push changes to KMFDDM

### Step 3: Add to Set

1. Go to **Sets** tab
2. Click **Edit** on the appropriate set
3. Check the checkbox next to your new declaration
4. Verify no warning badge appears (if it does, check Step 2)
5. Click **Save**

### Step 4: Sync Devices

Option A: Wait for automatic check-in (devices sync periodically)

Option B: Force sync immediately:
1. Go to device's detail page
2. Click **DDM** tab
3. Click **Force Sync** button

### Verification

1. Go to **Reports** → check DDM column shows correct count
2. Go to device detail → **DDM** tab → verify declaration shows Active=✓ Valid=✓

## Complete Workflow: Adding New Management Declaration

Management declarations are simpler - no StandardConfigurations needed:

### Step 1: Create Declaration

Same as above - create or import the declaration.

### Step 2: Add to Set

1. Go to **Sets** tab
2. Click **Edit** on the appropriate set
3. Check the checkbox next to your new declaration
4. No warning should appear (management types don't need activation)
5. Click **Save**

### Step 3: Sync Devices

Same as above - wait or force sync.

## Common Mistakes

| Mistake | Result | Fix |
|---------|--------|-----|
| Config not in StandardConfigurations | Declaration won't apply | Edit activation, add identifier to StandardConfigurations |
| Wrong activation in set | Configs won't apply | Ensure correct activation for OS (ios vs macos) |
| Management in StandardConfigurations | Works but unnecessary | Remove from StandardConfigurations (optional) |
| Forgot to Upload after editing | KMFDDM has old version | Click Upload button on declaration |
| Forgot to Save set | Changes lost | Always click Save |

## DDM in ProfileList (Profiles Tab)

Apple reports some DDM declarations in the ProfileList response, which appear in the Device Detail → Profiles tab with a purple `DDM` badge.

### Which DDM Declarations Appear in Profiles?

Not all DDM declarations show up in ProfileList. Apple only includes declarations that create a visible "profile" entry:

| Declaration Type | In ProfileList | Reason |
|------------------|----------------|--------|
| `passcode` | **Yes** | Creates passcode policy profile |
| `activation` | No | Internal DDM mechanism |
| `org-info` | No | Management type (metadata only) |
| `softwareupdate.settings` | No | System preference, not profile |
| `softwareupdate.enforcement` | No | System preference, not profile |
| `status-subscriptions` | No | Internal DDM mechanism |

### Display Format

DDM entries in Profiles tab show:
- **Name**: `DDM` badge + cleaned name (without "Remote Management" prefix)
- **Identifier**: Decoded DDM identifier (e.g., `com.sloto.ddm.passcode`)
- **Tooltip**: Original Apple identifier (hover over identifier to see)

### Where to See All DDM Declarations

To see **all** DDM declarations for a device (not just those in ProfileList):
1. Go to Device Detail
2. Click the **DDM** tab
3. View the full list with Active/Valid status

### Why This Matters

- **Profiles tab**: Shows only DDM declarations that Apple reports as "profiles"
- **DDM tab**: Shows all DDM declarations and their actual status
- If a declaration shows in DDM tab but not in Profiles tab, this is normal behavior
