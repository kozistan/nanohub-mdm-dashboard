# Database Schema

MySQL database structure for NanoHUB MDM Dashboard.

## Connection

```python
from config import Config
import mysql.connector

conn = mysql.connector.connect(**Config.DB)
```

Or direct:
```bash
mysql -h localhost -u nanohub -p nanohub
```

## Connection Pool

NanoHUB uses connection pooling for better performance under load.

| Parameter | Value | Description |
|-----------|-------|-------------|
| `DB_POOL_SIZE` | 25 | Max concurrent connections |
| `DB_POOL_NAME` | nanohub_pool | Pool identifier |
| `DB_POOL_RESET_SESSION` | True | Reset session state on return |

Configuration in `/opt/nanohub/backend_api/config.py`:

```python
DB_POOL_NAME = 'nanohub_pool'
DB_POOL_SIZE = 25
DB_POOL_RESET_SESSION = True
```

**Note:** Pool size was increased from 10 to 25 to handle concurrent operations (bulk updates + frontend requests).

## Tables

### device_inventory

Primary device registry.

```sql
CREATE TABLE device_inventory (
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
```

### device_details

Cached MDM data (hardware, security, profiles, apps).

```sql
CREATE TABLE device_details (
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
```

### command_history

Command execution log with 90-day retention.

```sql
CREATE TABLE command_history (
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
    INDEX idx_user (user),
    INDEX idx_command_id (command_id)
);
```

### admin_audit_log

Admin action audit trail.

```sql
CREATE TABLE admin_audit_log (
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
```

### manifests

Device group definitions.

```sql
CREATE TABLE manifests (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(255),
    INDEX idx_name (name)
);
```

### user_roles

User role overrides.

```sql
CREATE TABLE user_roles (
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
```

### required_profiles

Profiles required for each manifest (used by New Device Installation).

```sql
CREATE TABLE required_profiles (
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
```

**Columns:**
- `profile_filename` - Actual filename if different from identifier
- `install_order` - Installation sequence (lower = first)
- `is_optional` - 1 = optional profile (WiFi, FileVault, etc.)
- `variant_group` - For wildcard profiles: 'account', 'restrictions'

### required_applications

Applications for device installation (used by New Device Installation).

```sql
CREATE TABLE required_applications (
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

**Usage:**
- Applications are loaded dynamically in New Device Installation based on selected manifest
- Managed via Admin Panel > Applications > Manage Applications

## DDM Tables (KMFDDM)

### declarations

DDM declaration definitions.

### set_declarations

Mapping of declarations to sets.

### enrollment_sets

Device-to-set assignments.

### status_declarations

Declaration status reported by devices.

### status_errors

Declaration errors from devices.

## Common Queries

### Device Overview

```sql
SELECT
    di.hostname,
    di.serial,
    di.os,
    di.manifest,
    dd.hardware_updated_at,
    dd.apps_updated_at
FROM device_inventory di
LEFT JOIN device_details dd ON di.uuid = dd.uuid
ORDER BY di.hostname;
```

### Devices Never Updated

```sql
SELECT di.hostname, di.uuid
FROM device_inventory di
LEFT JOIN device_details dd ON di.uuid = dd.uuid
WHERE dd.hardware_data IS NULL;
```

### Recent Failed Commands

```sql
SELECT timestamp, user, command_name, device_hostname, result_summary
FROM command_history
WHERE success = 0
ORDER BY timestamp DESC
LIMIT 20;
```

### Storage Low Devices

```sql
SELECT
    di.hostname,
    JSON_UNQUOTE(JSON_EXTRACT(dd.hardware_data, '$.available_capacity')) as available
FROM device_inventory di
JOIN device_details dd ON di.uuid = dd.uuid
WHERE dd.hardware_data IS NOT NULL;
```

## Maintenance

### Cleanup Old History

Automatic via cron, or manual:

```sql
DELETE FROM command_history
WHERE timestamp < DATE_SUB(NOW(), INTERVAL 90 DAY);
```

### Optimize Tables

```sql
OPTIMIZE TABLE device_inventory, device_details, command_history;
```

### Backup

```bash
mysqldump -u nanohub -p nanohub > nanohub_backup.sql
```
