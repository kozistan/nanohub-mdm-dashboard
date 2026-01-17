# NanoHUB MDM Dashboard

Web-based management dashboard for Apple MDM (Mobile Device Management) using NanoHUB backend with LDAP authentication and comprehensive admin panel.

**Version:** 3.1
**Last Updated:** 2026-01-16

## Features

### Core Features
- **LDAP Authentication**: Active Directory login with role-based access control
- **SQL-Based Device Management**: Fast, scalable MySQL device database
- **Real-time Device Status**: Online/Active/Offline status indicators
- **Device Search**: Search by UUID, serial number, or hostname
- **Parallel Execution**: 10-20x faster bulk operations with race condition fixes
- **DDM Support**: Declarative Device Management with KMFDDM integration

### Admin Panel
- **Device Setup**: DB-driven installation workflows for new devices
- **Profiles**: Install, remove, list profiles
- **Applications**: App installation, Manage Applications (DB CRUD)
- **Device Control**: Lock, unlock, restart, erase
- **OS Updates**: OS update management
- **Remote Desktop**: Enable/disable remote access
- **Security**: Lost mode, security info
- **Diagnostics**: Device info, MDM analyzer
- **VPP Apps**: VPP license management
- **Database Tools**: Device inventory operations
- **DDM**: Declarative Device Management

### Modular Architecture (NEW in v3.0)
- **Package Structure**: Admin panel split into separate modules
- **nanohub_admin_core.py**: Core admin functionality and commands
- **nanohub_admin/routes/**: Modular route blueprints
  - `settings.py` - Settings page and configuration
  - `reports.py` - Reports and statistics
  - `vpp.py` - VPP/App management
  - `devices.py` - Device inventory list
- **Manifest Management**: Database-backed manifests with CRUD operations
- **User Role Management**: Database-stored role overrides with CLI tool

### VPP Panel
- **Token Management**: VPP token status with expiration warnings
- **License Overview**: Total apps, licenses, assigned/available counts
- **App Browser**: Visual app list with icons from iTunes API
- **Filtering**: By platform (iOS/macOS), search by name, low license alerts
- **Install/Remove**: Direct app installation and removal to selected devices

### Command History (NEW in v2.0)
- **MySQL Storage**: Persistent command history with 90-day retention
- **Detailed Logging**: Command name, parameters, device info, results
- **Filtering**: By date range, device, user, success/failure status
- **Pagination**: Browse through historical commands
- **Automatic Cleanup**: Daily cleanup of records older than 90 days

### Device Detail Panel (NEW in v2.1)
- **Device Card**: Comprehensive device information page (`/admin/device/<uuid>`)
- **Database Caching**: MDM data cached in MySQL (like Jamf) for instant access
- **Tab Interface**: Info, Hardware, Security, Profiles, Apps, History tabs
- **Quick Actions**: Lock, Restart, Erase directly from device page
- **Update Inventory**: Bulk inventory update command with filters
  - OS filter (macOS/iOS)
  - Manifest filter (dynamic list)
  - Last Updated filter (24h, 7 days, never)
- **Daily Cron**: Automatic inventory refresh at 14:00

### VPP Updates Dashboard (NEW in v2.3)
- **Automatic App Updates**: Compare installed vs expected versions from JSON manifests
- **Dashboard UI**: `/admin/vpp/updates` with device selection and filters
- **Database-Driven**: Reads cached app data from device_details table (no device polling)
- **Filters**: By OS (macOS/iOS), Manifest, device search
- **Actions**:
  - Check Updates: Dry-run to see which apps need updates
  - Apply Updates: Queue InstallApplication commands for outdated apps
  - Refresh Apps Data: Request fresh InstalledApplicationList from devices
  - Manage Apps: Edit managed apps JSON manifest
- **Smart Queue**: Replaces pending InstallApplication commands with latest version
- **Force Install**: Option to reinstall all managed apps regardless of version
- **Batch Script**: `update_vpp_from_db` for automated cron execution with Telegram reports
- **Cron Schedule**: Daily at 03:00 (Mon-Fri)

### Role-Based Access Control

| AD Group | Role | Access |
|----------|------|--------|
| `it` | admin | Full access to all devices |
| `mdm-admin` | admin | Full access to all devices |
| `mdm-restricted-admin` | restricted-admin | Full access, filtered by manifest |
| `mdm-operator` | operator | Device management, profiles, apps |
| `mdm-report` | report | Read-only access |

### Advanced Features
- **Manifest Filtering**: Restrict admin access to specific device groups
- **Device Manager**: Add/Update/Delete devices via web interface
- **Audit Logging**: Complete audit trail for all admin actions
- **Bulk Operations**: Execute commands on multiple devices simultaneously
- **Parallel Execution**: All bulk scripts execute commands in parallel for 10-20x speed improvement
- **Bulk Remote Desktop**: Enable/disable Remote Desktop on multiple macOS devices with device selection

## Screenshots

### Main Dashboard
![Main Dashboard](screenshots/01_main_dashboard.png)

### Admin Panel
![Admin Panel](screenshots/02_admin_panel.png)

### Profile_list command on Admin Panel
![command](screenshots/03_profile_list_command.png)

### VPP Panel
![VPP Panel](screenshots/04_vpp_panel.png)

### Device Detail Panel
![Device Panel](screenshots/05_device_panel.png)

## Architecture

```
┌─────────────────┐         ┌──────────────────┐         ┌─────────────────┐
│  Web Frontend   │────────▶│  Flask Web       │────────▶│   NanoMDM       │
│  (HTML/CSS/JS)  │         │  (nanohub_web)   │         │   Backend       │
└─────────────────┘         └──────────────────┘         └─────────────────┘
        │                           │
        │                   ┌───────┴───────┐
        │                   │               │
        ▼                   ▼               ▼
┌─────────────────┐  ┌─────────────┐  ┌─────────────┐
│  Admin Panel    │  │   LDAP/AD   │  │   MySQL     │
│  (nanohub_admin)│  │   Auth      │  │   Database  │
└─────────────────┘  └─────────────┘  └─────────────┘
```

## Prerequisites

- Python 3.8+
- MySQL/MariaDB database
- Active Directory (for LDAP authentication)
- Nginx (reverse proxy)
- NanoMDM server (running)
- systemd (service management)

## Installation

### 1. Clone Repository

```bash
git clone https://github.com/kozistan/nanohub-mdm-dashboard.git
cd nanohub-mdm-dashboard
```

### 2. Create Virtual Environment

```bash
python3 -m venv /opt/nanohub/venv
source /opt/nanohub/venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure Environment

Create environment file `/opt/nanohub/backend_api/nanohub_environment`:

```bash
# LDAP Configuration
LDAP_HOST=dc01.example.com
LDAP_HOST_FAILOVER=dc02.example.com
LDAP_BIND_DN=CN=ldapadmin,OU=Admins,DC=example,DC=com
LDAP_BIND_PASSWORD=your_ldap_password
LDAP_BASE_DN=DC=example,DC=com

# Database Configuration
DB_HOST=localhost
DB_USER=nanohub
DB_PASSWORD=your_db_password
DB_NAME=nanohub

# Flask Configuration
FLASK_SECRET_KEY=your-secret-key-change-in-production

# Paths
DASHBOARD_INDEX_PATH=/var/www/mdm-web/index.html
PROFILES_DIR=/opt/nanohub/profiles/
COMMANDS_DIR=/opt/nanohub/tools/api/commands
```

### 4. Install Files

```bash
# Backend API
sudo mkdir -p /opt/nanohub/backend_api
sudo cp opt/nanohub/backend_api/*.py /opt/nanohub/backend_api/

# Web frontend
sudo mkdir -p /var/www/mdm-web/static
sudo cp var/www/mdm-web/index.html /var/www/mdm-web/
sudo cp var/www/mdm-web/static/dashboard.css /var/www/mdm-web/static/

# Systemd services
sudo cp etc/systemd/system/nanohub-web.service /etc/systemd/system/
sudo cp etc/systemd/system/mdm-flask-api.service /etc/systemd/system/
```

### 5. Set Permissions

```bash
# Environment file (contains secrets)
sudo chmod 600 /opt/nanohub/backend_api/nanohub_environment

# Backend files
sudo chmod 755 /opt/nanohub/backend_api/*.py

# Web files
sudo chmod 644 /var/www/mdm-web/index.html
sudo chmod 644 /var/www/mdm-web/static/dashboard.css
```

### 6. Configure Database

```sql
CREATE DATABASE IF NOT EXISTS nanohub;
CREATE USER IF NOT EXISTS 'nanohub'@'localhost' IDENTIFIED BY 'your_password';
GRANT ALL PRIVILEGES ON nanohub.* TO 'nanohub'@'localhost';

-- Device inventory table
CREATE TABLE IF NOT EXISTS device_inventory (
    id INT AUTO_INCREMENT PRIMARY KEY,
    uuid VARCHAR(255) UNIQUE NOT NULL,
    serial VARCHAR(127),
    os VARCHAR(10),
    hostname VARCHAR(127),
    manifest VARCHAR(127) DEFAULT 'default',
    account VARCHAR(20) DEFAULT 'disabled',
    dep VARCHAR(20) DEFAULT '0',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_hostname (hostname),
    INDEX idx_serial (serial),
    INDEX idx_manifest (manifest),
    INDEX idx_os (os)
);

-- Command history table (NEW in v2.0)
CREATE TABLE IF NOT EXISTS command_history (
    id INT AUTO_INCREMENT PRIMARY KEY,
    timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    user VARCHAR(100) NOT NULL,
    command_id VARCHAR(100) NOT NULL,
    command_name VARCHAR(255) NOT NULL,
    device_udid VARCHAR(100),
    device_serial VARCHAR(50),
    device_hostname VARCHAR(255),
    params TEXT,
    result_summary TEXT,
    success TINYINT(1) NOT NULL DEFAULT 0,
    execution_time_ms INT,
    INDEX idx_timestamp (timestamp),
    INDEX idx_device_udid (device_udid),
    INDEX idx_device_serial (device_serial),
    INDEX idx_device_hostname (device_hostname),
    INDEX idx_user (user),
    INDEX idx_command_id (command_id)
);

-- Audit log table (legacy)
CREATE TABLE IF NOT EXISTS admin_audit_log (
    id INT AUTO_INCREMENT PRIMARY KEY,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    username VARCHAR(255),
    action VARCHAR(255),
    command VARCHAR(255),
    params TEXT,
    result TEXT,
    success BOOLEAN,
    INDEX idx_timestamp (timestamp),
    INDEX idx_username (username)
);

-- Device details cache (NEW in v2.1)
CREATE TABLE IF NOT EXISTS device_details (
    id INT AUTO_INCREMENT PRIMARY KEY,
    uuid VARCHAR(255) NOT NULL UNIQUE,
    hardware_data JSON,
    security_data JSON,
    profiles_data JSON,
    apps_data JSON,
    hardware_updated_at TIMESTAMP NULL,
    security_updated_at TIMESTAMP NULL,
    profiles_updated_at TIMESTAMP NULL,
    apps_updated_at TIMESTAMP NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_uuid (uuid)
);

-- Manifests table (NEW in v3.0)
CREATE TABLE IF NOT EXISTS manifests (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(255),
    INDEX idx_name (name)
);

-- User roles table (NEW in v3.0)
CREATE TABLE IF NOT EXISTS user_roles (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(100) NOT NULL UNIQUE,
    role VARCHAR(50) NOT NULL DEFAULT 'report',
    manifest_filter VARCHAR(100) DEFAULT NULL,
    is_active TINYINT(1) DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_by VARCHAR(100) DEFAULT NULL,
    notes TEXT DEFAULT NULL,
    INDEX idx_username (username),
    INDEX idx_role (role)
);

-- Required profiles table (NEW in v3.1)
CREATE TABLE IF NOT EXISTS required_profiles (
    id INT AUTO_INCREMENT PRIMARY KEY,
    manifest VARCHAR(127) NOT NULL,
    os VARCHAR(10) NOT NULL,
    profile_identifier VARCHAR(255) NOT NULL,
    profile_filename VARCHAR(255) DEFAULT NULL,
    install_order INT DEFAULT 100,
    is_optional TINYINT(1) DEFAULT 0,
    variant_group VARCHAR(50) DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY unique_manifest_os_profile (manifest, os, profile_identifier),
    INDEX idx_manifest (manifest),
    INDEX idx_os (os)
);

-- Required applications table (NEW in v3.1)
CREATE TABLE IF NOT EXISTS required_applications (
    id INT AUTO_INCREMENT PRIMARY KEY,
    manifest VARCHAR(127) NOT NULL,
    os VARCHAR(10) NOT NULL,
    app_name VARCHAR(255) NOT NULL,
    manifest_url VARCHAR(500) NOT NULL,
    install_order INT DEFAULT 100,
    is_optional TINYINT(1) DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_manifest (manifest),
    INDEX idx_os (os)
);
```

### 7. Configure Nginx

```nginx
server {
    listen 8000 ssl;
    server_name mdm.example.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    # Flask Web Frontend (with LDAP auth)
    location / {
        proxy_pass http://127.0.0.1:9007;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Static files
    location /static/ {
        alias /var/www/mdm-web/static/;
        expires 1d;
    }

    # API endpoints (for legacy compatibility)
    location /api/ {
        proxy_pass http://127.0.0.1:9006/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### 8. Start Services

```bash
sudo systemctl daemon-reload
sudo systemctl enable nanohub-web mdm-flask-api
sudo systemctl start nanohub-web mdm-flask-api
sudo systemctl restart nginx

# Verify services
systemctl status nanohub-web mdm-flask-api
```

## Configuration

### LDAP Groups

Configure AD groups in `nanohub_ldap_auth.py`:

```python
GROUP_ROLE_MAPPING = {
    'it': 'admin',
    'mdm-admin': 'admin',
    'mdm-restricted-admin': 'restricted-admin',
    'mdm-operator': 'operator',
    'mdm-report': 'report',
}

# Manifest filters for restricted roles
ROLE_MANIFEST_FILTER = {
    'restricted-admin': 'site-%',  # Only sees devices with site-* manifests
}
```

### Adding New Roles

To add a new restricted admin role:

1. Create AD group (e.g., `mdm-site-admin`)
2. Add to `GROUP_ROLE_MAPPING`: `'mdm-site-admin': 'site-admin'`
3. Add to `ROLE_PERMISSIONS`: `'site-admin': ['admin', 'operator', 'report', ...]`
4. Add manifest filter: `ROLE_MANIFEST_FILTER['site-admin'] = 'site-%'`
5. Update role hierarchy in `command_registry.py`
6. Restart nanohub-web service

## Usage

### Access Points

- **Main Dashboard**: `https://mdm.example.com:8000/`
- **Admin Panel**: `https://mdm.example.com:8000/admin`
- **Command History**: `https://mdm.example.com:8000/admin/history`
- **VPP Panel**: `https://mdm.example.com:8000/admin/vpp`
- **Device Detail**: `https://mdm.example.com:8000/admin/device/<uuid>`
- **Profiles**: `https://mdm.example.com:8000/admin/profiles`
- **Login**: `https://mdm.example.com:8000/login`

### Admin Panel Operations

1. Login with AD credentials
2. Navigate to Admin Panel
3. Select category and command
4. Fill in required parameters
5. Execute command
6. View results

### VPP Panel

1. Navigate to VPP tab in Admin Panel
2. View license counts and token expiration
3. Filter apps by platform or search
4. Click Install/Remove on any app
5. Select target devices in modal
6. Execute action

### Device Manager

- **ADD**: Create new device in inventory
- **UPDATE**: Modify existing device properties
- **DELETE**: Remove device from inventory

### New Device Installation

**Database-driven** workflow for provisioning new devices. Profiles and applications are loaded from `required_profiles` and `required_applications` tables.

1. Select manifest (device group)
2. Select device
3. Configure wildcard profiles:
   - Account: Disabled (default), Enabled, or Skip
   - Restrictions: Standard, iCloudSync, LevelC, or Skip (macOS)
4. Select applications (checkboxes, loaded from DB)
5. Configure optional settings (WiFi, FileVault, Directory Services, WireGuard)
6. Execute - installs all required profiles and selected applications

### Manage Applications

Admin command for managing applications in database:

- **LIST**: Show all applications grouped by manifest
- **ADD**: Add new application (manifest, OS, name, URL, order)
- **EDIT**: Modify existing application (two-step: select manifest, then app)
- **REMOVE**: Delete application from database

## API Endpoints

### Authentication
- `GET /login` - Login page
- `POST /login` - Authenticate user
- `GET /logout` - Logout user
- `GET /auth/check` - Check authentication status

### Admin Panel
- `GET /admin` - Admin dashboard
- `GET /admin/history` - Command history
- `GET /admin/vpp` - VPP license panel
- `GET /admin/profiles` - Profile management
- `POST /admin/execute` - Execute MDM command
- `POST /admin/api/vpp-action` - Execute VPP install/remove
- `GET /admin/api/devices` - Get all devices (with manifest filtering)
- `POST /admin/api/device-search` - Search devices

### Legacy API
- `GET /api/devices.json` - List all devices
- `POST /api/device-search` - Search device
- `GET /api/mdm-analyzer` - Device activity analysis

## Troubleshooting

### Service Issues

```bash
# Check service status
systemctl status nanohub-web
systemctl status mdm-flask-api

# View logs
journalctl -u nanohub-web -f
journalctl -u mdm-flask-api -f
```

### LDAP Issues

```bash
# Test LDAP connection
cd /opt/nanohub/backend_api
source /opt/nanohub/venv/bin/activate
python3 -c "from nanohub_ldap_auth import test_ldap_connection; test_ldap_connection()"
```

### Database Issues

```bash
# Test database connection
mysql -h localhost -u nanohub -p nanohub -e "SELECT COUNT(*) FROM device_inventory"

# Check command history
mysql -h localhost -u nanohub -p nanohub -e "SELECT COUNT(*) FROM command_history"
```

## Security Considerations

- Use HTTPS with valid SSL certificates
- Store credentials in environment file with restricted permissions (600)
- Use read-only database user for report queries
- Restrict Flask API to localhost
- Enable audit logging
- Regularly review audit logs
- Command history provides 90-day audit trail
- **Webhook HMAC Verification** (NEW in v3.0): Enable `-webhook-hmac-key` in NanoHUB service

## MDM Profiles

MDM configuration profiles are **not included** in this repository. You must create and sign your own profiles.

### Profile Locations

```
/opt/nanohub/profiles/                    # Standard profiles
/opt/nanohub/profiles/wireguard_configs/  # WireGuard VPN profiles
```

### Profile Requirements

- **Only signed profiles** (`.signed.mobileconfig`) are displayed in the Admin Panel GUI
- Profiles must be signed with a valid Apple-trusted certificate
- Unsigned profiles will not appear in the profile selection dropdown

### Profile Naming Convention

```
company.macos.ProfileName.profile.signed.mobileconfig   # macOS profiles
company.ios.ProfileName.profile.signed.mobileconfig     # iOS profiles
```

### Signing Profiles

Use Apple Configurator 2 or a signing tool to sign profiles:

```bash
# Example using openssl (requires Apple Developer certificate)
security cms -S -N "Your Signing Identity" -i unsigned.mobileconfig -o signed.mobileconfig
```

## DDM (Declarative Device Management)

DDM is Apple's newer device management approach that runs parallel to traditional MDM. It uses declarative configurations that devices apply autonomously.

### DDM Architecture

```
┌─────────────────┐         ┌──────────────────┐         ┌─────────────────┐
│   Admin Panel   │────────▶│    NanoMDM       │────────▶│   KMFDDM        │
│   (DDM cmds)    │         │    API           │         │   (DDM Engine)  │
└─────────────────┘         └──────────────────┘         └─────────────────┘
                                    │                            │
                                    │                    ┌───────┴───────┐
                                    ▼                    ▼               ▼
                            ┌─────────────┐      ┌─────────────┐  ┌─────────────┐
                            │   MySQL     │      │ Declarations│  │    Sets     │
                            │   (status)  │      │   (JSON)    │  │  (groups)   │
                            └─────────────┘      └─────────────┘  └─────────────┘
```

### DDM Hierarchy

1. **Declarations** - Individual configuration policies (JSON files)
2. **Sets** - Groups of declarations assigned together
3. **Enrollments** - Device assignments to sets

### Available Declaration Types (macOS/iOS)

| Type | Description | Platform |
|------|-------------|----------|
| `com.apple.configuration.passcode.settings` | Passcode requirements | macOS, iOS |
| `com.apple.configuration.softwareupdate.settings` | Software update policy | macOS, iOS |
| `com.apple.configuration.screensharing.host.settings` | Screen sharing settings | macOS |
| `com.apple.management.organization-info` | Organization information | macOS, iOS |
| `com.apple.activation.simple` | Activation declaration | macOS, iOS |

**Note:** FileVault and Firewall are NOT available as DDM declarations - use traditional MDM profiles.

### DDM Directory Structure

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
├── sets/                   # Set definition files (list of declarations)
│   ├── ios-default.txt
│   ├── macos-default.txt
│   └── macos-tech.txt
└── scripts/                # DDM management scripts
    ├── ddm-upload-declarations.sh
    ├── ddm-create-sets.sh
    ├── ddm-assign-device.sh
    ├── ddm-bulk-assign.sh
    ├── ddm-force-sync.sh
    └── ddm-status.sh
```

### DDM Scripts

All scripts use environment variables from `/opt/nanohub/environment.sh`:

```bash
# Upload all declarations to server
/opt/nanohub/ddm/scripts/ddm-upload-declarations.sh

# Create sets from definition files
/opt/nanohub/ddm/scripts/ddm-create-sets.sh

# Assign set to device
/opt/nanohub/ddm/scripts/ddm-assign-device.sh <UDID> <set-name>

# Force device to sync DDM
/opt/nanohub/ddm/scripts/ddm-force-sync.sh <UDID>

# View DDM status
/opt/nanohub/ddm/scripts/ddm-status.sh all|declarations|sets|device <UDID>
```

### Admin Panel DDM Commands

| Command | Description |
|---------|-------------|
| DDM Status | View declarations, sets, or device enrollment status |
| Manage DDM Sets | Assign/remove DDM sets to devices |
| Upload Declarations | Upload all declarations to server |
| Create Sets | Create/update all DDM sets |

### DDM Database Tables (MySQL)

```sql
-- DDM declarations
SELECT * FROM declarations;

-- Set-declaration mappings
SELECT * FROM set_declarations;

-- Device-set assignments
SELECT * FROM enrollment_sets;

-- Declaration status from devices
SELECT * FROM status_declarations;

-- Status errors (for troubleshooting)
SELECT * FROM status_errors;
```

### Verifying DDM on Client

```bash
# Check MDM enrollment
profiles status -type enrollment

# View DDM logs
log show --predicate 'eventMessage CONTAINS "declaration" OR eventMessage CONTAINS "DDM"' --last 1h

# Note: DDM declarations don't appear in 'profiles show' - they're processed directly by system services
```

## Webhook HMAC Configuration (NEW in v3.0)

Secure webhook communication between NanoHUB and the webhook handler using HMAC-SHA256 signatures.

### Enable HMAC in NanoHUB Service

Edit `/etc/systemd/system/nanohub.service` and add the `-webhook-hmac-key` flag:

```bash
ExecStart=/usr/bin/docker run --rm --name nanohub \
    ... \
    -webhook-url http://localhost:5001/webhook \
    -webhook-hmac-key ${NANOHUB_WEBHOOK_SECRET}
```

Add environment variable:
```
Environment=NANOHUB_WEBHOOK_SECRET=your-64-char-hex-secret
```

### Configure Webhook Handler

Set the same secret in webhook service environment:

```bash
# /etc/systemd/system/nanohub-webhook.service
Environment=WEBHOOK_SECRET=your-64-char-hex-secret
```

Or in webhook.py via environment variable `WEBHOOK_SECRET`.

### How It Works

1. NanoHUB computes HMAC-SHA256 of the webhook request body
2. Signature is sent in `X-Hmac-Signature` header (Base64 encoded)
3. Flask webhook handler verifies signature before processing
4. Invalid signatures return 401 Unauthorized

### Generate Secret

```bash
# Generate 64-character hex secret
openssl rand -hex 32
```

### Verify HMAC is Working

```bash
# Check webhook log for security warnings
grep SECURITY /var/log/nanohub/webhook.log

# Test with invalid signature (should return 401)
curl -X POST http://localhost:5001/webhook \
  -H "X-Hmac-Signature: invalid" \
  -d '{"test": true}'
```

## Files Structure

```
/opt/nanohub/
├── backend_api/
│   ├── nanohub_web.py          # Main Flask web frontend
│   ├── nanohub_ldap_auth.py    # LDAP authentication module
│   ├── nanohub_admin_core.py   # Admin panel core (~5,665 lines)
│   ├── command_registry.py     # MDM command definitions
│   ├── config.py               # Centralized configuration (NEW in v2.2)
│   ├── db_utils.py             # Database utilities (NEW in v2.2)
│   ├── command_executor.py     # Command execution
│   ├── webhook_poller.py       # Webhook polling
│   ├── mdm-flask-api_wrappper.py # Legacy API wrapper
│   ├── manage_roles.py         # CLI tool for user role management (NEW in v3.0)
│   ├── nanohub_admin/          # Admin panel package (NEW in v3.0)
│   │   ├── __init__.py         # Package init, blueprint registration
│   │   ├── utils.py            # Shared utilities
│   │   └── routes/             # Route modules
│   │       ├── settings.py     # Settings page (~1,180 lines)
│   │       ├── reports.py      # Reports page (~1,933 lines)
│   │       ├── vpp.py          # VPP management (~1,700 lines)
│   │       └── devices.py      # Device inventory (~400 lines)
│   └── nanohub_environment     # Environment configuration
├── webhook/                    # Webhook server (NEW in v2.2)
│   └── webhook.py              # Flask webhook with DB writes
├── ddm/                        # Declarative Device Management
│   ├── declarations/           # DDM declaration JSON files
│   ├── sets/                   # Set definition files
│   └── scripts/                # DDM management scripts
├── profiles/                   # MDM configuration profiles (not in repo)
│   └── wireguard_configs/      # WireGuard VPN profiles (not in repo)
├── tools/
│   ├── api/commands/           # MDM command scripts
│   └── inventory_update.py     # Daily inventory cron script
├── environment.sh              # Environment variables (API keys, URLs)
└── venv/                       # Python virtual environment

/var/www/mdm-web/
├── index.html                  # Main dashboard
└── static/
    └── dashboard.css           # Stylesheet

/etc/systemd/system/
├── nanohub-web.service         # Web frontend service
├── nanohub-webhook.service     # Webhook server (NEW in v2.2)
└── mdm-flask-api.service       # Legacy API service
```

## Changelog

### Version 3.1 (2026-01-16)
- **DB-Driven New Device Installation**: Complete refactoring
  - Profiles loaded from `required_profiles` table based on manifest
  - Applications loaded from `required_applications` table
  - Wildcard profile options: Account (disabled/enabled/skip), Restrictions (standard/icloud/levelc/skip)
  - Dynamic application checkboxes loaded via AJAX when manifest selected
  - Optional WiFi profile installation
- **Manage Applications**: New admin command in Applications category
  - LIST: View all applications grouped by manifest
  - ADD: Create new application entry
  - EDIT: Two-step selection (manifest → app) for easier editing
  - REMOVE: Delete application from database
- **Required Profiles Table**: Extended schema
  - New columns: `profile_filename`, `install_order`, `is_optional`, `variant_group`
  - Supports wildcard profiles (account, restrictions variants)
- **Required Applications Table**: New table for app management
  - Links applications to manifests
  - Supports install order and optional flag
- **Manifest Filter Patterns**: Support for suffix patterns (`%-site`)
  - Enables restricting admin access to manifests ending with specific suffix
- **UX Improvements**:
  - Application selection uses table layout with checkboxes
  - Manifest dropdown shows "Select Manifest" placeholder
  - Two-step app selection in Manage Applications for cleaner UX

### Version 3.0 (2026-01-13)
- **Webhook HMAC Verification**: Secure webhook communication
  - NanoHUB signs outgoing webhooks with HMAC-SHA256
  - Flask webhook handler verifies `X-Hmac-Signature` header (Base64 encoded)
  - Configure with `-webhook-hmac-key` flag in NanoHUB service
- **Modular Admin Panel**: Major refactoring for maintainability
  - Split monolithic admin module into separate route blueprints
  - `nanohub_admin_core.py` (5,665 lines) - core functionality
  - `nanohub_admin/routes/` - modular route handlers
  - Total ~5,100 lines extracted into modules
- **Manifest Management**: Database-backed manifest system
  - New `manifests` table for persistent storage
  - CRUD operations via Settings page
  - Dynamic manifest dropdowns across all pages
- **User Role Management**: Database role overrides
  - New `user_roles` table for custom permissions
  - CLI tool `manage_roles.py` for administration
  - Override LDAP-derived roles per user
- **Code Cleanup**: Removed ~1,600 lines of legacy code
  - Consolidated duplicate functions
  - Improved error handling
  - Better separation of concerns

### Version 2.2 (2026-01-11)
- **Webhook DB Integration**: Direct database writes from webhook
  - Webhook writes device details directly to MySQL
  - Eliminates need for log parsing in admin panel
  - Real-time data availability after MDM response
- **Centralized Configuration**: New `config.py` module
  - All credentials loaded from environment variables
  - Single source of truth for DB, API, LDAP settings
  - Connection pooling via `db_utils.py`
- **Value Formatting**: Improved display of MDM data
  - Battery level: 0.8 → 80%
  - Storage capacity: 245.0 → 245.0 GB
  - Boolean values: True/False → Yes/No
- **New Backend Modules**:
  - `config.py` - Centralized configuration
  - `db_utils.py` - Database utilities with connection pooling
  - `command_executor.py` - Sanitized command execution
  - `webhook_poller.py` - Webhook log polling
- **Security Info Command**: Query device security status
- **Webhook Service**: New systemd service for webhook server
  - `nanohub-webhook.service`
  - Standalone Flask server on port 5001

### Version 2.1 (2026-01-10)
- **Device Detail Panel**: New comprehensive device information page
  - Tab interface: Info, Hardware, Security, Profiles, Apps, History
  - Quick actions: Lock, Restart, Erase from device page
  - Click hostname in device list to open detail page
- **Database Caching**: MDM data cached in MySQL (Jamf-style architecture)
  - `device_details` table with JSON columns for flexible storage
  - Cached hardware, security, profiles, apps data
  - Timestamps for each data type
- **Update Inventory Command**: Bulk inventory update in Commands > Device Control
  - OS filter (macOS/iOS only)
  - Manifest filter (dynamic list from database)
  - Last Updated filter (24h, 7d, never updated)
  - Select specific devices or use filters to update all matching
- **Daily Inventory Cron**: Automatic refresh at 14:00
  - Script: `/opt/nanohub/tools/inventory_update.py`
  - Updates all devices with hardware, security, profiles, apps data
- **Energy Saver Profile Fix**: Wake On LAN enabled for battery power

### Version 2.0 (2026-01-09)
- **VPP Panel**: New visual panel for VPP license management
  - App icons from iTunes API
  - Install/Remove apps directly from panel
  - License statistics and filtering
- **Command History**: MySQL-based command history
  - 90-day retention with automatic cleanup
  - Filtering by date, device, user, status
  - Detailed parameter logging
- **DDM Improvements**:
  - Fixed timestamp display in DDM status
  - Set assignment validation (check before remove)
- **ProfileList**: Shows actual profile list from device response
- **History Details**: Shows all command parameters and device hostname

### Version 1.9 (2026-01-09)
- DDM support with KMFDDM integration
- Bulk DDM operations
- Improved parallel execution

## Contributing

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open Pull Request

## License

MIT License - See LICENSE file for details.

## Acknowledgments

- Built on NanoMDM by micromdm
- DDM support via KMFDDM by jessepeterson
- Uses Flask web framework
- ldap3 for Active Directory authentication
- Frontend with vanilla JavaScript (no frameworks)
