# NanoHUB MDM Dashboard - Help

Web-based management dashboard for Apple MDM with LDAP authentication.

## Quick Navigation

| Section | Description |
|---------|-------------|
| [Commands](commands) | MDM commands reference |
| [DDM](ddm) | Declarative Device Management |
| [VPP](vpp) | Volume Purchase Program & Apps |
| [Devices](devices) | Device inventory management |
| [Reports](reports) | Statistics and reporting |
| [Settings](settings) | Configuration and user roles |
| [Database](database) | Database schema reference |
| [Scripts](scripts) | CLI tools and automation |
| [Troubleshooting](troubleshooting) | Common issues and solutions |

## Architecture Overview

```
┌─────────────────┐         ┌──────────────────┐         ┌─────────────────┐
│  Web Frontend   │────────>│  Flask Web       │────────>│   NanoMDM       │
│  (HTML/CSS/JS)  │         │  (nanohub_web)   │         │   Backend       │
└─────────────────┘         └──────────────────┘         └─────────────────┘
        │                           │
        │                   ┌───────┴───────┐
        │                   │               │
        v                   v               v
┌─────────────────┐  ┌─────────────┐  ┌─────────────┐
│  Admin Panel    │  │   LDAP/AD   │  │   MySQL     │
│  (nanohub_admin)│  │   Auth      │  │   Database  │
└─────────────────┘  └─────────────┘  └─────────────┘
```

### Admin Panel Modules

```
nanohub_admin_core.py          # Blueprint registration only (~43 lines)
nanohub_admin/
├── __init__.py                # register_routes() - blueprint registration
├── core.py                    # Shared functions (device data, audit, VPP)
├── commands.py                # Command execution handlers
├── profiles.py                # Profile management
├── utils.py                   # Decorators (login_required, admin_required)
└── routes/                    # Feature blueprints
    ├── dashboard.py           # Commands page, command execution
    ├── history.py             # Command execution history
    ├── devices.py             # Device list & detail
    ├── settings.py            # Admin settings
    ├── reports.py             # Statistics and reports
    ├── vpp.py                 # VPP/App management
    ├── ddm.py                 # Declarative Device Management
    └── help.py                # Help documentation
```

## Role-Based Access Control

| AD Group | Role | Access |
|----------|------|--------|
| `it` | admin | Full access to all devices |
| `mdm-admin` | admin | Full access to all devices |
| `mdm-restricted-admin` | restricted-admin | Full access, filtered by manifest |
| `mdm-operator` | operator | Device management, profiles, apps |
| `mdm-report` | report | Read-only access |

## Key Features

- **Multi-Auth** - Local users, LDAP/AD, and Google SSO with role-based access
- **Local User Management** - Database-backed users with forced password change
- **Real-time Status** - Online/Active/Offline device indicators
- **Parallel Execution** - 10-20x faster bulk operations
- **DDM Support** - Declarative Device Management with KMFDDM
- **VPP Management** - App license management and deployment
- **Webhook HMAC** - Secure webhook verification
