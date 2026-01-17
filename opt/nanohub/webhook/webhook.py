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

# HMAC secret for webhook security (NanoMDM v0.9.0+)
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")

# Log file
LOGFILE = "/var/log/nanohub/webhook.log"

# Database configuration
DB_CONFIG = {
    'host': os.getenv('NANOHUB_DB_HOST', '127.0.0.1'),
    'port': int(os.getenv('NANOHUB_DB_PORT', '3306')),
    'user': os.getenv('NANOHUB_DB_USER', 'nanohub'),
    'password': os.getenv('NANOHUB_DB_PASSWORD', ''),
    'database': os.getenv('NANOHUB_DB_NAME', 'nanohub'),
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
        logger.info("=== MDM Event ===")
        logger.info(f"  topic: {data.get('topic')}")
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
