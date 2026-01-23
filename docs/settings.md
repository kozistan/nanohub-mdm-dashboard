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

## Required Profiles

Define which profiles must be installed on devices for compliance checking.

**Admin Panel > Settings > Required Profiles**

### Adding Required Profile

| Field | Description |
|-------|-------------|
| Manifest | Target manifest (e.g., `default`, `tech`) |
| OS | `ios` or `macos` |
| Profile Name | Display name for reports |
| Profile Identifier | Bundle ID to match (e.g., `com.company.restrictions.profile`) |
| Wildcard | Enable pattern matching with `%` suffix |

### Pattern Matching

- **Exact match** (`match_pattern=0`): Profile identifier must match exactly
- **Wildcard** (`match_pattern=1`): Identifier ending with `%` matches any suffix

Example:
```
com.company.restrictions.profile%  →  matches:
  - com.company.restrictions.profile
  - com.company.restrictions.profile.levelc
  - com.company.restrictions.profile.icloudsync
```

### Internal: is_optional Column

The `required_profiles` table has an `is_optional` column not exposed in UI:

| is_optional | Purpose |
|-------------|---------|
| 0 | **Compliance check** - device must have this profile |
| 1 | **Installation only** - used for new device setup, not checked |

Records with `is_optional=1` are internal variant definitions for the installation wizard. They don't appear in compliance reports.

```sql
-- View all required profiles
SELECT manifest, os, profile_identifier, match_pattern, is_optional
FROM required_profiles
WHERE manifest = 'default' AND os = 'macos'
ORDER BY is_optional, profile_identifier;
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

## Authentication Methods

NanoHUB supports three authentication methods:

| Method | Description | Priority |
|--------|-------------|----------|
| **Google SSO** | OAuth 2.0 login via Google Workspace | Primary (when configured) |
| **LDAP/AD** | Active Directory domain login | Secondary |
| **Local User** | Fallback admin account (hdadmin) | Fallback |

### Google SSO (OAuth 2.0)

Single Sign-On via Google Workspace accounts.

**Setup:**

1. Create OAuth 2.0 credentials in [Google Cloud Console](https://console.cloud.google.com/)
   - APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID
   - Application type: Web application
   - Authorized redirect URI: `https://your-domain/login/google/callback`

2. Configure environment variables:
```bash
GOOGLE_CLIENT_ID=xxxxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-xxxxx
GOOGLE_ALLOWED_DOMAINS=slotegrator.space
GOOGLE_DEFAULT_ROLE=operator
```

3. Restart Flask service:
```bash
sudo systemctl restart mdm-flask-api
```

**Notes:**
- Google button appears on login page only when credentials are configured
- Users must have email in allowed domain (e.g., `@slotegrator.space`)
- Default role is `operator` (configurable via `GOOGLE_DEFAULT_ROLE`)
- Database role overrides work for Google users (same as LDAP)
- 2FA on Google account is handled automatically by Google

### LDAP/Active Directory

Domain authentication against Active Directory.

See LDAP Group Mapping section below for role configuration.

### Local Fallback User

Emergency access when AD is unavailable.

- Username: `hdadmin`
- Password hash set via `NANOHUB_LOCAL_ADMIN_HASH` environment variable
- Role: `admin` (full access)

Generate hash:
```bash
python3 -c "import hashlib; print(hashlib.sha256('hdadmin:YOUR_PASSWORD:nanohub-salt'.encode()).hexdigest())"
```

## Configuration Files

### Environment Variables

Primary configuration: `/opt/nanohub/backend_api/mdm_flask_api_environment`

```bash
# LDAP
LDAP_HOST_1=dc01.example.com
LDAP_HOST_2=dc02.example.com
LDAP_BIND_DN=CN=ldapadmin,OU=Admins,DC=example,DC=com
LDAP_BIND_PASSWORD=***
LDAP_BASE_DN=DC=example,DC=com

# Google OAuth SSO
GOOGLE_CLIENT_ID=xxxxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=***
GOOGLE_ALLOWED_DOMAINS=slotegrator.space
GOOGLE_DEFAULT_ROLE=operator

# Database
NANOHUB_DB_HOST=localhost
NANOHUB_DB_USER=nanohub
NANOHUB_DB_PASSWORD=***
NANOHUB_DB_NAME=nanohub

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
