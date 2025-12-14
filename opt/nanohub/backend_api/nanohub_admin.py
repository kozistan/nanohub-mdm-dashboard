"""
NanoHUB Admin Panel
Web interface for MDM command execution
"""

import os
import subprocess
import json
import logging
import uuid
import time
from datetime import datetime
from functools import wraps
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import Blueprint, render_template_string, session, redirect, url_for, request, jsonify

from command_registry import (
    COMMANDS, CATEGORIES, COMMANDS_DIR, PROFILE_DIRS,
    get_commands_by_category, get_command, get_available_profiles, check_role_permission
)

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('nanohub_admin')

# Audit log path
AUDIT_LOG_PATH = '/var/log/nanohub/admin_audit.log'

# Webhook log path for polling command results
WEBHOOK_LOG_PATH = '/var/log/nanohub/webhook.log'

# Create Blueprint
admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

# Thread pool for parallel execution
executor = ThreadPoolExecutor(max_workers=10)

# Database configuration - use environment variables in production
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'user': os.getenv('DB_USER', 'nanohub'),
    'password': os.getenv('DB_PASSWORD', 'your_db_password_here'),
    'database': os.getenv('DB_NAME', 'nanohub')
}


# =============================================================================
# DECORATORS
# =============================================================================

def admin_required(f):
    """Require admin role"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login', next=request.url))
        if session['user'].get('role') != 'admin':
            return jsonify({'error': 'Admin access required'}), 403
        return f(*args, **kwargs)
    return decorated_function


def login_required_admin(f):
    """Require any authenticated user for admin panel"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function


# =============================================================================
# AUDIT LOGGING
# =============================================================================

def get_hostname_for_uuid(uuid):
    """Get hostname for a device UUID from database"""
    try:
        import mysql.connector
        conn = mysql.connector.connect(
            host=os.environ.get('DB_HOST', 'localhost'),
            user=os.environ.get('DB_USER', 'nanohub'),
            password=os.environ.get('DB_PASSWORD', ''),
            database=os.environ.get('DB_NAME', 'nanohub')
        )
        cursor = conn.cursor()
        cursor.execute("SELECT hostname FROM device_inventory WHERE uuid = %s", (uuid,))
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        return result[0] if result else None
    except Exception as e:
        logger.error(f"Failed to get hostname for UUID {uuid}: {e}")
        return None


def audit_log(user, action, command, params, result, success):
    """Log admin action to audit file"""
    try:
        os.makedirs(os.path.dirname(AUDIT_LOG_PATH), exist_ok=True)
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Enrich params with hostname if udid is present
        enriched_params = dict(params) if params else {}
        if 'udid' in enriched_params and enriched_params['udid']:
            hostname = get_hostname_for_uuid(enriched_params['udid'])
            if hostname:
                enriched_params['device'] = f"{hostname} ({enriched_params['udid']})"

        log_entry = {
            'timestamp': timestamp,
            'user': user,
            'action': action,
            'command': command,
            'params': enriched_params,
            'success': success,
            'result_summary': result[:500] if result else None
        }
        with open(AUDIT_LOG_PATH, 'a') as f:
            f.write(json.dumps(log_entry) + '\n')
    except Exception as e:
        logger.error(f"Failed to write audit log: {e}")


# =============================================================================
# WEBHOOK POLLING
# =============================================================================

def poll_webhook_for_command(command_uuid, initial_sleep=3, max_polls=15, poll_wait=1, window=1000):
    """Poll webhook log for command result by UUID"""
    import re

    if not command_uuid:
        return None

    time.sleep(initial_sleep)

    for poll_attempt in range(max_polls):
        try:
            with open(WEBHOOK_LOG_PATH, 'r') as f:
                lines = f.readlines()[-window:]

            # Parse blocks separated by "=== MDM Event ==="
            blocks = []
            block = []
            for line in lines:
                if '=== MDM Event ===' in line and block:
                    blocks.append(block)
                    block = []
                block.append(line)
            if block:
                blocks.append(block)

            # Search from newest to oldest for matching command_uuid
            for blk in reversed(blocks):
                for line in blk:
                    if 'command_uuid:' in line.lower():
                        if command_uuid.lower() in line.lower():
                            # Found matching block - format it nicely
                            return format_webhook_block(blk)

            time.sleep(poll_wait)

        except Exception as e:
            logger.error(f"Error polling webhook: {e}")
            time.sleep(poll_wait)

    return None


def format_webhook_block(block):
    """Format webhook block for display"""
    result = {
        'raw': ''.join(block),
        'parsed': {}
    }

    for line in block:
        line = line.strip()
        # Skip empty lines and timestamp prefix
        if not line or '[INFO]' not in line:
            continue

        # Extract content after [INFO]
        if '[INFO]' in line:
            content = line.split('[INFO]', 1)[1].strip()

            # Parse key-value pairs
            if ':' in content and not content.startswith('==='):
                key, _, value = content.partition(':')
                key = key.strip()
                value = value.strip()
                if key and value:
                    result['parsed'][key] = value

    return result


def extract_command_uuid_from_output(output):
    """Extract command_uuid from script output (JSON response from nanomdm)"""
    import re

    # Try to find JSON with command_uuid
    uuid_pattern = r'"command_uuid"\s*:\s*"([a-f0-9-]+)"'
    match = re.search(uuid_pattern, output, re.IGNORECASE)
    if match:
        return match.group(1)

    # Fallback: look for bare UUID pattern after "command_uuid"
    uuid_pattern2 = r'command_uuid["\s:]+([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})'
    match2 = re.search(uuid_pattern2, output, re.IGNORECASE)
    if match2:
        return match2.group(1)

    return None


# =============================================================================
# COMMAND EXECUTION
# =============================================================================

def sanitize_param(value):
    """Sanitize parameter to prevent command injection"""
    if not value:
        return value
    dangerous = ['`', '$', '|', '&', ';', '\n', '\r', '>', '<', '\\']
    for char in dangerous:
        value = value.replace(char, '')
    return value.strip()


def execute_command(cmd_id, params, user_info):
    """Execute a command script with parameters"""
    cmd = get_command(cmd_id)
    if not cmd:
        return {'success': False, 'error': f'Unknown command: {cmd_id}'}

    user_role = user_info.get('role', 'report')
    if not check_role_permission(user_role, cmd.get('min_role', 'admin')):
        return {'success': False, 'error': 'Insufficient permissions'}

    # Validate device access for users with manifest_filter (e.g., bel-admin)
    udid = params.get('udid') or params.get('uuid')
    if udid and user_info.get('manifest_filter'):
        if not validate_device_access(udid, user_info):
            return {'success': False, 'error': 'Access denied: You can only manage devices with your assigned manifest'}

    # Determine script directory (use custom if specified)
    script_dir = cmd.get('script_dir', COMMANDS_DIR)
    script_path = os.path.join(script_dir, cmd['script'])
    if not os.path.exists(script_path):
        return {'success': False, 'error': f'Script not found: {cmd["script"]}'}

    # Build command arguments
    args = [script_path]

    # Special handling for schedule_os_update - uses flags
    if cmd_id == 'schedule_os_update':
        udid = params.get('udid')
        action = params.get('action')
        if not udid or not action:
            return {'success': False, 'error': 'Missing required parameter: udid or action'}
        args.extend([sanitize_param(udid), sanitize_param(action)])
        # Add optional flags
        if params.get('key'):
            args.extend(['--key', sanitize_param(params['key'])])
        if params.get('version'):
            args.extend(['--version', sanitize_param(params['version'])])
        if params.get('deferrals'):
            args.extend(['--deferrals', sanitize_param(params['deferrals'])])
        if params.get('priority'):
            args.extend(['--priority', sanitize_param(params['priority'])])

    # Special handling for db_device_query
    elif cmd_id == 'db_device_query':
        query_type = params.get('query_type')
        if not query_type:
            return {'success': False, 'error': 'Missing required parameter: query_type'}
        args.append(sanitize_param(query_type))
        if params.get('param1'):
            args.append(sanitize_param(params['param1']))

    # Special handling for device_manager (internal CRUD operations)
    elif cmd_id == 'device_manager':
        command = params.get('command')
        if not command:
            return {'success': False, 'error': 'Missing required parameter: command'}

        if command == 'add':
            return execute_device_add(params, user_info)
        elif command == 'update':
            return execute_device_update(params, user_info)
        elif command == 'delete':
            return execute_device_delete(params, user_info)
        else:
            return {'success': False, 'error': f'Unknown command: {command}'}

    # Special handling for bulk_new_device_installation
    elif cmd_id == 'bulk_new_device_installation':
        return execute_bulk_new_device_installation(params, user_info)

    # Special handling for bulk_schedule_os_update - uses platform-specific flags
    elif cmd_id == 'bulk_schedule_os_update':
        action = params.get('action')
        if not action:
            return {'success': False, 'error': 'Missing required parameter: action'}
        args.append(sanitize_param(action))
        # Add selected devices (if any)
        devices = params.get('devices')
        if devices:
            # devices can be a list or comma-separated string
            if isinstance(devices, list):
                device_list = [sanitize_param(d.strip()) for d in devices if d and d.strip()]
            else:
                device_list = [sanitize_param(d.strip()) for d in devices.split(',') if d.strip()]
            if device_list:
                args.extend(['--devices', ','.join(device_list)])
        # Add filter options
        if params.get('manifest'):
            args.extend(['--manifest', sanitize_param(params['manifest'])])
        if params.get('account_filter'):
            args.extend(['--account', sanitize_param(params['account_filter'])])
        if params.get('os_filter'):
            if params['os_filter'] == 'ios':
                args.append('--only-ios')
            elif params['os_filter'] == 'macos':
                args.append('--only-macos')
        # Add iOS specific options
        if params.get('ios_key'):
            args.extend(['--ios-key', sanitize_param(params['ios_key'])])
        if params.get('ios_version'):
            args.extend(['--ios-version', sanitize_param(params['ios_version'])])
        if params.get('ios_deferrals'):
            args.extend(['--ios-deferrals', sanitize_param(params['ios_deferrals'])])
        if params.get('ios_priority'):
            args.extend(['--ios-priority', sanitize_param(params['ios_priority'])])
        # Add macOS specific options
        if params.get('macos_key'):
            args.extend(['--macos-key', sanitize_param(params['macos_key'])])
        if params.get('macos_version'):
            args.extend(['--macos-version', sanitize_param(params['macos_version'])])
        if params.get('macos_deferrals'):
            args.extend(['--macos-deferrals', sanitize_param(params['macos_deferrals'])])
        if params.get('macos_priority'):
            args.extend(['--macos-priority', sanitize_param(params['macos_priority'])])
        # Dry run option
        if params.get('dry_run'):
            args.append('--dry-run')
        # Auto-confirm for non-interactive execution
        args.append('--yes')

    # Default parameter handling
    else:
        for param_def in cmd.get('parameters', []):
            param_name = param_def['name']
            param_value = params.get(param_name)

            if param_def.get('required') and not param_value:
                return {'success': False, 'error': f'Missing required parameter: {param_name}'}

            if param_value:
                param_value = sanitize_param(str(param_value))

                if param_def['type'] == 'profile':
                    if not param_value.startswith('/'):
                        for profile_dir in PROFILE_DIRS.values():
                            full_path = os.path.join(profile_dir, param_value)
                            if os.path.exists(full_path):
                                param_value = full_path
                                break

                args.append(param_value)

    logger.info(f"Executing command: {cmd_id} by {user_info.get('username')} with args: {args[1:]}")

    try:
        # Set proper PATH for script execution
        env = os.environ.copy()
        env['PATH'] = '/usr/local/bin:/usr/bin:/bin:/usr/local/sbin:/usr/sbin:/sbin:' + env.get('PATH', '')

        result = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=120,
            cwd=script_dir,
            env=env
        )

        output = result.stdout + result.stderr
        success = result.returncode == 0

        # Extract command_uuid from script output (nanomdm JSON response)
        command_uuid = extract_command_uuid_from_output(output)

        # Poll webhook for command result if we have a UUID
        webhook_result = None
        if command_uuid and success:
            logger.info(f"Polling webhook for command_uuid: {command_uuid}")
            webhook_result = poll_webhook_for_command(command_uuid, initial_sleep=3, max_polls=20, poll_wait=1)

        audit_log(
            user=user_info.get('username'),
            action='execute',
            command=cmd_id,
            params=params,
            result=output,
            success=success
        )

        response = {
            'success': success,
            'output': output,
            'return_code': result.returncode,
            'command_uuid': command_uuid
        }

        if webhook_result:
            response['webhook_response'] = webhook_result

        return response

    except subprocess.TimeoutExpired:
        audit_log(
            user=user_info.get('username'),
            action='execute',
            command=cmd_id,
            params=params,
            result='Command timed out',
            success=False
        )
        return {'success': False, 'error': 'Command timed out after 120 seconds'}

    except Exception as e:
        logger.error(f"Command execution failed: {e}")
        audit_log(
            user=user_info.get('username'),
            action='execute',
            command=cmd_id,
            params=params,
            result=str(e),
            success=False
        )
        return {'success': False, 'error': str(e)}


def execute_bulk_command(cmd_id, devices, params, user_info):
    """Execute command on multiple devices in parallel"""
    results = []
    futures = {}

    for device in devices:
        device_params = params.copy()
        device_params['udid'] = device

        future = executor.submit(execute_command, cmd_id, device_params, user_info)
        futures[future] = device

    for future in as_completed(futures):
        device = futures[future]
        try:
            result = future.result()
            result['device'] = device
            results.append(result)
        except Exception as e:
            results.append({
                'device': device,
                'success': False,
                'error': str(e)
            })

    return results


# =============================================================================
# DATABASE FUNCTIONS
# =============================================================================

def get_devices_list(manifest_filter=None):
    """Get list of devices from database, optionally filtered by manifest"""
    where_clause = ""
    if manifest_filter:
        # manifest_filter is SQL LIKE pattern e.g. 'bel-%'
        where_clause = f"WHERE di.manifest LIKE '{manifest_filter}'"

    sql = f"""
    SELECT JSON_OBJECT(
        'uuid', di.uuid,
        'serial', di.serial,
        'os', di.os,
        'hostname', di.hostname,
        'manifest', di.manifest,
        'account', di.account,
        'dep', di.dep,
        'last_seen', e.max_last_seen,
        'status', CASE
            WHEN e.max_last_seen IS NULL THEN 'offline'
            WHEN TIMESTAMPDIFF(MINUTE, e.max_last_seen, NOW()) <= 15 THEN 'online'
            WHEN TIMESTAMPDIFF(MINUTE, e.max_last_seen, NOW()) <= 60 THEN 'active'
            ELSE 'offline'
        END
    )
    FROM device_inventory di
    LEFT JOIN (
        SELECT device_id, MAX(last_seen_at) as max_last_seen
        FROM enrollments
        GROUP BY device_id
    ) e ON di.uuid = e.device_id
    {where_clause}
    ORDER BY di.hostname
    """

    cmd = [
        MYSQL_BIN,
        '-h', DB_CONFIG['host'],
        '-u', DB_CONFIG['user'],
        f'-p{DB_CONFIG["password"]}',
        DB_CONFIG['database'],
        '-sN',
        '-e', sql
    ]

    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        output = result.stdout.strip()

        if not output:
            return []

        devices = []
        for line in output.split('\n'):
            if line.strip():
                try:
                    devices.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

        return devices

    except Exception as e:
        logger.error(f"Failed to get devices: {e}")
        return []


def search_devices(field, value, manifest_filter=None):
    """Search devices in database, optionally filtered by manifest"""
    manifest_clause = ""
    if manifest_filter:
        manifest_clause = f"AND di.manifest LIKE '{manifest_filter}'"

    sql = f"""
    SELECT JSON_OBJECT(
        'uuid', di.uuid,
        'serial', di.serial,
        'os', di.os,
        'hostname', di.hostname,
        'manifest', di.manifest,
        'account', di.account,
        'dep', di.dep,
        'last_seen', e.max_last_seen,
        'status', CASE
            WHEN e.max_last_seen IS NULL THEN 'offline'
            WHEN TIMESTAMPDIFF(MINUTE, e.max_last_seen, NOW()) <= 15 THEN 'online'
            WHEN TIMESTAMPDIFF(MINUTE, e.max_last_seen, NOW()) <= 60 THEN 'active'
            ELSE 'offline'
        END
    )
    FROM device_inventory di
    LEFT JOIN (
        SELECT device_id, MAX(last_seen_at) as max_last_seen
        FROM enrollments
        GROUP BY device_id
    ) e ON di.uuid = e.device_id
    WHERE di.{field} LIKE '%{value}%' {manifest_clause}
    ORDER BY di.hostname
    """

    cmd = [
        MYSQL_BIN,
        '-h', DB_CONFIG['host'],
        '-u', DB_CONFIG['user'],
        f'-p{DB_CONFIG["password"]}',
        DB_CONFIG['database'],
        '-sN',
        '-e', sql
    ]

    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        output = result.stdout.strip()

        if not output:
            return []

        devices = []
        for line in output.split('\n'):
            if line.strip():
                try:
                    devices.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

        return devices

    except Exception as e:
        logger.error(f"Failed to search devices: {e}")
        return []


def get_profiles_by_category():
    """Get profiles separated by category"""
    profiles = get_available_profiles()

    result = {
        'system': [],
        'wireguard': []
    }

    for p in profiles:
        if p['type'] == 'wireguard':
            result['wireguard'].append(p)
        else:
            result['system'].append(p)

    return result


# =============================================================================
# DEVICE ACCESS VALIDATION
# =============================================================================

def get_device_manifest(uuid):
    """Get manifest for a device by UUID"""
    sql = f"SELECT manifest FROM device_inventory WHERE uuid = '{uuid}'"
    cmd = [
        '/usr/bin/mysql',
        '-h', DB_CONFIG['host'],
        '-u', DB_CONFIG['user'],
        f'-p{DB_CONFIG["password"]}',
        DB_CONFIG['database'],
        '-sN',
        '-e', sql
    ]
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception as e:
        logger.error(f"Failed to get device manifest: {e}")
    return None


def validate_device_access(uuid, user_info):
    """Check if user has access to device based on manifest_filter"""
    manifest_filter = user_info.get('manifest_filter')
    if not manifest_filter:
        return True  # No filter = full access

    device_manifest = get_device_manifest(uuid)
    if not device_manifest:
        return False  # Device not found

    # Convert SQL LIKE pattern to simple check
    # 'bel-%' means manifest must start with 'bel-'
    if manifest_filter.endswith('%'):
        prefix = manifest_filter[:-1]  # Remove '%'
        return device_manifest.startswith(prefix)

    return device_manifest == manifest_filter


# =============================================================================
# INTERNAL DEVICE CRUD OPERATIONS
# =============================================================================

MYSQL_BIN = '/usr/bin/mysql'

def execute_device_add(params, user_info):
    """Add a new device to inventory (direct SQL)"""
    uuid_val = sanitize_param(params.get('uuid', ''))
    serial = sanitize_param(params.get('serial', ''))
    os_type = sanitize_param(params.get('os', ''))
    hostname = sanitize_param(params.get('hostname', ''))
    manifest = sanitize_param(params.get('manifest', 'default'))
    account = sanitize_param(params.get('account', 'default'))
    dep = sanitize_param(params.get('dep', '0'))

    # Validate required fields
    if not uuid_val or not serial or not os_type or not hostname:
        return {'success': False, 'error': 'Missing required fields: uuid, serial, os, hostname'}

    # Validate manifest for users with manifest_filter (e.g., bel-admin can only add bel-* devices)
    manifest_filter = user_info.get('manifest_filter')
    if manifest_filter:
        if manifest_filter.endswith('%'):
            required_prefix = manifest_filter[:-1]
            if not manifest.startswith(required_prefix):
                return {'success': False, 'error': f'Access denied: You can only add devices with manifest starting with "{required_prefix}"'}

    # Validate UUID format
    import re
    if not re.match(r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$', uuid_val, re.IGNORECASE):
        return {'success': False, 'error': 'Invalid UUID format'}

    # Build SQL
    sql = f"""INSERT INTO device_inventory (uuid, serial, os, hostname, manifest, account, dep)
              VALUES ('{uuid_val}', '{serial}', '{os_type}', '{hostname}', '{manifest}', '{account}', '{dep}')"""

    cmd = [
        MYSQL_BIN,
        '-h', DB_CONFIG['host'],
        '-u', DB_CONFIG['user'],
        f'-p{DB_CONFIG["password"]}',
        DB_CONFIG['database'],
        '-e', sql
    ]

    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        if result.returncode == 0:
            audit_log(
                user=user_info.get('username'),
                action='device_add',
                command='device_add',
                params=params,
                result=f'Device {hostname} ({uuid_val}) added successfully',
                success=True
            )
            return {
                'success': True,
                'output': f'Device added successfully:\n  UUID: {uuid_val}\n  Serial: {serial}\n  OS: {os_type}\n  Hostname: {hostname}\n  Manifest: {manifest}\n  Account: {account}\n  DEP: {dep}'
            }
        else:
            error_msg = result.stderr or 'Unknown error'
            if 'Duplicate entry' in error_msg:
                error_msg = f'Device with UUID {uuid_val} already exists'
            audit_log(
                user=user_info.get('username'),
                action='device_add',
                command='device_add',
                params=params,
                result=error_msg,
                success=False
            )
            return {'success': False, 'error': error_msg}

    except Exception as e:
        logger.error(f"Device add failed: {e}")
        return {'success': False, 'error': str(e)}


def execute_device_update(params, user_info):
    """Update existing device in inventory (direct SQL)"""
    uuid_val = sanitize_param(params.get('uuid', ''))

    if not uuid_val:
        return {'success': False, 'error': 'Missing required field: uuid'}

    # Build SET clause only for provided fields
    updates = []
    if params.get('serial'):
        updates.append(f"serial = '{sanitize_param(params['serial'])}'")
    if params.get('os'):
        updates.append(f"os = '{sanitize_param(params['os'])}'")
    if params.get('hostname'):
        updates.append(f"hostname = '{sanitize_param(params['hostname'])}'")
    if params.get('manifest'):
        updates.append(f"manifest = '{sanitize_param(params['manifest'])}'")
    if params.get('account'):
        updates.append(f"account = '{sanitize_param(params['account'])}'")
    if params.get('dep') is not None and params.get('dep') != '':
        updates.append(f"dep = '{sanitize_param(params['dep'])}'")

    if not updates:
        return {'success': False, 'error': 'No fields to update provided'}

    sql = f"UPDATE device_inventory SET {', '.join(updates)} WHERE uuid = '{uuid_val}'"

    cmd = [
        MYSQL_BIN,
        '-h', DB_CONFIG['host'],
        '-u', DB_CONFIG['user'],
        f'-p{DB_CONFIG["password"]}',
        DB_CONFIG['database'],
        '-e', sql
    ]

    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        if result.returncode == 0:
            audit_log(
                user=user_info.get('username'),
                action='device_update',
                command='device_update',
                params=params,
                result=f'Device {uuid_val} updated successfully',
                success=True
            )
            return {
                'success': True,
                'output': f'Device updated successfully:\n  UUID: {uuid_val}\n  Updated fields: {", ".join(updates)}'
            }
        else:
            error_msg = result.stderr or 'Unknown error'
            audit_log(
                user=user_info.get('username'),
                action='device_update',
                command='device_update',
                params=params,
                result=error_msg,
                success=False
            )
            return {'success': False, 'error': error_msg}

    except Exception as e:
        logger.error(f"Device update failed: {e}")
        return {'success': False, 'error': str(e)}


def execute_device_delete(params, user_info):
    """Delete device from inventory (direct SQL)"""
    uuid_val = sanitize_param(params.get('uuid', ''))

    if not uuid_val:
        return {'success': False, 'error': 'Missing required field: uuid'}

    # First get device info for logging
    get_sql = f"SELECT hostname, serial FROM device_inventory WHERE uuid = '{uuid_val}'"
    get_cmd = [
        MYSQL_BIN,
        '-h', DB_CONFIG['host'],
        '-u', DB_CONFIG['user'],
        f'-p{DB_CONFIG["password"]}',
        DB_CONFIG['database'],
        '-sN',
        '-e', get_sql
    ]

    device_info = "unknown"
    try:
        get_result = subprocess.run(get_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if get_result.returncode == 0 and get_result.stdout.strip():
            parts = get_result.stdout.strip().split('\t')
            if len(parts) >= 2:
                device_info = f"{parts[0]} ({parts[1]})"
    except:
        pass

    # Delete the device
    sql = f"DELETE FROM device_inventory WHERE uuid = '{uuid_val}'"

    cmd = [
        MYSQL_BIN,
        '-h', DB_CONFIG['host'],
        '-u', DB_CONFIG['user'],
        f'-p{DB_CONFIG["password"]}',
        DB_CONFIG['database'],
        '-e', sql
    ]

    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        if result.returncode == 0:
            audit_log(
                user=user_info.get('username'),
                action='device_delete',
                command='device_delete',
                params=params,
                result=f'Device {device_info} ({uuid_val}) deleted',
                success=True
            )
            return {
                'success': True,
                'output': f'Device deleted successfully:\n  UUID: {uuid_val}\n  Device: {device_info}'
            }
        else:
            error_msg = result.stderr or 'Unknown error'
            audit_log(
                user=user_info.get('username'),
                action='device_delete',
                command='device_delete',
                params=params,
                result=error_msg,
                success=False
            )
            return {'success': False, 'error': error_msg}

    except Exception as e:
        logger.error(f"Device delete failed: {e}")
        return {'success': False, 'error': str(e)}


def execute_bulk_new_device_installation(params, user_info):
    """Execute bulk new device installation workflow"""
    import time
    import glob

    branch = params.get('branch', '')
    platform = params.get('platform', '')
    udid = sanitize_param(params.get('udid', ''))
    munki_type = params.get('munki_type', 'default')
    hostname = sanitize_param(params.get('hostname', ''))
    install_filevault = params.get('install_filevault', 'no')
    install_wireguard = params.get('install_wireguard', 'no')

    if not branch or not platform or not udid:
        return {'success': False, 'error': 'Missing required fields: branch, platform, udid'}

    output_lines = []
    errors = []
    commands_executed = 0
    WAIT_INTERVAL = 5  # seconds between commands

    profiles_dir = '/opt/nanohub/profiles'
    commands_dir = '/opt/nanohub/tools/api/commands'

    def run_command(cmd_name, *args):
        """Execute a command script and return result"""
        nonlocal commands_executed
        script_path = os.path.join(commands_dir, cmd_name)
        if not os.path.exists(script_path):
            return False, f"Script not found: {cmd_name}"

        full_args = [script_path] + list(args)
        try:
            env = os.environ.copy()
            env['PATH'] = '/usr/local/bin:/usr/bin:/bin:' + env.get('PATH', '')
            result = subprocess.run(full_args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60, env=env)
            commands_executed += 1
            if result.returncode == 0:
                return True, result.stdout.strip() if result.stdout else 'OK'
            else:
                return False, result.stderr.strip() if result.stderr else 'Command failed'
        except subprocess.TimeoutExpired:
            return False, 'Command timed out'
        except Exception as e:
            return False, str(e)

    def install_profile(profile_name):
        """Install a profile and wait"""
        profile_path = os.path.join(profiles_dir, profile_name)
        output_lines.append(f"Installing profile: {profile_name}")
        success, msg = run_command('install_profile', udid, profile_path)
        if success:
            output_lines.append(f"  [OK] {profile_name}")
        else:
            output_lines.append(f"  [ERROR] {profile_name}: {msg}")
            errors.append(f"Profile {profile_name}: {msg}")
        time.sleep(WAIT_INTERVAL)
        return success

    def install_application(manifest_url):
        """Install an application and wait"""
        output_lines.append(f"Installing application: {manifest_url}")
        success, msg = run_command('install_application', udid, manifest_url)
        if success:
            output_lines.append(f"  [OK] {manifest_url.split('/')[-1]}")
        else:
            output_lines.append(f"  [ERROR] {manifest_url}: {msg}")
            errors.append(f"Application {manifest_url}: {msg}")
        time.sleep(WAIT_INTERVAL)
        return success

    output_lines.append("=" * 60)
    output_lines.append(f"New Device Installation - {branch.upper()} - {platform.upper()}")
    output_lines.append(f"Device UUID: {udid}")
    output_lines.append("=" * 60)

    # macOS Installation
    if platform == 'macos':
        output_lines.append("\n[PHASE 1] Installing base profiles...")

        # Common profiles for both branches
        install_profile('org.example.macos.appleRoot.profile.signed.mobileconfig')
        install_profile('org.example.macos.Root.profile.signed.mobileconfig')
        install_profile('org.example.macos.EnergySaver.profile.signed.mobileconfig')

        output_lines.append("\n[PHASE 2] Installing Munki profile...")

        # Munki profile selection based on munki_type (supports both old and new format)
        # Old format: 'default'/'tech' with branch determining bel- prefix
        # New format: 'default'/'tech'/'bel-default'/'bel-tech' explicit selection
        if munki_type == 'bel-default':
            install_profile('org.example.macos.Munki-Bel-Default.profile.signed.mobileconfig')
        elif munki_type == 'bel-tech':
            install_profile('org.example.macos.Munki-Bel-Tech.profile.signed.mobileconfig')
        elif branch == 'main_office':
            if munki_type == 'tech':
                install_profile('org.example.macos.Munki-Tech.profile.signed.mobileconfig')
            else:
                install_profile('org.example.macos.Munki-Default.profile.signed.mobileconfig')
            install_profile('org.example.macos.SSO.Drive.profile.signed.mobileconfig')
        else:  # branch_office with default/tech
            if munki_type == 'tech':
                install_profile('org.example.macos.Munki-Bel-Tech.profile.signed.mobileconfig')
            else:
                install_profile('org.example.macos.Munki-Bel-Default.profile.signed.mobileconfig')

        output_lines.append("\n[PHASE 3] Installing security profiles...")

        # Common profiles continued
        install_profile('org.example.macos.Restrictions.profile.signed.mobileconfig')
        install_profile('org.example.macos.Account-Disabled.profile.signed.mobileconfig')
        install_profile('org.example.macos.Firewall.profile.signed.mobileconfig')

        output_lines.append("\n[PHASE 4] Installing applications...")

        # Applications
        install_application('https://repo.example.com/munki/mdmagent.plist')
        install_application('https://repo.example.com/munki/munki.plist')

        # Branch-specific applications for main_office
        if branch == 'main_office':
            install_application('https://repo.example.com/munki/drivemap.plist')
            install_application('https://repo.example.com/munki/removeadmin_manifest.plist')

        # Directory Services (main_office only, if hostname provided)
        if branch == 'main_office' and hostname:
            output_lines.append("\n[PHASE 5] Setting up Directory Services...")

            # Set hostname first
            output_lines.append(f"Setting hostname to: {hostname}")
            success, msg = run_command('send_command', udid, 'hostname', hostname)
            if success:
                output_lines.append(f"  [OK] Hostname set to {hostname}")
            else:
                output_lines.append(f"  [WARNING] Failed to set hostname: {msg}")
            time.sleep(WAIT_INTERVAL)

            # Install Directory Services profile
            install_profile('org.example.macos.DirectoryServices.profile.signed.mobileconfig')

        # FileVault profile
        if install_filevault == 'yes':
            output_lines.append("\n[PHASE 6] Installing FileVault profile...")
            output_lines.append("NOTE: Client (not admin) should be logged in for FileVault!")
            install_profile('org.example.macos.Filevault.profile.signed.mobileconfig')

        # WireGuard profile (main_office only)
        if branch == 'main_office' and install_wireguard == 'yes' and hostname:
            output_lines.append("\n[PHASE 7] Installing WireGuard profile...")

            # Search for WireGuard profile
            wg_search_path = os.path.join(profiles_dir, 'wireguard_configs', '30_account', 'macos')
            wg_pattern = os.path.join(wg_search_path, f'*{hostname}*.signed.mobileconfig')
            wg_profiles = glob.glob(wg_pattern)

            if wg_profiles:
                wg_profile = wg_profiles[0]
                output_lines.append(f"Found WireGuard profile: {os.path.basename(wg_profile)}")
                success, msg = run_command('install_profile', udid, wg_profile)
                if success:
                    output_lines.append(f"  [OK] WireGuard profile installed")
                else:
                    output_lines.append(f"  [ERROR] WireGuard installation failed: {msg}")
                    errors.append(f"WireGuard: {msg}")
            else:
                output_lines.append(f"  [WARNING] No WireGuard profile found for hostname: {hostname}")
                output_lines.append(f"  Searched in: {wg_search_path}")

    # iOS Installation
    elif platform == 'ios':
        output_lines.append("\n[PHASE 1] Installing iOS profiles...")

        install_profile('org.example.ios.appleRoot.profile.signed.mobileconfig')
        install_profile('org.example.ios.Account-Disabled.profile.signed.mobileconfig')
        install_profile('org.example.ios.Restrictions.profile.signed.mobileconfig')
        install_profile('org.example.ios.whitelist.signed.mobileconfig')

    # Summary
    output_lines.append("\n" + "=" * 60)
    output_lines.append("INSTALLATION SUMMARY")
    output_lines.append("=" * 60)
    output_lines.append(f"Branch: {branch.upper()}")
    output_lines.append(f"Platform: {platform.upper()}")
    if platform == 'macos':
        output_lines.append(f"Munki Type: {munki_type}")
    output_lines.append(f"Device UUID: {udid}")
    output_lines.append(f"Commands executed: {commands_executed}")

    if errors:
        output_lines.append(f"\nErrors encountered: {len(errors)}")
        for err in errors:
            output_lines.append(f"  - {err}")

    # Audit log
    audit_log(
        user=user_info.get('username'),
        action='bulk_new_device_installation',
        command='bulk_new_device_installation',
        params=params,
        result=f"Installed {commands_executed} commands, {len(errors)} errors",
        success=len(errors) == 0
    )

    return {
        'success': len(errors) == 0,
        'output': '\n'.join(output_lines),
        'errors': errors if errors else None
    }


# =============================================================================
# HTML TEMPLATES - Using native dashboard.css styling
# =============================================================================

ADMIN_DASHBOARD_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Admin Panel - NanoHUB MDM</title>
    <link rel="stylesheet" href="/static/dashboard.css">
    <link rel="apple-touch-icon" sizes="180x180" href="/static/apple-touch-icon.png">
    <link rel="icon" type="image/png" sizes="32x32" href="/static/favicon-32x32.png">
    <link rel="shortcut icon" href="/static/favicon.ico">
    <style>
        .admin-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
        }
        .admin-header h2 {
            margin: 0;
            text-align: left;
        }
        .category-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
            gap: 20px;
            margin-top: 20px;
        }
        .category-card {
            background: #f7f8fa;
            border-radius: 5px;
            padding: 15px;
            text-align: left;
        }
        .category-card h3 {
            margin: 0 0 12px 0;
            font-size: 1.1em;
            color: #21243b;
            border-bottom: 2px solid #e7eaf2;
            padding-bottom: 8px;
        }
        .command-list {
            list-style: none;
            padding: 0;
            margin: 0;
        }
        .command-list li {
            margin-bottom: 6px;
        }
        .command-list a {
            display: block;
            padding: 6px 10px;
            background: #fff;
            border-radius: 4px;
            text-decoration: none;
            color: #21243b;
            font-size: 0.95em;
            border: 1px solid #e7eaf2;
        }
        .command-list a:hover {
            background: #e7eaf2;
            text-decoration: none;
        }
        .command-list a.dangerous {
            border-left: 3px solid #e92128;
        }
        .role-badge {
            display: inline-block;
            padding: 1px 6px;
            border-radius: 8px;
            font-size: 0.75em;
            margin-left: 6px;
            background: #f7dcdc;
            color: #e92128;
        }
        .nav-tabs {
            margin-bottom: 15px;
        }
        .nav-tabs a {
            margin-right: 8px;
        }
        .nav-tabs a.active {
            background: #e89898;
            color: white;
        }
    </style>
</head>
<body>
    <div id="wrap">
        <div style="display: flex; justify-content: center; align-items: center;">
            <img id="logo" src="/static/logo.svg" alt="Logo"/>
        </div>
        <h1>NanoHUB MDM Admin Panel</h1>

        <div class="panel">
            <div class="admin-header">
                <div class="panel-title" style="margin:0;">Commands</div>
                <div>
                    <span style="color:#4b5563;">{{ user.display_name }}</span>
                    <span class="role-badge">{{ user.role }}</span>
                    <a href="/" class="btn" style="margin-left:10px;">Dashboard</a>
                </div>
            </div>

            <div class="nav-tabs">
                <a href="/admin" class="btn active">Commands</a>
                <a href="/admin/history" class="btn">History</a>
                <a href="/admin/profiles" class="btn">Profiles</a>
            </div>

            <div class="category-grid">
                {% for cat_id, cat_data in categories.items() %}
                {% if cat_data.commands %}
                <div class="category-card">
                    <h3>{{ cat_data.info.name }}</h3>
                    <ul class="command-list">
                        {% for cmd_id, cmd in cat_data.commands.items() %}
                        {% if can_access(user.role, cmd.min_role) %}
                        <li>
                            <a href="/admin/command/{{ cmd_id }}" class="{% if cmd.dangerous %}dangerous{% endif %}">
                                {{ cmd.name }}
                                {% if cmd.min_role == 'admin' %}<span class="role-badge">admin</span>{% endif %}
                            </a>
                        </li>
                        {% endif %}
                        {% endfor %}
                    </ul>
                </div>
                {% endif %}
                {% endfor %}
            </div>
        </div>
    </div>
</body>
</html>
'''

ADMIN_COMMAND_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ command.name }} - NanoHUB Admin</title>
    <link rel="stylesheet" href="/static/dashboard.css">
    <link rel="shortcut icon" href="/static/favicon.ico">
    <style>
        .admin-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
        }
        .form-group {
            margin-bottom: 15px;
            text-align: left;
        }
        .form-group label {
            display: block;
            margin-bottom: 5px;
            font-weight: 500;
            color: #21243b;
        }
        .form-group input, .form-group select {
            width: 100%;
            box-sizing: border-box;
        }
        .device-table-container {
            max-height: 300px;
            overflow-y: auto;
            border: 1px solid #bcd2f7;
            border-radius: 5px;
            margin-top: 5px;
        }
        .device-table {
            width: 100%;
            font-size: 0.9em;
        }
        .device-table tr {
            cursor: pointer;
        }
        .device-table thead th {
            position: sticky;
            top: 0;
            background: #e7eaf2;
            color: #21243b;
            font-weight: 700;
            z-index: 10;
        }
        .device-table tr:hover {
            background: #f0f4ff;
        }
        .device-table tr.selected {
            background: #d4edda !important;
        }
        .selected-device-panel {
            background: #d4edda;
            padding: 8px 15px;
            border-radius: 6px;
            margin-top: 10px;
            display: none;
        }
        .selected-device-panel.visible {
            display: block;
        }
        .status-dot {
            display: inline-block;
            width: 10px;
            height: 10px;
            border-radius: 50%;
            margin-right: 5px;
        }
        .status-dot.online { background: #27ae60; }
        .status-dot.active { background: #f39c12; }
        .status-dot.offline { background: #95a5a6; }
        .warning-box {
            background: #f7dcdc;
            border: 1px solid #e92128;
            border-radius: 5px;
            padding: 12px;
            margin-bottom: 15px;
            text-align: left;
        }
        .warning-box h4 {
            margin: 0 0 8px 0;
            color: #e92128;
        }
        .output-panel {
            background: #1e1e1e;
            color: #d4d4d4;
            padding: 12px;
            border-radius: 5px;
            font-family: monospace;
            font-size: 0.85em;
            white-space: pre-wrap;
            max-height: 350px;
            overflow-y: auto;
            margin-top: 15px;
            text-align: left;
        }
        .output-panel.success { border-left: 4px solid #27ae60; }
        .output-panel.error { border-left: 4px solid #e92128; }
        .profile-select-group {
            margin-top: 10px;
        }
        .profile-select-group label {
            font-size: 0.9em;
            color: #4b5563;
        }
        .confirm-overlay {
            display: none;
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0,0,0,0.5);
            z-index: 1000;
            align-items: center;
            justify-content: center;
        }
        .confirm-overlay.show { display: flex; }
        .confirm-box {
            background: white;
            border-radius: 5px;
            padding: 25px;
            max-width: 450px;
            width: 90%;
            text-align: center;
        }
        .confirm-box h3 { color: #e92128; margin-bottom: 15px; }
    </style>
</head>
<body>
    <div id="wrap">
        <div style="display: flex; justify-content: center; align-items: center;">
            <img id="logo" src="/static/logo.svg" alt="Logo"/>
        </div>
        <h1>{{ command.name }}</h1>

        <div class="panel">
            <div class="admin-header">
                <div class="panel-title" style="margin:0;">{{ command.description }}</div>
                <a href="/admin" class="btn">Back to Commands</a>
            </div>

            {% if command.dangerous %}
            <div class="warning-box">
                <h4>{% if command.danger_level == 'critical' %}CRITICAL WARNING{% else %}Warning{% endif %}</h4>
                <p style="margin:0;">This is a potentially dangerous operation.
                {% if command.danger_level == 'critical' %}
                <br>This action cannot be undone. All data may be permanently lost.
                {% endif %}
                </p>
            </div>
            {% endif %}

            <form id="commandForm" onsubmit="return executeCommand(event)" style="text-align:left;">
                {% for param in command.parameters %}
                <div class="form-group">
                    <label>{{ param.label }}{% if param.required %} <span style="color:#e92128;">*</span>{% endif %}</label>

                    {% if param.type == 'device' %}
                    <div class="panel-actions" style="margin-bottom:8px;">
                        <input type="text" id="device-search" placeholder="Search hostname / serial / UUID" style="width:220px;">
                        <select id="os-filter" style="width:100px;margin-left:5px;">
                            <option value="all">All OS</option>
                            <option value="ios">iOS</option>
                            <option value="macos">macOS</option>
                        </select>
                        <button type="button" onclick="searchDevices()" class="btn" style="margin-left:5px;">Search</button>
                        <button type="button" onclick="showAllDevices()" class="btn" style="margin-left:5px;">Show All</button>
                    </div>
                    <div class="device-table-container">
                        <table class="device-table" id="device-table">
                            <thead>
                                <tr><th>Status</th><th>UUID</th><th>Hostname</th><th>Serial</th><th>OS</th><th>Account</th><th>Manifest</th><th>DEP</th></tr>
                            </thead>
                            <tbody id="device-tbody">
                                <tr><td colspan="8" style="text-align:center;color:#4b5563;">Click "Show All" or search for devices</td></tr>
                            </tbody>
                        </table>
                    </div>
                    <input type="hidden" name="udid" id="selected-udid" {% if param.required %}required{% endif %}>
                    <div id="selected-device-info" class="selected-device-panel"></div>

                    {% elif param.type == 'devices' %}
                    <div class="panel-actions" style="margin-bottom:8px;">
                        <input type="text" id="device-search" placeholder="Search hostname / serial / UUID" style="width:220px;">
                        <select id="os-filter" style="width:100px;margin-left:5px;">
                            <option value="all">All OS</option>
                            <option value="ios">iOS</option>
                            <option value="macos">macOS</option>
                        </select>
                        <button type="button" onclick="searchDevices()" class="btn" style="margin-left:5px;">Search</button>
                        <button type="button" onclick="showAllDevices()" class="btn" style="margin-left:5px;">Show All</button>
                    </div>
                    <div class="device-table-container">
                        <table class="device-table" id="device-table">
                            <thead>
                                <tr><th><input type="checkbox" id="select-all" onchange="toggleSelectAll()"></th><th>Status</th><th>UUID</th><th>Hostname</th><th>Serial</th><th>OS</th><th>Account</th><th>Manifest</th><th>DEP</th></tr>
                            </thead>
                            <tbody id="device-tbody">
                                <tr><td colspan="9" style="text-align:center;color:#4b5563;">Click "Show All" or search for devices</td></tr>
                            </tbody>
                        </table>
                    </div>
                    <div id="selected-count" style="margin-top:8px;color:#276beb;font-weight:500;"></div>

                    {% elif param.type == 'profile' %}
                    <div class="profile-select-group">
                        <label>System Profiles:</label>
                        <select name="{{ param.name }}" id="{{ param.name }}" {% if param.required %}required{% endif %}>
                            <option value="">-- Select Profile --</option>
                            <optgroup label="System Profiles">
                            {% for profile in profiles.system %}
                            <option value="{{ profile.path }}">{{ profile.name }}</option>
                            {% endfor %}
                            </optgroup>
                            <optgroup label="WireGuard Profiles">
                            {% for profile in profiles.wireguard %}
                            <option value="{{ profile.path }}">{{ profile.name }}</option>
                            {% endfor %}
                            </optgroup>
                        </select>
                    </div>

                    {% elif param.type == 'device_autofill' %}
                    <div class="panel-actions" style="margin-bottom:8px;">
                        <input type="text" id="autofill-device-search" placeholder="Search hostname / serial / UUID" style="width:220px;">
                        <select id="autofill-os-filter" style="width:100px;margin-left:5px;">
                            <option value="all">All OS</option>
                            <option value="ios">iOS</option>
                            <option value="macos">macOS</option>
                        </select>
                        <button type="button" onclick="searchAutofillDevices()" class="btn" style="margin-left:5px;">Search</button>
                        <button type="button" onclick="showAllAutofillDevices()" class="btn" style="margin-left:5px;">Show All</button>
                    </div>
                    <div class="device-table-container">
                        <table class="device-table" id="autofill-device-table">
                            <thead>
                                <tr><th>Status</th><th>UUID</th><th>Hostname</th><th>Serial</th><th>OS</th><th>Account</th><th>Manifest</th><th>DEP</th></tr>
                            </thead>
                            <tbody id="autofill-device-tbody">
                                <tr><td colspan="8" style="text-align:center;color:#4b5563;">Click "Show All" or search for devices</td></tr>
                            </tbody>
                        </table>
                    </div>
                    <div id="autofill-selected-info" class="selected-device-panel"></div>

                    {% elif param.type == 'select' %}
                    <select name="{{ param.name }}" id="{{ param.name }}" {% if param.required %}required{% endif %}>
                        {% for opt in param.options %}
                        <option value="{{ opt.value }}">{{ opt.label }}</option>
                        {% endfor %}
                    </select>

                    {% else %}
                    <input type="text" name="{{ param.name }}" id="{{ param.name }}"
                           placeholder="{{ param.placeholder or '' }}"
                           {% if param.required %}required{% endif %}>
                    {% endif %}
                </div>
                {% endfor %}

                <div style="margin-top:20px;">
                    <button type="submit" class="btn {% if command.dangerous %}red{% endif %}">
                        Execute {{ command.name }}
                    </button>
                </div>
            </form>

            <div id="loading" style="display:none;margin-top:15px;color:#e92128;font-weight:bold;">
                Executing command, please wait...
            </div>

            <div id="output-container"></div>
        </div>
    </div>

    {% if command.danger_level == 'critical' %}
    <div class="confirm-overlay" id="confirmOverlay">
        <div class="confirm-box">
            <h3>Confirm Dangerous Operation</h3>
            <p>You are about to execute: <strong>{{ command.name }}</strong></p>
            <p>{{ command.description }}</p>
            <div style="margin:15px 0;">
                <label>Type <strong>{{ command.confirm_text or 'CONFIRM' }}</strong> to proceed:</label>
                <input type="text" id="confirmInput" style="margin-top:8px;width:200px;">
            </div>
            <div>
                <button class="btn" onclick="closeConfirm()">Cancel</button>
                <button class="btn red" onclick="confirmExecute()" style="margin-left:10px;">Confirm</button>
            </div>
        </div>
    </div>
    {% endif %}

    <script>
    const commandId = '{{ cmd_id }}';
    const isDangerous = {{ 'true' if command.dangerous else 'false' }};
    const dangerLevel = '{{ command.danger_level or "" }}';
    const confirmText = '{{ command.confirm_text or "CONFIRM" }}';
    const isMultiSelect = {{ 'true' if has_devices_param else 'false' }};
    let allDevices = [];
    let pendingFormData = null;

    function detectFieldType(input) {
        if (/^[a-f0-9\\-]{36}$/i.test(input)) return 'uuid';
        else if (/^\\d+$/.test(input)) return 'serial';
        else return 'hostname';
    }

    function showAllDevices() {
        fetch('/admin/api/devices')
            .then(r => r.json())
            .then(devices => {
                allDevices = devices || [];
                renderDevices(filterByOS(allDevices));
            })
            .catch(err => {
                console.error('Failed to load devices:', err);
                allDevices = [];
                renderDevices([]);
            });
    }

    function searchDevices() {
        const input = document.getElementById('device-search').value.trim();
        if (!input) {
            showAllDevices();
            return;
        }
        const field = detectFieldType(input);
        fetch('/admin/api/device-search', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({field, value: input})
        })
        .then(r => r.json())
        .then(devices => {
            allDevices = Array.isArray(devices) ? devices : [];
            renderDevices(filterByOS(allDevices));
        })
        .catch(err => {
            console.error('Search failed:', err);
            allDevices = [];
            renderDevices([]);
        });
    }

    function filterByOS(devices) {
        const filter = document.getElementById('os-filter').value;
        if (filter === 'all') return devices;
        return devices.filter(d => d.os === filter);
    }

    document.getElementById('os-filter')?.addEventListener('change', function() {
        renderDevices(filterByOS(allDevices));
    });

    function renderDevices(devices) {
        const tbody = document.getElementById('device-tbody');
        if (!devices.length) {
            tbody.innerHTML = '<tr><td colspan="' + (isMultiSelect ? '9' : '8') + '" style="text-align:center;color:#4b5563;">No devices found</td></tr>';
            return;
        }

        let html = '';
        devices.forEach(dev => {
            const statusClass = dev.status || 'offline';
            // DEP is stored as 'enabled'/'disabled' or '0'/'1'
            const depVal = (dev.dep === 'enabled' || dev.dep === '1' || dev.dep === 1) ? 'Yes' : 'No';
            if (isMultiSelect) {
                html += `<tr onclick="toggleDeviceCheckbox('${dev.uuid}', this)">
                    <td><input type="checkbox" name="devices" value="${dev.uuid}" onclick="event.stopPropagation()"></td>
                    <td><span class="status-dot ${statusClass}"></span></td>
                    <td style="font-size:0.85em;">${dev.uuid || '-'}</td>
                    <td>${dev.hostname || '-'}</td>
                    <td>${dev.serial || '-'}</td>
                    <td>${dev.os || '-'}</td>
                    <td>${dev.account || '-'}</td>
                    <td>${dev.manifest || '-'}</td>
                    <td>${depVal}</td>
                </tr>`;
            } else {
                html += `<tr onclick="selectDevice('${dev.uuid}', '${dev.hostname || dev.serial}', this)">
                    <td><span class="status-dot ${statusClass}"></span></td>
                    <td style="font-size:0.85em;">${dev.uuid || '-'}</td>
                    <td>${dev.hostname || '-'}</td>
                    <td>${dev.serial || '-'}</td>
                    <td>${dev.os || '-'}</td>
                    <td>${dev.account || '-'}</td>
                    <td>${dev.manifest || '-'}</td>
                    <td>${depVal}</td>
                </tr>`;
            }
        });
        tbody.innerHTML = html;
    }

    function selectDevice(uuid, name, row) {
        document.querySelectorAll('#device-table tr').forEach(r => r.classList.remove('selected'));
        row.classList.add('selected');
        document.getElementById('selected-udid').value = uuid;
        const infoEl = document.getElementById('selected-device-info');
        infoEl.innerHTML = '<strong>Selected:</strong> ' + name + ' | ' + uuid +
            ' <button type="button" onclick="clearSelectedDevice()" style="margin-left:15px;padding:3px 10px;cursor:pointer;">Clear</button>';
        infoEl.classList.add('visible');
    }

    function clearSelectedDevice() {
        document.querySelectorAll('#device-table tr').forEach(r => r.classList.remove('selected'));
        document.getElementById('selected-udid').value = '';
        const infoEl = document.getElementById('selected-device-info');
        infoEl.innerHTML = '';
        infoEl.classList.remove('visible');
    }

    function toggleDeviceCheckbox(uuid, row) {
        const cb = row.querySelector('input[type="checkbox"]');
        cb.checked = !cb.checked;
        row.classList.toggle('selected', cb.checked);
        updateSelectedCount();
    }

    function toggleSelectAll() {
        const checked = document.getElementById('select-all').checked;
        document.querySelectorAll('#device-tbody input[type="checkbox"]').forEach(cb => {
            cb.checked = checked;
            cb.closest('tr').classList.toggle('selected', checked);
        });
        updateSelectedCount();
    }

    function updateSelectedCount() {
        const count = document.querySelectorAll('#device-tbody input[type="checkbox"]:checked').length;
        const el = document.getElementById('selected-count');
        if (el) el.textContent = count > 0 ? count + ' device(s) selected' : '';
    }

    // =========================================================================
    // AUTOFILL DEVICE FUNCTIONS (for Device Manager update/delete)
    // =========================================================================
    let allAutofillDevices = [];

    function showAllAutofillDevices() {
        fetch('/admin/api/devices')
            .then(r => r.json())
            .then(devices => {
                allAutofillDevices = devices || [];
                renderAutofillDevices(filterAutofillByOS(allAutofillDevices));
            })
            .catch(err => {
                console.error('Failed to load devices:', err);
                allAutofillDevices = [];
                renderAutofillDevices([]);
            });
    }

    function searchAutofillDevices() {
        const input = document.getElementById('autofill-device-search').value.trim();
        if (!input) {
            showAllAutofillDevices();
            return;
        }
        const field = detectFieldType(input);
        fetch('/admin/api/device-search', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({field, value: input})
        })
        .then(r => r.json())
        .then(devices => {
            allAutofillDevices = Array.isArray(devices) ? devices : [];
            renderAutofillDevices(filterAutofillByOS(allAutofillDevices));
        })
        .catch(err => {
            console.error('Search failed:', err);
            allAutofillDevices = [];
            renderAutofillDevices([]);
        });
    }

    function filterAutofillByOS(devices) {
        const filterEl = document.getElementById('autofill-os-filter');
        if (!filterEl) return devices;
        const filter = filterEl.value;
        if (filter === 'all') return devices;
        return devices.filter(d => d.os === filter);
    }

    document.getElementById('autofill-os-filter')?.addEventListener('change', function() {
        renderAutofillDevices(filterAutofillByOS(allAutofillDevices));
    });

    function renderAutofillDevices(devices) {
        const tbody = document.getElementById('autofill-device-tbody');
        if (!tbody) return;

        if (!devices.length) {
            tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:#4b5563;">No devices found</td></tr>';
            return;
        }

        let html = '';
        devices.forEach(dev => {
            const statusClass = dev.status || 'offline';
            // DEP is stored as 'enabled'/'disabled' or '0'/'1'
            const depVal = (dev.dep === 'enabled' || dev.dep === '1' || dev.dep === 1) ? 'Yes' : 'No';
            // Store device data as JSON in data attribute for autofill
            const devJson = JSON.stringify(dev).replace(/'/g, "\\'").replace(/"/g, '&quot;');
            html += `<tr onclick="selectAutofillDevice(this)" data-device="${devJson}">
                <td><span class="status-dot ${statusClass}"></span></td>
                <td style="font-size:0.85em;">${dev.uuid || '-'}</td>
                <td>${dev.hostname || '-'}</td>
                <td>${dev.serial || '-'}</td>
                <td>${dev.os || '-'}</td>
                <td>${dev.account || '-'}</td>
                <td>${dev.manifest || '-'}</td>
                <td>${depVal}</td>
            </tr>`;
        });
        tbody.innerHTML = html;
    }

    function selectAutofillDevice(row) {
        // Clear previous selection
        document.querySelectorAll('#autofill-device-table tr').forEach(r => r.classList.remove('selected'));
        row.classList.add('selected');

        // Parse device data from row
        const devJson = row.getAttribute('data-device');
        const dev = JSON.parse(devJson.replace(/&quot;/g, '"'));

        // Auto-fill form fields
        const uuidField = document.getElementById('uuid');
        const serialField = document.getElementById('serial');
        const hostnameField = document.getElementById('hostname');
        const osField = document.getElementById('os');
        const manifestField = document.getElementById('manifest');
        const accountField = document.getElementById('account');
        const depField = document.getElementById('dep');

        if (uuidField) uuidField.value = dev.uuid || '';
        if (serialField) serialField.value = dev.serial || '';
        if (hostnameField) hostnameField.value = dev.hostname || '';
        if (osField) osField.value = dev.os || '';
        if (manifestField) manifestField.value = dev.manifest || '';
        if (accountField) accountField.value = dev.account || '';
        if (depField) depField.value = (dev.dep === 'enabled' || dev.dep === '1' || dev.dep === 1) ? '1' : '0';

        // Show selected info panel
        const infoEl = document.getElementById('autofill-selected-info');
        if (infoEl) {
            infoEl.innerHTML = '<strong>Selected:</strong> ' + (dev.hostname || dev.serial) + ' | ' + dev.uuid +
                ' <button type="button" onclick="clearAutofillDevice()" style="margin-left:15px;padding:3px 10px;cursor:pointer;">Clear</button>';
            infoEl.classList.add('visible');
        }
    }

    function clearAutofillDevice() {
        document.querySelectorAll('#autofill-device-table tr').forEach(r => r.classList.remove('selected'));

        // Clear form fields
        const fields = ['uuid', 'serial', 'hostname', 'os', 'manifest', 'account', 'dep'];
        fields.forEach(f => {
            const el = document.getElementById(f);
            if (el) el.value = '';
        });

        const infoEl = document.getElementById('autofill-selected-info');
        if (infoEl) {
            infoEl.innerHTML = '';
            infoEl.classList.remove('visible');
        }
    }

    function executeCommand(event) {
        event.preventDefault();
        const form = document.getElementById('commandForm');
        const formData = new FormData(form);

        if (dangerLevel === 'critical') {
            pendingFormData = formData;
            document.getElementById('confirmOverlay').classList.add('show');
            return false;
        }

        submitCommand(formData);
        return false;
    }

    function closeConfirm() {
        document.getElementById('confirmOverlay').classList.remove('show');
        document.getElementById('confirmInput').value = '';
        pendingFormData = null;
    }

    function confirmExecute() {
        const input = document.getElementById('confirmInput').value;
        if (input !== confirmText) {
            alert('Confirmation text does not match. Please type: ' + confirmText);
            return;
        }
        closeConfirm();
        submitCommand(pendingFormData);
    }

    function submitCommand(formData) {
        document.getElementById('loading').style.display = 'block';
        document.getElementById('output-container').innerHTML = '';

        const params = {};
        for (let [key, value] of formData.entries()) {
            if (key === 'devices') {
                if (!params.devices) params.devices = [];
                params.devices.push(value);
            } else {
                params[key] = value;
            }
        }

        fetch('/admin/execute', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({command: commandId, params: params})
        })
        .then(r => r.json())
        .then(data => {
            document.getElementById('loading').style.display = 'none';

            let outputHtml = '<div class="output-panel ' + (data.success ? 'success' : 'error') + '">';

            // Show script output
            outputHtml += '<strong>Script Output:</strong>\\n';
            if (data.output) {
                outputHtml += escapeHtml(data.output);
            } else if (data.error) {
                outputHtml += 'Error: ' + escapeHtml(data.error);
            } else if (data.results) {
                data.results.forEach(r => {
                    outputHtml += '=== ' + r.device + ' ===\\n';
                    outputHtml += (r.success ? 'SUCCESS' : 'FAILED') + '\\n';
                    outputHtml += escapeHtml(r.output || r.error || '') + '\\n\\n';
                    if (r.webhook_response) {
                        outputHtml += '\\n<strong>Device Response:</strong>\\n';
                        outputHtml += formatWebhookResponse(r.webhook_response);
                    }
                });
            }

            // Show webhook response if available
            if (data.webhook_response) {
                outputHtml += '\\n\\n<strong>Device Response (webhook):</strong>\\n';
                outputHtml += formatWebhookResponse(data.webhook_response);
            }

            outputHtml += '</div>';
            document.getElementById('output-container').innerHTML = outputHtml;
        })
        .catch(err => {
            document.getElementById('loading').style.display = 'none';
            document.getElementById('output-container').innerHTML =
                '<div class="output-panel error">Request failed: ' + escapeHtml(err.toString()) + '</div>';
        });
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    function formatWebhookResponse(webhook) {
        if (!webhook) return 'No response received from device.\\n';

        // Always show full raw webhook block
        if (webhook.raw) {
            // Clean up the raw output - remove timestamps and [INFO] prefix for readability
            let lines = webhook.raw.split('\\n');
            let cleanLines = lines.map(line => {
                // Remove timestamp and [INFO] prefix: "2025-12-12 21:15:01,181 [INFO]   Status: Acknowledged"
                let match = line.match(/^\\d{4}-\\d{2}-\\d{2}\\s+\\d{2}:\\d{2}:\\d{2},\\d+\\s+\\[INFO\\]\\s*(.*)$/);
                if (match) {
                    return match[1];
                }
                return line;
            });
            return escapeHtml(cleanLines.join('\\n'));
        }

        return 'No response received from device.\\n';
    }
    </script>
</body>
</html>
'''

ADMIN_HISTORY_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Execution History - NanoHUB Admin</title>
    <link rel="stylesheet" href="/static/dashboard.css">
    <link rel="shortcut icon" href="/static/favicon.ico">
    <style>
        .admin-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
        }
        .nav-tabs { margin-bottom: 15px; }
        .nav-tabs a { margin-right: 8px; }
        .nav-tabs a.active { background: #e89898; color: white; }
        .status-success { color: #27ae60; font-weight: bold; }
        .status-failed { color: #e92128; font-weight: bold; }
    </style>
</head>
<body>
    <div id="wrap">
        <div style="display: flex; justify-content: center; align-items: center;">
            <img id="logo" src="/static/logo.svg" alt="Logo"/>
        </div>
        <h1>Execution History</h1>

        <div class="panel">
            <div class="admin-header">
                <div class="panel-title" style="margin:0;">Recent Commands</div>
                <a href="/admin" class="btn">Back to Commands</a>
            </div>

            <div class="nav-tabs">
                <a href="/admin" class="btn">Commands</a>
                <a href="/admin/history" class="btn active">History</a>
                <a href="/admin/profiles" class="btn">Profiles</a>
            </div>

            <table>
                <thead>
                    <tr>
                        <th>Timestamp</th>
                        <th>User</th>
                        <th>Command</th>
                        <th>Parameters</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody>
                    {% for entry in history %}
                    <tr>
                        <td>{{ entry.timestamp }}</td>
                        <td>{{ entry.user }}</td>
                        <td>{{ entry.command }}</td>
                        <td style="max-width:250px;overflow:hidden;text-overflow:ellipsis;font-size:0.85em;">
                            {{ entry.params | tojson }}
                        </td>
                        <td class="{% if entry.success %}status-success{% else %}status-failed{% endif %}">
                            {% if entry.success %}Success{% else %}Failed{% endif %}
                        </td>
                    </tr>
                    {% endfor %}
                    {% if not history %}
                    <tr>
                        <td colspan="5" style="text-align:center;color:#4b5563;">No execution history found</td>
                    </tr>
                    {% endif %}
                </tbody>
            </table>
        </div>
    </div>
</body>
</html>
'''

ADMIN_PROFILES_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Manage Profiles - NanoHUB Admin</title>
    <link rel="stylesheet" href="/static/dashboard.css">
    <link rel="shortcut icon" href="/static/favicon.ico">
    <style>
        .admin-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
        }
        .nav-tabs { margin-bottom: 15px; }
        .nav-tabs a { margin-right: 8px; }
        .nav-tabs a.active { background: #e89898; color: white; }
        .profile-section {
            margin-bottom: 25px;
            text-align: left;
        }
        .profile-section h3 {
            margin: 0 0 10px 0;
            color: #21243b;
            border-bottom: 2px solid #e7eaf2;
            padding-bottom: 8px;
        }
        .profile-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
            gap: 10px;
        }
        .profile-card {
            background: #f7f8fa;
            border-radius: 5px;
            padding: 10px 12px;
            font-size: 0.9em;
        }
        .profile-name {
            font-weight: 500;
            color: #21243b;
            word-break: break-all;
        }
        .profile-path {
            font-size: 0.8em;
            color: #4b5563;
            word-break: break-all;
        }
    </style>
</head>
<body>
    <div id="wrap">
        <div style="display: flex; justify-content: center; align-items: center;">
            <img id="logo" src="/static/logo.svg" alt="Logo"/>
        </div>
        <h1>Manage Profiles</h1>

        <div class="panel">
            <div class="admin-header">
                <div class="panel-title" style="margin:0;">Available Signed Profiles</div>
                <a href="/admin" class="btn">Back to Commands</a>
            </div>

            <div class="nav-tabs">
                <a href="/admin" class="btn">Commands</a>
                <a href="/admin/history" class="btn">History</a>
                <a href="/admin/profiles" class="btn active">Profiles</a>
            </div>

            <div class="profile-section">
                <h3>System Profiles ({{ profiles.system | length }})</h3>
                <div class="profile-grid">
                    {% for profile in profiles.system %}
                    <div class="profile-card">
                        <div class="profile-name">{{ profile.name }}</div>
                        <div class="profile-path">{{ profile.path }}</div>
                    </div>
                    {% endfor %}
                    {% if not profiles.system %}
                    <div style="color:#4b5563;">No system profiles found</div>
                    {% endif %}
                </div>
            </div>

            <div class="profile-section">
                <h3>WireGuard Profiles ({{ profiles.wireguard | length }})</h3>
                <div class="profile-grid">
                    {% for profile in profiles.wireguard %}
                    <div class="profile-card">
                        <div class="profile-name">{{ profile.name }}</div>
                        <div class="profile-path">{{ profile.rel_path or profile.path }}</div>
                    </div>
                    {% endfor %}
                    {% if not profiles.wireguard %}
                    <div style="color:#4b5563;">No WireGuard profiles found</div>
                    {% endif %}
                </div>
            </div>

            <div style="margin-top:20px;padding:15px;background:#f7f8fa;border-radius:5px;text-align:left;">
                <strong>Profile Directories:</strong>
                <ul style="margin:8px 0 0 0;padding-left:20px;color:#4b5563;">
                    <li>System: /opt/nanohub/profiles/</li>
                    <li>WireGuard: /opt/nanohub/profiles/wireguard_configs/</li>
                </ul>
                <p style="margin:8px 0 0 0;font-size:0.9em;color:#4b5563;">
                    Only signed profiles (*.signed.mobileconfig) are available for installation.
                </p>
            </div>
        </div>
    </div>
</body>
</html>
'''


# =============================================================================
# ROUTES
# =============================================================================

@admin_bp.route('/')
@login_required_admin
def admin_dashboard():
    """Admin panel dashboard"""
    user = session.get('user', {})
    categories = get_commands_by_category()

    return render_template_string(
        ADMIN_DASHBOARD_TEMPLATE,
        user=user,
        categories=categories,
        can_access=check_role_permission
    )


@admin_bp.route('/command/<cmd_id>')
@login_required_admin
def admin_command(cmd_id):
    """Command execution page"""
    user = session.get('user', {})
    command = get_command(cmd_id)

    if not command:
        return redirect(url_for('admin.admin_dashboard'))

    if not check_role_permission(user.get('role'), command.get('min_role', 'admin')):
        return render_template_string('''
            <h1>Access Denied</h1>
            <p>You do not have permission to execute this command.</p>
            <a href="/admin">Back to Admin</a>
        '''), 403

    profiles = get_profiles_by_category()

    # Check if command has 'devices' type parameter (multi-select)
    has_devices_param = any(p['type'] == 'devices' for p in command.get('parameters', []))

    return render_template_string(
        ADMIN_COMMAND_TEMPLATE,
        user=user,
        command=command,
        cmd_id=cmd_id,
        profiles=profiles,
        has_devices_param=has_devices_param
    )


@admin_bp.route('/execute', methods=['POST'])
@login_required_admin
def admin_execute():
    """Execute a command"""
    user = session.get('user', {})
    data = request.get_json()

    cmd_id = data.get('command')
    params = data.get('params', {})

    command = get_command(cmd_id)
    if not command:
        return jsonify({'success': False, 'error': 'Unknown command'})

    if not check_role_permission(user.get('role'), command.get('min_role', 'admin')):
        return jsonify({'success': False, 'error': 'Insufficient permissions'})

    # Check for bulk operation
    # Some commands handle device iteration internally (native bulk commands)
    native_bulk_commands = ['bulk_schedule_os_update', 'bulk_new_device_installation']
    if 'devices' in params and isinstance(params.get('devices'), list) and cmd_id not in native_bulk_commands:
        results = execute_bulk_command(cmd_id, params['devices'], params, user)
        return jsonify({'success': True, 'results': results})

    result = execute_command(cmd_id, params, user)
    return jsonify(result)


@admin_bp.route('/history')
@login_required_admin
def admin_history():
    """View execution history"""
    user = session.get('user', {})
    history = []

    try:
        if os.path.exists(AUDIT_LOG_PATH):
            with open(AUDIT_LOG_PATH, 'r') as f:
                lines = f.readlines()[-100:]
                for line in reversed(lines):
                    try:
                        entry = json.loads(line.strip())
                        history.append(entry)
                    except json.JSONDecodeError:
                        continue
    except Exception as e:
        logger.error(f"Failed to read audit log: {e}")

    return render_template_string(
        ADMIN_HISTORY_TEMPLATE,
        user=user,
        history=history
    )


@admin_bp.route('/profiles')
@login_required_admin
def admin_profiles():
    """Manage profiles page"""
    user = session.get('user', {})
    profiles = get_profiles_by_category()

    return render_template_string(
        ADMIN_PROFILES_TEMPLATE,
        user=user,
        profiles=profiles
    )


@admin_bp.route('/api/commands')
@login_required_admin
def api_commands():
    """Get all commands (JSON)"""
    user = session.get('user', {})
    user_role = user.get('role', 'report')

    available_commands = {}
    for cmd_id, cmd in COMMANDS.items():
        if check_role_permission(user_role, cmd.get('min_role', 'admin')):
            available_commands[cmd_id] = cmd

    return jsonify(available_commands)


@admin_bp.route('/api/devices')
@login_required_admin
def api_devices():
    """Get devices list (JSON), filtered by user's manifest_filter if any"""
    user = session.get('user', {})
    manifest_filter = user.get('manifest_filter')  # e.g. 'bel-%' for bel-admin
    devices = get_devices_list(manifest_filter=manifest_filter)
    return jsonify(devices)


@admin_bp.route('/api/device-search', methods=['POST'])
@login_required_admin
def api_device_search():
    """Search devices (JSON), filtered by user's manifest_filter if any"""
    user = session.get('user', {})
    manifest_filter = user.get('manifest_filter')

    data = request.get_json()
    field = data.get('field', 'hostname')
    value = data.get('value', '')

    # Sanitize field name
    allowed_fields = ['uuid', 'serial', 'hostname']
    if field not in allowed_fields:
        field = 'hostname'

    devices = search_devices(field, value, manifest_filter=manifest_filter)
    return jsonify(devices)


@admin_bp.route('/api/profiles')
@login_required_admin
def api_profiles():
    """Get profiles list (JSON)"""
    profiles = get_profiles_by_category()
    return jsonify(profiles)
