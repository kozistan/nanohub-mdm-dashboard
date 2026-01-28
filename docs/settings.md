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

## Local User Management

Database-backed local user accounts for authentication when LDAP/SSO is unavailable.

**Admin Panel > Settings > Users**

### Default Admin

On first startup, a default local user is created automatically:
- **Username:** `admin`
- **Password:** `password`
- **Role:** `admin`
- **Must change password:** Yes (forced on first login)

### Add Local User

| Field | Description |
|-------|-------------|
| Username | Unique login name (lowercase) |
| Display Name | Full name (optional) |
| Password | Minimum 6 characters |
| Role | admin, bel-admin, operator, report |
| Manifest Filter | SQL LIKE pattern for device filtering (optional) |
| Notes | Optional description |
| Force PW change | User must change password on next login |

### Password Management

- **Change Password** - Users can change their own password at `/change-password`
- **Forced Change** - When `must_change_password` is set, user is redirected to change password before accessing any page
- **Admin Reset** - Admins can reset any user's password from Settings > Users (sets forced change)
- **Password hash** - SHA256 of `username:password:nanohub-salt`

### Emergency Fallback

If the database is completely unavailable, an emergency fallback user `admin` / `password` is hardcoded for recovery access. This only activates when DB authentication fails entirely.

### Database Table

`local_users` - auto-created on startup. See [Database Schema](database) for details.

## Users Role Overrides

Override roles for LDAP and Google SSO users. The override takes precedence over the role derived from AD group membership or SSO default.

**Admin Panel > Settings > Users**

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
| bel-admin | Full access, filtered by manifest |
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
python manage_roles.py add username bel-admin --manifest "%-bel"

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
| **Local Users** | Database-backed local accounts | First (always available) |
| **LDAP/AD** | Active Directory domain login | Second |
| **Google SSO** | OAuth 2.0 login via Google Workspace | Primary button (when configured) |

Authentication order on login: local users are checked first, then LDAP. Google SSO uses a separate button/flow.

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

### Local Users (Database)

Database-backed local accounts managed via Settings > Users.

- Default user: `admin` / `password` (forced password change on first login)
- Supports multiple local users with different roles
- Password stored as SHA256 hash in `local_users` table
- See [Local User Management](#local-user-management) section above for details

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
# Secrets directory
chmod 700 /opt/nanohub/secrets
chmod 600 /opt/nanohub/secrets/*.env

# Environment file
chmod 600 /opt/nanohub/environment.sh

# Backend files
chmod 755 /opt/nanohub/backend_api/*.py
```

## Secrets Management

**IMPORTANT:** No password or token should ever be hardcoded in configuration files or systemd service files.

### Structure

```
/opt/nanohub/
├── environment.sh          # Primary credential source (sourced by scripts)
└── secrets/                # Docker env files (chmod 700)
    ├── mysql.env           # MYSQL_ROOT_PASSWORD, MYSQL_USER, etc.
    ├── nanohub.env         # NANOHUB_STORAGE_DSN, NANOHUB_API_KEY
    └── nanodep.env         # NANODEP_STORAGE_DSN, NANODEP_API
```

### Rules

| What | Where | How |
|------|-------|-----|
| DB passwords | `environment.sh`, `secrets/*.env` | Never in service files |
| API keys | `environment.sh`, `secrets/*.env` | Never in git |
| Tokens (VPP, Telegram) | `environment.sh` | Environment variables only |

### Systemd Services

Services use `--env-file` instead of hardcoded values:

```ini
# Correct
ExecStart=/usr/bin/docker run --env-file /opt/nanohub/secrets/nanohub.env ...

# Wrong (password visible in ps aux)
ExecStart=/usr/bin/docker run ... -storage-dsn "user:password@tcp(...)"
```

### Scripts

Bash scripts read from `environment.sh`:

```bash
#!/bin/bash
source /opt/nanohub/environment.sh
mysql -h "$DB_HOST" -u "$DB_USER" -p"$DB_PASSWORD" "$DB_NAME" -e "..."
```

### After Changing a Password

1. Update `/opt/nanohub/environment.sh`
2. Regenerate secrets files:
   ```bash
   source /opt/nanohub/environment.sh
   cat > /opt/nanohub/secrets/nanohub.env << EOF
   NANOHUB_STORAGE_DSN=${DB_USER}:${DB_PASSWORD}@tcp(127.0.0.1:3306)/${DB_NAME}?parseTime=true
   NANOHUB_API_KEY=${NANOHUB_API_KEY}
   NANOHUB_WEBHOOK_HMAC_KEY=${NANOHUB_API_KEY}
   EOF
   chmod 600 /opt/nanohub/secrets/*.env
   ```
3. Restart services:
   ```bash
   sudo systemctl restart nanohub nanodep mdm-flask-api
   ```

### Git Security

**Never add to git:**
- `/opt/nanohub/environment.sh`
- `/opt/nanohub/secrets/`
- Any file containing real passwords

These items are listed in `.gitignore`.
