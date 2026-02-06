"""
NanoHUB Admin - Command Execution Module
=========================================

This module contains all command execution functions:
- execute_command: Main command dispatcher
- execute_bulk_command: Bulk command execution
- execute_device_add/update/delete: Device CRUD operations
- execute_manage_applications: Application management
- execute_bulk_*: Bulk operations
- execute_*: Various command handlers

Moved from nanohub_admin_core.py for better modularity.
"""

import os
import re
import json
import base64
import urllib.request
import urllib.error
import logging
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

from config import Config
from db_utils import db, devices, required_profiles

# Database config for shell commands (mysql CLI)
DB_CONFIG = Config.DB

from command_registry import COMMANDS_DIR, PROFILE_DIRS, get_command, check_role_permission
from webhook_poller import poll_webhook_for_command

from .core import (
    audit_log,
    validate_device_access,
    sanitize_param,
    normalize_devices_param,
    extract_command_uuid_from_output,
)
from .profiles import execute_manage_profiles

logger = logging.getLogger(__name__)

# Thread pool for parallel command execution
thread_pool = ThreadPoolExecutor(max_workers=10)


def execute_command(cmd_id, params, user_info):
    """Execute a command script with parameters"""
    cmd = get_command(cmd_id)
    if not cmd:
        return {'success': False, 'error': f'Unknown command: {cmd_id}'}

    user_role = user_info.get('role', 'report')
    if not check_role_permission(user_role, cmd.get('min_role', 'admin')):
        return {'success': False, 'error': 'Insufficient permissions'}

    # Validate device access for users with manifest_filter (e.g., site-admin)
    udid = params.get('udid') or params.get('uuid')
    if udid and user_info.get('manifest_filter'):
        if not validate_device_access(udid, user_info):
            return {'success': False, 'error': 'Access denied: You can only manage devices with your assigned manifest'}

    # Determine script directory (use custom if specified)
    script_dir = cmd.get('script_dir', COMMANDS_DIR)
    script_path = os.path.join(script_dir, cmd['script'])
    # Skip script existence check for internal commands (start with '_internal')
    if not cmd['script'].startswith('_internal') and not os.path.exists(script_path):
        return {'success': False, 'error': f'Script not found: {cmd["script"]}'}

    # Build command arguments
    args = [script_path]

    # Special handling for db_device_query
    if cmd_id == 'db_device_query':
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

    # Special handling for manage_applications (internal CRUD operations)
    elif cmd_id == 'manage_applications':
        return execute_manage_applications(params, user_info)

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

    # Special handling for bulk_install_application - iterate over devices and call install_application
    elif cmd_id == 'bulk_install_application':
        return execute_bulk_install_application(params, user_info)

    # Special handling for bulk_remote_desktop - enable/disable RD on all macOS devices
    elif cmd_id == 'bulk_remote_desktop':
        return execute_bulk_remote_desktop(params, user_info)

    # ==========================================================================
    # CONSOLIDATED COMMAND HANDLERS
    # ==========================================================================

    # Manage Profiles (install/remove/list on one or more devices)
    elif cmd_id == 'manage_profiles':
        return execute_manage_profiles(params, user_info)

    # Manage DDM Sets (assign/remove on one or more devices)
    elif cmd_id == 'manage_ddm_sets':
        return execute_manage_ddm_sets(params, user_info)

    # DDM Force Sync (bulk push to devices)
    elif cmd_id == 'ddm_force_sync':
        return execute_ddm_force_sync(params, user_info)

    # Install Application (on one or more devices)
    elif cmd_id == 'install_application':
        return execute_install_application(params, user_info)

    # Device Action (lock/unlock/restart/erase/clear_passcode)
    elif cmd_id == 'device_action':
        return execute_device_action(params, user_info)

    # Update Inventory (bulk inventory update)
    elif cmd_id == 'update_inventory':
        return execute_update_inventory(params, user_info)

    # Schedule OS Update (on one or more devices)
    elif cmd_id == 'schedule_os_update':
        return execute_schedule_os_update(params, user_info)

    # Manage Remote Desktop (enable/disable on one or more devices)
    elif cmd_id == 'manage_remote_desktop':
        return execute_manage_remote_desktop(params, user_info)

    # Manage VPP App (install/remove for iOS/macOS)
    elif cmd_id == 'manage_vpp_app':
        return execute_manage_vpp_app(params, user_info)

    # Manage Command Queue (show/clear)
    elif cmd_id == 'manage_command_queue':
        return execute_manage_command_queue(params, user_info)

    # MDM Analyzer - needs --json flag for non-interactive mode
    elif cmd_id == 'mdm_analyzer':
        udid = sanitize_param(params.get('udid', ''))
        if not udid:
            return {'success': False, 'error': 'Missing required parameter: udid'}
        script_path = os.path.join(COMMANDS_DIR, 'mdm_analyzer')
        try:
            env = os.environ.copy()
            env['PATH'] = '/usr/local/bin:/usr/bin:/bin:' + env.get('PATH', '')
            result = subprocess.run(
                [script_path, udid, '--json'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=60,
                cwd=COMMANDS_DIR,
                env=env
            )
            return {
                'success': result.returncode == 0,
                'output': result.stdout + result.stderr,
                'return_code': result.returncode
            }
        except subprocess.TimeoutExpired:
            return {'success': False, 'error': 'Command timed out'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    # Default parameter handling
    else:
        for param_def in cmd.get('parameters', []):
            param_name = param_def['name']
            param_value = params.get(param_name)

            # Apply default value if not provided
            if not param_value and param_def.get('default'):
                param_value = param_def['default']

            if param_def.get('required') and not param_value:
                return {'success': False, 'error': f'Missing required parameter: {param_name}'}

            if param_value:
                # Handle 'devices' type - convert list to comma-separated string
                if param_def['type'] == 'devices' and isinstance(param_value, list):
                    param_value = ','.join([sanitize_param(str(d)) for d in param_value if d])
                else:
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
            timeout=300,  # Extended for bulk operations
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
        return {'success': False, 'error': 'Command timed out after 300 seconds'}

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

        future = thread_pool.submit(execute_command, cmd_id, device_params, user_info)
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



# ==============================================================================
# NOTE: Database/list functions moved to nanohub_admin.core
# ==============================================================================

# =============================================================================
# INTERNAL DEVICE CRUD OPERATIONS
# =============================================================================

MYSQL_BIN = '/usr/bin/mysql'

def execute_device_add(params, user_info):
    """Add a new device to inventory (direct SQL)"""
    uuid_val = params.get('uuid', '').strip()
    serial = params.get('serial', '').strip()
    os_type = params.get('os', '').strip()
    hostname = params.get('hostname', '').strip()
    manifest = params.get('manifest', 'default').strip()
    account = params.get('account', 'default').strip()
    dep = params.get('dep', '0').strip()

    # Validate required fields
    if not uuid_val or not serial or not os_type or not hostname:
        return {'success': False, 'error': 'Missing required fields: uuid, serial, os, hostname'}

    # Validate manifest for users with manifest_filter (e.g., site-admin can only add site-* devices)
    manifest_filter = user_info.get('manifest_filter')
    if manifest_filter:
        allowed = False
        if manifest_filter.startswith('%') and manifest_filter.endswith('%'):
            # '%text%' - contains
            substring = manifest_filter[1:-1]
            allowed = substring in manifest
            pattern_desc = f'containing "{substring}"'
        elif manifest_filter.endswith('%'):
            # 'prefix%' - starts with
            prefix = manifest_filter[:-1]
            allowed = manifest.startswith(prefix)
            pattern_desc = f'starting with "{prefix}"'
        elif manifest_filter.startswith('%'):
            # '%suffix' - ends with
            suffix = manifest_filter[1:]
            allowed = manifest.endswith(suffix)
            pattern_desc = f'ending with "{suffix}"'
        else:
            allowed = manifest == manifest_filter
            pattern_desc = f'equal to "{manifest_filter}"'

        if not allowed:
            return {'success': False, 'error': f'Access denied: You can only add devices with manifest {pattern_desc}'}

    # Validate UUID/UDID format (macOS UUID or iOS UDID)
    # macOS: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx (36 chars)
    # iOS new: 00008xxx-xxxxxxxxxxxxxxxx (25 chars)
    # iOS old: 40 hex chars without hyphens
    uuid_patterns = [
        r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$',  # macOS UUID
        r'^[a-f0-9]{8}-[a-f0-9]{16}$',  # iOS UDID (new format)
        r'^[a-f0-9]{40}$',  # iOS UDID (old format)
    ]
    if not any(re.match(p, uuid_val, re.IGNORECASE) for p in uuid_patterns):
        return {'success': False, 'error': 'Invalid UUID/UDID format'}

    try:
        db.execute(
            """INSERT INTO device_inventory (uuid, serial, os, hostname, manifest, account, dep)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (uuid_val, serial, os_type, hostname, manifest, account, dep)
        )
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

    except Exception as e:
        error_msg = str(e)
        if 'Duplicate entry' in error_msg:
            error_msg = f'Device with UUID {uuid_val} already exists'
        logger.error(f"Device add failed: {e}")
        audit_log(
            user=user_info.get('username'),
            action='device_add',
            command='device_add',
            params=params,
            result=error_msg,
            success=False
        )
        return {'success': False, 'error': error_msg}


def execute_device_update(params, user_info):
    """Update existing device in inventory (direct SQL)"""
    uuid_val = params.get('uuid', '').strip()

    if not uuid_val:
        return {'success': False, 'error': 'Missing required field: uuid'}

    # Build SET clause with parameterized values
    set_parts = []
    values = []
    updated_fields = []

    if params.get('serial'):
        set_parts.append("serial = %s")
        values.append(params['serial'].strip())
        updated_fields.append('serial')
    if params.get('os'):
        set_parts.append("os = %s")
        values.append(params['os'].strip())
        updated_fields.append('os')
    if params.get('hostname'):
        set_parts.append("hostname = %s")
        values.append(params['hostname'].strip())
        updated_fields.append('hostname')
    if params.get('manifest'):
        set_parts.append("manifest = %s")
        values.append(params['manifest'].strip())
        updated_fields.append('manifest')
    if params.get('account'):
        set_parts.append("account = %s")
        values.append(params['account'].strip())
        updated_fields.append('account')
    if params.get('dep') is not None and params.get('dep') != '':
        set_parts.append("dep = %s")
        values.append(params['dep'].strip())
        updated_fields.append('dep')

    if not set_parts:
        return {'success': False, 'error': 'No fields to update provided'}

    # Fetch old manifest+os before UPDATE (for DDM set reassignment)
    old_device = None
    if 'manifest' in updated_fields:
        old_device = db.query_one(
            "SELECT manifest, os FROM device_inventory WHERE uuid = %s", (uuid_val,)
        )

    # Add uuid to params for WHERE clause
    values.append(uuid_val)

    sql = f"UPDATE device_inventory SET {', '.join(set_parts)} WHERE uuid = %s"

    try:
        db.execute(sql, tuple(values))

        # If manifest changed, reassign DDM sets
        ddm_output_lines = []
        if old_device and 'manifest' in updated_fields:
            new_manifest = params['manifest'].strip()
            old_manifest = old_device['manifest']
            device_os = params.get('os', '').strip() if params.get('os') else old_device['os']

            if old_manifest != new_manifest:
                def run_ddm_script(script_path, *args):
                    """Execute a DDM script directly"""
                    if not os.path.exists(script_path):
                        return False, f"Script not found: {script_path}"
                    full_args = [script_path] + list(args)
                    try:
                        env = os.environ.copy()
                        env['PATH'] = '/usr/local/bin:/usr/bin:/bin:' + env.get('PATH', '')
                        result = subprocess.run(full_args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                                text=True, timeout=60, env=env)
                        if result.returncode == 0:
                            return True, result.stdout.strip() if result.stdout else 'OK'
                        else:
                            return False, result.stderr.strip() if result.stderr else 'Command failed'
                    except subprocess.TimeoutExpired:
                        return False, 'Command timed out'
                    except Exception as e:
                        return False, str(e)

                # Remove old DDM sets
                old_results = _remove_ddm_sets_for_device(uuid_val, old_manifest, device_os, run_ddm_script)
                for set_name, success, msg in old_results:
                    if success:
                        ddm_output_lines.append(f"  DDM set '{set_name}' removed (old manifest: {old_manifest})")
                    else:
                        ddm_output_lines.append(f"  DDM set '{set_name}' remove failed: {msg}")

                # Assign new DDM sets
                new_results = _assign_ddm_sets_for_device(uuid_val, new_manifest, device_os, run_ddm_script)
                for set_name, success, msg in new_results:
                    if success:
                        ddm_output_lines.append(f"  DDM set '{set_name}' assigned (new manifest: {new_manifest})")
                    else:
                        ddm_output_lines.append(f"  DDM set '{set_name}' assign failed: {msg}")

        audit_log(
            user=user_info.get('username'),
            action='device_update',
            command='device_update',
            params=params,
            result=f'Device {uuid_val} updated successfully',
            success=True
        )

        output = f'Device updated successfully:\n  UUID: {uuid_val}\n  Updated fields: {", ".join(updated_fields)}'
        if ddm_output_lines:
            output += '\n\nDDM Set Changes:\n' + '\n'.join(ddm_output_lines)

        return {
            'success': True,
            'output': output
        }

    except Exception as e:
        logger.error(f"Device update failed: {e}")
        audit_log(
            user=user_info.get('username'),
            action='device_update',
            command='device_update',
            params=params,
            result=str(e),
            success=False
        )
        return {'success': False, 'error': str(e)}


def execute_device_delete(params, user_info):
    """Delete device from inventory (direct SQL)"""
    uuid_val = params.get('uuid', '').strip()

    if not uuid_val:
        return {'success': False, 'error': 'Missing required field: uuid'}

    # First get device info for logging
    device_info = "unknown"
    try:
        row = db.query_one("SELECT hostname, serial FROM device_inventory WHERE uuid = %s", (uuid_val,))
        if row:
            device_info = f"{row.get('hostname', '')} ({row.get('serial', '')})"
    except Exception:
        pass

    # Delete the device
    try:
        db.execute("DELETE FROM device_inventory WHERE uuid = %s", (uuid_val,))
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

    except Exception as e:
        logger.error(f"Device delete failed: {e}")
        audit_log(
            user=user_info.get('username'),
            action='device_delete',
            command='device_delete',
            params=params,
            result=str(e),
            success=False
        )
        return {'success': False, 'error': str(e)}


def execute_manage_applications(params, user_info):
    """Manage applications in required_applications table (list, add, edit, remove)"""
    action = params.get('action', 'list')

    if action == 'list':
        # List all applications grouped by manifest
        apps = db.query_all("""
            SELECT id, manifest, os, app_name, manifest_url, install_order
            FROM required_applications
            ORDER BY manifest, os, install_order
        """)

        if not apps:
            return {'success': True, 'output': 'No applications defined.'}

        # Group by manifest
        grouped = {}
        for app in apps:
            key = f"{app['manifest']} ({app['os']})"
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(app)

        output_lines = ["=" * 70, "APPLICATIONS BY MANIFEST", "=" * 70, ""]
        for manifest_key, app_list in grouped.items():
            output_lines.append(f"[{manifest_key}]")
            for app in app_list:
                output_lines.append(f"  {app['install_order']}. {app['app_name']}")
                output_lines.append(f"     URL: {app['manifest_url']}")
                output_lines.append(f"     ID: {app['id']}")
            output_lines.append("")

        output_lines.append(f"Total: {len(apps)} applications")
        return {'success': True, 'output': '\n'.join(output_lines)}

    elif action == 'add':
        # Add new application
        manifest = params.get('manifest', '').strip()
        os_type = params.get('os', '').strip()
        app_name = params.get('app_name', '').strip()
        manifest_url = params.get('manifest_url', '').strip()
        install_order = params.get('install_order', '1').strip()

        if not manifest or not os_type or not app_name or not manifest_url:
            return {'success': False, 'error': 'Missing required fields: manifest, os, app_name, manifest_url'}

        try:
            install_order = int(install_order)
        except Exception:
            install_order = 1

        try:
            db.execute("""
                INSERT INTO required_applications (manifest, os, app_name, manifest_url, install_order)
                VALUES (%s, %s, %s, %s, %s)
            """, (manifest, os_type, app_name, manifest_url, install_order))

            audit_log(
                user=user_info.get('username'),
                action='manage_applications',
                command='add',
                params=params,
                result=f'Added {app_name} to {manifest}/{os_type}',
                success=True
            )

            return {
                'success': True,
                'output': f'Application added successfully:\n  Name: {app_name}\n  Manifest: {manifest}\n  OS: {os_type}\n  URL: {manifest_url}\n  Order: {install_order}'
            }
        except Exception as e:
            return {'success': False, 'error': f'Failed to add application: {e}'}

    elif action == 'edit':
        # Edit existing application
        app_id = params.get('app_id', '').strip()
        if not app_id:
            return {'success': False, 'error': 'Missing required field: app_id (select an application)'}

        # Get current values
        current = db.query_one("SELECT * FROM required_applications WHERE id = %s", (app_id,))
        if not current:
            return {'success': False, 'error': f'Application not found: {app_id}'}

        # Build update with provided values (or keep existing)
        manifest = params.get('manifest', '').strip() or current['manifest']
        os_type = params.get('os', '').strip() or current['os']
        app_name = params.get('app_name', '').strip() or current['app_name']
        manifest_url = params.get('manifest_url', '').strip() or current['manifest_url']
        install_order = params.get('install_order', '').strip()
        if install_order:
            try:
                install_order = int(install_order)
            except Exception:
                install_order = current['install_order']
        else:
            install_order = current['install_order']

        try:
            db.execute("""
                UPDATE required_applications
                SET manifest = %s, os = %s, app_name = %s, manifest_url = %s, install_order = %s
                WHERE id = %s
            """, (manifest, os_type, app_name, manifest_url, install_order, app_id))

            audit_log(
                user=user_info.get('username'),
                action='manage_applications',
                command='edit',
                params=params,
                result=f'Updated application ID {app_id}',
                success=True
            )

            return {
                'success': True,
                'output': f'Application updated successfully:\n  ID: {app_id}\n  Name: {app_name}\n  Manifest: {manifest}\n  OS: {os_type}\n  URL: {manifest_url}\n  Order: {install_order}'
            }
        except Exception as e:
            return {'success': False, 'error': f'Failed to update application: {e}'}

    elif action == 'remove':
        # Remove application
        app_id = params.get('app_id', '').strip()
        if not app_id:
            return {'success': False, 'error': 'Missing required field: app_id (select an application)'}

        # Get app info for logging
        app = db.query_one("SELECT app_name, manifest, os FROM required_applications WHERE id = %s", (app_id,))
        if not app:
            return {'success': False, 'error': f'Application not found: {app_id}'}

        try:
            db.execute("DELETE FROM required_applications WHERE id = %s", (app_id,))

            audit_log(
                user=user_info.get('username'),
                action='manage_applications',
                command='remove',
                params=params,
                result=f'Removed {app["app_name"]} from {app["manifest"]}/{app["os"]}',
                success=True
            )

            return {
                'success': True,
                'output': f'Application removed successfully:\n  ID: {app_id}\n  Name: {app["app_name"]}\n  Manifest: {app["manifest"]}\n  OS: {app["os"]}'
            }
        except Exception as e:
            return {'success': False, 'error': f'Failed to remove application: {e}'}

    else:
        return {'success': False, 'error': f'Unknown action: {action}'}


def _assign_ddm_sets_for_device(uuid, manifest, os_type, run_command_fn):
    """Assign DDM sets based on manifest+OS from ddm_required_sets table.

    Args:
        uuid: Device UUID
        manifest: Device manifest name
        os_type: Device OS ('macos' or 'ios')
        run_command_fn: Callable(script_path, action, uuid, set_name) -> (success, output)

    Returns:
        List of (set_name, success, message) tuples.
    """
    results = []
    sets = db.query_all(
        """SELECT s.name FROM ddm_required_sets r
           JOIN ddm_sets s ON r.set_id = s.id
           WHERE r.manifest = %s AND r.os = %s""",
        (manifest, os_type)
    )
    if not sets:
        return results

    script = os.path.join(Config.DDM_SCRIPTS_DIR, 'ddm-assign-device.sh')
    for row in sets:
        set_name = row['name']
        success, output = run_command_fn(script, 'assign', uuid, set_name)
        results.append((set_name, success, output))
    return results


def _remove_ddm_sets_for_device(uuid, manifest, os_type, run_command_fn):
    """Remove DDM sets for a device based on manifest+OS from ddm_required_sets table.

    Args:
        uuid: Device UUID
        manifest: Device manifest name
        os_type: Device OS ('macos' or 'ios')
        run_command_fn: Callable(script_path, action, uuid, set_name) -> (success, output)

    Returns:
        List of (set_name, success, message) tuples.
    """
    results = []
    sets = db.query_all(
        """SELECT s.name FROM ddm_required_sets r
           JOIN ddm_sets s ON r.set_id = s.id
           WHERE r.manifest = %s AND r.os = %s""",
        (manifest, os_type)
    )
    if not sets:
        return results

    script = os.path.join(Config.DDM_SCRIPTS_DIR, 'ddm-assign-device.sh')
    for row in sets:
        set_name = row['name']
        success, output = run_command_fn(script, 'remove', uuid, set_name)
        results.append((set_name, success, output))
    return results


def execute_bulk_new_device_installation(params, user_info):
    """
    Execute new device installation workflow - DB driven.
    Reads profiles from required_profiles and apps from required_applications.
    """
    # Get parameters
    manifest = params.get('manifest', '')
    udid = sanitize_param(params.get('udid', ''))
    account_type = params.get('account_type', 'disabled')
    restrictions_type = params.get('restrictions_type', 'standard')
    selected_app_urls = params.get('applications', [])
    if isinstance(selected_app_urls, str):
        selected_app_urls = [selected_app_urls] if selected_app_urls else []
    install_wifi = params.get('install_wifi', 'no')
    install_filevault = params.get('install_filevault', 'no')
    install_directory_services = params.get('install_directory_services', 'no')
    hostname = sanitize_param(params.get('hostname', ''))
    install_wireguard = params.get('install_wireguard', 'no')
    wireguard_username = sanitize_param(params.get('wireguard_username', ''))

    if not manifest or not udid:
        return {'success': False, 'error': 'Missing required fields: manifest, udid'}

    # Get device info from DB to determine OS
    device = db.query_one("SELECT os FROM device_inventory WHERE uuid = %s", (udid,))
    if not device:
        return {'success': False, 'error': f'Device not found: {udid}'}

    platform = device['os']
    if platform not in ('macos', 'ios'):
        return {'success': False, 'error': f'Invalid device OS: {platform}'}

    output_lines = []
    errors = []
    commands_executed = 0
    WAIT_INTERVAL = 5

    profiles_dir = Config.PROFILES_DIR
    commands_dir = Config.COMMANDS_DIR

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

    def install_profile(profile_filename, profile_name=None):
        """Install a profile and wait"""
        profile_path = os.path.join(profiles_dir, profile_filename)
        display_name = profile_name or profile_filename
        output_lines.append(f"  Installing: {display_name}")
        success, msg = run_command('install_profile', udid, profile_path)
        if success:
            output_lines.append(f"    [OK]")
        else:
            output_lines.append(f"    [ERROR] {msg}")
            errors.append(f"{display_name}: {msg}")
        time.sleep(WAIT_INTERVAL)
        return success

    def install_application(app_name, manifest_url):
        """Install an application and wait"""
        output_lines.append(f"  Installing: {app_name}")
        success, msg = run_command('install_application', udid, manifest_url)
        if success:
            output_lines.append(f"    [OK]")
        else:
            output_lines.append(f"    [ERROR] {msg}")
            errors.append(f"{app_name}: {msg}")
        time.sleep(WAIT_INTERVAL)
        return success

    # Build variant filename mappings from DB
    def get_variant_profiles(variant_group):
        """Query variant profiles from DB for this manifest/os/group"""
        rows = db.query_all("""
            SELECT variant_value, profile_filename, profile_name
            FROM required_profiles
            WHERE manifest = %s AND os = %s AND variant_group = %s
        """, (manifest, platform, variant_group))
        return {r['variant_value']: r for r in (rows or [])}

    account_profiles = get_variant_profiles('account')
    restrictions_profiles = get_variant_profiles('restrictions')

    output_lines.append("=" * 60)
    output_lines.append(f"NEW DEVICE INSTALLATION")
    output_lines.append(f"Manifest: {manifest} | OS: {platform.upper()}")
    output_lines.append(f"Device: {udid}")
    output_lines.append("=" * 60)

    # =================================================================
    # PHASE 1: Base profiles from DB (is_optional=0, no variant_group)
    # =================================================================
    output_lines.append("\n[PHASE 1] Base profiles from DB...")

    base_profiles = db.query_all("""
        SELECT profile_filename, profile_name
        FROM required_profiles
        WHERE manifest = %s AND os = %s
          AND is_optional = 0
          AND variant_group IS NULL
          AND profile_filename IS NOT NULL
        ORDER BY install_order
    """, (manifest, platform))

    for p in base_profiles:
        install_profile(p['profile_filename'], p['profile_name'])

    # =================================================================
    # PHASE 2: Variant profiles (munki, account, restrictions)
    # =================================================================
    output_lines.append("\n[PHASE 2] Variant profiles...")

    # Munki profile (from DB based on manifest - variant_group='munki')
    munki_profile = db.query_one("""
        SELECT profile_filename, profile_name
        FROM required_profiles
        WHERE manifest = %s AND os = %s AND variant_group = 'munki'
    """, (manifest, platform))

    if munki_profile and munki_profile['profile_filename']:
        install_profile(munki_profile['profile_filename'], munki_profile['profile_name'])

    # Account profile (user choice: disabled/enabled/skip)
    if account_type != 'skip':
        account_data = account_profiles.get(account_type) or account_profiles.get('disabled')
        if account_data:
            install_profile(account_data['profile_filename'], account_data.get('profile_name') or f"Account ({account_type.capitalize()})")
        else:
            output_lines.append(f"  [WARNING] Account profile '{account_type}' not found in DB for {manifest}/{platform}")
    else:
        output_lines.append("  Account profile: SKIPPED")

    # Restrictions profile (macOS only, user choice: standard/icloud/levelc/skip)
    if platform == 'macos':
        if restrictions_type != 'skip':
            restrictions_data = restrictions_profiles.get(restrictions_type) or restrictions_profiles.get('standard')
            if restrictions_data:
                install_profile(restrictions_data['profile_filename'], restrictions_data.get('profile_name') or f"Restrictions ({restrictions_type.capitalize()})")
            else:
                output_lines.append(f"  [WARNING] Restrictions profile '{restrictions_type}' not found in DB for {manifest}/{platform}")
        else:
            output_lines.append("  Restrictions profile: SKIPPED")

    # =================================================================
    # PHASE 3: Applications (user selected from UI)
    # =================================================================
    output_lines.append("\n[PHASE 3] Applications...")

    if selected_app_urls:
        # Get app names for selected URLs
        apps = db.query_all("""
            SELECT app_name, manifest_url
            FROM required_applications
            WHERE manifest = %s AND os = %s
            ORDER BY install_order
        """, (manifest, platform))

        app_name_map = {app['manifest_url']: app['app_name'] for app in (apps or [])}

        for url in selected_app_urls:
            app_name = app_name_map.get(url, url.split('/')[-1])
            install_application(app_name, url)
    else:
        output_lines.append("  No applications selected")

    # =================================================================
    # PHASE 4: Optional profiles (user selected)
    # =================================================================
    optional_installed = []

    # Query optional profiles from DB
    optional_profiles = {
        'wifi': get_variant_profiles('wifi'),
        'filevault': get_variant_profiles('filevault'),
        'directory': get_variant_profiles('directory'),
    }

    # WiFi
    if install_wifi == 'yes':
        output_lines.append("\n[OPTIONAL] WiFi profile...")
        wifi_data = optional_profiles.get('wifi', {})
        # Get any variant (there's usually just one)
        wifi_profile = next(iter(wifi_data.values()), None) if wifi_data else None
        if wifi_profile:
            install_profile(wifi_profile['profile_filename'], wifi_profile.get('profile_name') or "WiFi")
            optional_installed.append('WiFi')
        else:
            output_lines.append(f"  [WARNING] WiFi profile not found in DB for {manifest}/{platform}")

    # FileVault (macOS only)
    if platform == 'macos' and install_filevault == 'yes':
        output_lines.append("\n[OPTIONAL] FileVault profile...")
        output_lines.append("  NOTE: Client (not admin) must be logged in!")
        fv_data = optional_profiles.get('filevault', {})
        fv_profile = next(iter(fv_data.values()), None) if fv_data else None
        if fv_profile:
            install_profile(fv_profile['profile_filename'], fv_profile.get('profile_name') or "FileVault")
            optional_installed.append('FileVault')
        else:
            output_lines.append(f"  [WARNING] FileVault profile not found in DB for {manifest}/{platform}")

    # Directory Services (macOS only)
    if platform == 'macos' and install_directory_services == 'yes':
        output_lines.append("\n[OPTIONAL] Directory Services...")
        if hostname:
            output_lines.append(f"  Setting hostname: {hostname}")
            success, msg = run_command('send_command', udid, 'hostname', hostname)
            if success:
                output_lines.append(f"    [OK] Hostname set")
            else:
                output_lines.append(f"    [WARNING] {msg}")
            time.sleep(WAIT_INTERVAL)
        ds_data = optional_profiles.get('directory', {})
        ds_profile = next(iter(ds_data.values()), None) if ds_data else None
        if ds_profile:
            install_profile(ds_profile['profile_filename'], ds_profile.get('profile_name') or "Directory Services")
            optional_installed.append('Directory Services')
        else:
            output_lines.append(f"  [WARNING] Directory Services profile not found in DB for {manifest}/{platform}")

    # WireGuard
    if install_wireguard == 'yes' and wireguard_username:
        output_lines.append("\n[OPTIONAL] WireGuard profile...")
        wg_base_path = os.path.join(profiles_dir, 'wireguard_configs')
        wg_pattern = os.path.join(wg_base_path, '*', platform, f'*{wireguard_username}*.signed.mobileconfig')
        wg_profiles = glob.glob(wg_pattern)

        if wg_profiles:
            wg_profile = wg_profiles[0]
            wg_folder = os.path.basename(os.path.dirname(os.path.dirname(wg_profile)))
            output_lines.append(f"  Found in '{wg_folder}': {os.path.basename(wg_profile)}")
            success, msg = run_command('install_profile', udid, wg_profile)
            if success:
                output_lines.append(f"    [OK] WireGuard installed")
                optional_installed.append('WireGuard')
            else:
                output_lines.append(f"    [ERROR] {msg}")
                errors.append(f"WireGuard: {msg}")
        else:
            output_lines.append(f"  [WARNING] No profile found for: {wireguard_username}")
            output_lines.append(f"  Searched: {wg_base_path}/*/{platform}/*{wireguard_username}*")

    # =================================================================
    # PHASE 5: DDM Set Assignment (automatic based on manifest+OS)
    # =================================================================
    output_lines.append("\n[PHASE 5] DDM Sets...")

    def run_ddm_script(script_path, *args):
        """Execute a DDM script directly (full path)"""
        if not os.path.exists(script_path):
            return False, f"Script not found: {script_path}"
        full_args = [script_path] + list(args)
        try:
            env = os.environ.copy()
            env['PATH'] = '/usr/local/bin:/usr/bin:/bin:' + env.get('PATH', '')
            result = subprocess.run(full_args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    text=True, timeout=60, env=env)
            if result.returncode == 0:
                return True, result.stdout.strip() if result.stdout else 'OK'
            else:
                return False, result.stderr.strip() if result.stderr else 'Command failed'
        except subprocess.TimeoutExpired:
            return False, 'Command timed out'
        except Exception as e:
            return False, str(e)

    ddm_results = _assign_ddm_sets_for_device(udid, manifest, platform, run_ddm_script)
    if ddm_results:
        for set_name, success, msg in ddm_results:
            if success:
                output_lines.append(f"  [OK] DDM set '{set_name}' assigned")
                commands_executed += 1
            else:
                output_lines.append(f"  [ERROR] DDM set '{set_name}' failed: {msg}")
                errors.append(f"DDM set {set_name}: {msg}")
    else:
        output_lines.append("  No DDM sets configured for this manifest+OS")

    # =================================================================
    # SUMMARY
    # =================================================================
    output_lines.append("\n" + "=" * 60)
    output_lines.append("INSTALLATION SUMMARY")
    output_lines.append("=" * 60)
    output_lines.append(f"Manifest: {manifest}")
    output_lines.append(f"Platform: {platform.upper()}")
    output_lines.append(f"Account: {account_type}")
    if platform == 'macos':
        output_lines.append(f"Restrictions: {restrictions_type}")
    output_lines.append(f"Device: {udid}")
    output_lines.append(f"Commands executed: {commands_executed}")
    if optional_installed:
        output_lines.append(f"Optional installed: {', '.join(optional_installed)}")

    if errors:
        output_lines.append(f"\nErrors: {len(errors)}")
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


def execute_bulk_install_application(params, user_info):
    """Execute bulk application installation - iterates over devices and calls install_application"""
    devices = params.get('devices', [])
    manifest_url = sanitize_param(params.get('manifest_url', ''))

    if not devices:
        return {'success': False, 'error': 'No devices selected'}
    if not manifest_url:
        return {'success': False, 'error': 'Missing required parameter: manifest_url'}

    # Ensure devices is a list
    if isinstance(devices, str):
        devices = [d.strip() for d in devices.split(',') if d.strip()]

    output_lines = []
    errors = []
    success_count = 0
    WAIT_INTERVAL = 2  # seconds between commands

    install_script = os.path.join(COMMANDS_DIR, 'install_application')

    output_lines.append("=" * 60)
    output_lines.append("BULK APPLICATION INSTALLATION")
    output_lines.append("=" * 60)
    output_lines.append(f"Manifest URL: {manifest_url}")
    output_lines.append(f"Target devices: {len(devices)}")
    output_lines.append("")

    for i, udid in enumerate(devices, 1):
        udid = sanitize_param(udid)
        output_lines.append(f"[{i}/{len(devices)}] Installing on device: {udid}")

        try:
            env = os.environ.copy()
            env['PATH'] = '/usr/local/bin:/usr/bin:/bin:' + env.get('PATH', '')

            result = subprocess.run(
                [install_script, udid, manifest_url],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=60,
                cwd=COMMANDS_DIR,
                env=env
            )

            if result.returncode == 0:
                output_lines.append(f"  [OK] Installation command sent")
                success_count += 1
            else:
                error_msg = result.stderr.strip() if result.stderr else 'Command failed'
                output_lines.append(f"  [ERROR] {error_msg}")
                errors.append(f"{udid}: {error_msg}")

        except subprocess.TimeoutExpired:
            output_lines.append(f"  [ERROR] Command timed out")
            errors.append(f"{udid}: Timeout")
        except Exception as e:
            output_lines.append(f"  [ERROR] {str(e)}")
            errors.append(f"{udid}: {str(e)}")

        # Delay between devices (except last one)
        if i < len(devices):
            time.sleep(WAIT_INTERVAL)

    output_lines.append("")
    output_lines.append("=" * 60)
    output_lines.append("BULK INSTALLATION COMPLETE")
    output_lines.append("=" * 60)
    output_lines.append(f"Successful: {success_count}/{len(devices)}")
    output_lines.append(f"Failed: {len(errors)}")

    if errors:
        output_lines.append("")
        output_lines.append("Failed devices:")
        for err in errors:
            output_lines.append(f"  - {err}")

    # Audit log
    audit_log(
        user=user_info.get('username'),
        action='bulk_install_application',
        command='bulk_install_application',
        params={'devices_count': len(devices), 'manifest_url': manifest_url},
        result=f"Installed on {success_count}/{len(devices)} devices",
        success=len(errors) == 0
    )

    return {
        'success': len(errors) == 0,
        'output': '\n'.join(output_lines),
        'errors': errors if errors else None
    }


def execute_bulk_remote_desktop(params, user_info):
    """Execute bulk remote desktop enable/disable on selected or all macOS devices"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    action = params.get('action')
    selected_devices = params.get('devices')
    manifest_filter = params.get('manifest')

    if not action or action not in ['enable', 'disable']:
        return {'success': False, 'error': 'Missing or invalid action. Use "enable" or "disable"'}

    output_lines = []
    errors = []

    output_lines.append("=" * 60)
    output_lines.append(f"BULK REMOTE DESKTOP - {action.upper()}")
    output_lines.append("=" * 60)

    # Normalize selected_devices to list
    if selected_devices:
        if isinstance(selected_devices, str):
            selected_devices = [d.strip() for d in selected_devices.split(',') if d.strip()]
        elif isinstance(selected_devices, list):
            selected_devices = [d.strip() for d in selected_devices if d and str(d).strip()]

    # Get devices from database
    try:
        if selected_devices and len(selected_devices) > 0:
            # Use selected devices (must be macOS)
            placeholders = ','.join(['%s'] * len(selected_devices))
            sql = f"SELECT uuid, hostname FROM device_inventory WHERE uuid IN ({placeholders}) AND os='macos' ORDER BY hostname"
            devices = db.query_all(sql, selected_devices)
            output_lines.append(f"Selected devices: {len(selected_devices)}")
        else:
            # Build SQL query with filters - all macOS devices
            sql = "SELECT uuid, hostname FROM device_inventory WHERE os='macos'"
            sql_params = []

            if manifest_filter:
                sql += " AND manifest = %s"
                sql_params.append(manifest_filter)
                output_lines.append(f"Manifest filter: {manifest_filter}")

            sql += " ORDER BY hostname"
            devices = db.query_all(sql, sql_params)
    except Exception as e:
        return {'success': False, 'error': f'Database error: {str(e)}'}

    if not devices:
        return {'success': False, 'error': 'No macOS devices found matching the filters'}

    output_lines.append(f"Found {len(devices)} macOS device(s)")
    output_lines.append("")
    output_lines.append("Starting parallel execution...")
    output_lines.append("")

    # Determine which script to use
    script_name = 'enable_rd' if action == 'enable' else 'disable_rd'
    script_path = os.path.join(COMMANDS_DIR, script_name)

    success_count = 0

    def run_rd_command(device_info):
        """Execute RD command for a single device"""
        udid, hostname = device_info['uuid'], device_info['hostname']
        try:
            env = os.environ.copy()
            env['PATH'] = '/usr/local/bin:/usr/bin:/bin:' + env.get('PATH', '')

            result = subprocess.run(
                [script_path, udid],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=60,
                cwd=COMMANDS_DIR,
                env=env
            )

            if result.returncode == 0:
                return {'success': True, 'udid': udid, 'hostname': hostname}
            else:
                error_msg = result.stderr.strip() if result.stderr else 'Command failed'
                return {'success': False, 'udid': udid, 'hostname': hostname, 'error': error_msg}

        except subprocess.TimeoutExpired:
            return {'success': False, 'udid': udid, 'hostname': hostname, 'error': 'Timeout'}
        except Exception as e:
            return {'success': False, 'udid': udid, 'hostname': hostname, 'error': str(e)}

    # Execute in parallel using ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(run_rd_command, device): device for device in devices}

        for future in as_completed(futures):
            result = future.result()
            hostname = result.get('hostname', 'Unknown')
            udid = result.get('udid', 'Unknown')

            if result['success']:
                output_lines.append(f"[OK] {hostname} ({udid})")
                success_count += 1
            else:
                error_msg = result.get('error', 'Unknown error')
                output_lines.append(f"[ERROR] {hostname} ({udid}): {error_msg}")
                errors.append(f"{hostname}: {error_msg}")

    output_lines.append("")
    output_lines.append("=" * 60)
    output_lines.append("BULK REMOTE DESKTOP COMPLETE")
    output_lines.append("=" * 60)
    output_lines.append(f"Action: {action.upper()}")
    output_lines.append(f"Successful: {success_count}/{len(devices)}")
    output_lines.append(f"Failed: {len(errors)}")

    if errors:
        output_lines.append("")
        output_lines.append("Failed devices:")
        for err in errors:
            output_lines.append(f"  - {err}")

    # Audit log
    audit_log(
        user=user_info.get('username'),
        action='bulk_remote_desktop',
        command='bulk_remote_desktop',
        params={
            'action': action,
            'devices_count': len(devices),
            'selected_devices': len(selected_devices) if selected_devices else 'all',
            'manifest_filter': manifest_filter
        },
        result=f"{action.upper()} on {success_count}/{len(devices)} devices",
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
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="/static/dashboard.css">
    <link rel="stylesheet" href="/static/css/qbone.css">
    <link rel="stylesheet" href="/static/css/admin.css">
    <link rel="apple-touch-icon" sizes="180x180" href="/static/apple-touch-icon.png">
    <link rel="icon" type="image/png" sizes="32x32" href="/static/favicon-32x32.png">
    <link rel="shortcut icon" href="/static/favicon.ico">
</head>
<body class="page-with-table">
    <div id="wrap">
        <div style="display: flex; justify-content: center; align-items: center;">
            <img id="logo" src="{{ current_logo }}" alt="Logo" style="max-height:60px;max-width:200px;"/>
        </div>
        <h1>NanoHUB MDM Admin Panel</h1>

        <div class="panel">
            <div class="admin-header">
                <h2>Commands</h2>
                <div class="nav-tabs" style="margin:0;">
                    <a href="/admin" class="btn active">Commands</a>
                    <a href="/admin/devices" class="btn">Devices</a>
                    <a href="/admin/profiles" class="btn">Profiles</a>
                    <a href="/admin/ddm" class="btn">DDM</a>
                    <a href="/admin/vpp" class="btn">VPP</a>
                    <a href="/admin/reports" class="btn">Reports</a>
                    <a href="/admin/history" class="btn">History</a>
                </div>
                <div>
                    <span style="color:#B0B0B0;font-size:0.85em;">{{ user.display_name }}</span>
                    <span class="role-badge">{{ user.role }}</span>
                    {% if user.role == 'admin' %}<a href="/admin/settings" class="btn" style="margin-left:10px;">Settings</a>{% endif %}
                    <a href="/admin/help" class="btn" style="margin-left:10px;">Help</a>
                    <a href="/" class="btn" style="margin-left:10px;">Dashboard</a>
                </div>
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
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="/static/dashboard.css">
    <link rel="stylesheet" href="/static/css/qbone.css">
    <link rel="stylesheet" href="/static/css/admin.css">
    <link rel="shortcut icon" href="/static/favicon.ico">
</head>
<body class="page-with-table">
    <div id="wrap">
        <div style="display: flex; justify-content: center; align-items: center;">
            <img id="logo" src="{{ current_logo }}" alt="Logo" style="max-height:60px;max-width:200px;"/>
        </div>
        <h1>{{ command.name }}</h1>

        <div class="panel">
            <div class="admin-header">
                <h2>{{ command.description }}</h2>
                {% if command.dangerous %}
                <span style="color:#D91F25;font-size:0.9em;">This is a potentially dangerous operation.</span>
                {% endif %}
                <a href="/admin" class="btn">Back to Commands</a>
            </div>

            {% if os_versions %}
            <div style="margin-bottom:15px;padding:8px 12px;background:#1a1a1a;border:1px solid #333;border-radius:4px;font-size:0.85em;color:#B0B0B0;">
                {% if os_versions.ios %}iOS <strong style="color:#fff;">{{ os_versions.ios.version }}</strong> <code style="color:#666;">{{ os_versions.ios.product_key }}</code>{% endif %}{% if os_versions.ipados %} · iPadOS <strong style="color:#fff;">{{ os_versions.ipados.version }}</strong> <code style="color:#666;">{{ os_versions.ipados.product_key }}</code>{% endif %}{% if os_versions.macos %} · macOS <strong style="color:#fff;">{{ os_versions.macos.version }}</strong> <code style="color:#666;">{{ os_versions.macos.product_key }}</code>{% endif %}
            </div>
            {% endif %}

            <form id="commandForm" onsubmit="return executeCommand(event)" style="text-align:left;">
                {% for param in command.parameters %}
                <div class="form-group">
                    <label>{{ param.label }}{% if param.required %} <span style="color:#e92128;">*</span>{% endif %}</label>

                    {% if param.type == 'device' %}
                    <div class="filter-form">
                        <div class="filter-group">
                            <label>Search</label>
                            <input type="text" id="device-search" placeholder="Hostname, serial, UUID...">
                        </div>
                        <div class="filter-group">
                            <label>OS</label>
                            <select id="os-filter">
                                <option value="all">All</option>
                                <option value="ios">iOS</option>
                                <option value="macos">macOS</option>
                            </select>
                        </div>
                        <div class="filter-group">
                            <label>Manifest</label>
                            <select id="manifest-filter">
                                <option value="all">All</option>
                                {% for manifest in manifests %}
                                <option value="{{ manifest }}">{{ manifest }}</option>
                                {% endfor %}
                            </select>
                        </div>
                        <div class="filter-buttons">
                            <button type="button" onclick="searchDevices()" class="filter-btn">Search</button>
                            <button type="button" onclick="showAllDevices()" class="filter-btn">Show All</button>
                        </div>
                    </div>
                    <div class="device-table-container">
                        <table class="device-table" id="device-table">
                            <thead>
                                <tr><th>Hostname</th><th>Serial</th><th>OS</th><th>Version</th><th>Model</th><th>Manifest</th><th>DEP</th><th>Supervised</th><th>Encrypted</th><th>Outdated</th><th>Last Check-in</th><th>Status</th></tr>
                            </thead>
                            <tbody id="device-tbody">
                                <tr><td colspan="12" style="text-align:center;color:#B0B0B0;">Click "Show All" or search for devices</td></tr>
                            </tbody>
                        </table>
                    </div>
                    <input type="hidden" name="udid" id="selected-udid" {% if param.required %}required{% endif %}>

                    {% elif param.type == 'devices' %}
                    <div class="filter-form">
                        <div class="filter-group">
                            <label>Search</label>
                            <input type="text" id="device-search" placeholder="Hostname, serial, UUID...">
                        </div>
                        <div class="filter-group">
                            <label>OS</label>
                            <select id="os-filter">
                                <option value="all">All</option>
                                <option value="ios">iOS</option>
                                <option value="macos">macOS</option>
                            </select>
                        </div>
                        <div class="filter-group">
                            <label>Manifest</label>
                            <select id="manifest-filter">
                                <option value="all">All</option>
                                {% for manifest in manifests %}
                                <option value="{{ manifest }}">{{ manifest }}</option>
                                {% endfor %}
                            </select>
                        </div>
                        <div class="filter-buttons">
                            <button type="button" onclick="searchDevices()" class="filter-btn">Search</button>
                            <button type="button" onclick="showAllDevices()" class="filter-btn">Show All</button>
                        </div>
                    </div>
                    <div class="device-table-container">
                        <table class="device-table" id="device-table">
                            <thead>
                                <tr><th><input type="checkbox" id="select-all" onchange="toggleSelectAll()"></th><th>Hostname</th><th>Serial</th><th>OS</th><th>Version</th><th>Model</th><th>Manifest</th><th>DEP</th><th>Supervised</th><th>Encrypted</th><th>Outdated</th><th>Last Check-in</th><th>Status</th></tr>
                            </thead>
                            <tbody id="device-tbody">
                                <tr><td colspan="13" style="text-align:center;color:#B0B0B0;">Click "Show All" or search for devices</td></tr>
                            </tbody>
                        </table>
                    </div>
                    <div id="selected-count" style="margin-top:8px;color:#276beb;font-weight:500;"></div>

                    {% elif param.type == 'profile' %}
                    <div class="profile-select-group">
                        <label>Profile:</label>
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
                                <tr><th>Hostname</th><th>Serial</th><th>OS</th><th>Version</th><th>Model</th><th>Manifest</th><th>DEP</th><th>Supervised</th><th>Encrypted</th><th>Outdated</th><th>Last Check-in</th><th>Status</th></tr>
                            </thead>
                            <tbody id="autofill-device-tbody">
                                <tr><td colspan="12" style="text-align:center;color:#B0B0B0;">Click "Show All" or search for devices</td></tr>
                            </tbody>
                        </table>
                    </div>

                    {% elif param.type == 'select' %}
                    <select name="{{ param.name }}" id="{{ param.name }}" {% if param.required %}required{% endif %}>
                        {% for opt in param.options %}
                        <option value="{{ opt.value }}">{{ opt.label }}</option>
                        {% endfor %}
                    </select>

                    {% elif param.type == 'select_multiple' %}
                    <div id="applications-container" style="background:#1a1a1a;border:1px solid #333;border-radius:4px;padding:8px;">
                        <span style="color:#888;font-size:12px;">Select manifest to load applications</span>
                    </div>

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

            <div id="loading" style="display:none;margin:14px auto 10px auto;max-width:600px;text-align:center;padding:6px 22px;background:#1E1E1E;border:1px solid #5FC812;border-radius:5px;color:#5FC812;box-shadow:0 3px 12px -3px rgba(95,200,18,0.15);">
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
                <button class="btn btn-danger" onclick="confirmExecute()" style="margin-left:10px;">Confirm</button>
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
                renderDevices(filterDevices(allDevices));
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
            renderDevices(filterDevices(allDevices));
        })
        .catch(err => {
            console.error('Search failed:', err);
            allDevices = [];
            renderDevices([]);
        });
    }

    function filterDevices(devices) {
        const osFilter = document.getElementById('os-filter').value;
        const manifestFilter = document.getElementById('manifest-filter')?.value || 'all';
        let filtered = devices;
        if (osFilter !== 'all') {
            filtered = filtered.filter(d => d.os === osFilter);
        }
        if (manifestFilter !== 'all') {
            filtered = filtered.filter(d => d.manifest === manifestFilter);
        }
        return filtered;
    }

    document.getElementById('os-filter')?.addEventListener('change', function() {
        renderDevices(filterDevices(allDevices));
    });

    document.getElementById('manifest-filter')?.addEventListener('change', function() {
        renderDevices(filterDevices(allDevices));
    });

    function renderDevices(devices) {
        const tbody = document.getElementById('device-tbody');
        if (!devices.length) {
            tbody.innerHTML = '<tr><td colspan="' + (isMultiSelect ? '13' : '12') + '" style="text-align:center;color:#B0B0B0;">No devices found</td></tr>';
            return;
        }

        let html = '';
        devices.forEach(dev => {
            const statusClass = dev.status || 'offline';
            const osClass = (dev.os || '').toLowerCase();
            const yesClass = 'color:#16a34a;font-weight:500;';
            const noClass = 'color:#dc2626;font-weight:500;';
            if (isMultiSelect) {
                html += `<tr onclick="toggleDeviceCheckbox('${dev.uuid}', this)">
                    <td><input type="checkbox" name="devices" value="${dev.uuid}" onclick="event.stopPropagation()"></td>
                    <td><a href="/admin/device/${dev.uuid}" class="device-link" onclick="event.stopPropagation()">${dev.hostname || '-'}</a></td>
                    <td>${dev.serial || '-'}</td>
                    <td><span class="os-badge ${osClass}">${dev.os || '-'}</span></td>
                    <td>${dev.os_version || '-'}</td>
                    <td>${dev.model || '-'}</td>
                    <td>${dev.manifest || '-'}</td>
                    <td><span style="${dev.dep === 'Yes' ? yesClass : noClass}">${dev.dep || '-'}</span></td>
                    <td><span style="${dev.supervised === 'Yes' ? yesClass : noClass}">${dev.supervised || '-'}</span></td>
                    <td><span style="${dev.encrypted === 'Yes' ? yesClass : noClass}">${dev.encrypted || '-'}</span></td>
                    <td><span style="${dev.outdated === 'Yes' ? noClass : yesClass}">${dev.outdated || '-'}</span></td>
                    <td>${dev.last_seen || '-'}</td>
                    <td style="text-align:center;"><span class="status-dot ${statusClass}" title="${statusClass}"></span></td>
                </tr>`;
            } else {
                html += `<tr onclick="selectDevice('${dev.uuid}', '${dev.hostname || dev.serial}', this)">
                    <td><a href="/admin/device/${dev.uuid}" class="device-link" onclick="event.stopPropagation()">${dev.hostname || '-'}</a></td>
                    <td>${dev.serial || '-'}</td>
                    <td><span class="os-badge ${osClass}">${dev.os || '-'}</span></td>
                    <td>${dev.os_version || '-'}</td>
                    <td>${dev.model || '-'}</td>
                    <td>${dev.manifest || '-'}</td>
                    <td><span style="${dev.dep === 'Yes' ? yesClass : noClass}">${dev.dep || '-'}</span></td>
                    <td><span style="${dev.supervised === 'Yes' ? yesClass : noClass}">${dev.supervised || '-'}</span></td>
                    <td><span style="${dev.encrypted === 'Yes' ? yesClass : noClass}">${dev.encrypted || '-'}</span></td>
                    <td><span style="${dev.outdated === 'Yes' ? noClass : yesClass}">${dev.outdated || '-'}</span></td>
                    <td>${dev.last_seen || '-'}</td>
                    <td style="text-align:center;"><span class="status-dot ${statusClass}" title="${statusClass}"></span></td>
                </tr>`;
            }
        });
        tbody.innerHTML = html;
    }

    function selectDevice(uuid, name, row) {
        document.querySelectorAll('#device-table tr').forEach(r => r.classList.remove('selected'));
        row.classList.add('selected');
        document.getElementById('selected-udid').value = uuid;
    }

    function clearSelectedDevice() {
        document.querySelectorAll('#device-table tr').forEach(r => r.classList.remove('selected'));
        document.getElementById('selected-udid').value = '';
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
            tbody.innerHTML = '<tr><td colspan="12" style="text-align:center;color:#B0B0B0;">No devices found</td></tr>';
            return;
        }

        let html = '';
        devices.forEach(dev => {
            const statusClass = dev.status || 'offline';
            const osClass = (dev.os || '').toLowerCase();
            const yesClass = 'color:#16a34a;font-weight:500;';
            const noClass = 'color:#dc2626;font-weight:500;';
            // Store device data as JSON in data attribute for autofill
            const devJson = JSON.stringify(dev).replace(/'/g, "\\'").replace(/"/g, '&quot;');
            html += `<tr onclick="selectAutofillDevice(this)" data-device="${devJson}">
                <td><a href="/admin/device/${dev.uuid}" class="device-link" onclick="event.stopPropagation()">${dev.hostname || '-'}</a></td>
                <td>${dev.serial || '-'}</td>
                <td><span class="os-badge ${osClass}">${dev.os || '-'}</span></td>
                <td>${dev.os_version || '-'}</td>
                <td>${dev.model || '-'}</td>
                <td>${dev.manifest || '-'}</td>
                <td><span style="${dev.dep === 'Yes' ? yesClass : noClass}">${dev.dep || '-'}</span></td>
                <td><span style="${dev.supervised === 'Yes' ? yesClass : noClass}">${dev.supervised || '-'}</span></td>
                <td><span style="${dev.encrypted === 'Yes' ? yesClass : noClass}">${dev.encrypted || '-'}</span></td>
                <td><span style="${dev.outdated === 'Yes' ? noClass : yesClass}">${dev.outdated || '-'}</span></td>
                <td>${dev.last_seen || '-'}</td>
                <td><span class="status-dot ${statusClass}" title="${statusClass}"></span></td>
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

    }

    function clearAutofillDevice() {
        document.querySelectorAll('#autofill-device-table tr').forEach(r => r.classList.remove('selected'));

        // Clear form fields
        const fields = ['uuid', 'serial', 'hostname', 'os', 'manifest', 'account', 'dep'];
        fields.forEach(f => {
            const el = document.getElementById(f);
            if (el) el.value = '';
        });
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

    // Load applications based on selected manifest
    function loadApplicationsForManifest(manifest) {
        const container = document.getElementById('applications-container');
        if (!container) return;

        if (!manifest) {
            container.innerHTML = '<span style="color:#888;font-size:12px;">Select manifest to load applications</span>';
            return;
        }

        container.innerHTML = '<span style="color:#888;font-size:12px;">Loading...</span>';

        fetch('/admin/api/applications/' + encodeURIComponent(manifest))
            .then(r => r.json())
            .then(data => {
                if (!data.applications || data.applications.length === 0) {
                    container.innerHTML = '<span style="color:#888;font-size:12px;">No applications for this manifest</span>';
                    return;
                }

                let html = '<table style="width:100%;">';
                data.applications.forEach(app => {
                    html += '<tr>';
                    html += '<td style="padding:2px;width:20px;"><input type="checkbox" name="applications" value="' + app.manifest_url + '" checked></td>';
                    html += '<td style="padding:2px 10px 2px 4px;white-space:nowrap;">' + app.app_name + '</td>';
                    html += '<td style="padding:2px;color:#666;font-size:11px;">' + app.manifest_url + '</td>';
                    html += '</tr>';
                });
                html += '</table>';
                container.innerHTML = html;
            })
            .catch(err => {
                container.innerHTML = '<span style="color:#e92128;font-size:12px;">Failed to load applications</span>';
            });
    }

    // Load applications into app_id select (for Manage Applications)
    function loadApplicationsForAppIdSelect(manifest) {
        const appIdSelect = document.getElementById('app_id');
        if (!appIdSelect) return;

        if (!manifest) {
            appIdSelect.innerHTML = '<option value="">-- Select Manifest first --</option>';
            return;
        }

        appIdSelect.innerHTML = '<option value="">Loading...</option>';

        fetch('/admin/api/applications/' + encodeURIComponent(manifest))
            .then(r => r.json())
            .then(data => {
                if (!data.applications || data.applications.length === 0) {
                    appIdSelect.innerHTML = '<option value="">-- No applications for this manifest --</option>';
                    return;
                }

                let html = '<option value="">-- Select Application --</option>';
                data.applications.forEach(app => {
                    html += '<option value="' + app.id + '">' + app.app_name + ' (' + app.os + ')</option>';
                });
                appIdSelect.innerHTML = html;
            })
            .catch(err => {
                appIdSelect.innerHTML = '<option value="">-- Failed to load --</option>';
            });
    }

    // Listen for manifest change
    const manifestSelect = document.getElementById('manifest');
    if (manifestSelect) {
        manifestSelect.addEventListener('change', function() {
            loadApplicationsForManifest(this.value);
            loadApplicationsForAppIdSelect(this.value);
        });
        // Load on page init if manifest is pre-selected
        if (manifestSelect.value) {
            loadApplicationsForManifest(manifestSelect.value);
            loadApplicationsForAppIdSelect(manifestSelect.value);
        }
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

        // Lock device table height before adding scroll class
        const deviceTable = document.querySelector('.device-table-container');
        if (deviceTable) {
            const h = deviceTable.offsetHeight + 'px';
            deviceTable.style.setProperty('height', h, 'important');
            deviceTable.style.setProperty('max-height', h, 'important');
            deviceTable.style.setProperty('min-height', h, 'important');
            deviceTable.style.setProperty('overflow', 'auto', 'important');
        }
        // Also lock parent form-group
        const formGroup = document.querySelector('.form-group:has(.device-table-container)');
        if (formGroup) {
            const fh = formGroup.offsetHeight + 'px';
            formGroup.style.setProperty('height', fh, 'important');
            formGroup.style.setProperty('max-height', fh, 'important');
            formGroup.style.setProperty('overflow', 'hidden', 'important');
        }

        const params = {};
        for (let [key, value] of formData.entries()) {
            if (key === 'devices' || key === 'applications') {
                if (!params[key]) params[key] = [];
                params[key].push(value);
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
            // Enable page scroll and scroll to output
            document.body.classList.add('has-command-output');
            document.getElementById('output-container').scrollIntoView({behavior: 'smooth', block: 'start'});
        })
        .catch(err => {
            document.getElementById('loading').style.display = 'none';
            document.getElementById('output-container').innerHTML =
                '<div class="output-panel error">Request failed: ' + escapeHtml(err.toString()) + '</div>';
            document.body.classList.add('has-command-output');
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
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="/static/dashboard.css">
    <link rel="stylesheet" href="/static/css/qbone.css">
    <link rel="stylesheet" href="/static/css/admin.css">
    <link rel="shortcut icon" href="/static/favicon.ico">
</head>
<body class="page-with-table">
    <div id="wrap">
        <div style="display: flex; justify-content: center; align-items: center;">
            <img id="logo" src="{{ current_logo }}" alt="Logo" style="max-height:60px;max-width:200px;"/>
        </div>
        <h1>Execution History</h1>

        <div class="panel">
            <div class="admin-header">
                <h2>History</h2>
                <div class="nav-tabs" style="margin:0;">
                    <a href="/admin" class="btn">Commands</a>
                    <a href="/admin/devices" class="btn">Devices</a>
                    <a href="/admin/profiles" class="btn">Profiles</a>
                    <a href="/admin/ddm" class="btn">DDM</a>
                    <a href="/admin/vpp" class="btn">VPP</a>
                    <a href="/admin/reports" class="btn">Reports</a>
                    <a href="/admin/history" class="btn active">History</a>
                </div>
                <div>
                    <span style="color:#B0B0B0;font-size:0.85em;">{{ user.display_name }}</span>
                    <span class="role-badge">{{ user.role }}</span>
                    {% if user.role == 'admin' %}<a href="/admin/settings" class="btn" style="margin-left:10px;">Settings</a>{% endif %}
                    <a href="/admin/help" class="btn" style="margin-left:10px;">Help</a>
                    <a href="/" class="btn" style="margin-left:10px;">Dashboard</a>
                </div>
            </div>

            <form method="GET" class="filter-form">
                <div class="filter-group">
                    <label>Date From</label>
                    <input type="date" name="date_from" value="{{ date_from or '' }}" onchange="this.form.submit()">
                </div>
                <div class="filter-group">
                    <label>Date To</label>
                    <input type="date" name="date_to" value="{{ date_to or '' }}" onchange="this.form.submit()">
                </div>
                <div class="filter-group">
                    <label>Device (UDID/Serial/Hostname)</label>
                    <input type="text" name="device" value="{{ device_filter or '' }}" placeholder="Search device..." onkeypress="if(event.key==='Enter'){this.form.submit();}">
                </div>
                <div class="filter-group">
                    <label>User</label>
                    <select name="user_filter" onchange="this.form.submit()">
                        <option value="">All users</option>
                        {% for u in users %}
                        <option value="{{ u }}" {% if u == user_filter %}selected{% endif %}>{{ u }}</option>
                        {% endfor %}
                    </select>
                </div>
                <div class="filter-group">
                    <label>Status</label>
                    <select name="status" onchange="this.form.submit()">
                        <option value="">All</option>
                        <option value="1" {% if status_filter == '1' %}selected{% endif %}>Success</option>
                        <option value="0" {% if status_filter == '0' %}selected{% endif %}>Failed</option>
                    </select>
                </div>
                <div class="filter-buttons">
                    <button type="button" class="btn" onclick="window.location.href='/admin/history'">Clear</button>
                </div>
            </form>

            <div class="result-info">
                Showing {{ history|length }} of {{ total_count }} records
                {% if total_count > 0 %}(Page {{ page }} of {{ total_pages }}){% endif %}
            </div>

            <div class="table-wrapper">
            <table class="history-table">
                <thead>
                    <tr>
                        <th>Timestamp</th>
                        <th>User</th>
                        <th>Command</th>
                        <th>Details</th>
                        <th>Device</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody>
                    {% for entry in history %}
                    <tr>
                        <td>{{ entry.timestamp.strftime('%Y-%m-%d %H:%M:%S') if entry.timestamp else '' }}</td>
                        <td><strong style="color:#fff;">{{ entry.user or '' }}</strong></td>
                        <td>{{ entry.command_name }}</td>
                        <td class="details-cell">
                            {% if entry.params %}
                                {% for key, val in entry.params.items() %}
                                    {% if val and key not in ['devices', 'udid'] %}
                                        <strong>{{ key }}:</strong> {{ val }}<br>
                                    {% endif %}
                                {% endfor %}
                            {% endif %}
                            {% if entry.result_summary %}<div class="result-summary">{{ entry.result_summary }}</div>{% endif %}
                        </td>
                        <td class="device-cell">
                            {% if entry.device_hostname %}
                            <div class="device-hostname">{{ entry.device_hostname }}</div>
                            {% endif %}
                            {% if entry.device_udid %}
                            <div class="device-udid">{{ entry.device_udid }}</div>
                            {% endif %}
                        </td>
                        <td class="{% if entry.success %}status-success{% else %}status-failed{% endif %}">
                            {% if entry.success %}Success{% else %}Failed{% endif %}
                        </td>
                    </tr>
                    {% endfor %}
                    {% if not history %}
                    <tr>
                        <td colspan="6" style="text-align:center;color:#B0B0B0;">No execution history found</td>
                    </tr>
                    {% endif %}
                </tbody>
            </table>
            </div>

            {% if total_pages > 1 %}
            <div id="pagination-container" style="margin-top:15px;padding:10px 0;border-top:1px solid #e7eaf2;">
                <div style="font-size:0.85em;color:#6b7280;margin-bottom:8px;">
                    Showing {{ ((page - 1) * 50) + 1 }}-{{ [page * 50, total_count] | min }} of {{ total_count }} (Page {{ page }} of {{ total_pages }})
                </div>
                <div class="pagination">
                    {% if page > 1 %}
                    <a href="?page={{ page - 1 }}&date_from={{ date_from or '' }}&date_to={{ date_to or '' }}&device={{ device_filter or '' }}&user_filter={{ user_filter or '' }}&status={{ status_filter or '' }}">&laquo; Prev</a>
                    {% else %}
                    <span class="disabled">&laquo; Prev</span>
                    {% endif %}

                    {% for p in range(1, total_pages + 1) %}
                        {% if p == page %}
                        <span class="current">{{ p }}</span>
                        {% elif p <= 3 or p > total_pages - 2 or (p >= page - 1 and p <= page + 1) %}
                        <a href="?page={{ p }}&date_from={{ date_from or '' }}&date_to={{ date_to or '' }}&device={{ device_filter or '' }}&user_filter={{ user_filter or '' }}&status={{ status_filter or '' }}">{{ p }}</a>
                        {% elif p == 4 or p == total_pages - 2 %}
                        <span>...</span>
                        {% endif %}
                    {% endfor %}

                    {% if page < total_pages %}
                    <a href="?page={{ page + 1 }}&date_from={{ date_from or '' }}&date_to={{ date_to or '' }}&device={{ device_filter or '' }}&user_filter={{ user_filter or '' }}&status={{ status_filter or '' }}">Next &raquo;</a>
                    {% else %}
                    <span class="disabled">Next &raquo;</span>
                    {% endif %}
                </div>
            </div>
            {% endif %}
        </div>
    </div>
</body>
</html>
'''



# =============================================================================
# CONSOLIDATED COMMAND IMPLEMENTATIONS
# NOTE: normalize_devices_param moved to nanohub_admin.core
# NOTE: execute_manage_profiles moved to nanohub_admin.profiles
# =============================================================================

def execute_manage_ddm_sets(params, user_info):
    """Handle Manage DDM Sets command (assign/remove on one or more devices)"""
    action = params.get('action')
    devices = normalize_devices_param(params.get('devices'))
    set_name = params.get('set_name')

    if not action:
        return {'success': False, 'error': 'Missing required parameter: action'}
    if not devices:
        return {'success': False, 'error': 'Missing required parameter: devices'}
    if not set_name:
        return {'success': False, 'error': 'Missing required parameter: set_name'}

    # Load environment for API access from environment.sh
    nanohub_url = 'http://localhost:9004'
    api_key = ''
    try:
        with open(Config.ENVIRONMENT_FILE, 'r') as f:
            for line in f:
                if line.startswith('export NANOHUB_URL='):
                    nanohub_url = line.split('=', 1)[1].strip().strip('"\'')
                elif line.startswith('export NANOHUB_API_KEY='):
                    api_key = line.split('=', 1)[1].strip().strip('"\'')
    except Exception:
        pass

    # For remove action, check which devices actually have the set assigned
    device_sets_cache = {}
    if action == 'remove':
        auth_string = base64.b64encode(f"nanohub:{api_key}".encode()).decode()
        for udid in devices:
            try:
                req = urllib.request.Request(
                    f"{nanohub_url}/api/v1/ddm/enrollment-sets/{udid}",
                    headers={'Authorization': f'Basic {auth_string}'}
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode())
                    device_sets_cache[udid] = data if data else []
            except Exception as e:
                logger.error(f"Failed to get sets for {udid}: {e}")
                device_sets_cache[udid] = []

    # Use the DDM script
    script_path = os.path.join(Config.DDM_SCRIPTS_DIR, 'ddm-assign-device.sh')

    output_lines = []
    output_lines.append("=" * 60)
    output_lines.append(f"MANAGE DDM SETS - {action.upper()}")
    output_lines.append(f"Set: {set_name}")
    output_lines.append(f"Devices: {len(devices)}")
    output_lines.append("=" * 60)

    success_count = 0
    fail_count = 0
    skip_count = 0

    def run_ddm_cmd(udid):
        # For remove action, check if device has the set assigned
        if action == 'remove':
            assigned_sets = device_sets_cache.get(udid, [])
            if set_name not in assigned_sets:
                return {
                    'success': False,
                    'udid': udid,
                    'skipped': True,
                    'error': f'Set not assigned (has: {", ".join(assigned_sets) if assigned_sets else "none"})'
                }

        try:
            env = os.environ.copy()
            env['PATH'] = '/usr/local/bin:/usr/bin:/bin:' + env.get('PATH', '')

            result = subprocess.run(
                [script_path, action, udid, set_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=60,
                cwd=Config.DDM_SCRIPTS_DIR,
                env=env
            )

            if result.returncode == 0:
                return {'success': True, 'udid': udid, 'output': result.stdout}
            else:
                return {'success': False, 'udid': udid, 'error': result.stderr or 'Command failed'}

        except subprocess.TimeoutExpired:
            return {'success': False, 'udid': udid, 'error': 'Timeout'}
        except Exception as e:
            return {'success': False, 'udid': udid, 'error': str(e)}

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(run_ddm_cmd, udid): udid for udid in devices}
        for future in as_completed(futures):
            result = future.result()
            if result['success']:
                success_count += 1
                output_lines.append(f"[OK] {result['udid']}")
            elif result.get('skipped'):
                skip_count += 1
                output_lines.append(f"[SKIP] {result['udid']}: {result.get('error', 'Unknown error')}")
            else:
                fail_count += 1
                output_lines.append(f"[FAIL] {result['udid']}: {result.get('error', 'Unknown error')}")

    output_lines.append("")
    output_lines.append("=" * 60)
    summary_parts = [f"{success_count} success"]
    if skip_count > 0:
        summary_parts.append(f"{skip_count} skipped")
    summary_parts.append(f"{fail_count} failed")
    output_lines.append(f"SUMMARY: {', '.join(summary_parts)}")
    output_lines.append("=" * 60)

    audit_log(
        user=user_info.get('username'),
        action='manage_ddm_sets',
        command='manage_ddm_sets',
        params=params,
        result=f'{success_count} success, {skip_count} skipped, {fail_count} failed',
        success=(fail_count == 0 and skip_count == 0)
    )

    return {
        'success': fail_count == 0 and skip_count == 0,
        'output': '\n'.join(output_lines)
    }


def execute_install_application(params, user_info):
    """Handle Install Application command (on one or more devices)"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    devices = normalize_devices_param(params.get('devices'))
    manifest_url = params.get('manifest_url')

    if not devices:
        return {'success': False, 'error': 'Missing required parameter: devices'}
    if not manifest_url:
        return {'success': False, 'error': 'Missing required parameter: manifest_url'}

    script_path = os.path.join(COMMANDS_DIR, 'install_application')

    output_lines = []
    output_lines.append("=" * 60)
    output_lines.append("INSTALL APPLICATION")
    output_lines.append(f"Manifest: {manifest_url}")
    output_lines.append(f"Devices: {len(devices)}")
    output_lines.append("=" * 60)

    success_count = 0
    fail_count = 0

    def run_install_cmd(udid):
        try:
            env = os.environ.copy()
            env['PATH'] = '/usr/local/bin:/usr/bin:/bin:' + env.get('PATH', '')

            result = subprocess.run(
                [script_path, udid, manifest_url],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=60,
                cwd=COMMANDS_DIR,
                env=env
            )

            if result.returncode == 0:
                return {'success': True, 'udid': udid}
            else:
                return {'success': False, 'udid': udid, 'error': result.stderr or 'Command failed'}

        except subprocess.TimeoutExpired:
            return {'success': False, 'udid': udid, 'error': 'Timeout'}
        except Exception as e:
            return {'success': False, 'udid': udid, 'error': str(e)}

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(run_install_cmd, udid): udid for udid in devices}
        for future in as_completed(futures):
            result = future.result()
            if result['success']:
                success_count += 1
                output_lines.append(f"[OK] {result['udid']}")
            else:
                fail_count += 1
                output_lines.append(f"[FAIL] {result['udid']}: {result.get('error', 'Unknown error')}")

    output_lines.append("")
    output_lines.append("=" * 60)
    output_lines.append(f"SUMMARY: {success_count} success, {fail_count} failed")
    output_lines.append("=" * 60)

    audit_log(
        user=user_info.get('username'),
        action='install_application',
        command='install_application',
        params=params,
        result=f'{success_count} success, {fail_count} failed',
        success=(fail_count == 0)
    )

    return {
        'success': fail_count == 0,
        'output': '\n'.join(output_lines)
    }


def execute_device_action(params, user_info):
    """Handle Device Action command (lock/unlock/restart/erase/clear_passcode)"""
    action = params.get('action')
    udid = sanitize_param(params.get('udid', ''))
    pin = params.get('pin', '')
    message = params.get('message', '')
    confirm_erase = params.get('confirm_erase', '')

    if not action:
        return {'success': False, 'error': 'Missing required parameter: action'}
    if not udid:
        return {'success': False, 'error': 'Missing required parameter: udid'}

    # Map action to script
    script_map = {
        'lock': 'lock_device',
        'unlock': 'unlock_device',
        'restart': 'restart_device',
        'erase': 'erase_device',
        'clear_passcode': 'unlock_device'  # Same as unlock
    }

    script_name = script_map.get(action)
    if not script_name:
        return {'success': False, 'error': f'Invalid action: {action}'}

    # Check admin permission and confirmation for erase
    if action == 'erase':
        user_role = user_info.get('role', 'report')
        if user_role not in ['admin', 'site-admin']:
            return {'success': False, 'error': 'Erase requires admin permission'}
        # Require typing "ERASE" to confirm
        if confirm_erase != 'ERASE':
            return {'success': False, 'error': 'To erase device, you must type "ERASE" in the confirmation field'}

    script_path = os.path.join(COMMANDS_DIR, script_name)

    args = [script_path, udid]

    # Add optional parameters for lock/erase
    if action == 'lock':
        if pin:
            args.append(sanitize_param(pin))
        if message:
            args.append(sanitize_param(message))
    elif action == 'erase':
        if pin:
            args.append(sanitize_param(pin))

    try:
        env = os.environ.copy()
        env['PATH'] = '/usr/local/bin:/usr/bin:/bin:' + env.get('PATH', '')

        result = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=60,
            cwd=COMMANDS_DIR,
            env=env
        )

        output = result.stdout + result.stderr
        success = result.returncode == 0

        audit_log(
            user=user_info.get('username'),
            action='device_action',
            command=f'device_action:{action}',
            params=params,
            result=output,
            success=success
        )

        return {
            'success': success,
            'output': output,
            'return_code': result.returncode
        }

    except subprocess.TimeoutExpired:
        return {'success': False, 'error': 'Command timed out'}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def execute_update_inventory(params, user_info):
    """Handle Update Inventory command (bulk inventory update for multiple devices)"""

    selected_devices = normalize_devices_param(params.get('devices'))
    os_filter = params.get('os_filter', '')
    manifest_filter = params.get('manifest', '')
    last_updated_filter = params.get('last_updated', '')
    query_types = ['hardware', 'security', 'profiles', 'apps']

    output_lines = []
    output_lines.append("=" * 60)
    output_lines.append("UPDATE INVENTORY")
    output_lines.append("=" * 60)

    # Get devices either from selection or from filters
    if selected_devices and len(selected_devices) > 0:
        devices = selected_devices
        output_lines.append(f"Selected devices: {len(devices)}")
    else:
        # Query DB with filters
        try:
            # Build SQL with filters
            sql = """
                SELECT di.uuid, di.hostname
                FROM device_inventory di
                LEFT JOIN device_details dd ON di.uuid = dd.uuid
                WHERE 1=1
            """
            sql_params = []

            if os_filter:
                sql += " AND di.os = %s"
                sql_params.append(os_filter)
                output_lines.append(f"OS filter: {os_filter}")

            if manifest_filter:
                sql += " AND di.manifest = %s"
                sql_params.append(manifest_filter)
                output_lines.append(f"Manifest filter: {manifest_filter}")

            if last_updated_filter:
                if last_updated_filter == 'never':
                    sql += " AND dd.uuid IS NULL"
                    output_lines.append("Filter: Never updated")
                elif last_updated_filter == '24h':
                    cutoff = datetime.now() - timedelta(hours=24)
                    sql += " AND (dd.hardware_updated_at IS NULL OR dd.hardware_updated_at < %s)"
                    sql_params.append(cutoff)
                    output_lines.append("Filter: Not updated in 24h")
                elif last_updated_filter == '7d':
                    cutoff = datetime.now() - timedelta(days=7)
                    sql += " AND (dd.hardware_updated_at IS NULL OR dd.hardware_updated_at < %s)"
                    sql_params.append(cutoff)
                    output_lines.append("Filter: Not updated in 7 days")

            sql += " ORDER BY di.hostname"
            rows = db.query_all(sql, sql_params)
            devices = [row['uuid'] for row in rows]
            output_lines.append(f"Found {len(devices)} device(s) matching filters")

        except Exception as e:
            return {'success': False, 'error': f'Database error: {str(e)}'}

    if not devices:
        return {'success': False, 'error': 'No devices found matching the filters'}

    output_lines.append("")

    # Track results per device
    device_results = {}

    def run_device_queries(device_uuid):
        """Run all query types for a single device"""
        results = {'uuid': device_uuid, 'queries': {}}
        for qt in query_types:
            result = execute_device_query(device_uuid, qt)
            results['queries'][qt] = result.get('success', False)
            # Small delay between queries to not overwhelm MDM
            time.sleep(0.3)
        return results

    # Process devices with limited concurrency (MDM can't handle too many parallel requests)
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(run_device_queries, udid): udid for udid in devices}
        for future in as_completed(futures):
            result = future.result()
            device_uuid = result['uuid']
            device_results[device_uuid] = result['queries']

            # Build status line
            successes = sum(1 for v in result['queries'].values() if v)
            total = len(result['queries'])
            status = "OK" if successes == total else f"{successes}/{total}"
            output_lines.append(f"[{status}] {device_uuid[:8]}...")

    # Summary
    total_devices = len(devices)
    full_success = sum(1 for r in device_results.values() if all(r.values()))
    partial_success = sum(1 for r in device_results.values() if any(r.values()) and not all(r.values()))
    failed = total_devices - full_success - partial_success

    output_lines.append("")
    output_lines.append("=" * 60)
    output_lines.append(f"SUMMARY:")
    output_lines.append(f"  Full success: {full_success} devices")
    output_lines.append(f"  Partial: {partial_success} devices")
    output_lines.append(f"  Failed: {failed} devices")
    output_lines.append("=" * 60)

    audit_log(
        user=user_info.get('username'),
        action='update_inventory',
        command='update_inventory',
        params={'devices': len(devices)},
        result=f'{full_success} success, {partial_success} partial, {failed} failed',
        success=failed == 0
    )

    return {
        'success': failed == 0,
        'output': '\n'.join(output_lines),
        'details': device_results
    }


def execute_schedule_os_update(params, user_info):
    """Handle Schedule OS Update command (on one or more devices)"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    action = params.get('action')
    devices = normalize_devices_param(params.get('devices'))
    key = params.get('key', '')
    version = params.get('version', '')
    deferrals = params.get('deferrals', '')
    priority = params.get('priority', '')

    if not action:
        return {'success': False, 'error': 'Missing required parameter: action'}
    if not devices:
        return {'success': False, 'error': 'Missing required parameter: devices'}

    script_path = os.path.join(COMMANDS_DIR, 'schedule_os_update')

    output_lines = []
    output_lines.append("=" * 60)
    output_lines.append(f"SCHEDULE OS UPDATE - {action}")
    output_lines.append(f"Devices: {len(devices)}")
    output_lines.append("=" * 60)

    success_count = 0
    fail_count = 0

    def run_update_cmd(udid):
        try:
            env = os.environ.copy()
            env['PATH'] = '/usr/local/bin:/usr/bin:/bin:' + env.get('PATH', '')

            args = [script_path, udid, action]
            if key:
                args.extend(['--key', sanitize_param(key)])
            if version:
                args.extend(['--version', sanitize_param(version)])
            if deferrals:
                args.extend(['--deferrals', sanitize_param(deferrals)])
            if priority:
                args.extend(['--priority', sanitize_param(priority)])

            result = subprocess.run(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=60,
                cwd=COMMANDS_DIR,
                env=env
            )

            if result.returncode == 0:
                return {'success': True, 'udid': udid}
            else:
                return {'success': False, 'udid': udid, 'error': result.stderr or 'Command failed'}

        except subprocess.TimeoutExpired:
            return {'success': False, 'udid': udid, 'error': 'Timeout'}
        except Exception as e:
            return {'success': False, 'udid': udid, 'error': str(e)}

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(run_update_cmd, udid): udid for udid in devices}
        for future in as_completed(futures):
            result = future.result()
            if result['success']:
                success_count += 1
                output_lines.append(f"[OK] {result['udid']}")
            else:
                fail_count += 1
                output_lines.append(f"[FAIL] {result['udid']}: {result.get('error', 'Unknown error')}")

    output_lines.append("")
    output_lines.append("=" * 60)
    output_lines.append(f"SUMMARY: {success_count} success, {fail_count} failed")
    output_lines.append("=" * 60)

    audit_log(
        user=user_info.get('username'),
        action='schedule_os_update',
        command='schedule_os_update',
        params=params,
        result=f'{success_count} success, {fail_count} failed',
        success=(fail_count == 0)
    )

    return {
        'success': fail_count == 0,
        'output': '\n'.join(output_lines)
    }


def execute_manage_remote_desktop(params, user_info):
    """Handle Manage Remote Desktop command (enable/disable on one or more devices)"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    action = params.get('action')
    devices = normalize_devices_param(params.get('devices'))

    if not action or action not in ['enable', 'disable']:
        return {'success': False, 'error': 'Missing or invalid action. Use "enable" or "disable"'}
    if not devices:
        return {'success': False, 'error': 'Missing required parameter: devices'}

    script_name = 'enable_rd' if action == 'enable' else 'disable_rd'
    script_path = os.path.join(COMMANDS_DIR, script_name)

    output_lines = []
    output_lines.append("=" * 60)
    output_lines.append(f"MANAGE REMOTE DESKTOP - {action.upper()}")
    output_lines.append(f"Devices: {len(devices)}")
    output_lines.append("=" * 60)

    success_count = 0
    fail_count = 0

    def run_rd_cmd(udid):
        try:
            env = os.environ.copy()
            env['PATH'] = '/usr/local/bin:/usr/bin:/bin:' + env.get('PATH', '')

            result = subprocess.run(
                [script_path, udid],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=60,
                cwd=COMMANDS_DIR,
                env=env
            )

            if result.returncode == 0:
                return {'success': True, 'udid': udid}
            else:
                return {'success': False, 'udid': udid, 'error': result.stderr or 'Command failed'}

        except subprocess.TimeoutExpired:
            return {'success': False, 'udid': udid, 'error': 'Timeout'}
        except Exception as e:
            return {'success': False, 'udid': udid, 'error': str(e)}

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(run_rd_cmd, udid): udid for udid in devices}
        for future in as_completed(futures):
            result = future.result()
            if result['success']:
                success_count += 1
                output_lines.append(f"[OK] {result['udid']}")
            else:
                fail_count += 1
                output_lines.append(f"[FAIL] {result['udid']}: {result.get('error', 'Unknown error')}")

    output_lines.append("")
    output_lines.append("=" * 60)
    output_lines.append(f"SUMMARY: {success_count} success, {fail_count} failed")
    output_lines.append("=" * 60)

    audit_log(
        user=user_info.get('username'),
        action='manage_remote_desktop',
        command='manage_remote_desktop',
        params=params,
        result=f'{success_count} success, {fail_count} failed',
        success=(fail_count == 0)
    )

    return {
        'success': fail_count == 0,
        'output': '\n'.join(output_lines)
    }


def execute_manage_command_queue(params, user_info):
    """Handle Manage Command Queue command (show/clear)"""
    action = params.get('action')
    udid = sanitize_param(params.get('udid', ''))

    if not action or action not in ['show', 'clear']:
        return {'success': False, 'error': 'Missing or invalid action. Use "show" or "clear"'}
    if not udid:
        return {'success': False, 'error': 'Missing required parameter: udid'}

    output_lines = []
    output_lines.append("=" * 60)
    output_lines.append(f"COMMAND QUEUE - {action.upper()}")
    output_lines.append(f"Device: {udid}")
    output_lines.append("=" * 60)

    if action == 'show':
        # Query pending commands from enrollment_queue + commands tables
        # Include commands with no response OR NotNow status (device hasn't processed yet)
        sql = f"""
        SELECT
            c.command_uuid,
            c.request_type,
            c.created_at,
            TIMESTAMPDIFF(MINUTE, c.created_at, NOW()) as minutes_waiting,
            COALESCE(cr.status, 'Waiting') as status
        FROM commands c
        JOIN enrollment_queue eq ON c.command_uuid = eq.command_uuid
        LEFT JOIN command_results cr ON c.command_uuid = cr.command_uuid
        WHERE eq.id = '{udid}'
        AND (cr.command_uuid IS NULL OR cr.status = 'NotNow')
        ORDER BY c.created_at DESC
        LIMIT 50
        """
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
                if result.stdout.strip():
                    output_lines.append("")
                    output_lines.append(result.stdout)
                else:
                    output_lines.append("")
                    output_lines.append("No pending commands in queue.")
                return {'success': True, 'output': '\n'.join(output_lines)}
            else:
                return {'success': False, 'error': result.stderr or 'Database query failed'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    elif action == 'clear':
        # Use the existing clear_queue script with --auto flag
        script_path = os.path.join(COMMANDS_DIR, 'clear_queue')

        try:
            env = os.environ.copy()
            env['PATH'] = '/usr/local/bin:/usr/bin:/bin:' + env.get('PATH', '')

            result = subprocess.run(
                [script_path, udid, '--auto'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=60,
                cwd=COMMANDS_DIR,
                env=env
            )

            output_lines.append("")
            output_lines.append(result.stdout)
            if result.stderr:
                output_lines.append(result.stderr)

            audit_log(
                user=user_info.get('username'),
                action='clear_command_queue',
                command='manage_command_queue',
                params=params,
                result='Queue cleared' if result.returncode == 0 else 'Failed',
                success=(result.returncode == 0)
            )

            return {
                'success': result.returncode == 0,
                'output': '\n'.join(output_lines)
            }

        except subprocess.TimeoutExpired:
            return {'success': False, 'error': 'Command timed out'}
        except Exception as e:
            return {'success': False, 'error': str(e)}


def execute_manage_vpp_app(params, user_info):
    """Handle Manage VPP App command (install/remove for iOS/macOS)"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    platform = params.get('platform')
    action = params.get('action')
    devices = normalize_devices_param(params.get('devices'))
    adam_id = params.get('adam_id')

    if not platform or platform not in ['ios', 'macos']:
        return {'success': False, 'error': 'Missing or invalid platform. Use "ios" or "macos"'}
    if not action or action not in ['install', 'remove']:
        return {'success': False, 'error': 'Missing or invalid action. Use "install" or "remove"'}
    if not devices:
        return {'success': False, 'error': 'Missing required parameter: devices'}
    if not adam_id:
        return {'success': False, 'error': 'Missing required parameter: adam_id'}

    # Look up bundleId from app registry JSON
    bundle_id = ''
    app_json_file = f'/opt/nanohub/data/apps_{platform}.json'
    try:
        with open(app_json_file, 'r') as f:
            app_data = json.load(f)
        for app in app_data.get('apps', []):
            if str(app.get('adamId')) == str(adam_id):
                bundle_id = app.get('bundleId', '')
                break
    except Exception as e:
        logger.warning(f"Could not load app registry {app_json_file}: {e}")

    if not bundle_id:
        # Fallback: try iTunes API lookup
        try:
            import urllib.request
            resp = urllib.request.urlopen(f'https://itunes.apple.com/lookup?id={adam_id}', timeout=10)
            itunes_data = json.loads(resp.read())
            results = itunes_data.get('results', [])
            if results:
                bundle_id = results[0].get('bundleId', '')
        except Exception as e:
            logger.warning(f"iTunes lookup failed for adamId {adam_id}: {e}")

    if not bundle_id:
        return {'success': False, 'error': f'Cannot find bundleId for adamId {adam_id}. Add app to {app_json_file} first.'}

    # Look up serial numbers for all devices
    device_serials = {}
    try:
        placeholders = ','.join(['%s'] * len(devices))
        rows = db.query_all(
            f"SELECT uuid, serial FROM device_inventory WHERE uuid IN ({placeholders})",
            tuple(devices)
        )
        for row in rows:
            device_serials[row['uuid']] = row['serial']
    except Exception as e:
        logger.error(f"Failed to look up device serials: {e}")
        return {'success': False, 'error': f'Failed to look up device serials: {e}'}

    # Map to existing script names
    script_map = {
        ('ios', 'install'): 'install_vpp_app',
        ('ios', 'remove'): 'remove_vpp_app',
        ('macos', 'install'): 'install_vpp_app',
        ('macos', 'remove'): 'remove_vpp_app'
    }

    script_name = script_map.get((platform, action))
    script_path = os.path.join(COMMANDS_DIR, script_name)

    output_lines = []
    output_lines.append("=" * 60)
    output_lines.append(f"MANAGE VPP APP - {platform.upper()} {action.upper()}")
    output_lines.append(f"Adam ID: {adam_id} ({bundle_id})")
    output_lines.append(f"Devices: {len(devices)}")
    output_lines.append("=" * 60)

    success_count = 0
    fail_count = 0

    def run_vpp_cmd(udid):
        serial = device_serials.get(udid)
        if not serial:
            return {'success': False, 'udid': udid, 'error': 'Serial number not found in device_inventory'}
        try:
            env = os.environ.copy()
            env['PATH'] = '/usr/local/bin:/usr/bin:/bin:' + env.get('PATH', '')

            result = subprocess.run(
                [script_path, udid, adam_id, serial, bundle_id],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=60,
                cwd=COMMANDS_DIR,
                env=env
            )

            if result.returncode == 0:
                return {'success': True, 'udid': udid, 'output': result.stdout}
            else:
                return {'success': False, 'udid': udid, 'error': (result.stderr or result.stdout or 'Command failed').strip()}

        except subprocess.TimeoutExpired:
            return {'success': False, 'udid': udid, 'error': 'Timeout'}
        except Exception as e:
            return {'success': False, 'udid': udid, 'error': str(e)}

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(run_vpp_cmd, udid): udid for udid in devices}
        for future in as_completed(futures):
            result = future.result()
            if result['success']:
                success_count += 1
                output_lines.append(f"[OK] {result['udid']}")
            else:
                fail_count += 1
                output_lines.append(f"[FAIL] {result['udid']}: {result.get('error', 'Unknown error')}")

    output_lines.append("")
    output_lines.append("=" * 60)
    output_lines.append(f"SUMMARY: {success_count} success, {fail_count} failed")
    output_lines.append("=" * 60)

    audit_log(
        user=user_info.get('username'),
        action='manage_vpp_app',
        command='manage_vpp_app',
        params=params,
        result=f'{success_count} success, {fail_count} failed',
        success=(fail_count == 0)
    )

    return {
        'success': fail_count == 0,
        'output': '\n'.join(output_lines)
    }


def execute_ddm_force_sync(params, user_info):
    """Handle DDM Force Sync command (bulk push to multiple devices)"""
    devices = normalize_devices_param(params.get('devices'))

    if not devices:
        return {'success': False, 'error': 'Missing required parameter: devices'}

    # Load environment for API access
    nanohub_url = 'http://localhost:9004'
    api_key = ''
    try:
        with open(Config.ENVIRONMENT_FILE, 'r') as f:
            for line in f:
                if line.startswith('export NANOHUB_URL='):
                    nanohub_url = line.split('=', 1)[1].strip().strip('"\'')
                elif line.startswith('export NANOHUB_API_KEY='):
                    api_key = line.split('=', 1)[1].strip().strip('"\'')
    except Exception:
        pass

    auth_string = base64.b64encode(f"nanohub:{api_key}".encode()).decode()

    output_lines = []
    output_lines.append("=" * 60)
    output_lines.append("DDM FORCE SYNC")
    output_lines.append(f"Devices: {len(devices)}")
    output_lines.append("=" * 60)

    success_count = 0
    fail_count = 0

    def send_push(udid):
        try:
            req = urllib.request.Request(
                f"{nanohub_url}/api/v1/nanomdm/push/{udid}",
                method='PUT',
                headers={'Authorization': f'Basic {auth_string}'}
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                return {'success': True, 'udid': udid}
        except urllib.error.HTTPError as e:
            return {'success': False, 'udid': udid, 'error': f'HTTP {e.code}'}
        except Exception as e:
            return {'success': False, 'udid': udid, 'error': str(e)}

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(send_push, udid): udid for udid in devices}
        for future in as_completed(futures):
            result = future.result()
            if result['success']:
                success_count += 1
                output_lines.append(f"[OK] {result['udid']}")
            else:
                fail_count += 1
                output_lines.append(f"[FAIL] {result['udid']}: {result.get('error', 'Unknown error')}")

    output_lines.append("")
    output_lines.append("=" * 60)
    output_lines.append(f"SUMMARY: {success_count} success, {fail_count} failed")
    output_lines.append("=" * 60)

    return {
        'success': fail_count == 0,
        'output': '\n'.join(output_lines),
        'summary': {'success': success_count, 'failed': fail_count}
    }
