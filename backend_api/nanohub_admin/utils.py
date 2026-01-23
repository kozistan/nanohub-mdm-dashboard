"""
NanoHUB Admin - Shared Utilities
================================
Common functions used across all admin modules.
"""

import os
import json
import logging
from datetime import datetime
from functools import wraps

from flask import session, redirect, url_for, request, jsonify

from config import Config
from db_utils import db

# Logging
logger = logging.getLogger('nanohub_admin')

# =============================================================================
# DECORATORS
# =============================================================================

def admin_required(f):
    """Require admin role"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login', next=request.url))
        if session['user'].get('role') not in ['admin', 'bel-admin']:
            return jsonify({'error': 'Admin access required'}), 403
        return f(*args, **kwargs)
    return decorated_function


def login_required_admin(f):
    """Require any authenticated user for admin panel"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'error': 'Session expired. Please log in again.'}), 401
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function


def role_required(min_role):
    """Require minimum role level"""
    role_hierarchy = {'admin': 4, 'bel-admin': 3, 'operator': 2, 'report': 1}

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user' not in session:
                return redirect(url_for('login', next=request.url))
            user_role = session['user'].get('role', '')
            if role_hierarchy.get(user_role, 0) < role_hierarchy.get(min_role, 0):
                return jsonify({'error': f'{min_role} access required'}), 403
            return f(*args, **kwargs)
        return decorated_function
    return decorator


# =============================================================================
# DEVICE ACCESS VALIDATION
# =============================================================================

def get_device_manifest(uuid_val):
    """Get the manifest for a device by UUID"""
    row = db.query_one(
        "SELECT manifest FROM device_inventory WHERE uuid = %s",
        (uuid_val,)
    )
    return row['manifest'] if row else None


def validate_device_access(uuid_val, user_info):
    """
    Validate if user has access to a device based on manifest filter.
    Returns True if access is allowed, False otherwise.
    """
    manifest_filter = user_info.get('manifest_filter')
    if not manifest_filter:
        return True  # No filter = full access

    device_manifest = get_device_manifest(uuid_val)
    if not device_manifest:
        return False  # Device not found

    # Convert SQL LIKE pattern to fnmatch pattern
    import fnmatch
    pattern = manifest_filter.replace('%', '*')
    return fnmatch.fnmatch(device_manifest, pattern)


def filter_devices_by_manifest(devices_list, manifest_filter):
    """Filter a list of devices by manifest pattern"""
    if not manifest_filter:
        return devices_list

    import fnmatch
    pattern = manifest_filter.replace('%', '*')
    return [d for d in devices_list if fnmatch.fnmatch(d.get('manifest', ''), pattern)]


# =============================================================================
# AUDIT LOGGING
# =============================================================================

def audit_log(user, action, command=None, params=None, result=None, success=True, execution_time_ms=None):
    """Log admin actions to audit log file"""
    try:
        log_dir = os.path.dirname(Config.AUDIT_LOG_PATH)
        if not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)

        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'user': user,
            'action': action,
            'command': command,
            'params': params,
            'result': result[:500] if result and len(result) > 500 else result,
            'success': success,
            'execution_time_ms': execution_time_ms,
            'ip': request.remote_addr if request else None,
        }

        with open(Config.AUDIT_LOG_PATH, 'a') as f:
            f.write(json.dumps(log_entry) + '\n')
    except Exception as e:
        logger.error(f"Failed to write audit log: {e}")


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_user_info():
    """Get current user info from session"""
    return session.get('user', {})


def get_manifest_filter():
    """Get manifest filter for current user"""
    return session.get('user', {}).get('manifest_filter')


def can_access(user_role, required_role):
    """Check if user role can access a resource requiring a specific role"""
    role_hierarchy = {'admin': 4, 'bel-admin': 3, 'operator': 2, 'report': 1}
    return role_hierarchy.get(user_role, 0) >= role_hierarchy.get(required_role, 0)


def format_datetime(dt, format='%Y-%m-%d %H:%M'):
    """Format datetime object to string"""
    if not dt:
        return '-'
    if isinstance(dt, str):
        return dt
    return dt.strftime(format)


def sanitize_param(value):
    """Sanitize command parameter to prevent injection"""
    if value is None:
        return ''
    value = str(value)
    # Remove dangerous characters
    dangerous = ['`', '$', '|', ';', '&', '>', '<', '\n', '\r']
    for char in dangerous:
        value = value.replace(char, '')
    return value.strip()


# =============================================================================
# NAVIGATION HELPER
# =============================================================================

def get_nav_items(current_page=''):
    """Get navigation items with active state"""
    items = [
        {'url': '/admin', 'label': 'Commands', 'id': 'commands'},
        {'url': '/admin/devices', 'label': 'Devices', 'id': 'devices'},
        {'url': '/admin/profiles', 'label': 'Profiles', 'id': 'profiles'},
        {'url': '/admin/vpp', 'label': 'VPP', 'id': 'vpp'},
        {'url': '/admin/reports', 'label': 'Reports', 'id': 'reports'},
        {'url': '/admin/history', 'label': 'History', 'id': 'history'},
    ]
    for item in items:
        item['active'] = item['id'] == current_page
    return items
