#!/usr/bin/env python3
"""
NanoHUB Webhook Handler
=======================
Receives MDM events from NanoMDM and saves device data directly to database.

Features:
- HMAC signature verification for security
- Direct DB writes to device_details table
- Logs to file for debugging
"""

from flask import Flask, request
import base64
import plistlib
import logging
import sys
import os
import hmac
import hashlib
import json
import mysql.connector
from datetime import datetime

app = Flask(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

def load_env_from_file():
    """Load environment variables from /opt/nanohub/environment.sh"""
    env_vars = {}
    env_file = '/opt/nanohub/environment.sh'
    try:
        with open(env_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    # Handle export VAR=value and VAR=value
                    if line.startswith('export '):
                        line = line[7:]
                    key, value = line.split('=', 1)
                    # Remove quotes from value
                    value = value.strip().strip('"\'')
                    env_vars[key] = value
    except Exception:
        pass
    return env_vars

_env = load_env_from_file()

# HMAC secret for webhook security (NanoMDM v0.9.0+)
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET") or _env.get("WEBHOOK_SECRET", "")

# Log file
LOGFILE = "/var/log/nanohub/webhook.log"

# Database configuration
DB_CONFIG = {
    'host': os.getenv('NANOHUB_DB_HOST') or _env.get('DB_HOST', '127.0.0.1'),
    'port': int(os.getenv('NANOHUB_DB_PORT') or _env.get('DB_PORT', '3306')),
    'user': os.getenv('NANOHUB_DB_USER') or _env.get('DB_USER', 'nanohub'),
    'password': os.getenv('NANOHUB_DB_PASSWORD') or _env.get('DB_PASSWORD', ''),
    'database': os.getenv('NANOHUB_DB_NAME') or _env.get('DB_NAME', 'nanohub'),
    'charset': 'utf8mb4',
    'autocommit': True,
}

# =============================================================================
# LOGGING SETUP
# =============================================================================

logger = logging.getLogger('webhook')
logger.setLevel(logging.DEBUG if os.getenv("WEBHOOK_DEBUG") == "1" else logging.INFO)
logger.propagate = False

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
logger.addHandler(console_handler)

file_handler = logging.FileHandler(LOGFILE)
file_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
logger.addHandler(file_handler)

# =============================================================================
# DATABASE FUNCTIONS
# =============================================================================

def get_db_connection():
    """Get database connection."""
    try:
        return mysql.connector.connect(**DB_CONFIG)
    except Exception as e:
        logger.error(f"[DB] Failed to connect: {e}")
        return None


def save_device_details(udid: str, data_type: str, data: dict, command_uuid: str = None):
    """
    Save device details to database.

    Args:
        udid: Device UUID
        data_type: One of 'hardware', 'security', 'profiles', 'apps'
        data: Parsed data dict
        command_uuid: Optional command UUID for tracking
    """
    conn = get_db_connection()
    if not conn:
        return False

    try:
        cursor = conn.cursor()

        # Map data_type to column names
        column_map = {
            'hardware': ('hardware_data', 'hardware_updated_at'),
            'security': ('security_data', 'security_updated_at'),
            'profiles': ('profiles_data', 'profiles_updated_at'),
            'apps': ('apps_data', 'apps_updated_at'),
        }

        if data_type not in column_map:
            logger.warning(f"[DB] Unknown data_type: {data_type}")
            return False

        data_col, updated_col = column_map[data_type]
        json_data = json.dumps(data, default=str)
        now = datetime.now()

        # Upsert - insert or update
        sql = f"""
            INSERT INTO device_details (uuid, {data_col}, {updated_col})
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE
                {data_col} = VALUES({data_col}),
                {updated_col} = VALUES({updated_col})
        """

        cursor.execute(sql, (udid, json_data, now))
        conn.commit()
        return True

    except Exception as e:
        logger.error(f"[DB] Failed to save {data_type} for {udid}: {e}")
        return False
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()


# =============================================================================
# DATA PARSERS
# =============================================================================

def parse_device_information(plist_data: dict) -> dict:
    """Parse DeviceInformation response into structured data."""
    # Get QueryResponses if present (that's where the actual data is)
    info = plist_data.get('QueryResponses', plist_data)

    def format_capacity(capacity_val):
        if capacity_val is None:
            return 'N/A'
        try:
            val = float(capacity_val)
            # Apple returns capacity in GB already (not bytes)
            # Values < 10000 are already in GB, larger values would be bytes
            if val < 10000:
                return f"{val:.1f} GB"
            else:
                gb = val / (1024 ** 3)
                return f"{gb:.1f} GB"
        except:
            return str(capacity_val)

    def format_battery(level):
        if level is None:
            return 'N/A'
        try:
            return f"{int(float(level) * 100)}%"
        except:
            return str(level)

    return {
        'device_name': info.get('DeviceName', 'N/A'),
        'model_name': info.get('ModelName', 'N/A'),
        'model': info.get('Model', 'N/A'),
        'product_name': info.get('ProductName', 'N/A'),
        'os_version': info.get('OSVersion', 'N/A'),
        'build_version': info.get('BuildVersion', 'N/A'),
        'serial_number': info.get('SerialNumber', 'N/A'),
        'udid': info.get('UDID', 'N/A'),
        'device_capacity': format_capacity(info.get('DeviceCapacity')),
        'available_capacity': format_capacity(info.get('AvailableDeviceCapacity')),
        'battery_level': format_battery(info.get('BatteryLevel')),
        'wifi_mac': info.get('WiFiMAC', 'N/A'),
        'bluetooth_mac': info.get('BluetoothMAC', 'N/A'),
        'ethernet_mac': info.get('EthernetMAC', 'N/A'),
        'hostname': info.get('HostName', info.get('LocalHostName', 'N/A')),
        'local_hostname': info.get('LocalHostName', 'N/A'),
        'is_supervised': info.get('IsSupervised', False),
        'is_activation_lock_enabled': info.get('IsActivationLockEnabled', False),
        'sip_enabled': info.get('SystemIntegrityProtectionEnabled', 'N/A'),
        'imei': info.get('IMEI', 'N/A'),
        'meid': info.get('MEID', 'N/A'),
        'cellular_technology': info.get('CellularTechnology', 'N/A'),
    }


def parse_security_info(plist_data: dict) -> dict:
    """Parse SecurityInfo response into structured data."""
    info = plist_data.get('SecurityInfo', plist_data)

    # Nested objects inside SecurityInfo
    firewall = info.get('FirewallSettings', {})
    secure_boot = info.get('SecureBoot', {})
    management = info.get('ManagementStatus', {})

    return {
        # Hardware/Passcode
        'hardware_encryption_caps': info.get('HardwareEncryptionCaps', 'N/A'),
        'passcode_present': info.get('PasscodePresent', False),
        'passcode_compliant': info.get('PasscodeCompliant', False),
        'passcode_compliant_with_profiles': info.get('PasscodeCompliantWithProfiles', False),
        'passcode_lock_grace_period': info.get('PasscodeLockGracePeriod', 'N/A'),

        # FileVault
        'filevault_enabled': info.get('FDE_Enabled', False),
        'filevault_has_prk': info.get('FDE_HasPersonalRecoveryKey', False),
        'filevault_has_irk': info.get('FDE_HasInstitutionalRecoveryKey', False),

        # Firewall (nested in FirewallSettings)
        'firewall_enabled': firewall.get('FirewallEnabled', False),
        'block_all_incoming': firewall.get('BlockAllIncoming', False),
        'stealth_mode': firewall.get('StealthMode', False),

        # System Integrity
        'sip_enabled': info.get('SystemIntegrityProtectionEnabled', True),
        'authenticated_root_volume': info.get('AuthenticatedRootVolumeEnabled', 'N/A'),

        # Remote Access
        'remote_desktop_enabled': info.get('RemoteDesktopEnabled', False),

        # SecureBoot (nested in SecureBoot)
        'secure_boot_level': secure_boot.get('SecureBootLevel', 'N/A'),
        'external_boot_level': secure_boot.get('ExternalBootLevel', 'N/A'),

        # Bootstrap Token
        'bootstrap_token_allowed': info.get('BootstrapTokenAllowedForAuthentication', 'N/A'),
        'bootstrap_token_required_for_kext': info.get('BootstrapTokenRequiredForKernelExtensionApproval', False),
        'bootstrap_token_required_for_update': info.get('BootstrapTokenRequiredForSoftwareUpdate', False),

        # Recovery & Activation Lock
        'recovery_lock_enabled': info.get('IsRecoveryLockEnabled', False),
        'activation_lock_manageable': management.get('IsActivationLockManageable', False),

        # Management Status (nested in ManagementStatus)
        'enrolled_via_dep': management.get('EnrolledViaDEP', False),
        'user_approved_enrollment': management.get('UserApprovedEnrollment', False),
        'is_user_enrollment': management.get('IsUserEnrollment', False),
    }


def parse_profile_list(plist_data: dict) -> list:
    """Parse ProfileList response into structured data."""
    profiles = plist_data.get('ProfileList', [])

    result = []
    for profile in profiles:
        result.append({
            'identifier': profile.get('PayloadIdentifier', 'N/A'),
            'display_name': profile.get('PayloadDisplayName', 'N/A'),
            'description': profile.get('PayloadDescription', ''),
            'organization': profile.get('PayloadOrganization', ''),
            'uuid': profile.get('PayloadUUID', 'N/A'),
            'is_managed': profile.get('IsManaged', False),
            'is_encrypted': profile.get('IsEncrypted', False),
            'has_removal_passcode': profile.get('HasRemovalPasscode', False),
        })

    return result


def parse_installed_apps(plist_data: dict) -> list:
    """Parse InstalledApplicationList response into structured data."""
    apps = plist_data.get('InstalledApplicationList', [])

    result = []
    for app in apps:
        result.append({
            'name': app.get('Name', 'Unknown'),
            'identifier': app.get('Identifier', 'N/A'),
            'version': app.get('ShortVersion', app.get('Version', app.get('BundleVersion', 'N/A'))),
            'bundle_size': app.get('BundleSize', 0),
            'dynamic_size': app.get('DynamicSize', 0),
            'is_validated': app.get('IsValidated', False),
            'is_app_store': app.get('AppStoreVendable', False),
        })

    return result


# =============================================================================
# SECURITY
# =============================================================================

def verify_webhook_signature(body_bytes, signature_header):
    """
    Verify HMAC SHA-256 signature of webhook payload (NanoMDM v0.9.0+)
    NanoMDM uses X-Hmac-Signature header with Base64-encoded HMAC-SHA256
    """
    if not signature_header:
        return False

    expected_signature = base64.b64encode(
        hmac.new(
            WEBHOOK_SECRET.encode(),
            body_bytes,
            hashlib.sha256
        ).digest()
    ).decode()

    return hmac.compare_digest(expected_signature, signature_header)


# =============================================================================
# DDM (Declarative Device Management) FUNCTIONS
# =============================================================================

def save_ddm_status_report(enrollment_id: str, status_report: dict, status_id: str = None):
    """
    Save DDM status report to database.
    Note: NanoHUB already saves this, but we log it for visibility.
    """
    conn = get_db_connection()
    if not conn:
        return False

    try:
        cursor = conn.cursor()
        now = datetime.now()

        # Check if record exists and get row_count
        cursor.execute(
            "SELECT row_count FROM status_reports WHERE enrollment_id = %s AND status_id = %s",
            (enrollment_id, status_id or '')
        )
        existing = cursor.fetchone()

        if existing:
            row_count = existing[0] + 1
            sql = """
                UPDATE status_reports
                SET status_report = %s, row_count = %s, updated_at = %s
                WHERE enrollment_id = %s AND status_id = %s
            """
            cursor.execute(sql, (json.dumps(status_report, default=str), row_count, now, enrollment_id, status_id or ''))
        else:
            sql = """
                INSERT INTO status_reports (enrollment_id, status_report, status_id, row_count, created_at, updated_at)
                VALUES (%s, %s, %s, 1, %s, %s)
            """
            cursor.execute(sql, (enrollment_id, json.dumps(status_report, default=str), status_id or '', now, now))

        conn.commit()
        return True

    except Exception as e:
        logger.error(f"[DB] Failed to save DDM status report for {enrollment_id}: {e}")
        return False
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()


def save_ddm_declaration_status(enrollment_id: str, declarations: list):
    """
    Save DDM declaration statuses to database.
    """
    conn = get_db_connection()
    if not conn:
        return False

    try:
        cursor = conn.cursor()
        now = datetime.now()

        for decl in declarations:
            identifier = decl.get('identifier', '')
            if not identifier:
                continue

            sql = """
                INSERT INTO status_declarations
                    (enrollment_id, declaration_identifier, active, valid, server_token, item_type, reasons, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    active = VALUES(active),
                    valid = VALUES(valid),
                    server_token = VALUES(server_token),
                    reasons = VALUES(reasons),
                    updated_at = VALUES(updated_at)
            """
            cursor.execute(sql, (
                enrollment_id,
                identifier,
                1 if decl.get('active', False) else 0,
                decl.get('valid', 'unknown'),
                decl.get('server-token', ''),
                decl.get('type', 'configuration'),
                json.dumps(decl.get('reasons', []), default=str) if decl.get('reasons') else None,
                now,
                now
            ))

        conn.commit()
        return True

    except Exception as e:
        logger.error(f"[DB] Failed to save DDM declaration status for {enrollment_id}: {e}")
        return False
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()


def save_ddm_errors(enrollment_id: str, errors: list, status_id: str = None):
    """
    Save DDM errors to database.
    """
    if not errors:
        return True

    conn = get_db_connection()
    if not conn:
        return False

    try:
        cursor = conn.cursor()
        now = datetime.now()

        for error in errors:
            sql = """
                INSERT INTO status_errors
                    (enrollment_id, path, error, status_id, row_count, created_at, updated_at)
                VALUES (%s, %s, %s, %s, 1, %s, %s)
                ON DUPLICATE KEY UPDATE
                    error = VALUES(error),
                    row_count = row_count + 1,
                    updated_at = VALUES(updated_at)
            """
            cursor.execute(sql, (
                enrollment_id,
                error.get('path', ''),
                json.dumps(error, default=str),
                status_id or '',
                now,
                now
            ))

        conn.commit()
        return True

    except Exception as e:
        logger.error(f"[DB] Failed to save DDM errors for {enrollment_id}: {e}")
        return False
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()


def update_device_ddm_cache(enrollment_id: str):
    """
    Update device_details.ddm_data cache from status_declarations.
    This keeps the reports page in sync with actual DDM status.
    """
    conn = get_db_connection()
    if not conn:
        return False

    try:
        cursor = conn.cursor(dictionary=True)

        # Read current declarations from status_declarations
        cursor.execute("""
            SELECT declaration_identifier, active, valid, updated_at
            FROM status_declarations
            WHERE enrollment_id = %s
            ORDER BY declaration_identifier
        """, (enrollment_id,))
        rows = cursor.fetchall()

        if not rows:
            return True  # No declarations to cache

        # Format for device_details.ddm_data
        # Keep 'valid' as string ('valid'/'unknown') to match compliance check expectations
        declarations = []
        for row in rows:
            is_active = row.get('active') == 1 or row.get('active') == True
            valid_value = row.get('valid', 'unknown')  # Keep as string: 'valid' or 'unknown'
            declarations.append({
                'identifier': row.get('declaration_identifier', ''),
                'active': is_active,
                'valid': valid_value
            })

        # Update cache in device_details
        ddm_json = json.dumps(declarations)
        
        # First try UPDATE (most common case)
        cursor.execute("""
            UPDATE device_details 
            SET ddm_data = %s, ddm_updated_at = NOW()
            WHERE uuid = %s
        """, (ddm_json, enrollment_id))
        
        if cursor.rowcount == 0:
            # Row doesn't exist, try INSERT
            try:
                cursor.execute("""
                    INSERT INTO device_details (uuid, ddm_data, ddm_updated_at)
                    VALUES (%s, %s, NOW())
                """, (enrollment_id, ddm_json))
            except Exception as insert_err:
                logger.warning(f"[DB] Could not insert DDM cache for {enrollment_id}: {insert_err}")

        conn.commit()
        logger.info(f"[DB] Updated DDM cache for {enrollment_id}: {len(declarations)} declarations")
        return True

    except Exception as e:
        logger.error(f"[DB] Failed to update DDM cache for {enrollment_id}: {e}")
        return False
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()


def save_ddm_status_values(enrollment_id: str, status_items: dict, status_id: str = None):
    """
    Save DDM StatusItems to status_values table.
    Flattens nested JSON structure into key-value pairs.

    Example: {"device": {"model": {"family": "Mac"}}}
    becomes: path=".StatusItems.device.model.family", value="Mac"
    """
    if not status_items:
        return True

    conn = get_db_connection()
    if not conn:
        return False

    def flatten_dict(obj, parent_path=".StatusItems"):
        """Recursively flatten nested dict/list into (path, value, container_type, value_type) tuples."""
        items = []

        if isinstance(obj, dict):
            for key, val in obj.items():
                new_path = f"{parent_path}.{key}"
                if isinstance(val, dict):
                    # Skip 'declarations' under management - handled separately in status_declarations
                    if key == 'declarations' and 'management' in parent_path:
                        continue
                    # Skip 'client-capabilities' - too verbose, not useful for status display
                    if key == 'client-capabilities':
                        continue
                    items.extend(flatten_dict(val, new_path))
                elif isinstance(val, list):
                    # For lists, store each item separately
                    for i, item in enumerate(val):
                        if isinstance(item, dict):
                            items.extend(flatten_dict(item, f"{new_path}[{i}]"))
                        elif item is not None and str(item).strip():
                            vtype = 'string' if isinstance(item, str) else 'number' if isinstance(item, (int, float)) else 'boolean' if isinstance(item, bool) else 'string'
                            items.append((new_path, str(item), 'array', vtype))
                elif val is not None:
                    vtype = 'string'
                    if isinstance(val, bool):
                        vtype = 'boolean'
                        val = 'true' if val else 'false'
                    elif isinstance(val, int):
                        vtype = 'integer'
                    elif isinstance(val, float):
                        vtype = 'number'
                    items.append((new_path, str(val), 'single', vtype))

        return items

    try:
        cursor = conn.cursor()
        now = datetime.now()

        # Flatten all StatusItems
        flat_items = flatten_dict(status_items)

        if not flat_items:
            return True

        # First, delete old values for this enrollment (to handle removed items)
        cursor.execute(
            "DELETE FROM status_values WHERE enrollment_id = %s",
            (enrollment_id,)
        )

        # Insert new values
        sql = """
            INSERT INTO status_values
                (enrollment_id, path, container_type, value_type, value, status_id, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """

        for path, value, container_type, value_type in flat_items:
            # Truncate value if too long
            if len(value) > 255:
                value = value[:252] + '...'
            cursor.execute(sql, (
                enrollment_id,
                path,
                container_type,
                value_type,
                value,
                status_id or '',
                now,
                now
            ))

        conn.commit()
        logger.debug(f"[DB] Saved {len(flat_items)} DDM status values for {enrollment_id}")
        return True

    except Exception as e:
        logger.error(f"[DB] Failed to save DDM status values for {enrollment_id}: {e}")
        return False
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()


def handle_ddm_event(data: dict):
    """
    Handle DDM (Declarative Device Management) checkin events.
    DDM events use checkin_event, not acknowledge_event.
    """
    checkin = data.get("checkin_event", {})

    enrollment_id = checkin.get('enrollment_id') or checkin.get('udid', 'unknown')
    udid = checkin.get('udid', 'N/A')

    raw_payload = checkin.get("raw_payload", "")
    if not raw_payload:
        return ''

    try:
        decoded = base64.b64decode(raw_payload)
        plist_data = plistlib.loads(decoded)

        endpoint = plist_data.get('Endpoint', '')
        udid = plist_data.get('UDID', udid)  # Get UDID from plist if available

        # DDM Data field contains the actual DDM payload (JSON inside plist)
        ddm_data_raw = plist_data.get('Data')

        if ddm_data_raw:
            try:
                # Data is bytes containing JSON
                if isinstance(ddm_data_raw, bytes):
                    ddm_data = json.loads(ddm_data_raw.decode('utf-8'))
                else:
                    ddm_data = ddm_data_raw

                # Process based on endpoint type
                if endpoint == 'status':
                    handle_ddm_status_report(enrollment_id, udid, ddm_data)
                elif endpoint == 'declaration-items':
                    logger.info(f"[DDM] {udid} | declaration-items request")
                elif endpoint == 'tokens':
                    tokens = ddm_data.get('SyncTokens', {})
                    logger.info(f"[DDM] {udid} | tokens sync ({len(tokens)} tokens)")
                else:
                    logger.info(f"[DDM] {udid} | {endpoint}")

            except json.JSONDecodeError as e:
                logger.warning(f"[DDM] {udid} | JSON parse error: {e}")
        else:
            # Declaration fetch - device is downloading a declaration
            if endpoint and endpoint.startswith('declaration/'):
                # Extract declaration name from endpoint like "declaration/configuration/com.company.ddm.passcode"
                decl_name = endpoint.split('/')[-1] if '/' in endpoint else endpoint
                logger.info(f"[DDM] {udid} | fetch: {decl_name}")
            else:
                logger.info(f"[DDM] {udid} | {endpoint or 'unknown endpoint'}")

    except Exception as e:
        logger.warning(f"[DDM] Error: {e}")

    return ''


def handle_ddm_status_report(enrollment_id: str, udid: str, ddm_data: dict):
    """
    Process DDM status report and save to database.
    """
    # Extract StatusItems
    status_items = ddm_data.get('StatusItems', {})
    errors = ddm_data.get('Errors', [])

    # Process management declarations
    management = status_items.get('management', {})
    declarations = management.get('declarations', {})

    all_declarations = []
    decl_summary = []

    # Collect all declaration types
    for decl_type in ['configurations', 'activations', 'assets', 'management']:
        decl_list = declarations.get(decl_type, [])
        for decl in decl_list:
            decl['type'] = decl_type
            all_declarations.append(decl)
            # Build summary: ✓ for valid, ✗ for issues
            # Management declarations can be active=0 and still valid
            is_active = decl.get('active', False)
            is_valid = decl.get('valid', '') == 'valid'
            is_mgmt = decl_type == 'management'
            # For management: ✓ if valid (active=0 is normal)
            # For config: ✓ if active AND valid
            if is_mgmt:
                icon = "✓" if is_valid else "✗"
            else:
                icon = "✓" if is_active and is_valid else "○" if is_active else "✗"
            decl_summary.append(f"{icon} {decl.get('identifier', 'N/A').split('.')[-1]}")

    # Get device info if available
    device = status_items.get('device', {})
    device_info = ""
    if device and 'identifier' in device:
        serial = device['identifier'].get('serial-number', '')
        if serial:
            device_info = f" ({serial})"

    # Log compact status report
    logger.info(f"[DDM] {udid}{device_info} | status report: {len(all_declarations)} declarations")

    # Log declarations on one or few lines
    if decl_summary:
        # Group by 3 for readability
        for i in range(0, len(decl_summary), 3):
            chunk = decl_summary[i:i+3]
            logger.info(f"      {', '.join(chunk)}")

    # Log errors prominently
    if errors:
        logger.warning(f"[DDM] {udid} | {len(errors)} ERRORS:")
        for err in errors:
            logger.warning(f"      ✗ {err}")

    # Generate status_id for tracking
    status_id = hashlib.md5(json.dumps(ddm_data, sort_keys=True, default=str).encode()).hexdigest()[:16]

    # Save to database
    saved_parts = []
    if save_ddm_status_report(enrollment_id, ddm_data, status_id):
        saved_parts.append("report")
    if all_declarations and save_ddm_declaration_status(enrollment_id, all_declarations):
        saved_parts.append(f"{len(all_declarations)} decl")
        # Update device_details cache for reports page
        logger.info(f"[DDM] {enrollment_id} | Attempting cache update...")
        cache_result = update_device_ddm_cache(enrollment_id)
        logger.info(f"[DDM] {enrollment_id} | Cache update result: {cache_result}")
        if cache_result:
            saved_parts.append("cache")
    if status_items and save_ddm_status_values(enrollment_id, status_items, status_id):
        saved_parts.append("status")
    if errors and save_ddm_errors(enrollment_id, errors, status_id):
        saved_parts.append(f"{len(errors)} err")

    if saved_parts:
        logger.info(f"[DDM] {udid} | saved: {', '.join(saved_parts)}")


# =============================================================================
# WEBHOOK ENDPOINT
# =============================================================================

@app.route('/webhook', methods=['POST'])
def webhook():
    # HMAC security check (NanoMDM uses X-Hmac-Signature header)
    signature = request.headers.get('X-Hmac-Signature')
    if signature and not verify_webhook_signature(request.get_data(), signature):
        logger.warning(f"[SECURITY] Invalid HMAC signature from {request.remote_addr}")
        return 'Unauthorized', 401

    try:
        data = request.get_json()
        topic = data.get('topic', '')
        logger.info("=== MDM Event ===")
        logger.info(f"  topic: {topic}")

        # DDM events come as checkin_event, not acknowledge_event
        if topic == 'mdm.DeclarativeManagement':
            return handle_ddm_event(data)

        event = data.get("acknowledge_event", {})

        status = event.get('status')
        udid = event.get('udid')
        command_uuid = event.get('command_uuid', 'N/A')

        logger.info(f"  status: {status}")
        logger.info(f"  udid: {udid}")
        logger.info(f"  command_uuid: {command_uuid}")

        # Error diagnostics
        if event.get("error_chain"):
            logger.warning("  ErrorChain:")
            for i, e in enumerate(event["error_chain"]):
                logger.warning(f"    [{i}] {e}")
        if event.get("rejection_reason"):
            logger.warning(f"  RejectionReason: {event['rejection_reason']}")
        if event.get("error"):
            logger.warning(f"  Error: {event['error']}")

        # Skip if no payload or error status
        raw_payload = event.get("raw_payload", "")
        if not raw_payload:
            return ''

        if status in ('Error', 'CommandFormatError', 'NotNow'):
            logger.info(f"  Skipping DB save for status: {status}")
            return ''

        try:
            decoded = base64.b64decode(raw_payload)
            plist_data = plistlib.loads(decoded)

            request_type = plist_data.get("RequestType", "")
            if request_type:
                logger.info(f"  RequestType: {request_type}")

            # Process and save based on response type
            saved = False

            # DeviceInformation (hardware data)
            if "QueryResponses" in plist_data or request_type == "DeviceInformation":
                logger.info("[DeviceInformation] Device Info:")
                hardware_data = parse_device_information(plist_data)

                # Detailed logging
                info = plist_data.get('QueryResponses', plist_data)
                for key, val in info.items():
                    logger.info(f"  {key}: {val}")

                # Save to DB
                saved = save_device_details(udid, 'hardware', hardware_data, command_uuid)
                if saved:
                    logger.info(f"  [DB] Saved to device_details.hardware_data")

            # SecurityInfo
            elif "SecurityInfo" in plist_data:
                logger.info("[SecurityInfo] Security Status:")
                security_data = parse_security_info(plist_data)

                # Detailed logging
                for key, val in plist_data.get("SecurityInfo", {}).items():
                    logger.info(f"  {key}: {val}")

                # Save to DB
                saved = save_device_details(udid, 'security', security_data, command_uuid)
                if saved:
                    logger.info(f"  [DB] Saved to device_details.security_data")

            # ProfileList
            elif "ProfileList" in plist_data:
                logger.info("[ProfileList] Installed Profiles:")
                profiles_data = parse_profile_list(plist_data)

                # Detailed logging
                for i, profile in enumerate(plist_data.get("ProfileList", [])):
                    ident = profile.get("PayloadIdentifier", "N/A")
                    name = profile.get("PayloadDisplayName", "N/A")
                    verified = "Verified" if profile.get("IsEncrypted", False) else "Unverified"
                    logger.info(f"  [{i}] {ident} ({name}) — {verified}")

                # Save to DB
                saved = save_device_details(udid, 'profiles', profiles_data, command_uuid)
                if saved:
                    logger.info(f"  [DB] Saved {len(profiles_data)} profiles to device_details.profiles_data")

            # InstalledApplicationList
            elif "InstalledApplicationList" in plist_data:
                logger.info("[InstalledApplicationList] Installed Apps:")
                apps_data = parse_installed_apps(plist_data)

                # Detailed logging
                for i, app in enumerate(plist_data.get("InstalledApplicationList", [])):
                    name = app.get("Name", "Unknown")
                    bundle_id = app.get("Identifier", "Unknown")
                    version = app.get("ShortVersion", app.get("Version", app.get("BundleVersion", "")))
                    logger.info(f"  [{i}] {name} ({bundle_id}) v{version}")

                # Save to DB
                saved = save_device_details(udid, 'apps', apps_data, command_uuid)
                if saved:
                    logger.info(f"  [DB] Saved {len(apps_data)} apps to device_details.apps_data")

            # Other types - just log (not saved to DB)
            elif "ProvisioningProfileList" in plist_data:
                logger.info("[ProvisioningProfileList] Installed Provisioning Profiles:")
                for i, prov in enumerate(plist_data["ProvisioningProfileList"]):
                    ident = prov.get("PayloadIdentifier", "N/A")
                    name = prov.get("PayloadDisplayName", "N/A")
                    logger.info(f"  [{i}] {ident} ({name})")

            elif "CertificateList" in plist_data:
                logger.info("[CertificateList] Installed Certificates:")
                for i, cert in enumerate(plist_data["CertificateList"]):
                    common_name = cert.get("CommonName", "N/A")
                    is_root = cert.get("IsRoot", False)
                    logger.info(f"  [{i}] CN: {common_name} {'[ROOT]' if is_root else ''}")

            # OSUpdateStatus
            elif "OSUpdateStatus" in plist_data:
                logger.info("[OSUpdateStatus] Update Status:")
                status = plist_data.get("OSUpdateStatus", {})
                if isinstance(status, dict):
                    for key, val in status.items():
                        logger.info(f"  {key}: {val}")
                elif isinstance(status, list):
                    for i, item in enumerate(status):
                        logger.info(f"  [{i}] {item}")
                else:
                    logger.info(f"  Status: {status}")

            # AvailableOSUpdates
            elif "AvailableOSUpdates" in plist_data:
                logger.info("[AvailableOSUpdates] Available Updates:")
                updates = plist_data.get("AvailableOSUpdates", [])
                if updates:
                    for i, upd in enumerate(updates):
                        version = upd.get("ProductVersion", upd.get("Version", "?"))
                        name = upd.get("ProductName", upd.get("HumanReadableName", "?"))
                        key = upd.get("ProductKey", "?")
                        logger.info(f"  [{i}] {name} {version} (Key: {key})")
                else:
                    logger.info("  No updates available")

            else:
                # Fallback - log entire payload with values
                logger.info("=== Unknown Payload ===")
                import json
                for key, val in plist_data.items():
                    if isinstance(val, (dict, list)):
                        logger.info(f"  {key}: {json.dumps(val, indent=4, default=str)}")
                    else:
                        logger.info(f"  {key}: {val}")

        except Exception as e:
            logger.warning(f"[!] Error decoding payload: {e}")

    except Exception as e:
        logger.error(f"[!] Unexpected error in webhook: {e}")

    return ''


@app.route('/command-result', methods=['POST', 'PUT'])
def command_result():
    """Handle command results from MDM agent."""
    try:
        data = request.get_json()
        logger.info("=== COMMAND RESULT ===")
        logger.info(f"  Device: {data.get('device_udid')}")
        logger.info(f"  Command: {data.get('command_type')} -> {data.get('command_value')}")
        logger.info(f"  Status: {data.get('status')} (exit code: {data.get('exit_code')})")
        logger.info(f"  Timestamp: {data.get('timestamp')}")

        if data.get('output'):
            output = data.get('output', '').strip()
            if output:
                logger.info(f"  Output: {output}")

        logger.info("=== END COMMAND RESULT ===")

    except Exception as e:
        logger.error(f"[!] Error processing command result: {e}")

    return '', 200


@app.route('/webhook/command-result', methods=['POST', 'PUT'])
def webhook_command_result():
    """Forward /webhook/command-result to /command-result for agent compatibility"""
    return command_result()


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return {'status': 'ok', 'service': 'nanohub-webhook'}, 200


if __name__ == '__main__':
    logger.info("Starting NanoHUB Webhook with DB support...")
    app.run(host='0.0.0.0', port=5001)
