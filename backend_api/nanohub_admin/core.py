"""
NanoHUB Admin Core Functions
=============================
Shared utility functions for admin panel modules.
Extracted from nanohub_admin_core.py for better modularity.
"""

import os
import re
import ast
import ssl
import base64
import json
import logging
import uuid
import time
import urllib.request
import urllib.error
from datetime import datetime

from config import Config
from db_utils import db, devices, command_history, device_details, required_profiles
from command_registry import get_available_profiles, get_command
from cache_utils import device_cache

# Logging
logger = logging.getLogger('nanohub_admin')

# Paths from centralized config
AUDIT_LOG_PATH = Config.AUDIT_LOG_PATH
WEBHOOK_LOG_PATH = Config.WEBHOOK_LOG_PATH


# =============================================================================
# DEVICE DATA FUNCTIONS
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
                except Exception:
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
        for field in ['hardware', 'security', 'profiles', 'apps', 'ddm']:
            data_key = f"{field}_data"
            result[field] = row.get(data_key)

        # Add timestamps
        for ts_field in ['hardware_updated_at', 'security_updated_at', 'profiles_updated_at', 'apps_updated_at', 'ddm_updated_at']:
            result[ts_field] = row.get(ts_field)

        return result
    except Exception as e:
        logger.error(f"Failed to get device details: {e}")
        return None


def get_device_manifest(uuid_val):
    """Get manifest for a device by UUID"""
    try:
        row = db.query_one("SELECT manifest FROM device_inventory WHERE uuid = %s", (uuid_val,))
        if row and row.get('manifest'):
            return row['manifest']
    except Exception as e:
        logger.error(f"Failed to get device manifest: {e}")
    return None


def validate_device_access(uuid_val, user_info):
    """Check if user has access to device based on manifest_filter"""
    manifest_filter = user_info.get('manifest_filter')
    if not manifest_filter:
        return True  # No filter = full access

    device_manifest = get_device_manifest(uuid_val)
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
# APPLE OS VERSION CACHE
# =============================================================================

_apple_os_cache = {'data': None, 'timestamp': 0}
_APPLE_OS_CACHE_TTL = 6 * 60 * 60  # 6 hours in seconds

# Per-model cache for outdated detection
_model_version_cache = {}  # {model_id: {'version': '18.2', 'ver_tuple': (18, 2), 'timestamp': ...}}
_MODEL_CACHE_TTL = 24 * 60 * 60  # 24 hours - models don't change often


def fetch_max_os_for_model(model_id: str) -> dict:
    """Fetch maximum supported OS version for a specific device model from IPSW.me API.

    Args:
        model_id: Device identifier like 'iPhone14,5', 'MacBookAir10,1'

    Returns:
        Dict with 'version' and 'ver_tuple', or empty dict if failed
    """
    global _model_version_cache

    if not model_id:
        return {}

    now = time.time()

    # Check cache
    if model_id in _model_version_cache:
        cached = _model_version_cache[model_id]
        if (now - cached.get('timestamp', 0)) < _MODEL_CACHE_TTL:
            return cached

    try:
        url = f"https://api.ipsw.me/v4/device/{model_id}?type=ipsw"
        req = urllib.request.Request(url, headers={'User-Agent': 'NanoHUB/1.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))

        # Find latest signed firmware for this model
        firmwares = data.get('firmwares', [])
        signed = [f for f in firmwares if f.get('signed')]

        if signed:
            latest = signed[0]
            version = latest.get('version', '')

            # Parse version tuple
            try:
                ver_tuple = tuple(int(x) for x in str(version).split('.')[:3])
            except Exception:
                ver_tuple = (0,)

            result = {
                'version': version,
                'ver_tuple': ver_tuple,
                'timestamp': now
            }
            _model_version_cache[model_id] = result
            return result

    except Exception as e:
        logger.debug(f"Failed to fetch version for model {model_id}: {e}")

    return {}


def is_device_outdated(device_version: str, model_id: str) -> bool:
    """Check if device OS version is outdated compared to max supported for its model.

    Args:
        device_version: Current OS version on device (e.g., '15.8', '18.2')
        model_id: Device identifier (e.g., 'iPhone9,1', 'MacBookAir10,1')

    Returns:
        True if device can be updated to a newer OS, False otherwise
    """
    if not device_version or not model_id:
        return False

    # Parse device version
    try:
        device_tuple = tuple(int(x) for x in str(device_version).split('.')[:3])
    except Exception:
        return False

    # Get max supported version for this model
    max_info = fetch_max_os_for_model(model_id)
    if not max_info or 'ver_tuple' not in max_info:
        return False

    return device_tuple < max_info['ver_tuple']


def fetch_apple_latest_os():
    """Fetch latest OS versions from IPSW.me API with caching"""
    global _apple_os_cache

    # Check cache
    now = time.time()
    if _apple_os_cache['data'] and (now - _apple_os_cache['timestamp']) < _APPLE_OS_CACHE_TTL:
        return _apple_os_cache['data']

    # Representative devices for each OS type
    devices_map = {
        'ios': 'iPhone16,1',      # iPhone 15 Pro
        'ipados': 'iPad14,1',     # iPad mini 6
        'macos': 'Mac15,3',       # MacBook Pro M3
    }

    result = {}

    for os_type, device_id in devices_map.items():
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
                # Generate ProductKey in Apple's format
                if os_type == 'ios':
                    product_key = f"iOSUpdate{build}" if build else ''
                elif os_type == 'macos':
                    product_key = f"_OSX_{build}" if build else ''
                elif os_type == 'ipados':
                    product_key = f"iPadOSUpdate{build}" if build else ''
                else:
                    product_key = ''

                # Parse version tuple for comparison
                try:
                    ver_tuple = tuple(int(x) for x in str(version).split('.')[:3])
                except Exception:
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


# =============================================================================
# MDM DEVICE QUERY
# =============================================================================

def execute_device_query(uuid_val, query_type):
    """Execute MDM query command and poll webhook for JSON response"""

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
            old_timestamp = None
            try:
                old_data = get_device_details(uuid_val, query_type)
                if old_data:
                    old_timestamp = old_data.get('updated_at')
            except Exception:
                pass

            # Poll DB for new data (max 20 seconds per attempt)
            got_notnow = False
            for i in range(20):
                time.sleep(1)
                try:
                    # Check webhook log for NotNow or errors
                    with open(WEBHOOK_LOG, 'r') as f:
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
            except Exception:
                pass
        # Capacity: already in GB, add suffix
        if 'capacity' in key_lower and 'available' not in key_lower.replace('capacity', ''):
            try:
                val = float(value)
                if val < 10000:
                    return f"{val:.1f} GB"
            except Exception:
                pass
        if 'availabledevicecapacity' in key_lower or 'available_capacity' in key_lower:
            try:
                val = float(value)
                if val < 10000:
                    return f"{val:.1f} GB"
            except Exception:
                pass
        return value

    result = {}

    if query_type in ['hardware', 'security']:
        # Parse key: value pairs
        for line in lines:
            match = re.search(r'\[INFO\]\s+(\w+):\s*(.+)$', line)
            if match:
                key = match.group(1).strip()
                value = match.group(2).strip()
                if key.lower() not in ['status', 'udid', 'topic', 'command_uuid']:
                    snake_key = camel_to_snake(key)

                    if value.startswith('{') and value.endswith('}'):
                        try:
                            clean_value = re.sub(
                                r'datetime\.datetime\((\d+),\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)\)',
                                r'"\1-\2-\3 \4:\5:\6"',
                                value
                            )
                            parsed = ast.literal_eval(clean_value)
                            if isinstance(parsed, dict):
                                result[snake_key] = parsed
                                continue
                        except Exception:
                            pass
                    if value.lower() in ['true', 'yes', '1']:
                        result[snake_key] = True
                    elif value.lower() in ['false', 'no', '0']:
                        result[snake_key] = False
                    else:
                        result[snake_key] = format_value(key, value)

    elif query_type == 'profiles':
        profiles = []
        for line in lines:
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
        apps = []
        for line in lines:
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


# =============================================================================
# LISTS (MANIFESTS, DEVICES)
# =============================================================================

def get_manifests_list(manifest_filter=None):
    """Get list of manifests from manifests table, optionally filtered by pattern."""
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
        except Exception:
            return []


def get_devices_list(manifest_filter=None):
    """Get list of devices from database, optionally filtered by manifest"""
    params = []
    where_clause = ""
    if manifest_filter:
        where_clause = "WHERE di.manifest LIKE %s"
        params.append(manifest_filter)

    sql = f"""
    SELECT
        di.uuid,
        di.serial,
        di.os,
        di.hostname,
        di.manifest,
        di.account,
        di.dep,
        e.max_last_seen as last_seen,
        COALESCE(
            JSON_UNQUOTE(JSON_EXTRACT(dd.hardware_data, '$.os_version')),
            JSON_UNQUOTE(JSON_EXTRACT(dd.hardware_data, '$.OSVersion')),
            ''
        ) as os_version,
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
    """

    try:
        rows = db.query_all(sql, tuple(params) if params else None)
        devices_list = []
        for row in rows:
            device = dict(row)
            if device.get('last_seen'):
                device['last_seen'] = str(device['last_seen'])
            devices_list.append(device)
        return devices_list
    except Exception as e:
        logger.error(f"Failed to get devices: {e}")
        return []


def get_devices_full(manifest_filter=None, search_term=None):
    """Get full device list with all fields for standard device table format."""
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
            device_uuid = row.get('uuid', '')
            os_type = (row.get('os') or '').lower()
            manifest = row.get('manifest', '') or ''

            # Try to get processed data from cache
            cached = device_cache.get(device_uuid)

            if cached:
                os_ver = cached.get('os_version', '-')
                model = cached.get('model', '-')
                product_name = cached.get('product_name', '-')
                is_supervised = cached.get('is_supervised', False)
                is_encrypted = cached.get('is_encrypted', False)
                is_dep = cached.get('is_dep', False)
                profile_check = cached.get('profile_check', {'required': 0, 'installed': 0, 'missing': 0, 'complete': True, 'missing_list': []})
            else:
                # Parse JSON and process data
                hw = row.get('hardware_data')
                if hw and isinstance(hw, str):
                    try: hw = json.loads(hw)
                    except Exception: hw = {}
                elif not hw:
                    hw = {}

                sec = row.get('security_data')
                if sec and isinstance(sec, str):
                    try: sec = json.loads(sec)
                    except Exception: sec = {}
                elif not sec:
                    sec = {}

                profiles = row.get('profiles_data')
                if profiles and isinstance(profiles, str):
                    try: profiles = json.loads(profiles)
                    except Exception: profiles = []
                if not profiles:
                    profiles = []

                os_ver = hw.get('os_version', hw.get('OSVersion', '')) if hw else ''
                model = hw.get('model_name', hw.get('ModelName', '')) if hw else ''
                product_name = hw.get('product_name', hw.get('ProductName', '')) if hw else ''

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

                # DEP enrolled
                is_dep = False
                if sec:
                    dep_sec = sec.get('enrolled_via_dep', sec.get('IsDeviceEnrollmentProgram', sec.get('DEPEnrolled')))
                    is_dep = dep_sec is True or str(dep_sec).lower() in ('true', 'yes', '1')
                if not is_dep:
                    dep_val = str(row.get('dep', '')).lower()
                    is_dep = dep_val in ('enabled', '1', 'yes', 'true')

                # Profile compliance check
                profile_check = required_profiles.check_device_profiles(manifest, os_type, profiles)

                # Store in cache
                device_cache.set(device_uuid, {
                    'os_version': os_ver,
                    'model': model,
                    'product_name': product_name,
                    'is_supervised': is_supervised,
                    'is_encrypted': is_encrypted,
                    'is_dep': is_dep,
                    'profile_check': profile_check
                })

            # Outdated check - compare against max supported version for this specific model
            is_outdated = is_device_outdated(os_ver, product_name)

            # Last check-in
            last_seen = row.get('max_last_seen')
            last_seen_str = last_seen.strftime('%Y-%m-%d %H:%M') if last_seen else '-'

            device = {
                'uuid': device_uuid,
                'hostname': row.get('hostname', ''),
                'serial': row.get('serial', ''),
                'os': os_type,
                'os_version': os_ver or '-',
                'model': model or '-',
                'product_name': product_name or '-',
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
    allowed_fields = {'uuid', 'serial', 'os', 'hostname', 'manifest', 'account', 'dep'}
    if field not in allowed_fields:
        logger.warning(f"Invalid search field: {field}")
        return []

    params = [f"%{value}%"]
    manifest_clause = ""
    if manifest_filter:
        manifest_clause = "AND di.manifest LIKE %s"
        params.append(manifest_filter)

    sql = f"""
    SELECT
        di.uuid,
        di.serial,
        di.os,
        di.hostname,
        di.manifest,
        di.account,
        di.dep,
        e.max_last_seen as last_seen,
        COALESCE(
            JSON_UNQUOTE(JSON_EXTRACT(dd.hardware_data, '$.os_version')),
            JSON_UNQUOTE(JSON_EXTRACT(dd.hardware_data, '$.OSVersion')),
            ''
        ) as os_version,
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
    WHERE di.{field} LIKE %s {manifest_clause}
    ORDER BY di.hostname
    """

    try:
        rows = db.query_all(sql, tuple(params))
        devices_list = []
        for row in rows:
            device = dict(row)
            if device.get('last_seen'):
                device['last_seen'] = str(device['last_seen'])
            devices_list.append(device)
        return devices_list
    except Exception as e:
        logger.error(f"Failed to search devices: {e}")
        return []


# =============================================================================
# PROFILES HELPERS
# =============================================================================

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
# AUDIT & HISTORY
# =============================================================================

def audit_log(user, action, command, params, result, success, execution_time_ms=None):
    """Log admin action to MySQL command_history and file"""
    try:
        # Extract device info
        device_udid = None
        device_serial = None
        device_hostname = None

        if params:
            if 'udid' in params and params['udid']:
                device_udid = params['udid']
                device_info = get_device_info_for_uuid(device_udid)
                device_serial = device_info.get('serial')
                device_hostname = device_info.get('hostname')
            elif 'devices' in params and params['devices']:
                devices_param = params['devices']
                if isinstance(devices_param, list) and len(devices_param) > 0:
                    device_udid = devices_param[0]
                    device_info = get_device_info_for_uuid(device_udid)
                    device_serial = device_info.get('serial')
                    device_hostname = device_info.get('hostname')

        # Get command name from registry
        cmd_info = get_command(command)
        command_name = cmd_info.get('name', command) if cmd_info else command

        # Write to MySQL
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
        from datetime import datetime
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
    token = get_vpp_token()
    if not token:
        return {'error': 'VPP token not found'}

    try:
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
    assets_response = fetch_vpp_assets()

    if 'error' in assets_response:
        return assets_response

    assets = assets_response.get('assets', [])

    # Load local app definitions for name mapping
    app_names = {}
    for json_path in [Config.APPS_IOS_JSON, Config.APPS_MACOS_JSON]:
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

    # Collect ALL adamIds for batch lookup
    all_adam_ids = [str(asset.get('adamId', '')) for asset in assets if asset.get('adamId')]

    # Batch lookup from iTunes API
    if all_adam_ids:
        try:
            ids_str = ','.join(all_adam_ids[:200])
            url = f"https://itunes.apple.com/lookup?id={ids_str}&country=us"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
                for result in data.get('results', []):
                    track_id = str(result.get('trackId', ''))
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

    enriched.sort(key=lambda x: x.get('name', '').lower())

    return {
        'apps': enriched,
        'tokenExpiration': assets_response.get('tokenExpirationDate'),
        'totalApps': len(enriched)
    }


# =============================================================================
# WEBHOOK POLLING
# =============================================================================

def poll_webhook_for_command_result(command_uuid, initial_sleep=3, max_polls=15, poll_wait=1, window=1000):
    """Poll webhook log for command result by UUID"""
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
        if not line or '[INFO]' not in line:
            continue

        if '[INFO]' in line:
            content = line.split('[INFO]', 1)[1].strip()

            if ':' in content and not content.startswith('==='):
                key, _, value = content.partition(':')
                key = key.strip()
                value = value.strip()
                if key and value:
                    result['parsed'][key] = value

    return result


def extract_command_uuid_from_output(output):
    """Extract command_uuid from script output (JSON response from nanomdm)"""
    uuid_pattern = r'"command_uuid"\s*:\s*"([a-f0-9-]+)"'
    match = re.search(uuid_pattern, output, re.IGNORECASE)
    if match:
        return match.group(1)

    uuid_pattern2 = r'command_uuid["\s:]+([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})'
    match2 = re.search(uuid_pattern2, output, re.IGNORECASE)
    if match2:
        return match2.group(1)

    uuid_pattern3 = r'Command\s+UUID:\s*([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})'
    match3 = re.search(uuid_pattern3, output, re.IGNORECASE)
    if match3:
        return match3.group(1)

    return None


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def sanitize_param(value):
    """Sanitize parameter to prevent command injection"""
    if not value:
        return value
    dangerous = ['`', '$', '|', '&', ';', '\n', '\r', '>', '<', '\\']
    for char in dangerous:
        value = value.replace(char, '')
    return value.strip()


def normalize_devices_param(devices_param):
    """Normalize devices parameter to list of UDIDs"""
    if not devices_param:
        return []
    if isinstance(devices_param, str):
        return [d.strip() for d in devices_param.split(',') if d.strip()]
    elif isinstance(devices_param, list):
        return [str(d).strip() for d in devices_param if d and str(d).strip()]
    return []
