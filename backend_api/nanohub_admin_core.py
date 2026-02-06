"""
NanoHUB Admin Panel - Blueprint Registration
=============================================

This module defines the main admin_bp Blueprint and registers all route modules.

Routes are organized in separate files under nanohub_admin/routes/:
- dashboard.py  - Commands dashboard, command execution (/admin, /admin/command/*)
- devices.py    - Device inventory and detail pages
- profiles.py   - Profile management
- settings.py   - Admin settings
- reports.py    - Reports and statistics
- vpp.py        - VPP/App management
- ddm.py        - Declarative Device Management
- history.py    - Command execution history
- help.py       - Help documentation

Shared utilities are in:
- nanohub_admin/core.py     - Device data, MDM queries, shared functions
- nanohub_admin/commands.py - Command execution logic
- nanohub_admin/utils.py    - Authentication decorators, helpers
"""

from flask import Blueprint
from db_utils import app_settings

# Create the main admin Blueprint
admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


@admin_bp.context_processor
def inject_logo():
    """Inject current logo path into all admin templates."""
    try:
        current_logo = app_settings.get('header_logo', '/static/logos/slotegrator_green.png')
        return {'current_logo': current_logo}
    except Exception:
        return {'current_logo': '/static/logos/slotegrator_green.png'}


# Register all route blueprints
from nanohub_admin import register_routes
register_routes()
