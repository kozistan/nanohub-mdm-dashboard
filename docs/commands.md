# MDM Commands Reference

Complete list of MDM commands available in the Admin Panel.

## Device Setup

| Command | Description | Parameters |
|---------|-------------|------------|
| New Device Installation | DB-driven device provisioning | Manifest, Account, Restrictions, WiFi, Apps |
| Device Manager | Add/Update/Delete devices | UUID, Serial, Hostname, OS, Manifest |

### New Device Installation

Automated workflow for provisioning new devices. **Fully database-driven** - profiles and applications are loaded from `required_profiles` and `required_applications` tables based on selected manifest.

**Parameters:**
- **Manifest** - Device group (determines which profiles/apps to install)
- **Account Profile** - Disabled (default), Enabled, or Skip
- **Restrictions Profile** - Standard (default), iCloudSync, LevelC, or Skip (macOS only)
- **Applications** - Checkboxes for apps defined in DB for selected manifest
- **WiFi Profile** - Optional WiFi configuration
- **FileVault** - Optional disk encryption (macOS, client must be logged in)
- **Directory Services** - Optional AD join (macOS, requires hostname)
- **WireGuard** - Optional VPN profile (searches by username)

## Applications

| Command | Description | Parameters |
|---------|-------------|------------|
| Manage Applications | Add/Edit/Remove applications in DB | Manifest, App Name, URL, Order |
| Install App | Install application via manifest URL | Manifest URL |

### Manage Applications

Database management for applications used in New Device Installation.

**Actions:**
- **LIST** - Show all applications grouped by manifest
- **ADD** - Add new application to database
- **EDIT** - Modify existing application (select manifest first, then app)
- **REMOVE** - Delete application from database

## Profiles

| Command | Description | Notes |
|---------|-------------|-------|
| Manage Profiles | Install/Remove/List profiles | Multi-device support |

## Device Information

| Command | Description | Output |
|---------|-------------|--------|
| Device Info | Hardware and OS information | Model, OS, Serial, UDID |
| Security Info | Security status and settings | FileVault, Firewall, SIP |
| Profile List | Installed configuration profiles | Profile names and identifiers |
| Installed Apps | Application inventory | App names, versions, sizes |
| Certificate List | Installed certificates | Certificate names, expiry |

## Device Control

| Command | Description | Notes |
|---------|-------------|-------|
| Lock Device | Immediately lock device | Requires passcode to unlock |
| Restart Device | Restart device | macOS: immediate, iOS: user prompt |
| Shutdown | Shut down device | macOS only |
| Erase Device | Factory reset | Removes all data |
| Update Inventory | Refresh cached device data | Bulk operation supported |

## Remote Access (macOS)

| Command | Description | Notes |
|---------|-------------|-------|
| Enable Remote Desktop | Enable screen sharing | ARD compatible |
| Disable Remote Desktop | Disable screen sharing | Security measure |
| Bulk Remote Desktop | Enable/disable on multiple devices | Device selection |

## Security

| Command | Description | Parameters |
|---------|-------------|------------|
| Lost Mode | Lost Mode for supervised iOS/iPadOS | Action (enable/locate/disable), Reason*, Message, Phone, Footnote |
| Clear Passcode | Remove device passcode | iOS only |

### Lost Mode & Location (iOS/iPadOS only)

- Single command with an **Action** selector: Enable / Request Location / Disable.
- **admin** role + mandatory **Reason** (audit-logged to `command_history`).
- **macOS not supported** — Apple provides neither Lost Mode nor DeviceLocation on Mac; commands are hidden for macOS devices.
- **Enable auto-requests location** — enabling Lost Mode also enqueues a `DeviceLocation` automatically, so the location comes back without a second step (conditional on the enable succeeding).
- **Request Location works only while the device is in active Lost Mode.** Otherwise Apple returns `Error`/`NotNow`. Use it to refresh the location after Enable.
- Location is returned asynchronously when the device next checks in — it is an on-demand snapshot, not live tracking.
- The `DeviceLocation` response is stored in `device_details.location_data` and shown read-only on the device detail **Location** tab. Activation happens via the command menu, not the device page.
- **Map is self-hosted** — Leaflet assets under `/static/leaflet/` and OSM tiles via the nginx `/osm-tiles/` proxy (the server fetches tiles; the browser only talks to the portal, so the map works without internet access from the admin workstation).
- Workflow: **Enable (auto-locates) → Request Location (refresh) → (recover) → Disable**.

## OS Updates

| Command | Description | Parameters |
|---------|-------------|------------|
| Schedule OS Update | Schedule system update | Version, Action, Priority |
| Available Updates | List available updates | - |

## Profiles

| Command | Description | Notes |
|---------|-------------|-------|
| Install Profile | Push configuration profile | Signed profiles only |
| Remove Profile | Remove by identifier | Cannot remove MDM profile |
| List Profiles | Show installed profiles | Includes managed status |

## Bulk Operations

All commands support bulk execution on multiple devices:

1. Select devices using checkboxes
2. Use filters (OS, Manifest, Status)
3. Execute command
4. View results in Command History

### Performance

- Parallel execution: 10-20 concurrent operations
- Typical bulk command: 50 devices in ~10 seconds
- Progress tracking in real-time

## Command History

All executed commands are logged to `command_history` table:

- Timestamp
- User who executed
- Command name and parameters
- Target device(s)
- Success/failure status
- Execution time

Access via **Admin Panel > History**
