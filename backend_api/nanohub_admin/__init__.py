"""
NanoHUB Admin Panel - Modular Package
======================================

This package provides the admin panel functionality.
Routes are organized into separate modules under routes/.

Structure:
- routes/dashboard.py - Commands dashboard and command execution
- routes/settings.py  - Settings page and configuration
- routes/reports.py   - Reports and statistics
- routes/vpp.py       - VPP/App management
- routes/devices.py   - Device inventory list
- routes/ddm.py       - Declarative Device Management
- routes/help.py      - Help documentation
- routes/history.py   - Command execution history
- profiles.py         - Profile management routes
- nanohub_admin_core.py - Blueprint registration (minimal)
- core.py - Shared utility functions (device data, MDM queries, etc.)
"""

# Import shared functions from core module (no circular dependency)
from .core import (
    execute_device_query,
    audit_log,
    validate_device_access,
    get_device_info_for_uuid,
    get_device_details,
    get_devices_list,
    get_devices_full,
)

# Re-export commonly used items from utils
from .utils import (
    admin_required,
    login_required_admin,
    can_access,
    get_manifest_filter,
)


def get_admin_blueprint():
    """Lazy import of admin_bp to avoid circular imports.

    Use this function when you need admin_bp outside of nanohub_admin_core.
    """
    from nanohub_admin_core import admin_bp
    return admin_bp


def register_routes():
    """Register all route blueprints with admin_bp.

    Called after nanohub_admin_core is fully initialized.
    """
    from nanohub_admin_core import admin_bp
    from .routes.dashboard import dashboard_bp
    from .routes.settings import settings_bp
    from .routes.reports import reports_bp
    from .routes.vpp import vpp_bp
    from .routes.devices import devices_bp
    from .routes.help import help_bp
    from .routes.ddm import ddm_bp
    from .routes.history import history_bp
    from .profiles import profiles_bp

    admin_bp.register_blueprint(dashboard_bp)
    admin_bp.register_blueprint(settings_bp)
    admin_bp.register_blueprint(reports_bp)
    admin_bp.register_blueprint(vpp_bp)
    admin_bp.register_blueprint(devices_bp)
    admin_bp.register_blueprint(help_bp)
    admin_bp.register_blueprint(ddm_bp)
    admin_bp.register_blueprint(history_bp)
    admin_bp.register_blueprint(profiles_bp)


__all__ = [
    'execute_device_query',
    'admin_required',
    'login_required_admin',
    'audit_log',
    'validate_device_access',
    'can_access',
    'get_manifest_filter',
    'get_admin_blueprint',
    'register_routes',
]
