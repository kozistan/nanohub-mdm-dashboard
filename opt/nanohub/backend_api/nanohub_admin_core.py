"""
NanoHUB Admin Panel
Web interface for MDM command execution
Refactored to use centralized utility modules.
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
from web_config import get_munki_profile, get_value

# Import centralized modules
from config import Config
from db_utils import db, devices, command_history, device_details, required_profiles, app_settings
from command_executor import executor as cmd_executor
from webhook_poller import poller, poll_webhook_for_command

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('nanohub_admin')

# Paths from centralized config
AUDIT_LOG_PATH = Config.AUDIT_LOG_PATH
WEBHOOK_LOG_PATH = Config.WEBHOOK_LOG_PATH

# Create Blueprint
admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


@admin_bp.context_processor
def inject_logo():
    """Inject current logo path into all templates"""
    try:
        current_logo = app_settings.get('header_logo', '/static/logos/slotegrator_green.png')
        return {'current_logo': current_logo}
    except Exception:
        return {'current_logo': '/static/logos/slotegrator_green.png'}


# Thread pool for parallel execution (separate from cmd_executor)
thread_pool = ThreadPoolExecutor(max_workers=Config.THREAD_POOL_WORKERS)

# Legacy compatibility - DB_CONFIG from centralized config
DB_CONFIG = Config.DB


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
            # Return JSON error for AJAX requests, redirect for regular requests
            if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'error': 'Session expired. Please log in again.'}), 401
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function


# =============================================================================
# AUDIT LOGGING & COMMAND HISTORY
# =============================================================================

def get_device_info_for_uuid(uuid_val):
    """Get device info (hostname, serial) for a device UUID from database"""
    try:
        result = db.query_one(
            "SELECT hostname, serial FROM device_inventory WHERE uuid = %s",
            (uuid_val,)
        )
        return result if result else {'hostname': None, 'serial': None}
    except Exception as e:
        logger.error(f"Failed to get device info for UUID {uuid_val}: {e}")
        return {'hostname': None, 'serial': None}


def get_hostname_for_uuid(uuid_val):
    """Get hostname for a device UUID from database (backwards compatibility)"""
    return devices.get_hostname(uuid_val)


def get_device_detail(uuid_val):
    """Get complete device info from device_inventory + enrollments for Device Detail page"""
    try:
        return devices.get_by_uuid(uuid_val)
    except Exception as e:
        logger.error(f"Failed to get device detail for UUID {uuid_val}: {e}")
        return None


def get_device_command_history(uuid_val, limit=Config.DEFAULT_COMMAND_HISTORY_LIMIT):
    """Get command history for a specific device"""
    try:
        results = command_history.get_for_device(uuid_val, limit)
        # Parse params JSON
        for entry in results:
            if entry.get('params'):
                try:
                    entry['params'] = json.loads(entry['params'])
                except:
                    entry['params'] = {}
        return results
    except Exception as e:
        logger.error(f"Failed to get command history for UUID {uuid_val}: {e}")
        return []


def save_device_details(uuid_val, query_type, data):
    """Save MDM query results to device_details table"""
    try:
        result = device_details.save(uuid_val, query_type, json.dumps(data))
        if result:
            logger.info(f"Saved {query_type} data for device {uuid_val}")
        return result
    except Exception as e:
        logger.error(f"Failed to save device details: {e}")
        return False


def get_device_details(uuid_val, query_type=None):
    """Get cached device details from database"""
    try:
        if query_type:
            # Returns {'data': parsed_json, 'updated_at': timestamp}
            return device_details.get(uuid_val, query_type)

        # Full query - device_details.get() already returns parsed JSON
        row = device_details.get(uuid_val)
        if not row:
            return None

        # Convert keys from 'hardware_data' to 'hardware' for backward compatibility
        result = {}
        for field in ['hardware', 'security', 'profiles', 'apps']:
            data_key = f"{field}_data"
            result[field] = row.get(data_key)

        # Add timestamps
        for ts_field in ['hardware_updated_at', 'security_updated_at', 'profiles_updated_at', 'apps_updated_at']:
            result[ts_field] = row.get(ts_field)

        return result
    except Exception as e:
        logger.error(f"Failed to get device details: {e}")
        return None


# Cache for Apple OS versions (refreshed every 6 hours)
_apple_os_cache = {'data': None, 'timestamp': 0}
_APPLE_OS_CACHE_TTL = 6 * 60 * 60  # 6 hours in seconds


def fetch_apple_latest_os():
    """Fetch latest OS versions from IPSW.me API with caching"""
    import time
    import urllib.request
    import urllib.error

    global _apple_os_cache

    # Check cache
    now = time.time()
    if _apple_os_cache['data'] and (now - _apple_os_cache['timestamp']) < _APPLE_OS_CACHE_TTL:
        return _apple_os_cache['data']

    # Representative devices for each OS type
    devices = {
        'ios': 'iPhone16,1',      # iPhone 15 Pro
        'ipados': 'iPad14,1',     # iPad mini 6
        'macos': 'Mac15,3',       # MacBook Pro M3
    }

    result = {}

    for os_type, device_id in devices.items():
        try:
            url = f"https://api.ipsw.me/v4/device/{device_id}?type=ipsw"
            req = urllib.request.Request(url, headers={'User-Agent': 'NanoHUB/1.0'})
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode('utf-8'))

            # Find latest signed firmware
            firmwares = data.get('firmwares', [])
            signed = [f for f in firmwares if f.get('signed')]

            if signed:
                latest = signed[0]  # First signed is latest
                version = latest.get('version', '')
                build = latest.get('buildid', '')
                # Generate ProductKey in Apple's format (verified from AvailableOSUpdates responses)
                if os_type == 'ios':
                    product_key = f"iOSUpdate{build}" if build else ''
                elif os_type == 'macos':
                    product_key = f"_OSX_{build}" if build else ''
                elif os_type == 'ipados':
                    product_key = f"iPadOSUpdate{build}" if build else ''  # Assumed format
                else:
                    product_key = ''

                # Parse version tuple for comparison
                try:
                    ver_tuple = tuple(int(x) for x in str(version).split('.')[:3])
                except:
                    ver_tuple = (0,)

                result[os_type] = {
                    'version': version,
                    'build': build,
                    'product_key': product_key,
                    'ver_tuple': ver_tuple,
                    'release_date': latest.get('releasedate', '')
                }
        except Exception as e:
            logger.warning(f"Failed to fetch {os_type} version from IPSW.me: {e}")
            continue

    # Update cache if we got data
    if result:
        _apple_os_cache = {'data': result, 'timestamp': now}

    return result


def get_latest_os_versions():
    """Get latest OS versions from Apple (via IPSW.me API) for schedule_os_update info display"""
    try:
        data = fetch_apple_latest_os()

        # Remove internal ver_tuple from output for template
        result = {}
        for os_type, info in data.items():
            result[os_type] = {
                'version': info['version'],
                'build': info.get('build', ''),
                'product_key': info['product_key']
            }

        return result
    except Exception as e:
        logger.error(f"Failed to get latest OS versions: {e}")
        return {}


def execute_device_query(uuid_val, query_type):
    """Execute MDM query command and poll webhook for JSON response"""
    import re
    import uuid
    import time
    import urllib.request
    import urllib.error
    import base64

    WEBHOOK_LOG = Config.WEBHOOK_LOG_PATH
    MDM_API = Config.MDM_ENQUEUE_URL
    MDM_PUSH_API = Config.MDM_PUSH_URL
    MDM_USER = Config.MDM_API_USER

    # Load API key from environment file (service may not have env vars)
    MDM_PASS = Config.MDM_API_KEY
    try:
        with open(Config.ENVIRONMENT_FILE, 'r') as f:
            for line in f:
                if line.startswith('export NANOHUB_API_KEY='):
                    MDM_PASS = line.split('=', 1)[1].strip().strip('"\'')
                    break
    except Exception:
        pass

    def send_push(device_uuid):
        """Send APNs push notification to wake up device"""
        try:
            push_url = f'{MDM_PUSH_API}/{device_uuid}'
            req = urllib.request.Request(push_url, method='POST')
            auth_string = base64.b64encode(f'{MDM_USER}:{MDM_PASS}'.encode()).decode()
            req.add_header('Authorization', f'Basic {auth_string}')
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    logger.info(f"Push sent to {device_uuid}")
                    return True
        except Exception as e:
            logger.warning(f"Failed to send push to {device_uuid}: {e}")
        return False

    # Define MDM command templates
    query_configs = {
        'hardware': {
            'request_type': 'DeviceInformation',
            'queries': [
                'UDID', 'DeviceName', 'OSVersion', 'BuildVersion', 'ModelName',
                'Model', 'ProductName', 'SerialNumber', 'DeviceCapacity',
                'AvailableDeviceCapacity', 'BatteryLevel', 'CellularTechnology',
                'IMEI', 'MEID', 'ModemFirmwareVersion', 'IsSupervised',
                'IsDeviceLocatorServiceEnabled', 'IsActivationLockEnabled',
                'IsDoNotDisturbInEffect', 'IsCloudBackupEnabled', 'OSUpdateSettings',
                'LocalHostName', 'HostName', 'SystemIntegrityProtectionEnabled',
                'IsMDMLostModeEnabled', 'WiFiMAC', 'BluetoothMAC', 'EthernetMAC'
            ]
        },
        'security': {
            'request_type': 'SecurityInfo',
            'queries': None
        },
        'profiles': {
            'request_type': 'ProfileList',
            'queries': None
        },
        'apps': {
            'request_type': 'InstalledApplicationList',
            'queries': None
        }
    }

    if query_type not in query_configs:
        return {'success': False, 'error': f'Unknown query type: {query_type}'}

    config = query_configs[query_type]
    cmd_uuid = str(uuid.uuid4())

    # Build plist command
    if config['queries']:
        queries_xml = '\n'.join(f'            <string>{q}</string>' for q in config['queries'])
        plist = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Command</key>
    <dict>
        <key>RequestType</key>
        <string>{config['request_type']}</string>
        <key>Queries</key>
        <array>
{queries_xml}
        </array>
    </dict>
    <key>CommandUUID</key>
    <string>{cmd_uuid}</string>
</dict>
</plist>'''
    else:
        plist = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Command</key>
    <dict>
        <key>RequestType</key>
        <string>{config['request_type']}</string>
    </dict>
    <key>CommandUUID</key>
    <string>{cmd_uuid}</string>
</dict>
</plist>'''

    try:
        # Send push notification first to wake up the device
        send_push(uuid_val)
        time.sleep(1)  # Give device time to wake up

        url = f'{MDM_API}/{uuid_val}'
        auth_string = base64.b64encode(f'{MDM_USER}:{MDM_PASS}'.encode()).decode()

        # Retry logic - try up to N times if device returns NotNow
        max_retries = Config.DEVICE_QUERY_MAX_RETRIES
        for attempt in range(max_retries):
            # Generate new command UUID for each attempt
            if attempt > 0:
                cmd_uuid = str(uuid.uuid4())
                # Update plist with new UUID
                if config['queries']:
                    queries_xml = '\n'.join(f'            <string>{q}</string>' for q in config['queries'])
                    plist = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Command</key>
    <dict>
        <key>RequestType</key>
        <string>{config['request_type']}</string>
        <key>Queries</key>
        <array>
{queries_xml}
        </array>
    </dict>
    <key>CommandUUID</key>
    <string>{cmd_uuid}</string>
</dict>
</plist>'''
                else:
                    plist = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Command</key>
    <dict>
        <key>RequestType</key>
        <string>{config['request_type']}</string>
    </dict>
    <key>CommandUUID</key>
    <string>{cmd_uuid}</string>
</dict>
</plist>'''
                # Send another push before retry
                logger.info(f"Retry {attempt + 1}/{max_retries} for {query_type} on {uuid_val}")
                send_push(uuid_val)
                time.sleep(2)

            # Send command to MDM
            logger.info(f"Sending {query_type} query to device {uuid_val}, cmd_uuid={cmd_uuid}, attempt={attempt + 1}")
            req = urllib.request.Request(url, data=plist.encode('utf-8'), method='PUT')
            req.add_header('Content-Type', 'application/xml')
            req.add_header('Authorization', f'Basic {auth_string}')

            with urllib.request.urlopen(req, timeout=10) as resp:
                response_body = resp.read().decode('utf-8')
                logger.info(f"MDM API response: HTTP {resp.status}, body: {response_body[:200]}")
                if resp.status != 200:
                    return {'success': False, 'error': f'MDM API error: HTTP {resp.status}'}

            # Get current timestamp from DB before polling
            timestamp_col = f"{query_type}_updated_at"
            old_timestamp = None
            try:
                old_data = get_device_details(uuid_val, query_type)
                if old_data:
                    old_timestamp = old_data.get('updated_at')
            except:
                pass

            # Poll DB for new data (max 20 seconds per attempt)
            got_notnow = False
            for i in range(20):
                time.sleep(1)
                try:
                    # Check webhook log for NotNow or errors
                    with open(WEBHOOK_LOG, 'r') as f:
                        # Read last 100 lines
                        lines = f.readlines()[-100:]

                    # Look for our UDID in recent log entries
                    for line in reversed(lines):
                        if uuid_val in line:
                            if 'Status: NotNow' in line:
                                logger.info(f"Device {uuid_val} returned NotNow for {query_type}, attempt {attempt + 1}")
                                got_notnow = True
                                break
                            if 'Status: Error' in line or 'ErrorChain' in line:
                                logger.warning(f"Device {uuid_val} returned error for {query_type}")
                                break

                    if got_notnow:
                        break  # Exit poll loop, will retry

                    # Check if DB has new data (timestamp changed)
                    cached = get_device_details(uuid_val, query_type)
                    if cached and cached.get('data'):
                        new_timestamp = cached.get('updated_at')
                        # Data is new if timestamp changed or we had no previous data
                        if old_timestamp is None or (new_timestamp and new_timestamp != old_timestamp):
                            logger.info(f"Got fresh {query_type} data for {uuid_val} (ts: {new_timestamp})")
                            # Apply same transformations as cached path
                            cached_data = cached['data']
                            if query_type == 'profiles' and isinstance(cached_data, list):
                                profiles = []
                                for p in cached_data:
                                    profiles.append({
                                        'name': p.get('display_name', p.get('name', 'N/A')),
                                        'identifier': p.get('identifier', 'N/A'),
                                        'status': 'Managed' if p.get('is_managed') else 'Installed'
                                    })
                                cached_data = {'profiles': profiles, 'count': len(profiles)}
                            elif query_type == 'apps' and isinstance(cached_data, list):
                                apps = []
                                for a in cached_data:
                                    apps.append({
                                        'name': a.get('name', 'Unknown'),
                                        'bundle_id': a.get('identifier', a.get('bundle_id', 'N/A')),
                                        'version': a.get('version', 'N/A')
                                    })
                                cached_data = {'applications': apps, 'count': len(apps)}

                            return {
                                'success': True,
                                'data': cached_data,
                                'query_type': query_type,
                                'command_uuid': cmd_uuid
                            }

                except Exception as e:
                    logger.warning(f"Error polling for device data: {e}")
                    continue

            # If we got NotNow, continue to next retry attempt
            if got_notnow and attempt < max_retries - 1:
                continue

            # If no NotNow and no result, we timed out on this attempt
            if not got_notnow:
                break  # No point retrying if device didn't respond at all

        # All retries exhausted
        return {'success': False, 'error': 'Device not responding. It may be offline or sleeping.'}

    except urllib.error.HTTPError as e:
        logger.error(f"MDM API HTTP error for {uuid_val}: {e.code} {e.reason}")
        return {'success': False, 'error': f'MDM API error: HTTP {e.code} - Device may not be enrolled'}
    except urllib.error.URLError as e:
        logger.error(f"MDM API URL error for {uuid_val}: {e}")
        return {'success': False, 'error': f'MDM API error: {e}'}
    except Exception as e:
        logger.error(f"MDM query error for {uuid_val}: {e}")
        return {'success': False, 'error': str(e)}


def parse_webhook_output(lines, query_type):
    """Parse webhook log lines into structured JSON data"""
    import re
    import ast

    def camel_to_snake(name):
        """Convert CamelCase to snake_case"""
        s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
        return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()

    def format_value(key, value):
        """Format specific values like battery and capacity"""
        key_lower = key.lower()
        # Battery level: 0.8 -> 80%
        if 'batterylevel' in key_lower:
            try:
                level = float(value)
                if level <= 1:
                    return f"{int(level * 100)}%"
            except:
                pass
        # Capacity: already in GB, add suffix
        if 'capacity' in key_lower and 'available' not in key_lower.replace('capacity', ''):
            try:
                val = float(value)
                if val < 10000:
                    return f"{val:.1f} GB"
            except:
                pass
        if 'availabledevicecapacity' in key_lower or 'available_capacity' in key_lower:
            try:
                val = float(value)
                if val < 10000:
                    return f"{val:.1f} GB"
            except:
                pass
        return value

    result = {}

    if query_type in ['hardware', 'security']:
        # Parse key: value pairs
        for line in lines:
            # Match lines like: 2026-01-10 17:22:13,848 [INFO]     ModelName: iPhone
            match = re.search(r'\[INFO\]\s+(\w+):\s*(.+)$', line)
            if match:
                key = match.group(1).strip()
                value = match.group(2).strip()
                # Skip status/udid/topic lines
                if key.lower() not in ['status', 'udid', 'topic', 'command_uuid']:
                    # Convert to snake_case
                    snake_key = camel_to_snake(key)

                    # Try to parse dict-like values (e.g. {'IsUserEnrollment': False})
                    if value.startswith('{') and value.endswith('}'):
                        try:
                            # Replace datetime.datetime(...) with string representation
                            clean_value = re.sub(
                                r'datetime\.datetime\((\d+),\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)\)',
                                r'"\1-\2-\3 \4:\5:\6"',
                                value
                            )
                            parsed = ast.literal_eval(clean_value)
                            if isinstance(parsed, dict):
                                result[snake_key] = parsed
                                continue
                        except:
                            pass
                    # Convert boolean-like values
                    if value.lower() in ['true', 'yes', '1']:
                        result[snake_key] = True
                    elif value.lower() in ['false', 'no', '0']:
                        result[snake_key] = False
                    else:
                        # Format special values
                        result[snake_key] = format_value(key, value)

    elif query_type == 'profiles':
        # Parse profile list
        profiles = []
        for line in lines:
            # Match: [0] com.identifier (Name) — Status
            match = re.search(r'\[(\d+)\]\s+(\S+)\s+\(([^)]+)\)\s*[—-]?\s*(\w+)?', line)
            if match:
                profiles.append({
                    'index': int(match.group(1)),
                    'identifier': match.group(2),
                    'name': match.group(3),
                    'status': match.group(4) or 'Unknown'
                })
        logger.info(f"Parsed {len(profiles)} profiles from {len(lines)} lines")
        result = {'profiles': profiles, 'count': len(profiles)}

    elif query_type == 'apps':
        # Parse application list
        apps = []
        for line in lines:
            # Match: [0] AppName (com.bundle.id) v1.0
            match = re.search(r'\[(\d+)\]\s+(.+?)\s+\(([^)]+)\)\s+v?([\d.]+)?', line)
            if match:
                apps.append({
                    'index': int(match.group(1)),
                    'name': match.group(2).strip(),
                    'bundle_id': match.group(3),
                    'version': match.group(4) or '-'
                })
        logger.info(f"Parsed {len(apps)} apps from {len(lines)} lines")
        result = {'applications': apps, 'count': len(apps)}

    return result


def audit_log(user, action, command, params, result, success, execution_time_ms=None):
    """Log admin action to MySQL command_history and file"""
    try:
        # Extract device info
        device_udid = None
        device_serial = None
        device_hostname = None

        if params:
            # Handle single device UDID
            if 'udid' in params and params['udid']:
                device_udid = params['udid']
                device_info = get_device_info_for_uuid(device_udid)
                device_serial = device_info.get('serial')
                device_hostname = device_info.get('hostname')
            # Handle multiple devices (take first for primary record)
            elif 'devices' in params and params['devices']:
                devices = params['devices']
                if isinstance(devices, list) and len(devices) > 0:
                    device_udid = devices[0]
                    device_info = get_device_info_for_uuid(device_udid)
                    device_serial = device_info.get('serial')
                    device_hostname = device_info.get('hostname')

        # Get command name from registry
        from command_registry import get_command
        cmd_info = get_command(command)
        command_name = cmd_info.get('name', command) if cmd_info else command

        # Write to MySQL using centralized db_utils
        try:
            result_summary = result[:2000] if result else None
            command_history.add(
                user=user,
                command_id=command,
                command_name=command_name,
                device_udid=device_udid,
                device_serial=device_serial,
                device_hostname=device_hostname,
                params=json.dumps(params) if params else None,
                result_summary=result_summary,
                success=success,
                execution_time_ms=execution_time_ms
            )
        except Exception as db_err:
            logger.error(f"Failed to write to command_history: {db_err}")

        # Also write to file (backup)
        os.makedirs(os.path.dirname(AUDIT_LOG_PATH), exist_ok=True)
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        enriched_params = dict(params) if params else {}
        if device_hostname and device_udid:
            enriched_params['device'] = f"{device_hostname} ({device_udid})"

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


def cleanup_old_history(days=Config.DEFAULT_HISTORY_RETENTION_DAYS):
    """Delete command history older than specified days"""
    try:
        deleted_count = command_history.cleanup(days)
        logger.info(f"Cleaned up {deleted_count} old history records (older than {days} days)")
        return deleted_count
    except Exception as e:
        logger.error(f"Failed to cleanup old history: {e}")
        return 0


# =============================================================================
# VPP/ABM FUNCTIONS
# =============================================================================

def get_vpp_token():
    """Get VPP token from environment.sh"""
    try:
        with open(Config.ENVIRONMENT_FILE, 'r') as f:
            for line in f:
                if line.startswith('export VPP_TOKEN='):
                    return line.split('=', 1)[1].strip().strip('"\'')
    except Exception as e:
        logger.error(f"Failed to read VPP token: {e}")
    return None


def get_vpp_token_info():
    """Get VPP token metadata (expiration, org name)"""
    import base64
    token = get_vpp_token()
    if not token:
        return None
    try:
        decoded = base64.b64decode(token).decode('utf-8')
        return json.loads(decoded)
    except Exception as e:
        logger.error(f"Failed to decode VPP token: {e}")
        return None


def fetch_vpp_assets():
    """Fetch VPP assets (licenses) from Apple ABM API"""
    import urllib.request
    import ssl

    token = get_vpp_token()
    if not token:
        return {'error': 'VPP token not found'}

    try:
        # Create SSL context that doesn't verify (for internal use)
        ctx = ssl.create_default_context()

        req = urllib.request.Request(
            "https://vpp.itunes.apple.com/mdm/v2/assets?pageSize=500",
            headers={
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }
        )
        with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        logger.error(f"Failed to fetch VPP assets: {e}")
        return {'error': str(e)}


def get_vpp_apps_with_names():
    """Get VPP assets enriched with app names from local JSON files and iTunes API"""
    import urllib.request

    assets_response = fetch_vpp_assets()

    if 'error' in assets_response:
        return assets_response

    assets = assets_response.get('assets', [])

    # Load local app definitions for name mapping
    app_names = {}
    for json_path in [Config.APPS_IOS_JSON,
                      Config.APPS_MACOS_JSON]:
        try:
            with open(json_path, 'r') as f:
                data = json.load(f)
                for app in data.get('apps', []):
                    app_names[app.get('adamId')] = {
                        'name': app.get('name', ''),
                        'bundleId': app.get('bundleId', '')
                    }
        except Exception:
            pass

    # Collect ALL adamIds for batch lookup (to get icons)
    all_adam_ids = [str(asset.get('adamId', '')) for asset in assets if asset.get('adamId')]

    # Batch lookup from iTunes API (up to 200 at once) - for names and icons
    if all_adam_ids:
        try:
            ids_str = ','.join(all_adam_ids[:200])
            url = f"https://itunes.apple.com/lookup?id={ids_str}&country=us"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
                for result in data.get('results', []):
                    track_id = str(result.get('trackId', ''))
                    # Update or add entry with icon
                    existing = app_names.get(track_id, {})
                    app_names[track_id] = {
                        'name': existing.get('name') or result.get('trackName', ''),
                        'bundleId': existing.get('bundleId') or result.get('bundleId', ''),
                        'icon': result.get('artworkUrl60', '')
                    }
        except Exception as e:
            logger.error(f"Failed to batch lookup iTunes: {e}")

    # Enrich assets with names
    enriched = []
    for asset in assets:
        adam_id = str(asset.get('adamId', ''))
        app_info = app_names.get(adam_id, {})

        enriched.append({
            'adamId': adam_id,
            'name': app_info.get('name') or f'App {adam_id}',
            'bundleId': app_info.get('bundleId', ''),
            'icon': app_info.get('icon', ''),
            'totalCount': asset.get('totalCount', 0),
            'assignedCount': asset.get('assignedCount', 0),
            'availableCount': asset.get('availableCount', 0),
            'platforms': asset.get('supportedPlatforms', []),
            'deviceAssignable': asset.get('deviceAssignable', False)
        })

    # Sort by name
    enriched.sort(key=lambda x: x.get('name', '').lower())

    return {
        'apps': enriched,
        'tokenExpiration': assets_response.get('tokenExpirationDate'),
        'totalApps': len(enriched)
    }


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

    # Fallback: look for "Command UUID:" format (from shell scripts)
    uuid_pattern3 = r'Command\s+UUID:\s*([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})'
    match3 = re.search(uuid_pattern3, output, re.IGNORECASE)
    if match3:
        return match3.group(1)

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


# =============================================================================
# DATABASE FUNCTIONS
# =============================================================================

def get_manifests_list(manifest_filter=None):
    """Get list of manifests from manifests table, optionally filtered by pattern.

    Args:
        manifest_filter: SQL LIKE pattern e.g. 'site-%' for site-admin users

    Returns:
        List of manifest names (strings)
    """
    try:
        if manifest_filter:
            rows = db.query_all(
                "SELECT name FROM manifests WHERE name LIKE %s ORDER BY name",
                (manifest_filter,)
            )
        else:
            rows = db.query_all("SELECT name FROM manifests ORDER BY name")
        return [r['name'] for r in rows if r['name']]
    except Exception as e:
        logger.error(f"Failed to get manifests from table: {e}")
        # Fallback to device_inventory if manifests table doesn't exist
        try:
            if manifest_filter:
                rows = db.query_all(
                    "SELECT DISTINCT manifest FROM device_inventory WHERE manifest IS NOT NULL AND manifest LIKE %s ORDER BY manifest",
                    (manifest_filter,)
                )
            else:
                rows = db.query_all("SELECT DISTINCT manifest FROM device_inventory WHERE manifest IS NOT NULL ORDER BY manifest")
            return [r['manifest'] for r in rows if r['manifest']]
        except:
            return []


def get_devices_list(manifest_filter=None):
    """Get list of devices from database, optionally filtered by manifest"""
    where_clause = ""
    if manifest_filter:
        # manifest_filter is SQL LIKE pattern e.g. 'site-%'
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
        'os_version', COALESCE(
            JSON_UNQUOTE(JSON_EXTRACT(dd.hardware_data, '$.os_version')),
            JSON_UNQUOTE(JSON_EXTRACT(dd.hardware_data, '$.OSVersion')),
            ''
        ),
        'status', CASE
            WHEN e.max_last_seen IS NULL THEN 'offline'
            WHEN TIMESTAMPDIFF(MINUTE, e.max_last_seen, NOW()) <= 15 THEN 'online'
            WHEN TIMESTAMPDIFF(MINUTE, e.max_last_seen, NOW()) <= 60 THEN 'active'
            ELSE 'offline'
        END
    )
    FROM device_inventory di
    LEFT JOIN device_details dd ON di.uuid = dd.uuid
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


def get_devices_full(manifest_filter=None, search_term=None):
    """Get full device list with all fields for standard device table format.

    Returns all fields: uuid, hostname, serial, os, os_version, model, manifest,
    account, dep, supervised, encrypted, outdated, profiles_status, last_seen, status
    """
    # Get Apple latest versions for outdated detection
    apple_latest = fetch_apple_latest_os()
    latest_versions = {}
    for os_type, info in apple_latest.items():
        latest_versions[os_type] = info.get('ver_tuple', (0,))

    # Build WHERE clause
    where_parts = []
    if manifest_filter:
        where_parts.append(f"di.manifest LIKE '{manifest_filter}'")
    if search_term:
        search_escaped = search_term.replace("'", "''")
        where_parts.append(f"""(
            di.hostname LIKE '%{search_escaped}%' OR
            di.serial LIKE '%{search_escaped}%' OR
            di.uuid LIKE '%{search_escaped}%'
        )""")

    where_clause = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

    device_list = []
    try:
        rows = db.query_all(f"""
            SELECT
                di.uuid, di.hostname, di.serial, di.os, di.manifest, di.account, di.dep,
                dd.hardware_data, dd.security_data, dd.profiles_data,
                e.max_last_seen,
                CASE
                    WHEN e.max_last_seen IS NULL THEN 'offline'
                    WHEN TIMESTAMPDIFF(MINUTE, e.max_last_seen, NOW()) <= 15 THEN 'online'
                    WHEN TIMESTAMPDIFF(MINUTE, e.max_last_seen, NOW()) <= 60 THEN 'active'
                    ELSE 'offline'
                END as status
            FROM device_inventory di
            LEFT JOIN device_details dd ON di.uuid = dd.uuid
            LEFT JOIN (
                SELECT device_id, MAX(last_seen_at) as max_last_seen
                FROM enrollments
                GROUP BY device_id
            ) e ON di.uuid = e.device_id
            {where_clause}
            ORDER BY di.hostname
        """)

        for row in rows or []:
            hw = row.get('hardware_data')
            if hw and isinstance(hw, str):
                try: hw = json.loads(hw)
                except: hw = {}

            sec = row.get('security_data')
            if sec and isinstance(sec, str):
                try: sec = json.loads(sec)
                except: sec = {}

            profiles = row.get('profiles_data')
            if profiles and isinstance(profiles, str):
                try: profiles = json.loads(profiles)
                except: profiles = []
            if not profiles:
                profiles = []

            os_type = (row.get('os') or '').lower()
            os_ver = hw.get('os_version', hw.get('OSVersion', '')) if hw else ''
            model = hw.get('model_name', hw.get('ModelName', '')) if hw else ''
            manifest = row.get('manifest', '') or ''

            # Supervised
            is_supervised = False
            if hw:
                sup = hw.get('is_supervised', hw.get('IsSupervised', False))
                is_supervised = sup is True or sup == 'true'

            # Encrypted (FileVault for macOS)
            is_encrypted = False
            if sec:
                fv = sec.get('filevault_enabled', sec.get('FDE_Enabled', False))
                is_encrypted = fv is True or fv == 'true'

            # DEP enrolled (primary: security_data, fallback: di.dep)
            is_dep = False
            if sec:
                dep_sec = sec.get('enrolled_via_dep', sec.get('IsDeviceEnrollmentProgram', sec.get('DEPEnrolled')))
                is_dep = dep_sec is True or str(dep_sec).lower() in ('true', 'yes', '1')
            if not is_dep:
                # Fallback to di.dep column
                dep_val = str(row.get('dep', '')).lower()
                is_dep = dep_val in ('enabled', '1', 'yes', 'true')

            # Outdated check
            is_outdated = False
            if os_ver and os_type in latest_versions:
                try:
                    ver_tuple = tuple(int(x) for x in str(os_ver).split('.')[:3])
                    is_outdated = ver_tuple < latest_versions[os_type]
                except:
                    pass

            # Profile compliance check
            profile_check = required_profiles.check_device_profiles(manifest, os_type, profiles)

            # Last check-in
            last_seen = row.get('max_last_seen')
            last_seen_str = last_seen.strftime('%Y-%m-%d %H:%M') if last_seen else '-'

            device = {
                'uuid': row.get('uuid', ''),
                'hostname': row.get('hostname', ''),
                'serial': row.get('serial', ''),
                'os': os_type,
                'os_version': os_ver or '-',
                'model': model or '-',
                'manifest': manifest or '-',
                'account': row.get('account', '') or '-',
                'dep': 'Yes' if is_dep else 'No',
                'supervised': 'Yes' if is_supervised else 'No',
                'encrypted': 'Yes' if is_encrypted else 'No',
                'outdated': 'Yes' if is_outdated else 'No',
                'profiles_required': profile_check['required'],
                'profiles_installed': profile_check['installed'],
                'profiles_missing': profile_check['missing'],
                'profiles_complete': profile_check['complete'],
                'profiles_missing_list': profile_check['missing_list'],
                'last_seen': last_seen_str,
                'status': row.get('status', 'offline')
            }
            device_list.append(device)

    except Exception as e:
        logger.error(f"get_devices_full error: {e}")

    return device_list


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
        'os_version', COALESCE(
            JSON_UNQUOTE(JSON_EXTRACT(dd.hardware_data, '$.os_version')),
            JSON_UNQUOTE(JSON_EXTRACT(dd.hardware_data, '$.OSVersion')),
            ''
        ),
        'status', CASE
            WHEN e.max_last_seen IS NULL THEN 'offline'
            WHEN TIMESTAMPDIFF(MINUTE, e.max_last_seen, NOW()) <= 15 THEN 'online'
            WHEN TIMESTAMPDIFF(MINUTE, e.max_last_seen, NOW()) <= 60 THEN 'active'
            ELSE 'offline'
        END
    )
    FROM device_inventory di
    LEFT JOIN device_details dd ON di.uuid = dd.uuid
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


def get_required_profiles_map():
    """Get mapping of manifest -> list of profile identifiers for filtering"""
    try:
        rows = db.query_all(
            "SELECT manifest, profile_identifier FROM required_profiles ORDER BY manifest"
        )
        result = {}
        for row in rows:
            manifest = row['manifest']
            if manifest not in result:
                result[manifest] = []
            result[manifest].append(row['profile_identifier'])
        return result
    except Exception as e:
        logger.error(f"Failed to get required profiles map: {e}")
        return {}


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
    # 'site-%' means manifest must start with 'site-'
    # '%-bel' means manifest must end with '-bel'
    if manifest_filter.startswith('%') and manifest_filter.endswith('%'):
        # '%text%' - contains
        substring = manifest_filter[1:-1]
        return substring in device_manifest
    elif manifest_filter.endswith('%'):
        # 'prefix%' - starts with
        prefix = manifest_filter[:-1]
        return device_manifest.startswith(prefix)
    elif manifest_filter.startswith('%'):
        # '%suffix' - ends with
        suffix = manifest_filter[1:]
        return device_manifest.endswith(suffix)

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
    import re
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
        except:
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
            except:
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


def execute_bulk_new_device_installation(params, user_info):
    """
    Execute new device installation workflow - DB driven.
    Reads profiles from required_profiles and apps from required_applications.
    """
    import time
    import glob

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

    # Build variant filename mappings
    account_filenames = {
        'disabled': f'sloto.{platform}.Account-Disabled.profile.signed.mobileconfig',
        'enabled': f'sloto.{platform}.Account-Enabled.profile.signed.mobileconfig',
    }
    restrictions_filenames = {
        'standard': 'sloto.macos.Restrictions.profile.signed.mobileconfig',
        'icloud': 'sloto.macos.Restrictions-iCloudSync.profile.signed.mobileconfig',
        'levelc': 'sloto.macos.Restrictions-LevelC.profile.signed.mobileconfig',
    }

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
        account_filename = account_filenames.get(account_type, account_filenames['disabled'])
        install_profile(account_filename, f"Account ({account_type.capitalize()})")
    else:
        output_lines.append("  Account profile: SKIPPED")

    # Restrictions profile (macOS only, user choice: standard/icloud/levelc/skip)
    if platform == 'macos':
        if restrictions_type != 'skip':
            restrictions_filename = restrictions_filenames.get(restrictions_type, restrictions_filenames['standard'])
            install_profile(restrictions_filename, f"Restrictions ({restrictions_type.capitalize()})")
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

    # WiFi
    if install_wifi == 'yes':
        wifi_filename = f'sloto.{platform}.WiFi.profile.signed.mobileconfig'
        output_lines.append("\n[OPTIONAL] WiFi profile...")
        install_profile(wifi_filename, "WiFi")
        optional_installed.append('WiFi')

    # FileVault (macOS only)
    if platform == 'macos' and install_filevault == 'yes':
        output_lines.append("\n[OPTIONAL] FileVault profile...")
        output_lines.append("  NOTE: Client (not admin) must be logged in!")
        install_profile('sloto.macos.Filevault.profile.signed.mobileconfig', "FileVault")
        optional_installed.append('FileVault')

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
        install_profile('sloto.macos.DirectoryServices.profile.signed.mobileconfig', "Directory Services")
        optional_installed.append('Directory Services')

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
    import time

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
<body>
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
<body>
    <div id="wrap">
        <div style="display: flex; justify-content: center; align-items: center;">
            <img id="logo" src="{{ current_logo }}" alt="Logo" style="max-height:60px;max-width:200px;"/>
        </div>
        <h1>{{ command.name }}</h1>

        <div class="panel">
            <div class="admin-header">
                <h2>{{ command.description }}</h2>
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

            {% if os_versions %}
            <div class="info-box">
                <h4>Latest OS Versions in Fleet</h4>
                <div class="os-info">
                    {% if os_versions.macos %}
                    <div class="os-item">
                        <h5>macOS</h5>
                        <div class="version-info">Version: {{ os_versions.macos.version }}</div>
                        <div class="product-key">ProductKey: {{ os_versions.macos.product_key }}</div>
                    </div>
                    {% endif %}
                    {% if os_versions.ios %}
                    <div class="os-item">
                        <h5>iOS</h5>
                        <div class="version-info">Version: {{ os_versions.ios.version }}</div>
                        <div class="product-key">ProductKey: {{ os_versions.ios.product_key }}</div>
                    </div>
                    {% endif %}
                    {% if os_versions.ipados %}
                    <div class="os-item">
                        <h5>iPadOS</h5>
                        <div class="version-info">Version: {{ os_versions.ipados.version }}</div>
                        <div class="product-key">ProductKey: {{ os_versions.ipados.product_key }}</div>
                    </div>
                    {% endif %}
                </div>
                <p style="margin-top:10px;font-size:0.8em;color:#6b7280;">Use these values in Product Key and Version fields to update devices to latest version.</p>
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
                    <div class="device-table-container" style="overflow-x:auto;">
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
                    <div id="selected-device-info" class="selected-device-panel"></div>

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
                    <div class="device-table-container" style="overflow-x:auto;">
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
                    <div class="device-table-container" style="overflow-x:auto;">
                        <table class="device-table" id="autofill-device-table">
                            <thead>
                                <tr><th>Hostname</th><th>Serial</th><th>OS</th><th>Version</th><th>Model</th><th>Manifest</th><th>DEP</th><th>Supervised</th><th>Encrypted</th><th>Outdated</th><th>Last Check-in</th><th>Status</th></tr>
                            </thead>
                            <tbody id="autofill-device-tbody">
                                <tr><td colspan="12" style="text-align:center;color:#B0B0B0;">Click "Show All" or search for devices</td></tr>
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
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="/static/dashboard.css">
    <link rel="stylesheet" href="/static/css/qbone.css">
    <link rel="stylesheet" href="/static/css/admin.css">
    <link rel="shortcut icon" href="/static/favicon.ico">
</head>
<body>
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
                    <input type="date" name="date_from" value="{{ date_from or '' }}">
                </div>
                <div class="filter-group">
                    <label>Date To</label>
                    <input type="date" name="date_to" value="{{ date_to or '' }}">
                </div>
                <div class="filter-group">
                    <label>Device (UDID/Serial/Hostname)</label>
                    <input type="text" name="device" value="{{ device_filter or '' }}" placeholder="Search device...">
                </div>
                <div class="filter-group">
                    <label>User</label>
                    <select name="user_filter">
                        <option value="">All users</option>
                        {% for u in users %}
                        <option value="{{ u }}" {% if u == user_filter %}selected{% endif %}>{{ u }}</option>
                        {% endfor %}
                    </select>
                </div>
                <div class="filter-group">
                    <label>Status</label>
                    <select name="status">
                        <option value="">All</option>
                        <option value="1" {% if status_filter == '1' %}selected{% endif %}>Success</option>
                        <option value="0" {% if status_filter == '0' %}selected{% endif %}>Failed</option>
                    </select>
                </div>
                <div class="filter-buttons">
                    <button type="submit" class="btn">Filter</button>
                    <button type="button" class="btn" onclick="window.location.href='/admin/history'">Clear</button>
                </div>
            </form>

            <div class="result-info">
                Showing {{ history|length }} of {{ total_count }} records
                {% if total_count > 0 %}(Page {{ page }} of {{ total_pages }}){% endif %}
            </div>

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
                        <td>{{ entry.user }}</td>
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

            {% if total_pages > 1 %}
            <div style="margin-top:15px;padding:10px 0;border-top:1px solid #e7eaf2;">
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

ADMIN_PROFILES_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Required Profiles - NanoHUB Admin</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="/static/dashboard.css">
    <link rel="stylesheet" href="/static/css/qbone.css">
    <link rel="stylesheet" href="/static/css/admin.css">
    <link rel="shortcut icon" href="/static/favicon.ico">
</head>
<body>
    <div id="wrap">
        <div style="display: flex; justify-content: center;">
            <img id="logo" src="{{ current_logo }}" alt="Logo" style="max-height:60px;max-width:200px;"/>
        </div>
        <h1>Required Profiles</h1>

        <div class="panel">
            <div class="admin-header">
                <h2>Profile Requirements</h2>
                <div class="nav-tabs" style="margin:0;">
                    <a href="/admin" class="btn">Commands</a>
                    <a href="/admin/devices" class="btn">Devices</a>
                    <a href="/admin/profiles" class="btn active">Profiles</a>
                    <a href="/admin/vpp" class="btn">VPP</a>
                    <a href="/admin/reports" class="btn">Reports</a>
                    <a href="/admin/history" class="btn">History</a>
                </div>
                <div>
                    <span style="color:#B0B0B0;font-size:0.85em;">{{ user.display_name or user.username }}</span>
                    <span class="role-badge">{{ user.role }}</span>
                    {% if user.role == 'admin' %}<a href="/admin/settings" class="btn" style="margin-left:10px;">Settings</a>{% endif %}
                    <a href="/admin/help" class="btn" style="margin-left:10px;">Help</a>
                    <a href="/" class="btn" style="margin-left:10px;">Dashboard</a>
                </div>
            </div>

            <!-- Filter row -->
            <div class="filter-form">
                <div class="filter-group">
                    <label>Manifest</label>
                    <select id="filterManifest" onchange="filterProfiles()">
                        <option value="">All Manifests</option>
                        {% for m in manifests %}
                        <option value="{{ m }}">{{ m }}</option>
                        {% endfor %}
                    </select>
                </div>
                <div class="filter-group">
                    <label>OS</label>
                    <select id="filterOS" onchange="filterProfiles()">
                        <option value="">All</option>
                        <option value="macos">macOS</option>
                        <option value="ios">iOS</option>
                    </select>
                </div>
                <div class="filter-group">
                    <label>Search</label>
                    <input type="text" id="filterSearch" placeholder="Profile name..." onkeyup="filterProfiles()">
                </div>
                <div class="filter-buttons" style="margin-left:auto;">
                    <button class="btn" style="background:#5FC812;color:#0D0D0D;border-color:#5FC812;" onclick="openAddModal()">Add Profile</button>
                </div>
            </div>

            <!-- Profiles Table -->
            <table class="device-table" id="profilesTable">
                <thead>
                    <tr>
                        <th>Profile Name</th>
                        <th>Identifier</th>
                        <th>OS</th>
                        <th>Manifest</th>
                        <th style="text-align:center;">Pattern</th>
                        <th style="width:80px;text-align:center;">Actions</th>
                    </tr>
                </thead>
                <tbody>
                    {% for m, os_data in required_profiles.items() %}
                        {% for os, profiles in os_data.items() %}
                            {% for p in profiles %}
                    <tr data-manifest="{{ m }}" data-os="{{ os }}" data-name="{{ p.profile_name | lower }}" data-id="{{ p.id }}">
                        <td><span class="app-name">{{ p.profile_name }}</span></td>
                        <td><span class="app-bundle">{{ p.profile_identifier }}</span></td>
                        <td><span class="platform-badge platform-{{ os }}">{{ os }}</span></td>
                        <td>{{ m }}</td>
                        <td style="text-align:center;">{% if p.match_pattern %}<span style="background:rgba(136,38,227,0.2);color:#8826E3;border:1px solid #8826E3;padding:2px 6px;border-radius:3px;font-size:0.8em;">Wildcard</span>{% else %}-{% endif %}</td>
                        <td style="text-align:center;"><button class="btn btn-small btn-danger" style="margin:0;" onclick="removeProfile({{ p.id }})">Remove</button></td>
                    </tr>
                            {% endfor %}
                        {% endfor %}
                    {% endfor %}
                    {% if not required_profiles %}
                    <tr class="no-data"><td colspan="6" style="text-align:center;color:#B0B0B0;padding:20px;">No profiles configured</td></tr>
                    {% endif %}
                </tbody>
            </table>

            <div id="pagination" style="margin-top:15px;padding:10px 0;border-top:1px solid #3A3A3A;">
                <div id="pageInfo" style="font-size:0.85em;color:#B0B0B0;margin-bottom:8px;"></div>
                <div id="pageNumbers" class="pagination"></div>
            </div>

            <div style="margin-top:15px;padding:10px;background:rgba(245,166,35,0.15);border:1px solid #F5A623;border-radius:5px;font-size:0.85em;color:#F5A623;">
                <strong>Note:</strong> Wildcard pattern matches any profile identifier starting with the given prefix (e.g. <code style="background:#2A2A2A;padding:2px 5px;border-radius:3px;">com.wireguard.%</code>).
            </div>
        </div>
    </div>

    <!-- Add Profile Modal -->
    <div id="addModal" class="modal-overlay" style="display:none;">
        <div class="modal-box">
            <h3>Add Required Profile</h3>
            <div class="modal-body">
                <label>Manifest</label>
                <select id="addManifest">
                    {% for m in manifests %}
                    <option value="{{ m }}">{{ m }}</option>
                    {% endfor %}
                </select>
                <label style="margin-top:10px;">OS</label>
                <select id="addOS">
                    <option value="macos">macOS</option>
                    <option value="ios">iOS</option>
                </select>
                <label style="margin-top:10px;">Profile</label>
                <select id="addProfileSelect" onchange="onProfileSelect()">
                    <option value="">-- Select Profile --</option>
                    {% for p in profile_options %}
                    <option value="{{ p.name }}" data-id="{{ p.identifier }}">{{ p.name }}</option>
                    {% endfor %}
                    <option value="_custom">Custom...</option>
                </select>
                <div id="customFields" style="display:none;margin-top:10px;">
                    <label>Custom Profile Name</label>
                    <input type="text" id="addCustomName" placeholder="Profile Name">
                </div>
                <label style="margin-top:10px;">Identifier</label>
                <input type="text" id="addIdentifier" placeholder="com.example.profile">
                <label style="margin-top:10px;display:flex;align-items:center;gap:8px;font-weight:normal;">
                    <input type="checkbox" id="addPattern" onchange="onPatternChange()"> Use wildcard pattern (%)
                </label>
            </div>
            <div class="modal-footer">
                <button class="btn" onclick="closeAddModal()">Cancel</button>
                <button class="btn" style="background:#10b981;color:white;" onclick="addProfile()">Add Profile</button>
            </div>
        </div>
    </div>

    <script>
    let allRows = [];
    let filteredRows = [];
    let currentPage = 1;
    const itemsPerPage = 30;

    document.addEventListener('DOMContentLoaded', function() {
        allRows = Array.from(document.querySelectorAll('#profilesTable tbody tr:not(.no-data)'));
        filteredRows = allRows;
        showPage();
    });

    function filterProfiles() {
        const manifest = document.getElementById('filterManifest').value;
        const os = document.getElementById('filterOS').value;
        const search = document.getElementById('filterSearch').value.toLowerCase();

        filteredRows = allRows.filter(row => {
            if (manifest && row.dataset.manifest !== manifest) return false;
            if (os && row.dataset.os !== os) return false;
            if (search && !row.dataset.name.includes(search)) return false;
            return true;
        });

        currentPage = 1;
        showPage();
    }

    function showPage() {
        const start = (currentPage - 1) * itemsPerPage;
        const end = start + itemsPerPage;
        const totalPages = Math.ceil(filteredRows.length / itemsPerPage) || 1;

        allRows.forEach(row => row.style.display = 'none');
        filteredRows.slice(start, end).forEach(row => row.style.display = '');

        document.getElementById('pageInfo').textContent = filteredRows.length > 0
            ? `Showing ${start + 1}-${Math.min(end, filteredRows.length)} of ${filteredRows.length} (Page ${currentPage} of ${totalPages})`
            : 'No profiles found';

        renderPageNumbers(totalPages);
    }

    function renderPageNumbers(totalPages) {
        const container = document.getElementById('pageNumbers');
        if (totalPages <= 1) { container.innerHTML = ''; return; }

        let html = '';
        if (currentPage > 1) {
            html += '<a onclick="goToPage(' + (currentPage - 1) + ')">&laquo; Prev</a>';
        } else {
            html += '<span class="disabled">&laquo; Prev</span>';
        }
        for (let p = 1; p <= totalPages; p++) {
            if (p === currentPage) {
                html += '<span class="current">' + p + '</span>';
            } else if (p <= 3 || p > totalPages - 2 || (p >= currentPage - 1 && p <= currentPage + 1)) {
                html += '<a onclick="goToPage(' + p + ')">' + p + '</a>';
            } else if (p === 4 || p === totalPages - 2) {
                html += '<span>...</span>';
            }
        }
        if (currentPage < totalPages) {
            html += '<a onclick="goToPage(' + (currentPage + 1) + ')">Next &raquo;</a>';
        } else {
            html += '<span class="disabled">Next &raquo;</span>';
        }
        container.innerHTML = html;
    }

    function goToPage(page) {
        currentPage = page;
        showPage();
    }

    function openAddModal() {
        document.getElementById('addModal').style.display = 'flex';
        document.getElementById('addProfileSelect').value = '';
        document.getElementById('addIdentifier').value = '';
        document.getElementById('addIdentifier').readOnly = true;
        document.getElementById('addPattern').checked = false;
        document.getElementById('customFields').style.display = 'none';
        document.getElementById('addCustomName').value = '';
    }

    function closeAddModal() {
        document.getElementById('addModal').style.display = 'none';
    }

    function onProfileSelect() {
        const sel = document.getElementById('addProfileSelect');
        const idInput = document.getElementById('addIdentifier');
        const customFields = document.getElementById('customFields');

        if (sel.value === '_custom') {
            customFields.style.display = 'block';
            idInput.readOnly = false;
            idInput.value = '';
        } else if (sel.value) {
            customFields.style.display = 'none';
            idInput.readOnly = true;
            idInput.value = sel.options[sel.selectedIndex].dataset.id || '';
        } else {
            customFields.style.display = 'none';
            idInput.readOnly = true;
            idInput.value = '';
        }
    }

    function onPatternChange() {
        const pattern = document.getElementById('addPattern').checked;
        const idInput = document.getElementById('addIdentifier');
        if (pattern) {
            idInput.readOnly = false;
        }
    }

    function addProfile() {
        const manifest = document.getElementById('addManifest').value;
        const os = document.getElementById('addOS').value;
        const sel = document.getElementById('addProfileSelect');
        const customName = document.getElementById('addCustomName').value.trim();
        const identifier = document.getElementById('addIdentifier').value.trim();
        const pattern = document.getElementById('addPattern').checked;

        const name = sel.value === '_custom' ? customName : sel.value;

        if (!name || !identifier) {
            alert('Please select a profile or enter custom name and identifier');
            return;
        }

        fetch('/admin/api/required-profiles/add', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                manifest: manifest,
                os: os,
                profile_name: name,
                profile_identifier: identifier,
                match_pattern: pattern
            })
        })
        .then(r => r.json())
        .then(d => {
            if (d.success) {
                location.reload();
            } else {
                alert('Error: ' + d.error);
            }
        })
        .catch(e => alert('Error: ' + e));
    }

    function removeProfile(id) {
        if (!confirm('Remove this profile requirement?')) return;

        fetch('/admin/api/required-profiles/remove', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({id: id})
        })
        .then(r => r.json())
        .then(d => {
            if (d.success) {
                const row = document.querySelector('tr[data-id="' + id + '"]');
                if (row) row.remove();
                allRows = Array.from(document.querySelectorAll('#profilesTable tbody tr:not(.no-data)'));
                filterProfiles();
            } else {
                alert('Error: ' + d.error);
            }
        })
        .catch(e => alert('Error: ' + e));
    }
    </script>
</body>
</html>
'''



# =============================================================================
# CONSOLIDATED COMMAND IMPLEMENTATIONS
# =============================================================================

def normalize_devices_param(devices):
    """Normalize devices parameter to list of UDIDs"""
    if not devices:
        return []
    if isinstance(devices, str):
        return [d.strip() for d in devices.split(',') if d.strip()]
    elif isinstance(devices, list):
        return [str(d).strip() for d in devices if d and str(d).strip()]
    return []


def execute_manage_profiles(params, user_info):
    """Handle Manage Profiles command (install/remove/list on one or more devices)"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    action = params.get('action')
    devices = normalize_devices_param(params.get('devices'))
    profile = params.get('profile')
    identifier = params.get('identifier')

    if not action:
        return {'success': False, 'error': 'Missing required parameter: action'}
    if not devices:
        return {'success': False, 'error': 'Missing required parameter: devices'}

    # Validate action-specific requirements
    if action == 'install' and not profile:
        return {'success': False, 'error': 'Profile is required for Install action'}
    if action == 'remove' and not identifier:
        return {'success': False, 'error': 'Profile Identifier is required for Remove action'}

    # Map action to script
    script_map = {
        'install': 'install_profile',
        'remove': 'remove_profile',
        'list': 'profile_list'
    }
    script_name = script_map.get(action)
    if not script_name:
        return {'success': False, 'error': f'Invalid action: {action}'}

    script_path = os.path.join(COMMANDS_DIR, script_name)

    output_lines = []
    output_lines.append("=" * 60)
    output_lines.append(f"MANAGE PROFILES - {action.upper()}")
    output_lines.append(f"Devices: {len(devices)}")
    output_lines.append("=" * 60)

    success_count = 0
    fail_count = 0

    def run_profile_cmd(udid):
        try:
            env = os.environ.copy()
            env['PATH'] = '/usr/local/bin:/usr/bin:/bin:' + env.get('PATH', '')

            args = [script_path, udid]
            if action == 'install':
                # Resolve profile path
                profile_path = profile
                if not profile_path.startswith('/'):
                    for pdir in PROFILE_DIRS.values():
                        full_path = os.path.join(pdir, profile_path)
                        if os.path.exists(full_path):
                            profile_path = full_path
                            break
                args.append(profile_path)
            elif action == 'remove':
                args.append(identifier)

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
                return {'success': True, 'udid': udid, 'output': result.stdout}
            else:
                return {'success': False, 'udid': udid, 'error': result.stderr or 'Command failed'}

        except subprocess.TimeoutExpired:
            return {'success': False, 'udid': udid, 'error': 'Timeout'}
        except Exception as e:
            return {'success': False, 'udid': udid, 'error': str(e)}

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(run_profile_cmd, udid): udid for udid in devices}
        for future in as_completed(futures):
            result = future.result()
            if result['success']:
                success_count += 1
                output_lines.append(f"[OK] {result['udid']}")
                if action == 'list' and result.get('output'):
                    output_lines.append(result['output'])
            else:
                fail_count += 1
                output_lines.append(f"[FAIL] {result['udid']}: {result.get('error', 'Unknown error')}")

    output_lines.append("")
    output_lines.append("=" * 60)
    output_lines.append(f"SUMMARY: {success_count} success, {fail_count} failed")
    output_lines.append("=" * 60)

    audit_log(
        user=user_info.get('username'),
        action='manage_profiles',
        command='manage_profiles',
        params=params,
        result=f'{success_count} success, {fail_count} failed',
        success=(fail_count == 0)
    )

    return {
        'success': fail_count == 0,
        'output': '\n'.join(output_lines)
    }


def execute_manage_ddm_sets(params, user_info):
    """Handle Manage DDM Sets command (assign/remove on one or more devices)"""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import urllib.request
    import base64

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
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import time
    from datetime import datetime, timedelta

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
        sql = f"""
        SELECT
            c.command_uuid,
            c.request_type,
            c.created_at,
            TIMESTAMPDIFF(MINUTE, c.created_at, NOW()) as minutes_waiting
        FROM commands c
        JOIN enrollment_queue eq ON c.command_uuid = eq.command_uuid
        LEFT JOIN command_results cr ON c.command_uuid = cr.command_uuid
        WHERE eq.id = '{udid}'
        AND cr.command_uuid IS NULL
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
    output_lines.append(f"Adam ID: {adam_id}")
    output_lines.append(f"Devices: {len(devices)}")
    output_lines.append("=" * 60)

    success_count = 0
    fail_count = 0

    def run_vpp_cmd(udid):
        try:
            env = os.environ.copy()
            env['PATH'] = '/usr/local/bin:/usr/bin:/bin:' + env.get('PATH', '')

            result = subprocess.run(
                [script_path, udid, adam_id],
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


# =============================================================================
# DEVICE DETAIL TEMPLATE
# =============================================================================

DEVICE_DETAIL_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ device.hostname or device.uuid }} - Device Detail</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="/static/dashboard.css">
    <link rel="stylesheet" href="/static/css/qbone.css">
    <link rel="stylesheet" href="/static/css/admin.css">
    <link rel="shortcut icon" href="/static/favicon.ico">
    <style>
        /* Device Detail page-specific styles */
        .tabs {
            display: flex;
            gap: 5px;
            margin-bottom: 20px;
            border-bottom: 2px solid #3A3A3A;
            padding-bottom: 0;
        }
        .tab-btn {
            padding: 10px 20px;
            background: transparent;
            border: none;
            cursor: pointer;
            font-size: 0.95em;
            color: #B0B0B0;
            border-bottom: 2px solid transparent;
            margin-bottom: -2px;
            transition: all 0.2s;
        }
        .tab-btn:hover { color: #5FC812; }
        .tab-btn.active {
            color: #FFFFFF;
            border-bottom-color: #5FC812;
            font-weight: 600;
        }
        .tab-btn .badge {
            background: #3A3A3A;
            color: #B0B0B0;
            padding: 2px 8px;
            border-radius: 10px;
            font-size: 0.8em;
            margin-left: 5px;
        }
        .tab-btn.active .badge { background: #5FC812; color: #0D0D0D; }

        .tab-content { display: none; }
        .tab-content.active { display: block; }

        .info-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
            gap: 12px;
        }
        .info-card {
            background: #2A2A2A;
            border: 1px solid #3A3A3A;
            padding: 12px;
            border-radius: 8px;
            overflow: hidden;
            text-align: left;
        }
        .info-card.wide {
            grid-column: span 2;
        }
        .info-card.full-width {
            grid-column: 1 / -1;
        }
        .info-card.wide .value,
        .info-card.full-width .value {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
            gap: 0 20px;
        }
        .info-card label {
            display: block;
            font-size: 0.8em;
            color: #B0B0B0;
            margin-bottom: 4px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .info-card .value {
            font-size: 0.95em;
            font-weight: 500;
            color: #FFFFFF;
            word-break: break-word;
            overflow-wrap: break-word;
        }
        .info-card .nested-item {
            display: flex;
            padding: 3px 0;
            gap: 8px;
            font-size: 0.85em;
            border-bottom: 1px solid #3A3A3A;
        }
        .info-card .nested-item:last-child {
            border-bottom: none;
        }
        .info-card .nested-item .nested-key {
            color: #B0B0B0;
            min-width: 240px;
            flex-shrink: 0;
        }
        .info-card .nested-item .nested-val {
            color: #FFFFFF;
            word-break: break-all;
        }

        .security-badge {
            display: inline-block;
            padding: 4px 10px;
            border-radius: 4px;
            font-size: 0.85em;
            font-weight: 500;
        }
        .security-badge.ok { background: rgba(95,200,18,0.15); color: #5FC812; border: 1px solid #5FC812; }
        .security-badge.warn { background: rgba(245,166,35,0.15); color: #F5A623; border: 1px solid #F5A623; }
        .security-badge.bad { background: rgba(217,31,37,0.15); color: #D91F25; border: 1px solid #D91F25; }

        .quick-actions {
            display: flex;
            gap: 10px;
            margin-top: 20px;
            padding-top: 20px;
            border-top: 1px solid #3A3A3A;
        }
        .quick-actions .btn { min-width: 100px; }

        .loading-spinner {
            display: inline-block;
            width: 16px;
            height: 16px;
            border: 2px solid #3A3A3A;
            border-top-color: #5FC812;
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
            margin-right: 8px;
        }
        @keyframes spin {
            to { transform: rotate(360deg); }
        }

        .refresh-btn {
            float: right;
            padding: 5px 12px;
            font-size: 0.85em;
        }

        .output-box {
            background: #1e293b;
            color: #e2e8f0;
            padding: 15px;
            border-radius: 8px;
            font-family: monospace;
            font-size: 0.85em;
            max-height: 400px;
            overflow-y: auto;
            white-space: pre-wrap;
            word-break: break-all;
        }

        .error-box {
            background: rgba(217,31,37,0.1);
            border: 1px solid #D91F25;
            color: #D91F25;
            padding: 15px;
            border-radius: 8px;
            text-align: center;
        }
    </style>
</head>
<body>
    <div id="wrap">
        <div style="display: flex; justify-content: center; align-items: center;">
            <img id="logo" src="{{ current_logo }}" alt="Logo" style="max-height:60px;max-width:200px;"/>
        </div>
        <h1>Device Detail</h1>

        <div class="panel">
            <div class="admin-header">
                <h2>
                    <span class="status-dot {{ device.status }}"></span>
                    {{ device.hostname or 'Unknown' }}
                    <span class="os-badge {{ device.os }}">{{ device.os }}</span>
                </h2>
                <a href="/admin/devices" class="btn">Back to Devices</a>
            </div>

            <div class="tabs">
                <button class="tab-btn active" onclick="showTab('info')">Info</button>
                <button class="tab-btn" onclick="showTab('hardware')" id="tab-hardware">Hardware</button>
                <button class="tab-btn" onclick="showTab('security')" id="tab-security">Security</button>
                <button class="tab-btn" onclick="showTab('profiles')" id="tab-profiles">Profiles <span class="badge" id="profiles-count">-</span></button>
                <button class="tab-btn" onclick="showTab('apps')" id="tab-apps">Apps <span class="badge" id="apps-count">-</span></button>
                <button class="tab-btn" onclick="showTab('history')">History <span class="badge">{{ history|length }}</span></button>
            </div>

            <!-- Info Tab -->
            <div id="tab-content-info" class="tab-content active">
                <div class="info-grid">
                    <div class="info-card">
                        <label>UUID</label>
                        <div class="value" style="font-size:0.9em; font-family:monospace;">{{ device.uuid }}</div>
                    </div>
                    <div class="info-card">
                        <label>Serial Number</label>
                        <div class="value">{{ device.serial or '-' }}</div>
                    </div>
                    <div class="info-card">
                        <label>Hostname</label>
                        <div class="value">{{ device.hostname or '-' }}</div>
                    </div>
                    <div class="info-card">
                        <label>Operating System</label>
                        <div class="value">{{ device.os | upper }}</div>
                    </div>
                    <div class="info-card">
                        <label>Manifest</label>
                        <div class="value">{{ device.manifest or 'default' }}</div>
                    </div>
                    <div class="info-card">
                        <label>DEP Enrolled</label>
                        <div class="value">{{ 'Yes' if device.dep in ['1', 'enabled', True] else 'No' }}</div>
                    </div>
                    <div class="info-card">
                        <label>Status</label>
                        <div class="value">
                            <span class="status-dot {{ device.status }}"></span>
                            {{ device.status | capitalize }}
                        </div>
                    </div>
                    <div class="info-card">
                        <label>Last Seen</label>
                        <div class="value">{{ device.last_seen_at or 'Never' }}</div>
                    </div>
                </div>

                <div class="quick-actions">
                    <button class="btn" onclick="executeDeviceAction('lock')">Lock</button>
                    <button class="btn" onclick="executeDeviceAction('restart')">Restart</button>
                    <button class="btn red" onclick="showEraseModal()" style="margin-left:auto;">Erase Device</button>
                </div>
            </div>

            <!-- Erase Confirmation Modal -->
            <div id="erase-modal" style="display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.4);z-index:1000;align-items:center;justify-content:center;">
                <div style="background:white;padding:15px;border-radius:8px;max-width:400px;width:90%;box-shadow:0 4px 20px rgba(0,0,0,0.15);font-size:0.85em;">
                    <h3 style="margin:0 0 10px 0;color:#dc2626;font-size:0.95em;">Erase Device</h3>
                    <p style="color:#B0B0B0;margin-bottom:12px;">
                        <strong>WARNING:</strong> This will permanently erase ALL DATA on the device. This action cannot be undone!
                    </p>
                    <p style="color:#B0B0B0;margin-bottom:8px;">
                        Device: <strong>{{ device.hostname }}</strong> ({{ device.serial }})
                    </p>
                    <p style="color:#6b7280;margin-bottom:10px;">
                        To confirm, type <strong style="color:#dc2626;">ERASE</strong> below:
                    </p>
                    <input type="text" id="erase-confirm-input" placeholder="Type ERASE to confirm"
                           style="width:100%;padding:8px;border:1px solid #d1d5db;border-radius:4px;font-size:0.9em;margin-bottom:12px;box-sizing:border-box;"
                           oninput="checkEraseInput()">
                    <div style="display:flex;gap:8px;justify-content:flex-end;">
                        <button class="btn" onclick="hideEraseModal()" style="font-size:0.85em;padding:6px 14px;">Cancel</button>
                        <button class="btn red" id="erase-confirm-btn" onclick="confirmErase()" disabled
                                style="opacity:0.5;cursor:not-allowed;font-size:0.85em;padding:6px 14px;">Erase Device</button>
                    </div>
                </div>
            </div>

            <!-- Hardware Tab -->
            <div id="tab-content-hardware" class="tab-content">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:15px;">
                    <div>
                        <h3 style="margin:0;display:inline;">Hardware Information</h3>
                        <span id="hardware-timestamp" style="margin-left:15px;"></span>
                    </div>
                    <button class="btn" onclick="refreshData('hardware')">Refresh from Device</button>
                </div>
                <div id="hardware-loading" style="display:none;"><span class="loading-spinner"></span> Querying device...</div>
                <div id="hardware-content" class="info-grid"></div>
            </div>

            <!-- Security Tab -->
            <div id="tab-content-security" class="tab-content">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:15px;">
                    <div>
                        <h3 style="margin:0;display:inline;">Security Information</h3>
                        <span id="security-timestamp" style="margin-left:15px;"></span>
                    </div>
                    <button class="btn" onclick="refreshData('security')">Refresh from Device</button>
                </div>
                <div id="security-loading" style="display:none;"><span class="loading-spinner"></span> Querying device...</div>
                <div id="security-content" class="info-grid"></div>
            </div>

            <!-- Profiles Tab -->
            <div id="tab-content-profiles" class="tab-content">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:15px;">
                    <div>
                        <h3 style="margin:0;display:inline;">Installed Profiles</h3>
                        <span id="profiles-timestamp" style="margin-left:15px;"></span>
                    </div>
                    <button class="btn" onclick="refreshData('profiles')">Refresh from Device</button>
                </div>

                <!-- Required Profiles Status Box -->
                {% if required_profiles_status and required_profiles_status.required > 0 %}
                <div class="info-box">
                    <h4>Required Profiles for {{ device.manifest or 'default' }}</h4>
                    <div style="display:flex;gap:15px;margin-bottom:10px;font-size:0.85em;">
                        <span style="color:#5FC812;"><strong>{{ required_profiles_status.installed }}</strong> installed</span>
                        <span style="color:#D91F25;"><strong>{{ required_profiles_status.missing }}</strong> missing</span>
                    </div>
                    <div style="display:flex;flex-wrap:wrap;gap:8px;">
                        {% for p in required_profiles_status.all_profiles %}
                        <span style="padding:4px 10px;border-radius:4px;font-size:0.85em;{% if p.installed %}background:rgba(95,200,18,0.15);color:#5FC812;border:1px solid #5FC812;{% else %}background:rgba(217,31,37,0.15);color:#D91F25;border:1px solid #D91F25;{% endif %}">
                            {{ p.name }}
                        </span>
                        {% endfor %}
                    </div>
                </div>
                {% endif %}

                <div id="profiles-loading" style="display:none;"><span class="loading-spinner"></span> Querying device...</div>
                <div id="profiles-content"></div>
            </div>

            <!-- Apps Tab -->
            <div id="tab-content-apps" class="tab-content">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:15px;">
                    <div>
                        <h3 style="margin:0;display:inline;">Installed Applications</h3>
                        <span id="apps-timestamp" style="margin-left:15px;"></span>
                    </div>
                    <button class="btn" onclick="refreshData('apps')">Refresh from Device</button>
                </div>
                <div id="apps-loading" style="display:none;"><span class="loading-spinner"></span> Querying device...</div>
                <div id="apps-content"></div>
            </div>

            <!-- History Tab -->
            <div id="tab-content-history" class="tab-content">
                <h3>Command History</h3>
                {% if history %}
                <table class="history-table">
                    <thead>
                        <tr>
                            <th>Timestamp</th>
                            <th>User</th>
                            <th>Command</th>
                            <th>Status</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for entry in history %}
                        <tr>
                            <td>{{ entry.timestamp }}</td>
                            <td>{{ entry.user }}</td>
                            <td>{{ entry.command_name }}</td>
                            <td class="{{ 'status-success' if entry.success else 'status-failed' }}">
                                {{ 'Success' if entry.success else 'Failed' }}
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
                <div style="margin-top:15px;">
                    <a href="/admin/history?device={{ device.uuid }}" class="btn">View Full History</a>
                </div>
                {% else %}
                <p>No command history for this device.</p>
                {% endif %}
            </div>
        </div>
    </div>

    <script>
        const deviceUuid = '{{ device.uuid }}';

        function showTab(tabName) {
            document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
            document.getElementById('tab-content-' + tabName).classList.add('active');
            event.target.classList.add('active');
        }

        function loadData(type, forceRefresh = false) {
            const loadingEl = document.getElementById(type + '-loading');
            const contentEl = document.getElementById(type + '-content');
            const timestampEl = document.getElementById(type + '-timestamp');

            loadingEl.style.display = 'block';
            if (forceRefresh) contentEl.innerHTML = '';

            fetch('/admin/api/device/' + deviceUuid + '/query', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({query_type: type, force_refresh: forceRefresh})
            })
            .then(r => r.json())
            .then(data => {
                loadingEl.style.display = 'none';
                if (data.success && data.data) {
                    renderData(type, data.data, contentEl);
                    // Show timestamp
                    if (timestampEl) {
                        if (data.cached && data.updated_at) {
                            timestampEl.innerHTML = '<span style="color:#6b7280;font-size:0.85em;">Cached: ' + data.updated_at + '</span>';
                        } else if (!data.cached) {
                            timestampEl.innerHTML = '<span style="color:#27ae60;font-size:0.85em;">Updated just now</span>';
                        }
                    }
                } else {
                    contentEl.innerHTML = '<div class="error-box">' + (data.error || 'No data received') + '</div>';
                    if (timestampEl) timestampEl.innerHTML = '';
                }
            })
            .catch(err => {
                loadingEl.style.display = 'none';
                contentEl.innerHTML = '<div class="error-box">Error: ' + err.message + '</div>';
            });
        }

        function refreshData(type) {
            loadData(type, true);  // Force refresh from MDM
        }

        function renderData(type, data, container) {
            if (type === 'hardware' || type === 'security') {
                // Render key-value pairs as info cards
                let html = '';
                for (const [key, value] of Object.entries(data)) {
                    let displayVal;
                    let cardClass = 'info-card';

                    if (typeof value === 'boolean') {
                        displayVal = value ? '<span style="color:#27ae60">Yes</span>' : '<span style="color:#dc2626">No</span>';
                    } else if (Array.isArray(value)) {
                        displayVal = value.length + ' items';
                        if (value.length > 5) cardClass += ' wide';
                    } else if (typeof value === 'object' && value !== null) {
                        // Handle nested objects - display as nice list
                        const entries = Object.entries(value);
                        const parts = [];
                        for (const [k, v] of entries) {
                            if (typeof v === 'boolean') {
                                parts.push('<div class="nested-item"><span class="nested-key">' + formatKey(k) + '</span><span class="nested-val">' + (v ? '<span style="color:#27ae60">Yes</span>' : '<span style="color:#dc2626">No</span>') + '</span></div>');
                            } else if (typeof v !== 'object') {
                                let displayV = String(v);
                                if (displayV.length > 60) {
                                    displayV = '<span title="' + displayV.replace(/"/g, '&quot;') + '">' + displayV.substring(0, 57) + '...</span>';
                                }
                                parts.push('<div class="nested-item"><span class="nested-key">' + formatKey(k) + '</span><span class="nested-val">' + displayV + '</span></div>');
                            }
                        }
                        displayVal = parts.length > 0 ? parts.join('') : '-';
                        // Dynamic sizing based on content
                        if (entries.length >= 3) {
                            cardClass += ' wide';
                        }
                    } else {
                        displayVal = value || '-';
                        // Wide card for long text values
                        if (String(value).length > 30) cardClass += ' wide';
                    }
                    html += `<div class="${cardClass}"><label>${formatKey(key)}</label><div class="value">${displayVal}</div></div>`;
                }
                container.innerHTML = html || '<div class="error-box">No data available</div>';

            } else if (type === 'profiles') {
                const profiles = data.profiles || [];
                document.getElementById('profiles-count').textContent = profiles.length;

                if (profiles.length === 0) {
                    container.innerHTML = '<div class="error-box">No profiles installed</div>';
                    return;
                }

                let html = '<table class="history-table"><thead><tr><th>#</th><th>Name</th><th>Identifier</th><th>Status</th></tr></thead><tbody>';
                profiles.forEach((p, i) => {
                    html += `<tr><td>${i + 1}</td><td>${p.name}</td><td style="font-size:0.85em;color:#6b7280;">${p.identifier}</td><td>${p.status}</td></tr>`;
                });
                html += '</tbody></table>';
                container.innerHTML = html;

            } else if (type === 'apps') {
                const allApps = data.applications || [];
                const thirdPartyApps = allApps.filter(a => a.bundle_id && !a.bundle_id.startsWith('com.apple.'));
                document.getElementById('apps-count').textContent = allApps.length;

                if (allApps.length === 0) {
                    container.innerHTML = '<div class="error-box">No applications found</div>';
                    return;
                }

                let html = '<div style="margin-bottom:10px;display:flex;gap:10px;align-items:center;">';
                html += '<input type="text" id="apps-search" placeholder="Search apps..." onkeyup="filterApps()" style="padding:8px;width:300px;border:1px solid #d1d5db;border-radius:5px;">';
                html += '<label style="display:flex;align-items:center;gap:5px;cursor:pointer;"><input type="checkbox" id="hide-system" onchange="filterApps()"> Hide system apps (com.apple.*)</label>';
                html += '<span style="color:#6b7280;font-size:0.9em;">Total: ' + allApps.length + ' | Third-party: ' + thirdPartyApps.length + '</span>';
                html += '</div>';
                html += '<table class="history-table" id="apps-table"><thead><tr><th>#</th><th>Name</th><th>Bundle ID</th><th>Version</th></tr></thead><tbody>';
                allApps.forEach((a, i) => {
                    const isSystem = a.bundle_id && a.bundle_id.startsWith('com.apple.');
                    html += `<tr data-system="${isSystem}"><td>${i + 1}</td><td>${a.name}</td><td style="font-size:0.85em;color:#6b7280;">${a.bundle_id}</td><td>${a.version}</td></tr>`;
                });
                html += '</tbody></table>';
                container.innerHTML = html;
            }
        }

        function formatKey(key) {
            // Handle common acronyms
            let result = key
                .replace(/([a-z])([A-Z])/g, '$1 $2')  // camelCase to spaces
                .replace(/([A-Z]+)([A-Z][a-z])/g, '$1 $2')  // Handle consecutive caps
                .replace(/^./, s => s.toUpperCase());
            // Fix known acronyms
            result = result.replace(/O S /g, 'OS ').replace(/I D/g, 'ID').replace(/M A C/g, 'MAC')
                          .replace(/D E P/g, 'DEP').replace(/S I P/g, 'SIP').replace(/U R L/g, 'URL');
            return result.trim();
        }

        function filterApps() {
            const search = document.getElementById('apps-search').value.toLowerCase();
            const hideSystem = document.getElementById('hide-system')?.checked || false;
            const rows = document.querySelectorAll('#apps-table tbody tr');
            rows.forEach(row => {
                const text = row.textContent.toLowerCase();
                const isSystem = row.dataset.system === 'true';
                const matchesSearch = text.includes(search);
                const showRow = matchesSearch && !(hideSystem && isSystem);
                row.style.display = showRow ? '' : 'none';
            });
        }

        function showEraseModal() {
            document.getElementById('erase-modal').style.display = 'flex';
            document.getElementById('erase-confirm-input').value = '';
            document.getElementById('erase-confirm-btn').disabled = true;
            document.getElementById('erase-confirm-btn').style.opacity = '0.5';
            document.getElementById('erase-confirm-btn').style.cursor = 'not-allowed';
        }

        function hideEraseModal() {
            document.getElementById('erase-modal').style.display = 'none';
        }

        function checkEraseInput() {
            const input = document.getElementById('erase-confirm-input').value;
            const btn = document.getElementById('erase-confirm-btn');
            if (input === 'ERASE') {
                btn.disabled = false;
                btn.style.opacity = '1';
                btn.style.cursor = 'pointer';
            } else {
                btn.disabled = true;
                btn.style.opacity = '0.5';
                btn.style.cursor = 'not-allowed';
            }
        }

        function confirmErase() {
            hideEraseModal();
            fetch('/admin/execute', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    command: 'device_action',
                    params: {action: 'erase', udid: deviceUuid, confirm_erase: 'ERASE'}
                })
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    alert('Erase command sent successfully. Device will be wiped.');
                } else {
                    alert('Error: ' + (data.error || data.output || 'Unknown error'));
                }
            })
            .catch(err => alert('Error: ' + err.message));
        }

        function executeDeviceAction(action) {
            fetch('/admin/execute', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({command: 'device_action', params: {action: action, udid: deviceUuid}})
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    alert('Command sent successfully');
                } else {
                    alert('Error: ' + (data.error || data.output || 'Unknown error'));
                }
            })
            .catch(err => alert('Error: ' + err.message));
        }

        function executeAction(action) {
            // For system_report, use the query API to get full data
            if (action === 'system_report') {
                showTab('hardware');
                document.querySelector('.tab-btn[onclick*="hardware"]').classList.add('active');
                refreshData('hardware');
                return;
            }

            fetch('/admin/execute', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({command: action, params: {udid: deviceUuid}})
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    alert('Command sent successfully');
                } else {
                    alert('Error: ' + (data.error || data.output || 'Unknown error'));
                }
            })
            .catch(err => alert('Error: ' + err.message));
        }

        // Auto-load data on page load
        // Load cached data on page load (fast), user can click Refresh for live data
        document.addEventListener('DOMContentLoaded', function() {
            setTimeout(() => loadData('hardware'), 100);
            setTimeout(() => loadData('security'), 200);
            setTimeout(() => loadData('profiles'), 300);
            setTimeout(() => loadData('apps'), 400);
        });
    </script>
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

    # Refresh manifest options from DB for commands with manifest parameter
    import copy
    command = copy.deepcopy(command)  # Don't modify cached command
    manifest_filter = user.get('manifest_filter')
    fresh_manifests = get_manifests_list(manifest_filter)
    for param in command.get('parameters', []):
        if param.get('name') == 'manifest' and param.get('type') == 'select':
            # Build fresh options from DB
            param['options'] = [{'value': '', 'label': '-- Select Manifest --'}]
            param['options'].extend([{'value': m, 'label': m} for m in fresh_manifests])
        # Load applications list for Manage Applications command - empty by default, loaded via JS
        if param.get('name') == 'app_id' and param.get('type') == 'select':
            param['options'] = [{'value': '', 'label': '-- Select Manifest first --'}]
    profiles = get_profiles_by_category()

    # Check if command has 'devices' type parameter (multi-select)
    has_devices_param = any(p['type'] == 'devices' for p in command.get('parameters', []))

    # Get latest OS versions for schedule_os_update command
    os_versions = None
    if cmd_id == 'schedule_os_update':
        os_versions = get_latest_os_versions()

    return render_template_string(
        ADMIN_COMMAND_TEMPLATE,
        user=user,
        manifests=fresh_manifests,
        command=command,
        cmd_id=cmd_id,
        profiles=profiles,
        has_devices_param=has_devices_param,
        os_versions=os_versions
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
    native_bulk_commands = ['bulk_schedule_os_update', 'bulk_new_device_installation', 'bulk_install_application']
    if 'devices' in params and isinstance(params.get('devices'), list) and cmd_id not in native_bulk_commands:
        results = execute_bulk_command(cmd_id, params['devices'], params, user)
        return jsonify({'success': True, 'results': results})

    result = execute_command(cmd_id, params, user)
    return jsonify(result)


@admin_bp.route('/history')
@login_required_admin
def admin_history():
    """View execution history from MySQL with filters"""
    from math import ceil

    user = session.get('user', {})
    manifest_filter = user.get('manifest_filter')  # e.g. 'site-%' for site-admin
    history = []
    total_count = 0
    users_list = []

    # Pagination
    page = request.args.get('page', 1, type=int)
    per_page = 50

    # Filters
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    device_filter = request.args.get('device', '')
    user_filter = request.args.get('user_filter', '')
    status_filter = request.args.get('status', '')

    try:
        # Get list of users for filter dropdown
        users_rows = db.query_all("SELECT DISTINCT user FROM command_history ORDER BY user")
        users_list = [row['user'] for row in users_rows]

        # Build query with filters
        where_clauses = ["ch.timestamp >= DATE_SUB(NOW(), INTERVAL 90 DAY)"]
        params = []

        # Add manifest filter for site-admin (join with device_inventory)
        join_clause = ""
        if manifest_filter:
            join_clause = "LEFT JOIN device_inventory di ON ch.device_udid = di.uuid"
            where_clauses.append("di.manifest LIKE %s")
            params.append(manifest_filter)

        if date_from:
            where_clauses.append("DATE(ch.timestamp) >= %s")
            params.append(date_from)

        if date_to:
            where_clauses.append("DATE(ch.timestamp) <= %s")
            params.append(date_to)

        if device_filter:
            where_clauses.append(
                "(ch.device_udid LIKE %s OR ch.device_serial LIKE %s OR ch.device_hostname LIKE %s)"
            )
            like_val = f"%{device_filter}%"
            params.extend([like_val, like_val, like_val])

        if user_filter:
            where_clauses.append("ch.user = %s")
            params.append(user_filter)

        if status_filter in ('0', '1'):
            where_clauses.append("ch.success = %s")
            params.append(int(status_filter))

        where_sql = " AND ".join(where_clauses)

        # Get total count
        total_count = db.query_value(f"""
            SELECT COUNT(*) FROM command_history ch {join_clause} WHERE {where_sql}
        """, params) or 0

        # Calculate pagination
        total_pages = ceil(total_count / per_page) if total_count > 0 else 1
        page = min(max(1, page), total_pages)
        offset_val = (page - 1) * per_page

        # Get paginated results
        history = db.query_all(f"""
            SELECT ch.id, ch.timestamp, ch.user, ch.command_id, ch.command_name, ch.device_udid,
                   ch.device_serial, ch.device_hostname, ch.params, ch.result_summary, ch.success
            FROM command_history ch
            {join_clause}
            WHERE {where_sql}
            ORDER BY ch.timestamp DESC
            LIMIT %s OFFSET %s
        """, params + [per_page, offset_val])

        # Parse params JSON for each entry
        for entry in history:
            if entry.get('params'):
                try:
                    entry['params'] = json.loads(entry['params'])
                except:
                    entry['params'] = {}

        # Run cleanup periodically (every 100 requests approximately)
        import random
        if random.randint(1, 100) == 1:
            cleanup_old_history(90)

    except Exception as e:
        logger.error(f"Failed to read command history: {e}")

    return render_template_string(
        ADMIN_HISTORY_TEMPLATE,
        user=user,
        history=history,
        total_count=total_count,
        total_pages=total_pages if 'total_pages' in dir() else 1,
        page=page,
        date_from=date_from,
        date_to=date_to,
        device_filter=device_filter,
        user_filter=user_filter,
        status_filter=status_filter,
        users=users_list
    )


@admin_bp.route('/profiles')
@login_required_admin
def admin_profiles():
    """Manage profiles page"""
    user = session.get('user', {})
    manifest_filter = user.get('manifest_filter')  # e.g. 'site-%' for site-admin

    # Get required profiles grouped by manifest
    req_profiles = required_profiles.get_grouped()

    # Get list of manifests from DB (filtered for site-admin)
    manifests = get_manifests_list(manifest_filter)
    if manifest_filter:
        # Filter req_profiles to only show allowed manifests
        req_profiles = {k: v for k, v in req_profiles.items() if k in manifests}

    # Get available profiles with identifiers for dropdown
    profiles = get_profiles_by_category()
    profile_options = []
    for p in profiles.get('system', []):
        if p.get('identifier'):
            profile_options.append({'name': p['name'], 'identifier': p['identifier']})
    for p in profiles.get('wireguard', []):
        if p.get('identifier'):
            profile_options.append({'name': p['name'], 'identifier': p['identifier']})

    return render_template_string(
        ADMIN_PROFILES_TEMPLATE,
        user=user,
        required_profiles=req_profiles,
        manifests=manifests,
        profile_options=profile_options
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
    """Get full devices list (JSON) with all fields, filtered by user's manifest_filter if any"""
    user = session.get('user', {})
    manifest_filter = user.get('manifest_filter')  # e.g. 'site-%' for site-admin
    devices = get_devices_full(manifest_filter=manifest_filter)
    return jsonify(devices)


@admin_bp.route('/api/device-search', methods=['POST'])
@login_required_admin
def api_device_search():
    """Search devices (JSON) with all fields, filtered by user's manifest_filter if any"""
    user = session.get('user', {})
    manifest_filter = user.get('manifest_filter')

    data = request.get_json()
    search_term = data.get('value', '')

    devices = get_devices_full(manifest_filter=manifest_filter, search_term=search_term)
    return jsonify(devices)


@admin_bp.route('/api/profiles')
@login_required_admin
def api_profiles():
    """Get profiles list (JSON)"""
    profiles = get_profiles_by_category()
    return jsonify(profiles)


@admin_bp.route('/api/required-profiles')
@login_required_admin
def api_required_profiles():
    """Get required profiles grouped by manifest/os"""
    return jsonify(required_profiles.get_grouped())


@admin_bp.route('/api/applications/<manifest>')
@login_required_admin
def api_applications_for_manifest(manifest):
    """Get applications for a specific manifest (both macos and ios)"""
    try:
        apps = db.query_all("""
            SELECT id, manifest, os, app_name, manifest_url, install_order, is_optional
            FROM required_applications
            WHERE manifest = %s
            ORDER BY os, install_order
        """, (manifest,))
        return jsonify({'success': True, 'applications': apps or []})
    except Exception as e:
        logger.error(f"Failed to get applications for manifest {manifest}: {e}")
        return jsonify({'success': False, 'applications': [], 'error': str(e)})


@admin_bp.route('/api/profile-options')
@login_required_admin
def api_profile_options():
    """Debug endpoint - get available profile options"""
    profiles = get_profiles_by_category()

    # Debug: show raw profile data
    system_raw = profiles.get('system', [])[:3]
    wireguard_raw = profiles.get('wireguard', [])[:3]

    profile_options = []
    for p in profiles.get('system', []):
        if p.get('identifier'):
            profile_options.append({'name': p['name'], 'identifier': p['identifier']})
    for p in profiles.get('wireguard', []):
        if p.get('identifier'):
            profile_options.append({'name': p['name'], 'identifier': p['identifier']})

    return jsonify({
        'count': len(profile_options),
        'options': profile_options[:10],
        'debug': {
            'system_count': len(profiles.get('system', [])),
            'wireguard_count': len(profiles.get('wireguard', [])),
            'system_sample': system_raw,
            'wireguard_sample': wireguard_raw
        }
    })


@admin_bp.route('/api/required-profiles/add', methods=['POST'])
@admin_required
def api_required_profiles_add():
    """Add a new required profile"""
    import fnmatch as fnmatch_mod
    user = session.get('user', {})
    manifest_filter = user.get('manifest_filter')

    data = request.get_json()
    manifest = data.get('manifest', '').strip()
    os = data.get('os', '').strip().lower()
    profile_identifier = data.get('profile_identifier', '').strip()
    profile_name = data.get('profile_name', '').strip()
    match_pattern = data.get('match_pattern', False)

    if not all([manifest, os, profile_identifier, profile_name]):
        return jsonify({'success': False, 'error': 'Missing required fields'})

    if os not in ['ios', 'macos']:
        return jsonify({'success': False, 'error': 'Invalid OS (must be ios or macos)'})

    # Validate manifest access for users with manifest_filter
    if manifest_filter:
        pattern = manifest_filter.replace('%', '*')
        if not fnmatch_mod.fnmatch(manifest, pattern):
            return jsonify({'success': False, 'error': 'Access denied for this manifest'})

    success = required_profiles.add(manifest, os, profile_identifier, profile_name, match_pattern)
    if success:
        audit_log(
            user=session.get('user', {}).get('username', 'unknown'),
            action='add_required_profile',
            command='required_profiles_add',
            params={'manifest': manifest, 'os': os, 'profile_name': profile_name, 'profile_identifier': profile_identifier},
            result=f"Added {profile_name}",
            success=True
        )
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'Failed to add profile (may already exist)'})


@admin_bp.route('/api/required-profiles/remove', methods=['POST'])
@admin_required
def api_required_profiles_remove():
    """Remove a required profile by ID"""
    import fnmatch as fnmatch_mod
    user = session.get('user', {})
    manifest_filter = user.get('manifest_filter')

    data = request.get_json()
    profile_id = data.get('id')

    if not profile_id:
        return jsonify({'success': False, 'error': 'Missing profile ID'})

    # Validate manifest access for users with manifest_filter
    if manifest_filter:
        profile = required_profiles.get_by_id(int(profile_id))
        if not profile:
            return jsonify({'success': False, 'error': 'Profile not found'})
        pattern = manifest_filter.replace('%', '*')
        if not fnmatch_mod.fnmatch(profile['manifest'], pattern):
            return jsonify({'success': False, 'error': 'Access denied for this manifest'})

    success = required_profiles.remove(int(profile_id))
    if success:
        audit_log(
            user=session.get('user', {}).get('username', 'unknown'),
            action='remove_required_profile',
            command='required_profiles_remove',
            params={'profile_id': profile_id},
            result=f"Removed profile ID {profile_id}",
            success=True
        )
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'Failed to remove profile'})


# =============================================================================
# DEVICE DETAIL ROUTES
# =============================================================================

@admin_bp.route('/device/<device_uuid>')
@login_required_admin
def device_detail(device_uuid):
    """Device detail page with tabs for hardware, security, profiles, apps, history"""
    user = session.get('user', {})

    # Validate device access for users with manifest filter
    if user.get('manifest_filter'):
        if not validate_device_access(device_uuid, user):
            return render_template_string('''
                <html><body>
                <h1>Access Denied</h1>
                <p>You do not have permission to view this device.</p>
                <a href="/admin">Back to Admin</a>
                </body></html>
            '''), 403

    # Get device info from database
    device = get_device_detail(device_uuid)
    if not device:
        return render_template_string('''
            <html><body>
            <h1>Device Not Found</h1>
            <p>Device with UUID {{ uuid }} was not found in the database.</p>
            <a href="/admin">Back to Admin</a>
            </body></html>
        ''', uuid=device_uuid), 404

    # Get command history for this device
    history = get_device_command_history(device_uuid, limit=20)

    # Get required profiles status for this device (same approach as Reports page)
    required_profiles_status = None
    try:
        manifest = device.get('manifest') or ''
        os_type = (device.get('os') or '').lower()

        # Get profiles_data from device_details table (same as Reports)
        row = db.query_one("""
            SELECT profiles_data FROM device_details WHERE uuid = %s
        """, (device_uuid,))

        profiles = []
        if row and row.get('profiles_data'):
            profiles_data = row.get('profiles_data')
            if isinstance(profiles_data, str):
                profiles = json.loads(profiles_data)
            else:
                profiles = profiles_data or []

        # Get required profiles and check compliance (same as Reports)
        profile_check = required_profiles.check_device_profiles(manifest, os_type, profiles)

        if profile_check['required'] > 0:
            # Build all_profiles list with installed status
            req_list = required_profiles.get_for_manifest(manifest, os_type)
            missing_names = {m['name'] for m in profile_check.get('missing_list', [])}

            all_profiles = []
            for req in req_list:
                all_profiles.append({
                    'name': req['profile_name'],
                    'identifier': req['profile_identifier'],
                    'installed': req['profile_name'] not in missing_names
                })

            required_profiles_status = {
                'required': profile_check['required'],
                'installed': profile_check['installed'],
                'missing': profile_check['missing'],
                'all_profiles': all_profiles
            }
    except Exception as e:
        logger.error(f"Failed to get required profiles status: {e}")

    return render_template_string(
        DEVICE_DETAIL_TEMPLATE,
        user=user,
        device=device,
        history=history,
        required_profiles_status=required_profiles_status
    )


@admin_bp.route('/api/device/<device_uuid>/profile-check')
@login_required_admin
def api_device_profile_check(device_uuid):
    """Debug endpoint to check profile compliance for a device"""
    try:
        row = db.query_one("""
            SELECT di.uuid, di.hostname, di.serial, di.os, di.manifest, dd.profiles_data
            FROM device_inventory di
            LEFT JOIN device_details dd ON di.uuid = dd.uuid
            WHERE di.uuid = %s OR di.serial = %s
        """, (device_uuid, device_uuid))

        if not row:
            return jsonify({'error': 'Device not found'})

        profiles_data = row.get('profiles_data')
        if profiles_data and isinstance(profiles_data, str):
            profiles = json.loads(profiles_data)
        else:
            profiles = profiles_data or []

        manifest = row.get('manifest', '')
        os_type = (row.get('os') or '').lower()

        # Get required profiles
        req = required_profiles.get_for_manifest(manifest, os_type)

        # Extract installed identifiers
        installed_ids = []
        for p in profiles:
            if isinstance(p, dict):
                ident = p.get('identifier') or p.get('PayloadIdentifier') or p.get('Identifier', '')
                if ident:
                    installed_ids.append(ident)

        # Run check
        result = required_profiles.check_device_profiles(manifest, os_type, profiles)

        return jsonify({
            'device': {
                'hostname': row.get('hostname'),
                'serial': row.get('serial'),
                'os': os_type,
                'manifest': manifest
            },
            'required_profiles': [{'name': r['profile_name'], 'id': r['profile_identifier'], 'pattern': bool(r['match_pattern'])} for r in req],
            'installed_identifiers': sorted(installed_ids),
            'result': result
        })
    except Exception as e:
        return jsonify({'error': str(e)})


@admin_bp.route('/api/device/<device_uuid>/query', methods=['POST'])
@login_required_admin
def api_device_query(device_uuid):
    """API endpoint to query device data (hardware, security, profiles, apps)"""
    user = session.get('user', {})

    # Validate device access
    if user.get('manifest_filter'):
        if not validate_device_access(device_uuid, user):
            return jsonify({'success': False, 'error': 'Access denied'}), 403

    data = request.get_json() or {}
    query_type = data.get('query_type')
    force_refresh = data.get('force_refresh', False)

    if not query_type:
        return jsonify({'success': False, 'error': 'Missing query_type parameter'})

    # Try to get cached data from DB first (unless force_refresh)
    if not force_refresh:
        cached = get_device_details(device_uuid, query_type)
        if cached and cached.get('data'):
            # Transform cached data to match frontend expectations
            # Webhook saves different field names than parse_webhook_output returns
            cached_data = cached['data']

            if query_type == 'profiles' and isinstance(cached_data, list):
                # Transform: display_name -> name, add status field
                profiles = []
                for p in cached_data:
                    profiles.append({
                        'name': p.get('display_name', p.get('name', 'N/A')),
                        'identifier': p.get('identifier', 'N/A'),
                        'status': 'Managed' if p.get('is_managed') else 'Installed'
                    })
                cached_data = {'profiles': profiles, 'count': len(profiles)}

            elif query_type == 'apps' and isinstance(cached_data, list):
                # Transform: identifier -> bundle_id
                apps = []
                for a in cached_data:
                    apps.append({
                        'name': a.get('name', 'Unknown'),
                        'bundle_id': a.get('identifier', a.get('bundle_id', 'N/A')),
                        'version': a.get('version', 'N/A')
                    })
                cached_data = {'applications': apps, 'count': len(apps)}

            return jsonify({
                'success': True,
                'data': cached_data,
                'query_type': query_type,
                'cached': True,
                'updated_at': cached.get('updated_at')
            })

    # Execute MDM query (and save to DB)
    result = execute_device_query(device_uuid, query_type)

    if result.get('success'):
        result['cached'] = False

    return jsonify(result)


@admin_bp.route('/api/device/<device_uuid>/cached', methods=['GET'])
@login_required_admin
def api_device_cached(device_uuid):
    """API endpoint to get all cached device data from DB"""
    user = session.get('user', {})

    # Validate device access
    if user.get('manifest_filter'):
        if not validate_device_access(device_uuid, user):
            return jsonify({'success': False, 'error': 'Access denied'}), 403

    cached = get_device_details(device_uuid)
    if cached:
        return jsonify({
            'success': True,
            'data': cached
        })
    else:
        return jsonify({
            'success': True,
            'data': None,
            'message': 'No cached data available'
        })

