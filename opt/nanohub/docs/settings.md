# Settings

Configuration and administration settings.

## Access

**Admin Panel > Settings** or `/admin/settings`

## Manifest Management

Manifests are device groups used for filtering and organization.

### View Manifests

List of all configured manifests with device counts.

### Add Manifest

Create new manifest:
- **Name** - Unique identifier (e.g., `site-a`, `department-it`)
- **Description** - Optional description

### Edit Manifest

Modify manifest description.

### Delete Manifest

Remove manifest (only if no devices assigned).

### Assign Devices

Bulk assign devices to manifest:
1. Select manifest from dropdown
2. Select devices
3. Apply assignment

## User Role Management

Override LDAP-derived roles for specific users.

### View Users

List of users with role overrides:
- Username
- Role
- Manifest filter (for restricted roles)
- Active status

### Add Role Override

```
Username: john.doe
Role: operator
Manifest Filter: site-a (optional)
```

### Roles

| Role | Permissions |
|------|-------------|
| admin | Full access to all devices |
| restricted-admin | Full access, filtered by manifest |
| operator | Device management, profiles, apps |
| report | Read-only access |

### CLI Tool

```bash
cd /opt/nanohub/backend_api
source /opt/nanohub/venv/bin/activate

# List all role overrides
python manage_roles.py list

# Add role override
python manage_roles.py add username admin

# Add with manifest filter
python manage_roles.py add username restricted-admin --manifest "site-%"

# Remove override
python manage_roles.py remove username

# Deactivate user
python manage_roles.py deactivate username
```

## Database Tables

### Manifests

```sql
SELECT * FROM manifests;

-- Add manifest
INSERT INTO manifests (name, description, created_by)
VALUES ('site-b', 'Site B devices', 'admin');
```

### User Roles

```sql
SELECT * FROM user_roles;

-- Add role override
INSERT INTO user_roles (username, role, manifest_filter)
VALUES ('john.doe', 'operator', NULL);
```

## Configuration Files

### Environment Variables

Primary configuration: `/opt/nanohub/backend_api/nanohub_environment`

```bash
# LDAP
LDAP_HOST=dc01.example.com
LDAP_BIND_DN=CN=ldapadmin,OU=Admins,DC=example,DC=com
LDAP_BIND_PASSWORD=***
LDAP_BASE_DN=DC=example,DC=com

# Database
DB_HOST=localhost
DB_USER=nanohub
DB_PASSWORD=***
DB_NAME=nanohub

# Flask
FLASK_SECRET_KEY=***
```

### Centralized Config

`/opt/nanohub/backend_api/config.py` - Python configuration class with environment variable support.

### LDAP Group Mapping

`/opt/nanohub/backend_api/nanohub_ldap_auth.py`:

```python
GROUP_ROLE_MAPPING = {
    'it': 'admin',
    'mdm-admin': 'admin',
    'mdm-restricted-admin': 'restricted-admin',
    'mdm-operator': 'operator',
    'mdm-report': 'report',
}
```

## Security Settings

### Session Lifetime

Default: 8 hours (configurable in `config.py`)

### Webhook HMAC

Enable in NanoHUB service with `-webhook-hmac-key` flag.

Set `WEBHOOK_SECRET` environment variable to match.

### File Permissions

```bash
# Environment file (contains secrets)
chmod 600 /opt/nanohub/backend_api/nanohub_environment

# Backend files
chmod 755 /opt/nanohub/backend_api/*.py
```
