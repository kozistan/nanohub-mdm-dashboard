#!/usr/bin/env python3
"""
NanoHUB MDM Flask API
=====================
REST API for MDM operations, device management, and queries.
Refactored to use centralized utility modules.
"""

from flask import Flask, request, jsonify
import subprocess
import json
import os
import re
import time
import logging

# Import centralized modules
from config import Config
from db_utils import db, devices
from command_executor import executor, sanitize_param
from webhook_poller import poller, poll_webhook_for_command

app = Flask(__name__)

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('mdm_flask_api')


# =============================================================================
# LEGACY COMPATIBILITY FUNCTIONS
# =============================================================================

def run_command(command, args=None):
    """Run command (legacy compatibility)."""
    result = executor.run(command, *(args or []))
    return result.output, result.error or ''


def search_devices_sql(field, value):
    """Search devices in SQL database (legacy compatibility)."""
    return devices.search(field, value) or None


def get_all_devices_sql():
    """Get all devices from SQL database (legacy compatibility)."""
    return devices.get_all()


def universal_device_search(source, field, value):
    """Universal device search (legacy compatibility)."""
    matches = devices.search(field, value)
    return matches[0] if matches else None


# =============================================================================
# WEBHOOK POLLING FUNCTIONS
# =============================================================================

def universal_webhook_poll(criteria, pattern_type="uuid", logfile=None,
                           initial_sleep=5, max_polls=10, poll_wait=1, window=1000):
    """Poll webhook for command result (legacy compatibility)."""
    response = poller.poll_for_command(
        criteria,
        initial_sleep=initial_sleep,
        max_attempts=max_polls,
        poll_interval=poll_wait,
        window=window
    )
    if response:
        return response.raw.split('\n')
    return []


def poll_custom_command_result(udid, command_type, logfile=None,
                               initial_sleep=30, max_polls=10, poll_wait=2, window=1000):
    """Poll webhook for custom agent command results."""
    time.sleep(initial_sleep)

    for poll_attempt in range(max_polls):
        try:
            with open(Config.WEBHOOK_LOG_PATH, "r") as f:
                lines = f.readlines()[-window:]

            blocks = []
            block = []
            for line in lines:
                if '=== MDM Event ===' in line or '=== COMMAND RESULT ===' in line:
                    if block:
                        blocks.append(block)
                    block = []
                block.append(line)
            if block:
                blocks.append(block)

            for blk in reversed(blocks):
                block_text = ''.join(blk)
                if '=== COMMAND RESULT ===' in block_text and udid.upper() in block_text.upper():
                    if f'Command: {command_type}' in block_text:
                        return list(blk)

            time.sleep(poll_wait)
        except Exception as e:
            logger.warning(f"Error polling custom command: {e}")
            time.sleep(poll_wait)

    return []


# =============================================================================
# EXTRACTION FUNCTIONS
# =============================================================================

def extract_custom_command_result(block):
    """Extract result from custom command response."""
    result = {}
    for line in block:
        if 'Device:' in line:
            result['device'] = line.split('Device:')[1].strip()
        if 'Command:' in line:
            result['command'] = line.split('Command:')[1].strip()
        if 'Status:' in line and 'exit code' in line:
            result['status'] = line.split('Status:')[1].strip()
        if 'Timestamp:' in line:
            result['timestamp'] = line.split('Timestamp:')[1].strip()
    return result


def extract_os_updates(block):
    """Extract OS updates from webhook block."""
    updates = []
    status = ''
    for l in block:
        row = l.strip() if isinstance(l, str) else str(l).strip()
        if "Status:" in row:
            status = row.split("Status:", 1)[1].strip()
        if '{' in row and 'ProductKey' in row:
            try:
                raw = row.split("{", 1)[1].rstrip("}").strip()
                d = eval("{" + raw + "}")
                updates.append({
                    "ProductName": d.get("ProductName") or d.get("HumanReadableName") or d.get("Version") or "",
                    "ProductKey": d.get("ProductKey", ""),
                    "Version": d.get("Version", ""),
                    "IsCritical": d.get("IsCritical", False),
                    "RestartRequired": d.get("RestartRequired", False),
                    "Status": status
                })
            except Exception:
                continue
    return updates


def extract_device_info(block):
    """Extract device info from webhook block."""
    info = {}
    for l in block:
        row = l.strip() if isinstance(l, str) else str(l).strip()
        if "DeviceName:" in row:
            info["device_name"] = row.split("DeviceName:", 1)[1].strip()
        if "OSVersion:" in row:
            info["os_version"] = row.split("OSVersion:", 1)[1].strip()
        if "SerialNumber:" in row:
            info["serial_number"] = row.split("SerialNumber:", 1)[1].strip()
        if "Status:" in row:
            info["status"] = row.split("Status:", 1)[1].strip()
    if block:
        parts = block[0].split(' [', 1)[0].strip() if isinstance(block[0], str) else ''
        info["checkin_time"] = parts
    return info


def extract_profile_list(block):
    """Extract profile list from webhook block."""
    profiles = []
    capture = False
    for l in block:
        raw = l.strip() if isinstance(l, str) else str(l).strip()
        if "[ProfileList] Installed Profiles:" in raw:
            capture = True
            continue
        if capture:
            m = re.match(r".*\[([0-9]+)\]\s+([^\s]+)\s+\(([^)]+)\)\s+[–\-—]\s+(.+)", raw)
            if m:
                profiles.append({
                    "PayloadIdentifier": m.group(2),
                    "PayloadDisplayName": m.group(3),
                    "Status": m.group(4)
                })
    return profiles


def extract_installed_apps(block):
    """Extract installed apps from webhook block."""
    apps = []
    capture = False
    for l in block:
        row = l.strip() if isinstance(l, str) else str(l).strip()
        if "[InstalledApplicationList] Installed Apps:" in row:
            capture = True
            continue
        if capture:
            m = re.match(r".*\[(\d+)\]\s+(.+?)\s+\((.+?)\)\s+v([^\s]+)", row)
            if m:
                apps.append({
                    "Index": m.group(1),
                    "Name": m.group(2),
                    "BundleID": m.group(3),
                    "Version": m.group(4)
                })
    return apps


def extract_system_report(block):
    """Extract extended device information for system report."""
    info = {}
    for l in block:
        row = l.strip() if isinstance(l, str) else str(l).strip()

        # Basic Info
        field_map = {
            "DeviceName:": "device_name",
            "OSVersion:": "os_version",
            "BuildVersion:": "build_version",
            "ModelName:": "model_name",
            "ProductName:": "product_name",
            "SerialNumber:": "serial_number",
            "WiFiMAC:": "wifi_mac",
            "BluetoothMAC:": "bluetooth_mac",
            "EthernetMAC:": "ethernet_mac",
            "LocalHostName:": "local_hostname",
            "CellularTechnology:": "cellular_technology",
            "IMEI:": "imei",
            "MEID:": "meid",
            "ModemFirmwareVersion:": "modem_firmware",
            "IsSupervised:": "is_supervised",
            "SystemIntegrityProtectionEnabled:": "sip_enabled",
            "IsActivationLockEnabled:": "activation_lock",
            "IsDeviceLocatorServiceEnabled:": "find_my_enabled",
            "IsCloudBackupEnabled:": "cloud_backup",
            "IsMDMLostModeEnabled:": "mdm_lost_mode",
            "IsDoNotDisturbInEffect:": "dnd_enabled",
        }

        for key, field in field_map.items():
            if key in row:
                info[field] = row.split(key, 1)[1].strip()

        # Special handling for Model (avoid ModelName conflict)
        if "Model:" in row and "ModelName:" not in row:
            info["model"] = row.split("Model:", 1)[1].strip()

        # Special handling for HostName
        if "HostName:" in row and "LocalHostName:" not in row:
            info["hostname"] = row.split("HostName:", 1)[1].strip()

        # Storage - parse as GB
        if "DeviceCapacity:" in row:
            try:
                capacity = float(row.split("DeviceCapacity:", 1)[1].strip())
                if capacity > 1000:  # Probably bytes
                    capacity = capacity / (1024**3)
                info["device_capacity"] = f"{capacity:.2f} GB"
            except:
                info["device_capacity"] = row.split("DeviceCapacity:", 1)[1].strip()

        if "AvailableDeviceCapacity:" in row:
            try:
                available = float(row.split("AvailableDeviceCapacity:", 1)[1].strip())
                if available > 1000:
                    available = available / (1024**3)
                info["available_capacity"] = f"{available:.2f} GB"
            except:
                info["available_capacity"] = row.split("AvailableDeviceCapacity:", 1)[1].strip()

        # Battery
        if "BatteryLevel:" in row:
            try:
                battery = float(row.split("BatteryLevel:", 1)[1].strip())
                if battery <= 1.0:
                    battery = battery * 100
                info["battery_level"] = f"{battery:.0f}%"
            except:
                info["battery_level"] = row.split("BatteryLevel:", 1)[1].strip()

        if "Status:" in row:
            info["status"] = row.split("Status:", 1)[1].strip()

    if block and len(block) > 0:
        first = block[0] if isinstance(block[0], str) else str(block[0])
        parts = first.split(' [', 1)[0].strip()
        info["checkin_time"] = parts

    return info


def extract_security_info_detailed(block):
    """Extract detailed security information."""
    info = {}
    for line in block:
        row = line.strip() if isinstance(line, str) else str(line).strip()

        # FileVault / FDE
        if "FDE_Enabled:" in row:
            info["filevault_enabled"] = row.split("FDE_Enabled:", 1)[1].strip()
        if "FDE_HasPersonalRecoveryKey:" in row:
            info["filevault_has_recovery_key"] = row.split("FDE_HasPersonalRecoveryKey:", 1)[1].strip()
        if "FDE_HasInstitutionalRecoveryKey:" in row:
            info["filevault_has_institutional_key"] = row.split("FDE_HasInstitutionalRecoveryKey:", 1)[1].strip()

        # Firewall
        if "FirewallSettings:" in row:
            if "'FirewallEnabled': True" in row:
                info["firewall_enabled"] = "True"
            elif "'FirewallEnabled': False" in row:
                info["firewall_enabled"] = "False"
            if "'BlockAllIncoming': True" in row:
                info["firewall_block_all"] = "True"
            elif "'BlockAllIncoming': False" in row:
                info["firewall_block_all"] = "False"
            if "'StealthMode': True" in row:
                info["firewall_stealth"] = "True"
            elif "'StealthMode': False" in row:
                info["firewall_stealth"] = "False"

        # Other security fields
        if "RemoteDesktopEnabled:" in row:
            info["remote_desktop_enabled"] = row.split("RemoteDesktopEnabled:", 1)[1].strip()
        if "SystemIntegrityProtectionEnabled:" in row:
            info["sip_enabled"] = row.split("SystemIntegrityProtectionEnabled:", 1)[1].strip()
        if "SecureBootLevel:" in row or "'SecureBootLevel':" in row:
            if "'full'" in row or "full" in row.lower():
                info["secure_boot_level"] = "full"
            elif "'medium'" in row or "medium" in row.lower():
                info["secure_boot_level"] = "medium"
            elif "'none'" in row or "none" in row.lower():
                info["secure_boot_level"] = "none"
        if "BootstrapTokenAllowedForAuthentication:" in row:
            info["bootstrap_token_auth"] = row.split("BootstrapTokenAllowedForAuthentication:", 1)[1].strip()
        if "IsRecoveryLockEnabled:" in row:
            info["recovery_lock_enabled"] = row.split("IsRecoveryLockEnabled:", 1)[1].strip()

    return info


def extract_device_info_detailed(block):
    """Extract detailed device information."""
    return extract_system_report(block)


# =============================================================================
# API ENDPOINTS
# =============================================================================

@app.route('/api/dep-account-detail')
def dep_account_detail():
    """Get DEP account details."""
    result = executor.run('/opt/nanohub/dep/dep-account-detail.sh')
    return result.output, 200, {'Content-Type': 'application/json'}


@app.route('/api/cfg-get-cert')
def depcert():
    """Get certificate expiry information."""
    try:
        result = executor.run(f"{Config.BACKEND_API_DIR}/cfg-get-cert-expiry.sh")
        if not result.success:
            return jsonify({"error": result.error}), 500

        certs = []
        for line in result.output.strip().split('\n'):
            cols = line.split('|')
            if len(cols) >= 3:
                cert = {'name': cols[0], 'usage': cols[1], 'expiry': cols[2]}
                if len(cols) >= 4:
                    cert['url'] = cols[3]
                certs.append(cert)
        return jsonify(certs)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/device-search', methods=['POST'])
def device_search():
    """Search for devices."""
    data = request.json
    field = data.get('field', 'hostname')
    value = data.get('value', '')

    result = devices.search(field, value)
    if not result:
        return jsonify({"error": f"No device found for {field}={value}"}), 404
    return jsonify(result)


@app.route('/api/devices', methods=['GET'])
def get_devices():
    """Get all devices."""
    return jsonify(devices.get_all())


@app.route('/api/devices', methods=['POST'])
def add_device():
    """Add a new device to device_inventory."""
    data = request.json

    required_fields = ['uuid', 'serial', 'os', 'hostname']
    for field in required_fields:
        if not data.get(field):
            return jsonify({"error": f"Missing required field: {field}"}), 400

    if data['os'] not in ['ios', 'macos']:
        return jsonify({"error": "OS must be 'ios' or 'macos'"}), 400

    uuid_val = sanitize_param(data['uuid'])
    serial = sanitize_param(data['serial'])
    os_type = sanitize_param(data['os'])
    hostname = sanitize_param(data['hostname'])
    manifest = sanitize_param(data.get('manifest', 'default'))
    account = sanitize_param(data.get('account', 'disabled'))
    dep = sanitize_param(data.get('dep', 'enabled'))

    try:
        if devices.exists(uuid_val):
            return jsonify({"error": "Device with this UUID already exists"}), 409

        success = devices.add(uuid_val, serial, os_type, hostname, manifest, account, dep)
        if success:
            return jsonify({
                "success": True,
                "message": "Device added successfully",
                "device": {
                    "uuid": uuid_val, "serial": serial, "os": os_type,
                    "hostname": hostname, "manifest": manifest,
                    "account": account, "dep": dep
                }
            }), 201
        else:
            return jsonify({"error": "Failed to add device"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/devices/<uuid>', methods=['PUT'])
def update_device(uuid):
    """Update an existing device."""
    data = request.json

    if not devices.exists(uuid):
        return jsonify({"error": "Device not found"}), 404

    if 'os' in data and data['os'] not in ['ios', 'macos']:
        return jsonify({"error": "OS must be 'ios' or 'macos'"}), 400

    update_fields = {}
    for field in ['serial', 'os', 'hostname', 'manifest', 'account', 'dep']:
        if field in data:
            update_fields[field] = sanitize_param(data[field])

    if not update_fields:
        return jsonify({"error": "No fields to update"}), 400

    try:
        success = devices.update(uuid, **update_fields)
        if success:
            return jsonify({"success": True, "message": "Device updated successfully", "uuid": uuid})
        else:
            return jsonify({"error": "Failed to update device"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/devices/<uuid>', methods=['DELETE'])
def delete_device(uuid):
    """Delete a device."""
    device = devices.get_by_uuid(uuid)
    if not device:
        return jsonify({"error": "Device not found"}), 404

    hostname = device.get('hostname', 'unknown')

    try:
        success = devices.delete(uuid)
        if success:
            return jsonify({
                "success": True,
                "message": f"Device '{hostname}' deleted successfully",
                "uuid": uuid
            })
        else:
            return jsonify({"error": "Failed to delete device"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/mdm-analyzer')
def mdm_analyzer():
    """Run MDM analyzer for device."""
    search_type = request.args.get('type')
    search_value = request.args.get('value', '').strip().lower()

    device = universal_device_search("json", search_type, search_value)
    if not device:
        return jsonify({"error": "Device not found"}), 404

    uuid = device.get("uuid")
    result = executor.run('mdm_analyzer', uuid, '--json', timeout=60)

    if not result.success:
        return jsonify({"error": result.error or result.output}), 500

    try:
        return jsonify(json.loads(result.output)), 200
    except json.JSONDecodeError:
        return jsonify({"error": "Invalid JSON response", "raw": result.output}), 500


@app.route('/api/device-info', methods=['POST'])
def deviceinfo():
    """Get device information."""
    searchtype = request.json.get('type')
    searchvalue = request.json.get('value', '').strip().lower()

    device = universal_device_search("json", searchtype, searchvalue)
    if not device:
        return jsonify({"error": "Device not found"}), 404

    uuid = device.get("uuid")
    result = executor.run('device_information', uuid)

    if not result.success or not result.command_uuid:
        match = re.search(r'[a-f0-9\-]{36}', result.output)
        command_uuid = match.group(0) if match else result.command_uuid
        if not command_uuid:
            return jsonify({"error": "No command_uuid found"}), 500
    else:
        command_uuid = result.command_uuid

    block = universal_webhook_poll(command_uuid, "uuid", initial_sleep=3)
    info = extract_device_info(block) if block else {}

    if not info:
        return jsonify({"error": "Device info not found"}), 404

    # Add device status from database if not in webhook response
    if not info.get("status"):
        info["status"] = device.get("status", "")

    return jsonify(info)


@app.route('/api/os-updates', methods=['POST'])
def os_updates():
    """Get available OS updates for device."""
    udid = request.json.get('udid')
    if not udid:
        return jsonify({"error": "Missing UDID"}), 400

    result = executor.run('available_os_updates', udid)
    if not result.success:
        return jsonify({"error": f"Failed to trigger OS updates: {result.error}"}), 500

    command_uuid = result.command_uuid
    if not command_uuid:
        match = re.search(r'[a-f0-9\-]{36}', result.output)
        command_uuid = match.group(0) if match else None
    if not command_uuid:
        return jsonify({"error": "No command_uuid found"}), 500

    block = universal_webhook_poll(command_uuid, "uuid", initial_sleep=5)
    updates = extract_os_updates(block) if block else []

    if updates:
        return jsonify(updates)
    else:
        return jsonify({"error": "No OS update info found"}), 404


@app.route('/api/installed-apps', methods=['POST'])
def installed_apps():
    """Get installed applications list."""
    udid = request.json.get('udid')
    if not udid:
        return jsonify({"error": "Missing UDID"}), 400

    result = executor.run('installed_application_list', udid)
    if not result.success:
        return jsonify({"error": f"Failed to trigger Installed Apps List: {result.error}"}), 500

    command_uuid = result.command_uuid
    if not command_uuid:
        match = re.search(r'[a-f0-9\-]{36}', result.output)
        command_uuid = match.group(0) if match else None
    if not command_uuid:
        return jsonify({"error": "No command_uuid found"}), 500

    block = universal_webhook_poll(command_uuid, "uuid", initial_sleep=5)
    apps = extract_installed_apps(block) if block else []

    if apps:
        return jsonify(apps)
    else:
        return jsonify({"error": "No Installed Applications info found"}), 404


@app.route('/api/profile-list', methods=['POST'])
def profile_list():
    """Get installed profiles list."""
    udid = request.json.get('udid')
    if not udid:
        return jsonify({"error": "Missing UDID"}), 400

    result = executor.run('profile_list', udid)
    if not result.success:
        return jsonify({"error": f"Failed to trigger Profile List: {result.error}"}), 500

    command_uuid = result.command_uuid
    if not command_uuid:
        match = re.search(r'[a-f0-9\-]{36}', result.output)
        command_uuid = match.group(0) if match else None
    if not command_uuid:
        return jsonify({"error": "No command_uuid found"}), 500

    block = universal_webhook_poll(command_uuid, "uuid", initial_sleep=5)
    profiles = extract_profile_list(block) if block else []

    if profiles:
        return jsonify(profiles)
    else:
        return jsonify({"error": "No Profile List info found"}), 404


@app.route('/api/wake-device', methods=['POST'])
def wake_device():
    """Schedule device wake."""
    udid = request.json.get('udid')
    if not udid:
        return jsonify({"error": "Missing UDID"}), 400

    import datetime
    wake_time = datetime.datetime.now() + datetime.timedelta(seconds=30)
    wake_cmd = wake_time.strftime('%m/%d/%y %H:%M:%S')

    try:
        result = executor.run('send_command', udid, 'shell', f"pmset schedule wake '{wake_cmd}'")
        if not result.success:
            return jsonify({"error": f"Failed to send wake command: {result.error}"}), 500

        block = poll_custom_command_result(udid, 'shell', initial_sleep=5, max_polls=10, poll_wait=2)
        if block:
            cmd_result = extract_custom_command_result(block)
            return jsonify({
                "message": "Wake command sent successfully",
                "wake_time": wake_cmd,
                "result": cmd_result
            })
        else:
            return jsonify({"error": "No response from device"}), 404
    except Exception as e:
        return jsonify({"error": f"Failed to send wake command: {e}"}), 500


@app.route('/api/device-system-report', methods=['POST'])
def device_system_report():
    """Get system report for device (database info only)."""
    data = request.json
    field = data.get('field', 'hostname')
    value = data.get('value', '')

    if not value:
        return jsonify({"error": "Missing search value"}), 400

    device = universal_device_search("json", field, value)
    if not device:
        return jsonify({"error": "Device not found"}), 404

    udid = device.get("uuid")

    report = {
        "basic_info": {
            "uuid": device.get("uuid", "N/A"),
            "serial": device.get("serial", "N/A"),
            "hostname": device.get("hostname", "N/A"),
            "os": device.get("os", "N/A"),
            "manifest": device.get("manifest", "N/A"),
            "account": device.get("account", "N/A"),
            "dep": device.get("dep", "N/A"),
            "status": device.get("status", "N/A"),
            "last_seen": str(device.get("last_seen", "N/A"))
        }
    }

    # Get enrollment info
    enrollment = db.query_one("""
        SELECT type, enabled, last_seen_at, created_at, token_update_tally
        FROM enrollments WHERE device_id = %s
        ORDER BY last_seen_at DESC LIMIT 1
    """, (udid,))

    if enrollment:
        report["enrollment_info"] = {
            "type": enrollment.get("type"),
            "enabled": "Yes" if enrollment.get("enabled") else "No",
            "last_seen": str(enrollment.get("last_seen_at")),
            "enrolled_at": str(enrollment.get("created_at")),
            "token_updates": enrollment.get("token_update_tally")
        }

    return jsonify(report)


@app.route('/api/device-system-report-live', methods=['POST'])
def device_system_report_live():
    """Get live system report with device information."""
    data = request.json
    field = data.get('field', 'hostname')
    value = data.get('value', '')

    if not value:
        return jsonify({"error": "Missing search value"}), 400

    device = universal_device_search("json", field, value)
    if not device:
        return jsonify({"error": "Device not found"}), 404

    udid = device.get("uuid")

    result = executor.run('system_report', udid)
    if not result.success:
        return jsonify({"error": f"Failed to trigger system report: {result.error}"}), 500

    command_uuid = result.command_uuid
    if not command_uuid:
        match = re.search(r'[a-f0-9\-]{36}', result.output)
        command_uuid = match.group(0) if match else None
    if not command_uuid:
        return jsonify({"error": "No command_uuid found"}), 500

    block = universal_webhook_poll(command_uuid, "uuid", initial_sleep=5, max_polls=15, poll_wait=1)
    system_info = extract_system_report(block) if block else {}

    if not system_info:
        return jsonify({"error": "No system report data received from device"}), 404

    report = {
        "basic_info": {
            "uuid": device.get("uuid", "N/A"),
            "serial": device.get("serial", "N/A"),
            "hostname": device.get("hostname", "N/A"),
            "os": device.get("os", "N/A"),
            "manifest": device.get("manifest", "N/A"),
            "account": device.get("account", "N/A"),
            "dep": device.get("dep", "N/A"),
            "status": device.get("status", "N/A"),
            "last_seen": str(device.get("last_seen", "N/A"))
        },
        "hardware_info": {
            "model_name": system_info.get("model_name", "N/A"),
            "model": system_info.get("model", "N/A"),
            "product_name": system_info.get("product_name", "N/A"),
            "device_capacity": system_info.get("device_capacity", "N/A"),
            "available_capacity": system_info.get("available_capacity", "N/A"),
            "battery_level": system_info.get("battery_level", "N/A")
        },
        "software_info": {
            "os_version": system_info.get("os_version", "N/A"),
            "build_version": system_info.get("build_version", "N/A")
        },
        "network_info": {
            "hostname": system_info.get("hostname", "N/A"),
            "local_hostname": system_info.get("local_hostname", "N/A"),
            "wifi_mac": system_info.get("wifi_mac", "N/A"),
            "bluetooth_mac": system_info.get("bluetooth_mac", "N/A"),
            "ethernet_mac": system_info.get("ethernet_mac", "N/A")
        },
        "cellular_info": {
            "technology": system_info.get("cellular_technology", "N/A"),
            "imei": system_info.get("imei", "N/A"),
            "meid": system_info.get("meid", "N/A"),
            "modem_firmware": system_info.get("modem_firmware", "N/A")
        },
        "security_info": {
            "supervised": system_info.get("is_supervised", "N/A"),
            "sip_enabled": system_info.get("sip_enabled", "N/A"),
            "activation_lock": system_info.get("activation_lock", "N/A"),
            "find_my_enabled": system_info.get("find_my_enabled", "N/A"),
            "cloud_backup": system_info.get("cloud_backup", "N/A"),
            "mdm_lost_mode": system_info.get("mdm_lost_mode", "N/A"),
            "dnd_enabled": system_info.get("dnd_enabled", "N/A")
        }
    }

    return jsonify(report)


@app.route('/api/device-system-report-full', methods=['POST'])
def device_system_report_full():
    """Get comprehensive system report with all available information."""
    data = request.json
    field = data.get('field', 'hostname')
    value = data.get('value', '')

    if not value:
        return jsonify({"error": "Missing search value"}), 400

    device = universal_device_search("json", field, value)
    if not device:
        return jsonify({"error": "Device not found"}), 404

    udid = device.get("uuid")

    # Trigger full system report (DeviceInformation + SecurityInfo)
    result = executor.run('system_report_full', udid, timeout=10)
    if not result.success:
        return jsonify({"error": f"Failed to trigger system report: {result.error}"}), 500

    # Parse the two command UUIDs
    match = re.search(r'([a-f0-9\-]{36})\|([a-f0-9\-]{36})', result.output)
    if not match:
        return jsonify({"error": "Failed to get command UUIDs"}), 500

    cmd_uuid_device = match.group(1)
    cmd_uuid_security = match.group(2)

    # Poll for DeviceInformation
    block_device = universal_webhook_poll(cmd_uuid_device, "uuid", initial_sleep=5, max_polls=12, poll_wait=2)
    device_info = extract_device_info_detailed(block_device) if block_device else {}

    # Poll for SecurityInfo
    block_security = universal_webhook_poll(cmd_uuid_security, "uuid", initial_sleep=5, max_polls=10, poll_wait=2)
    security_info = extract_security_info_detailed(block_security) if block_security else {}

    report = {
        "basic_info": {
            "uuid": device.get("uuid", "N/A"),
            "serial": device.get("serial", "N/A"),
            "hostname": device.get("hostname", "N/A"),
            "os": device.get("os", "N/A"),
            "manifest": device.get("manifest", "N/A"),
            "account": device.get("account", "N/A"),
            "dep": device.get("dep", "N/A"),
            "status": device.get("status", "N/A"),
            "last_seen": str(device.get("last_seen", "N/A"))
        },
        "hardware_info": {
            "model_name": device_info.get("model_name", "N/A"),
            "model": device_info.get("model", "N/A"),
            "product_name": device_info.get("product_name", "N/A"),
            "device_capacity": device_info.get("device_capacity", "N/A"),
            "available_capacity": device_info.get("available_capacity", "N/A"),
            "battery_level": device_info.get("battery_level", "N/A")
        },
        "software_info": {
            "os_version": device_info.get("os_version", "N/A"),
            "build_version": device_info.get("build_version", "N/A")
        },
        "network_info": {
            "hostname": device_info.get("hostname", "N/A"),
            "local_hostname": device_info.get("local_hostname", "N/A"),
            "wifi_mac": device_info.get("wifi_mac", "N/A"),
            "bluetooth_mac": device_info.get("bluetooth_mac", "N/A"),
            "ethernet_mac": device_info.get("ethernet_mac", "N/A")
        },
        "security_info": {
            "supervised": device_info.get("is_supervised", "N/A"),
            "sip_enabled": security_info.get("sip_enabled", device_info.get("sip_enabled", "N/A")),
            "filevault_enabled": security_info.get("filevault_enabled", "N/A"),
            "filevault_recovery_key": security_info.get("filevault_has_recovery_key", "N/A"),
            "firewall_enabled": security_info.get("firewall_enabled", "N/A"),
            "firewall_block_all": security_info.get("firewall_block_all", "N/A"),
            "firewall_stealth": security_info.get("firewall_stealth", "N/A"),
            "remote_desktop": security_info.get("remote_desktop_enabled", "N/A"),
            "secure_boot": security_info.get("secure_boot_level", "N/A"),
            "activation_lock": device_info.get("activation_lock", "N/A"),
            "find_my_enabled": device_info.get("find_my_enabled", "N/A"),
            "recovery_lock": security_info.get("recovery_lock_enabled", "N/A")
        }
    }

    # Add cellular info if available
    if device_info.get("cellular_technology") and device_info.get("cellular_technology") != "N/A":
        report["cellular_info"] = {
            "technology": device_info.get("cellular_technology", "N/A"),
            "imei": device_info.get("imei", "N/A"),
            "meid": device_info.get("meid", "N/A"),
            "modem_firmware": device_info.get("modem_firmware", "N/A")
        }

    return jsonify(report)


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=9006)
