# Declarative Device Management (DDM)

DDM is Apple's modern device management approach that runs parallel to traditional MDM. Devices apply configurations autonomously based on declarations.

## Architecture

```
┌─────────────────┐         ┌──────────────────┐         ┌─────────────────┐
│   Admin Panel   │────────>│    NanoMDM       │────────>│   KMFDDM        │
│   (DDM cmds)    │         │    API           │         │   (DDM Engine)  │
└─────────────────┘         └──────────────────┘         └─────────────────┘
                                    │                            │
                                    │                    ┌───────┴───────┐
                                    v                    v               v
                            ┌─────────────┐      ┌─────────────┐  ┌─────────────┐
                            │   MySQL     │      │ Declarations│  │    Sets     │
                            │   (status)  │      │   (JSON)    │  │  (groups)   │
                            └─────────────┘      └─────────────┘  └─────────────┘
```

## Hierarchy

1. **Declarations** - Individual configuration policies (JSON files)
2. **Sets** - Groups of declarations assigned together
3. **Enrollments** - Device assignments to sets

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
├── declarations/           # DDM declaration JSON files
│   ├── com.company.ddm.activation.ios.json
│   ├── com.company.ddm.activation.macos.json
│   ├── com.company.ddm.org-info.json
│   ├── com.company.ddm.passcode.json
│   ├── com.company.ddm.screensharing.json
│   ├── com.company.ddm.softwareupdate.ios.json
│   └── com.company.ddm.softwareupdate.macos.json
├── sets/                   # Set definition files
│   ├── ios-default.txt
│   ├── macos-default.txt
│   └── macos-tech.txt
└── scripts/                # Management scripts
    ├── ddm-upload-declarations.sh
    ├── ddm-create-sets.sh
    ├── ddm-assign-device.sh
    ├── ddm-bulk-assign.sh
    ├── ddm-force-sync.sh
    └── ddm-status.sh
```

## Admin Panel Commands

| Command | Description |
|---------|-------------|
| DDM Status | View declarations, sets, or device enrollment |
| Manage DDM Sets | Assign/remove DDM sets to devices |
| Upload Declarations | Upload all declarations to server |
| Create Sets | Create/update all DDM sets |

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

```sql
-- Declarations
SELECT * FROM declarations;

-- Set-declaration mappings
SELECT * FROM set_declarations;

-- Device-set assignments
SELECT * FROM enrollment_sets;

-- Declaration status from devices
SELECT * FROM status_declarations;

-- Status errors
SELECT * FROM status_errors;
```

## Verifying on Client

```bash
# Check MDM enrollment
profiles status -type enrollment

# View DDM logs
log show --predicate 'eventMessage CONTAINS "declaration"' --last 1h
```

**Note:** DDM declarations don't appear in `profiles show` - they're processed directly by system services.
