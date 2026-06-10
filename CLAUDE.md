# NanoHUB MDM Dashboard

Web-based management dashboard for Apple MDM (Mobile Device Management) using NanoMDM backend with LDAP authentication and role-based access control.

## Quick Reference

```bash
# Aktivace prostředí
source /opt/nanohub/venv/bin/activate

# Restart služeb
sudo systemctl restart nanohub-web mdm-flask-api nanohub-webhook nginx

# Logy
journalctl -u nanohub-web -f
journalctl -u mdm-flask-api -f
tail -f /var/log/nanohub/webhook.log

# Test databáze
mysql -h localhost -u nanohub -p nanohub -e "SELECT 1"
```

## Statické soubory (CSS, JS)

**DŮLEŽITÉ:** Nginx servíruje statické soubory z `/var/www/mdm-web/static/`, NE z `/opt/nanohub/backend_api/static/`!

Po úpravě CSS/JS souborů je nutné je zkopírovat:
```bash
sudo cp /opt/nanohub/backend_api/static/css/admin.css /var/www/mdm-web/static/css/admin.css
sudo systemctl restart nginx
```

## Git Repository

**GitHub:** https://github.com/kozistan/nanohub-mdm-dashboard
**Lokální repo:** `/opt/nanohub/git-repo/`
**Produkční deployment:** `/opt/nanohub/`

### Struktura repozitáře
```
/opt/nanohub/git-repo/
├── backend_api/              # Flask aplikace (kopíruje se do /opt/nanohub/)
├── tools/                    # Utility scripts
├── docs/                     # Dokumentace
├── etc/                      # Systemd service files, nginx config
├── var/                      # Log directory templates
├── screenshots/              # UI screenshots pro README
├── README.md                 # Hlavní dokumentace
├── DEPLOYMENT_CHECKLIST.md   # Deployment postup
├── requirements.txt          # Python dependencies
└── .gitignore
```

### Workflow: Po každé úpravě kódu

**POVINNÉ KROKY po dokončení změn:**

1. **Zkopírovat změněné soubory do git-repo:**
   ```bash
   # Příklad pro backend_api
   cp -r /opt/nanohub/backend_api/* /opt/nanohub/git-repo/backend_api/

   # Příklad pro tools
   cp -r /opt/nanohub/tools/* /opt/nanohub/git-repo/tools/

   # Příklad pro docs
   cp -r /opt/nanohub/docs/* /opt/nanohub/git-repo/docs/
   ```

2. **Připravit commit:**
   ```bash
   cd /opt/nanohub/git-repo
   git status
   git diff
   git add <změněné soubory>
   git commit -m "Popis změny"
   ```

3. **Push (volitelně, na vyžádání):**
   ```bash
   git push origin main
   ```

### Commit pravidla

- **NIKDY nepřidávat** poznámky o AI/Claude kooperaci do commit messages
- Commit messages psát stručně a věcně
- Formát: `[oblast] Popis změny` např. `[vpp] Add license expiration warning`
- Nepushovat automaticky - pouze na explicitní požádání uživatele

### Synchronizace production ↔ repo

| Směr | Kdy | Příkaz |
|------|-----|--------|
| repo → production | Po pull z GitHubu | `cp -r git-repo/backend_api/* backend_api/` |
| production → repo | Po lokálních změnách | `cp -r backend_api/* git-repo/backend_api/` |

## Údržba dokumentace

**POVINNÉ: Po každé změně dokumentace v `/opt/nanohub/docs/` aktualizovat tento CLAUDE.md soubor, aby informace zůstaly konzistentní.**

Kontrolovat zejména:
- Nové/změněné sekce v docs/*.md
- Změny v API endpoints
- Nové příkazy nebo funkce
- Změny v databázovém schématu

## Technology Stack

- **Python 3.8+** + Flask 3.0.0
- **MySQL/MariaDB** s connection pooling (25 spojení)
- **LDAP/AD** + Google OAuth 2.0 autentizace
- **NanoMDM** backend API (port 9004)
- **Bootstrap** frontend

## Project Structure

```
/opt/nanohub/
├── backend_api/                 # Hlavní Flask aplikace
│   ├── nanohub_web.py          # Entry point (port 9007)
│   ├── config.py               # Centralizovaná konfigurace
│   ├── db_utils.py             # Database manager s poolingem
│   ├── command_registry.py     # MDM command definice
│   ├── nanohub_ldap_auth.py    # LDAP/SSO autentizace
│   ├── manage_roles.py         # CLI pro správu rolí
│   └── nanohub_admin/          # Modular admin package
│       ├── core.py             # Shared utilities
│       ├── commands.py         # Command handlers
│       ├── utils.py            # Decorators (@login_required, @role_required)
│       └── routes/             # Feature blueprints
│           ├── dashboard.py    # Commands & execution
│           ├── devices.py      # Device inventory
│           ├── reports.py      # Statistics
│           ├── vpp.py          # App management
│           ├── ddm.py          # DDM management
│           └── settings.py     # Configuration
├── webhook/                     # Webhook event handler (port 5001)
├── tools/
│   ├── api/commands/           # 30+ MDM command scripts
│   ├── inventory_update.py     # Daily device refresh
│   └── queue_cleanup.py        # MDM queue maintenance
├── ddm/declarations/           # DDM JSON konfigurace
├── profiles/                   # MDM profiles (~80 souborů)
├── data/                       # App manifests (apps_ios.json, apps_macos.json)
├── docs/                       # Dokumentace (10 .md souborů)
├── environment.sh              # API keys, credentials (secrets)
└── venv/                       # Python virtual environment
```

## Code Conventions

### Flask Patterns
- **Blueprint pattern** pro modularitu - každá feature v `routes/`
- **Inline templates** - `render_template_string()` místo template souborů
- **Lazy imports** - předcházení circular dependencies s `get_admin_blueprint()`

### Database Access
```python
# Vždy používat db_utils.py s poolingem
from db_utils import DatabaseManager
db = DatabaseManager()

# Parameterized queries - NIKDY string concatenation
db.query_all("SELECT * FROM devices WHERE manifest = %s", (manifest,))
db.execute("INSERT INTO audit_log (user, action) VALUES (%s, %s)", (user, action))

# Context manager pro transakce
with db.transaction():
    db.execute(...)
```

### Authentication Decorators
```python
from nanohub_admin.utils import login_required, role_required, admin_required

@login_required           # Vyžaduje přihlášení
@role_required('admin')   # Vyžaduje konkrétní roli
@admin_required()         # Vyžaduje admin+ roli
```

### Error Handling
- Try/catch s audit logováním
- User-friendly error messages
- HTTP error handlers v nanohub_web.py (403, 404)

## Database Schema

### Core Tables
| Table | Purpose |
|-------|---------|
| `device_inventory` | Device registry (uuid, serial, hostname, manifest, os) |
| `device_details` | Cached MDM data jako JSON |
| `command_history` | Command execution log (90-day retention) |
| `admin_audit_log` | Admin action trail |
| `user_roles` | Role overrides (LDAP/SSO) |
| `local_users` | Local user accounts (DB-backed auth) |
| `manifests` | Device groups |
| `required_profiles` | Compliance profiles |
| `required_applications` | Required apps |

### DDM Tables (KMFDDM)
- `declarations`, `declaration_sets`, `set_declarations`
- `ddm_required_sets`, `status_declarations`, `status_errors`

## Role-Based Access Control

### LDAP Group Mapping
```python
GROUP_ROLE_MAPPING = {
    'it': 'admin',
    'mdm-admin': 'admin',
    'mdm-restricted-admin': 'restricted-admin',
    'mdm-operator': 'operator',
    'mdm-report': 'report',
}
```

### Permissions
| Role | Devices | Commands | Settings |
|------|---------|----------|----------|
| admin | All | Full | Full |
| restricted-admin | Filtered | Full | Limited |
| operator | Filtered | Full | No |
| report | Filtered | Read-only | No |

## Common Tasks

### Přidání nového MDM příkazu
1. Vytvořit script v `/opt/nanohub/tools/api/commands/`
2. Přidat do `COMMANDS` dict v `command_registry.py`
3. Vytvořit handler v `nanohub_admin/commands.py`

### Přidání nové admin stránky
1. Vytvořit `routes/newfeature.py` s Blueprint
2. Registrovat v `nanohub_admin/__init__.py` → `register_routes()`
3. Přidat DB tables pokud potřeba

### User Role Management
```bash
# List all overrides
python /opt/nanohub/backend_api/manage_roles.py list

# Add restricted admin
python /opt/nanohub/backend_api/manage_roles.py add john.doe restricted-admin --manifest "site-%"

# Remove override
python /opt/nanohub/backend_api/manage_roles.py remove john.doe
```

## API Endpoints

### Web Frontend (port 9007)
- `GET /admin` - Commands dashboard
- `GET /admin/device/<uuid>` - Device detail
- `GET /admin/vpp` - VPP management
- `GET /admin/reports` - Reports & statistics
- `POST /admin/execute` - Execute command
- `GET /admin/api/reports/data` - Report data (AJAX)

### Legacy API (port 9006)
- `GET /api/devices.json` - List devices
- `POST /api/device-search` - Search device

### Webhook (port 5001)
- `POST /webhook` - MDM events (HMAC verified)

## Environment Variables

```bash
# Database
NANOHUB_DB_HOST, NANOHUB_DB_PORT, NANOHUB_DB_USER, NANOHUB_DB_PASSWORD, NANOHUB_DB_NAME

# MDM API
NANOHUB_URL, NANOHUB_API_KEY

# LDAP
LDAP_HOST_1, LDAP_HOST_2, LDAP_BIND_DN, LDAP_BIND_PASSWORD, LDAP_BASE_DN

# Google OAuth
GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_ALLOWED_DOMAINS

# VPP
VPP_TOKEN

# Telegram Notifications
TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
```

## Cron Jobs

```bash
# Daily inventory update (14:00)
0 14 * * * /opt/nanohub/venv/bin/python /opt/nanohub/tools/inventory_update.py

# VPP app update (03:00 workdays)
0 3 * * 1-5 /opt/nanohub/tools/api/commands/update_vpp_from_db
```

## Troubleshooting

### Service Issues
```bash
systemctl status nanohub-web mdm-flask-api nanohub-webhook
journalctl -u nanohub-web --since "1 hour ago"
```

### Database Issues
```bash
mysql -u nanohub -p nanohub -e "SHOW PROCESSLIST"
mysql -u nanohub -p nanohub -e "SELECT COUNT(*) FROM device_inventory"
```

### LDAP Testing
```python
cd /opt/nanohub/backend_api
source /opt/nanohub/venv/bin/activate
python3 -c "from nanohub_ldap_auth import test_ldap_connection; test_ldap_connection()"
```

## Security Notes

### Secrets Management
- **NIKDY** hardcoded hesla v service souborech nebo skriptech
- Hlavní zdroj credentials: `/opt/nanohub/environment.sh` (chmod 600)
- Docker secrets: `/opt/nanohub/secrets/*.env` (chmod 600, adresář chmod 700)
- Systemd služby používají `--env-file` místo `-storage-dsn "user:pass@..."`
- Skripty používají `source /opt/nanohub/environment.sh` + `$DB_PASSWORD`

### Secrets struktura
```
/opt/nanohub/secrets/
├── mysql.env      # MYSQL_ROOT_PASSWORD, MYSQL_USER, MYSQL_PASSWORD
├── nanohub.env    # NANOHUB_STORAGE_DSN, NANOHUB_API_KEY
└── nanodep.env    # NANODEP_STORAGE_DSN, NANODEP_API
```

### Obecné
- HTTPS/SSL přes nginx reverse proxy
- HMAC-SHA256 webhook verification
- Prepared statements pro SQL injection prevention
- 90-day audit log retention

## Documentation

Podrobná dokumentace v `/opt/nanohub/docs/`:
- `index.md` - Architecture overview
- `commands.md` - MDM command reference
- `database.md` - Schema, queries, maintenance
- `ddm.md` - Declarative Device Management
- `vpp.md` - Volume Purchase Program
- `troubleshooting.md` - Common issues & solutions
