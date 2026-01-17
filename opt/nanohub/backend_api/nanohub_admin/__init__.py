"""
NanoHUB Admin Panel - Modular Package
======================================

This package provides the admin panel functionality.
Routes are organized into separate modules under routes/.

Structure:
- routes/settings.py - Settings page and configuration
- routes/reports.py  - Reports and statistics (TODO)
- routes/vpp.py      - VPP/App management (TODO)
- routes/devices.py  - Device management (TODO)
- routes/commands.py - Command execution (TODO)
"""

# Import the admin blueprint from the core module
from nanohub_admin_core import admin_bp

# Import and register route modules
from .routes.settings import settings_bp
from .routes.reports import reports_bp
from .routes.vpp import vpp_bp
from .routes.devices import devices_bp
from .routes.help import help_bp
admin_bp.register_blueprint(settings_bp)
admin_bp.register_blueprint(reports_bp)
admin_bp.register_blueprint(vpp_bp)
admin_bp.register_blueprint(devices_bp)
admin_bp.register_blueprint(help_bp)

# Re-export commonly used items from utils
from .utils import (
    admin_required,
    login_required_admin,
    audit_log,
    validate_device_access,
    can_access,
    get_manifest_filter,
)

__all__ = [
    'admin_bp',
    'admin_required',
    'login_required_admin',
    'audit_log',
    'validate_device_access',
    'can_access',
    'get_manifest_filter',
]
