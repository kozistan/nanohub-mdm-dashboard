#!/usr/bin/env python3
from flask import Flask, request, jsonify
import subprocess, json, os, re, time

app = Flask(__name__)

# Database configuration
DB_CONFIG = {
    'host': '127.0.0.1',
    'user': 'nanohub',
    'password': 'YOUR_DATABASE_PASSWORD',
    'database': 'nanohub'
}

WEBHOOK_LOG_PATH = "/var/log/nanohub/webhook.log"

def run_command(command, args=None):
    cmd = [command] + (args or [])
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return result.stdout, result.stderr

def search_devices_sql(field, value):
    """Search devices in SQL database with online/offline status"""
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
    WHERE di.{field} LIKE '%{value}%'
    ORDER BY di.hostname
    """
    cmd = [
        'mysql',
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
            return None

        matches = []
        for line in output.split('\n'):
            if line.strip():
                try:
                    matches.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return matches if matches else None
    except subprocess.CalledProcessError:
        return None

def get_all_devices_sql():
    """Get all devices from SQL database with online/offline status"""
    sql = """
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
    ORDER BY di.hostname
    """
    cmd = [
        'mysql',
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
    except subprocess.CalledProcessError:
        return []

def poll_custom_command_result(udid, command_type, logfile=WEBHOOK_LOG_PATH, initial_sleep=30, max_polls=10, poll_wait=2, window=1000):
    """Poll webhook for custom agent command results"""
    time.sleep(initial_sleep)

    for poll_attempt in range(max_polls):
        with open(logfile, "r") as f:
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

        # Search for COMMAND RESULT block with matching UDID
        for blk in reversed(blocks):
            block_text = ''.join(blk)
            if '=== COMMAND RESULT ===' in block_text and udid.upper() in block_text.upper():
                # Check if it's the right command type
                if f'Command: {command_type}' in block_text:
                    return list(blk)

        time.sleep(poll_wait)
    return []

def extract_custom_command_result(block):
    """Extract result from custom command response"""
    result = {}
    for line in block:
        if 'Device:' in line:
            result['device'] = line.split('Device:')[1].strip()
        if 'Command:' in line:
            result['command'] = line.split('Command:')[1].strip()
        if 'Status:' in line and 'exit code' in line:
            status_part = line.split('Status:')[1].strip()
            result['status'] = status_part
        if 'Timestamp:' in line:
            result['timestamp'] = line.split('Timestamp:')[1].strip()
    return result

def universal_webhook_poll(criteria, pattern_type="uuid", logfile=WEBHOOK_LOG_PATH, initial_sleep=5, max_polls=10, poll_wait=1, window=1000):
    import re
    time.sleep(initial_sleep)

    for poll_attempt in range(max_polls):
        with open(logfile, "r") as f:
            lines = f.readlines()[-window:]

        blocks = []
        block = []
        for line in lines:
            if '=== MDM Event ===' in line and block:
                blocks.append(block)
                block = []
            block.append(line)
        if block:
            blocks.append(block)

        # Search from newest to oldest
        for blk in reversed(blocks):
            # Check if this block contains the specific command_uuid
            for line in blk:
                if 'command_uuid:' in line.lower() or 'CommandUUID:' in line:
                    if criteria.lower() in line.lower():
                        return list(blk)

        time.sleep(poll_wait)
    return []

def extract_os_updates(block):
    updates = []
    status = ''
    for l in block:
        row = l.strip()
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
    info = {}
    for l in block:
        row = l.strip()
        if "DeviceName:" in row:
            info["device_name"] = row.split("DeviceName:",1)[1].strip()
        if "OSVersion:" in row:
            info["os_version"] = row.split("OSVersion:",1)[1].strip()
        if "SerialNumber:" in row:
            info["serial_number"] = row.split("SerialNumber:",1)[1].strip()
        if "Status:" in row or "status:" in row:
            info["status"] = row.split("Status:",1)[1].strip() if "Status:" in row else row.split("status:",1)[1].strip()
        if block:
            parts = block[0].split(' [', 1)[0].strip()
            info["checkin_time"] = parts
    return info

def extract_profile_list(block):
    import re
    profiles = []
    capture = False
    for l in block:
        raw = l.strip()
        if "[ProfileList] Installed Profiles:" in raw:
            capture = True
            continue
        if capture:
            m = re.match(r".*\[([0-9]+)\]\s+([^\s]+)\s+\(([^)]+)\)\s+[–\-—]\s+(.+)", raw)
            if m:
                identifier = m.group(2)
                display_name = m.group(3)
                status = m.group(4)
                profiles.append({
                    "PayloadIdentifier": identifier,
                    "PayloadDisplayName": display_name,
                    "Status": status
                })
    return profiles

def extract_installed_apps(block):
    import re
    apps = []
    capture = False
    for l in block:
        row = l.strip()
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

def universal_device_search(source, field, value):
    """Universal device search - now uses SQL only"""
    matches = search_devices_sql(field, value)
    # Return first match for backward compatibility with other functions
    return matches[0] if matches else None

@app.route('/api/dep-account-detail')
def dep_account_detail():
    output, error = run_command('/opt/nanohub/dep/dep-account-detail.sh')
    return output, 200, {'Content-Type': 'application/json'}

@app.route('/api/cfg-get-cert')
def depcert():
    try:
        result = subprocess.run(
            ["/opt/nanohub/backend_api/cfg-get-cert-expiry.sh"],
            stdout=subprocess.PIPE, text=True, check=True
        )
        certs = []
        for line in result.stdout.strip().split('\n'):
            cols = line.split('|')
            if len(cols) == 3:
                certs.append({'name': cols[0], 'usage': cols[1], 'expiry': cols[2]})
        return jsonify(certs)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/device-search', methods=['POST'])
def device_search():
    data = request.json
    source = data.get('source', 'json')  # Keep for backward compatibility
    field = data.get('field', 'hostname')
    value = data.get('value', '')
    # Call search_devices_sql directly to get all matches
    devices = search_devices_sql(field, value)
    if not devices:
        return jsonify({"error": f"No device found for {field}={value}"}), 404
    # Return as array to support multiple devices with same hostname
    return jsonify(devices)

@app.route('/api/devices', methods=['GET'])
def get_devices():
    """GET endpoint for getting all devices"""
    devices = get_all_devices_sql()
    return jsonify(devices)

# Device Management Endpoints (CRUD operations)

@app.route('/api/devices', methods=['POST'])
def add_device():
    """Add a new device to device_inventory"""
    data = request.json

    # Validate required fields
    required_fields = ['uuid', 'serial', 'os', 'hostname']
    for field in required_fields:
        if not data.get(field):
            return jsonify({"error": f"Missing required field: {field}"}), 400

    # Validate OS
    if data['os'] not in ['ios', 'macos']:
        return jsonify({"error": "OS must be 'ios' or 'macos'"}), 400

    # Set defaults
    manifest = data.get('manifest', 'default')
    account = data.get('account', 'disabled')
    dep = data.get('dep', 'enabled')

    # SQL insert
    sql = f"""
    INSERT INTO device_inventory (uuid, serial, os, hostname, manifest, account, dep)
    VALUES ('{data['uuid']}', '{data['serial']}', '{data['os']}', '{data['hostname']}',
            '{manifest}', '{account}', '{dep}')
    """

    cmd = [
        'mysql',
        '-h', DB_CONFIG['host'],
        '-u', DB_CONFIG['user'],
        f'-p{DB_CONFIG["password"]}',
        DB_CONFIG['database'],
        '-e', sql
    ]

    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        return jsonify({
            "success": True,
            "message": "Device added successfully",
            "device": {
                "uuid": data['uuid'],
                "serial": data['serial'],
                "os": data['os'],
                "hostname": data['hostname'],
                "manifest": manifest,
                "account": account,
                "dep": dep
            }
        }), 201
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr if e.stderr else str(e)
        if "Duplicate entry" in error_msg:
            return jsonify({"error": "Device with this UUID already exists"}), 409
        return jsonify({"error": f"Database error: {error_msg}"}), 500

@app.route('/api/devices/<uuid>', methods=['PUT'])
def update_device(uuid):
    """Update an existing device"""
    data = request.json

    # Check if device exists
    check_sql = f"SELECT COUNT(*) FROM device_inventory WHERE uuid='{uuid}'"
    cmd = [
        'mysql',
        '-h', DB_CONFIG['host'],
        '-u', DB_CONFIG['user'],
        f'-p{DB_CONFIG["password"]}',
        DB_CONFIG['database'],
        '-sN',
        '-e', check_sql
    ]

    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        if result.stdout.strip() == '0':
            return jsonify({"error": "Device not found"}), 404
    except subprocess.CalledProcessError:
        return jsonify({"error": "Database error"}), 500

    # Build update query
    updates = []
    if 'serial' in data:
        updates.append(f"serial='{data['serial']}'")
    if 'os' in data:
        if data['os'] not in ['ios', 'macos']:
            return jsonify({"error": "OS must be 'ios' or 'macos'"}), 400
        updates.append(f"os='{data['os']}'")
    if 'hostname' in data:
        updates.append(f"hostname='{data['hostname']}'")
    if 'manifest' in data:
        updates.append(f"manifest='{data['manifest']}'")
    if 'account' in data:
        updates.append(f"account='{data['account']}'")
    if 'dep' in data:
        updates.append(f"dep='{data['dep']}'")

    if not updates:
        return jsonify({"error": "No fields to update"}), 400

    update_sql = f"UPDATE device_inventory SET {', '.join(updates)} WHERE uuid='{uuid}'"

    cmd = [
        'mysql',
        '-h', DB_CONFIG['host'],
        '-u', DB_CONFIG['user'],
        f'-p{DB_CONFIG["password"]}',
        DB_CONFIG['database'],
        '-e', update_sql
    ]

    try:
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        return jsonify({
            "success": True,
            "message": "Device updated successfully",
            "uuid": uuid
        })
    except subprocess.CalledProcessError as e:
        return jsonify({"error": f"Database error: {e.stderr}"}), 500

@app.route('/api/devices/<uuid>', methods=['DELETE'])
def delete_device(uuid):
    """Delete a device"""

    # Check if device exists
    check_sql = f"SELECT hostname FROM device_inventory WHERE uuid='{uuid}'"
    cmd = [
        'mysql',
        '-h', DB_CONFIG['host'],
        '-u', DB_CONFIG['user'],
        f'-p{DB_CONFIG["password"]}',
        DB_CONFIG['database'],
        '-sN',
        '-e', check_sql
    ]

    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        hostname = result.stdout.strip()
        if not hostname:
            return jsonify({"error": "Device not found"}), 404
    except subprocess.CalledProcessError:
        return jsonify({"error": "Database error"}), 500

    # Delete device
    delete_sql = f"DELETE FROM device_inventory WHERE uuid='{uuid}'"

    cmd = [
        'mysql',
        '-h', DB_CONFIG['host'],
        '-u', DB_CONFIG['user'],
        f'-p{DB_CONFIG["password"]}',
        DB_CONFIG['database'],
        '-e', delete_sql
    ]

    try:
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        return jsonify({
            "success": True,
            "message": f"Device '{hostname}' deleted successfully",
            "uuid": uuid
        })
    except subprocess.CalledProcessError as e:
        return jsonify({"error": f"Database error: {e.stderr}"}), 500

@app.route('/api/mdm-analyzer')
def mdm_analyzer():
    search_type = request.args.get('type')
    search_value = request.args.get('value', '').strip().lower()
    uuid = None
    device = universal_device_search("json", search_type, search_value)
    if device:
        uuid = device.get("uuid")
    if not uuid:
        return jsonify({"error": "Device not found"}), 404
    try:
        result = subprocess.run(["/opt/nanohub/tools/api/commands/mdm_analyzer", uuid, "--json"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            return jsonify({"error": result.stderr}), 500
        obj = json.loads(result.stdout)
        return jsonify(obj), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/device-info', methods=['POST'])
def deviceinfo():
    searchtype = request.json.get('type')
    searchvalue = request.json.get('value', '').strip().lower()
    uuid = None
    device = universal_device_search("json", searchtype, searchvalue)
    if device:
        uuid = device.get("uuid")
    if not uuid:
        return jsonify({"error": "Device not found"}), 404
    try:
        result = subprocess.run(
            ['/opt/nanohub/tools/api/commands/device_information', uuid],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        # OPRAVA: Hledej UUID v plain textu stejně jako ostatní
        match = re.search(r'[a-f0-9\-]{36}', result.stdout)
        command_uuid = match.group(0) if match else None
        if not command_uuid:
            return jsonify({"error": "No command_uuid found from shell!"}), 500
    except Exception as e:
        return jsonify({"error": f"Failed to trigger DeviceInformation: {e}"}), 500

    block = universal_webhook_poll(command_uuid, "uuid", initial_sleep=3)
    info = extract_device_info(block) if block else {}
    if not info:
        return jsonify({"error": "Device info not found"}), 404
    return jsonify(info)

@app.route('/api/os-updates', methods=['POST'])
def os_updates():
    udid = request.json.get('udid')
    if not udid:
        return jsonify({"error": "Missing UDID"}), 400
    try:
        result = subprocess.run(
            ['/opt/nanohub/tools/api/commands/available_os_updates', udid],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        match = re.search(r'[a-f0-9\-]{36}', result.stdout)
        command_uuid = match.group(0) if match else None
        if not command_uuid:
            return jsonify({"error": "No command_uuid found from shell!"}), 500
    except Exception as e:
        return jsonify({"error": f"Failed to trigger OS updates: {e}"}), 500

    block = universal_webhook_poll(command_uuid, "uuid", initial_sleep=5)
    updates = extract_os_updates(block) if block else []
    if updates:
        return jsonify(updates)
    else:
        return jsonify({"error": "No OS update info found"}), 404

@app.route('/api/installed-apps', methods=['POST'])
def installed_apps():
    udid = request.json.get('udid')
    if not udid:
        return jsonify({"error": "Missing UDID"}), 400
    try:
        result = subprocess.run(
            ['/opt/nanohub/tools/api/commands/installed_application_list', udid],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        match = re.search(r'[a-f0-9\-]{36}', result.stdout)
        command_uuid = match.group(0) if match else None
        if not command_uuid:
            return jsonify({"error": "No command_uuid found from shell!"}), 500
    except Exception as e:
        return jsonify({"error": f"Failed to trigger Installed Apps List: {e}"}), 500

    block = universal_webhook_poll(command_uuid, "uuid", initial_sleep=5)
    apps = extract_installed_apps(block) if block else []
    if apps:
        return jsonify(apps)
    else:
        return jsonify({"error": "No Installed Applications info found"}), 404


@app.route('/api/profile-list', methods=['POST'])
def profile_list():
    udid = request.json.get('udid')
    if not udid:
        return jsonify({"error": "Missing UDID"}), 400
    try:
        result = subprocess.run(
            ['/opt/nanohub/tools/api/commands/profile_list', udid],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        match = re.search(r'[a-f0-9\-]{36}', result.stdout)
        command_uuid = match.group(0) if match else None
        if not command_uuid:
            return jsonify({"error": "No command_uuid found from shell!"}), 500
    except Exception as e:
        return jsonify({"error": f"Failed to trigger Profile List: {e}"}), 500

    block = universal_webhook_poll(command_uuid, "uuid", initial_sleep=5)
    profiles = extract_profile_list(block) if block else []
    if profiles:
        return jsonify(profiles)
    else:
        return jsonify({"error": "No Profile List info found"}), 404

@app.route('/api/wake-device', methods=['POST'])
def wake_device():
    udid = request.json.get('udid')
    if not udid:
        return jsonify({"error": "Missing UDID"}), 400

    # Calculate wake time (30 seconds from now)
    import datetime
    wake_time = datetime.datetime.now() + datetime.timedelta(seconds=30)
    wake_cmd = wake_time.strftime('%m/%d/%y %H:%M:%S')

    try:
        # Call send_command script
        result = subprocess.run(
            ['/opt/nanohub/tools/api/commands/send_command', udid, 'shell', f"pmset schedule wake '{wake_cmd}'"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        # Poll for result (5s initial wait, then poll every 2s up to 20s total)
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
    """Get comprehensive system report for a device"""
    data = request.json
    field = data.get('field', 'hostname')
    value = data.get('value', '')

    if not value:
        return jsonify({"error": "Missing search value"}), 400

    # Search for device
    device = universal_device_search("json", field, value)
    if not device:
        return jsonify({"error": "Device not found"}), 404

    udid = device.get("uuid")

    # Get basic device info from database
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
            "last_seen": device.get("last_seen", "N/A")
        }
    }

    # Get enrollment info from database
    sql = f"""
    SELECT
        type,
        enabled,
        last_seen_at,
        created_at,
        token_update_tally
    FROM enrollments
    WHERE device_id = '{udid}'
    ORDER BY last_seen_at DESC
    LIMIT 1
    """

    try:
        cmd = [
            'mysql',
            '-h', DB_CONFIG['host'],
            '-u', DB_CONFIG['user'],
            f'-p{DB_CONFIG["password"]}',
            DB_CONFIG['database'],
            '-sN',
            '-e', sql
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.stdout.strip():
            parts = result.stdout.strip().split('\t')
            if len(parts) >= 5:
                report["enrollment_info"] = {
                    "type": parts[0],
                    "enabled": "Yes" if parts[1] == '1' else "No",
                    "last_seen": parts[2],
                    "enrolled_at": parts[3],
                    "token_updates": parts[4]
                }
    except Exception:
        pass

    # Get command statistics from database
    sql_commands = f"""
    SELECT
        COUNT(*) as total_commands,
        SUM(CASE WHEN cr.status = 'Acknowledged' THEN 1 ELSE 0 END) as acknowledged,
        SUM(CASE WHEN cr.status = 'Error' THEN 1 ELSE 0 END) as errors,
        SUM(CASE WHEN cr.status = 'NotNow' THEN 1 ELSE 0 END) as not_now,
        MAX(cr.created_at) as last_command
    FROM command_results cr
    WHERE cr.id = '{udid}'
    """

    try:
        cmd = [
            'mysql',
            '-h', DB_CONFIG['host'],
            '-u', DB_CONFIG['user'],
            f'-p{DB_CONFIG["password"]}',
            DB_CONFIG['database'],
            '-sN',
            '-e', sql_commands
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.stdout.strip():
            parts = result.stdout.strip().split('\t')
            if len(parts) >= 5:
                report["command_statistics"] = {
                    "total_commands": parts[0],
                    "acknowledged": parts[1],
                    "errors": parts[2],
                    "not_now": parts[3],
                    "last_command": parts[4] if parts[4] != 'NULL' else 'N/A'
                }
    except Exception:
        pass

    # Get recent command types
    sql_recent = f"""
    SELECT
        c.request_type,
        COUNT(*) as count,
        MAX(cr.created_at) as last_used
    FROM commands c
    JOIN command_results cr ON c.command_uuid = cr.command_uuid
    WHERE cr.id = '{udid}'
    GROUP BY c.request_type
    ORDER BY last_used DESC
    LIMIT 10
    """

    try:
        cmd = [
            'mysql',
            '-h', DB_CONFIG['host'],
            '-u', DB_CONFIG['user'],
            f'-p{DB_CONFIG["password"]}',
            DB_CONFIG['database'],
            '-sN',
            '-e', sql_recent
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.stdout.strip():
            recent_commands = []
            for line in result.stdout.strip().split('\n'):
                parts = line.split('\t')
                if len(parts) >= 3:
                    recent_commands.append({
                        "command": parts[0],
                        "count": parts[1],
                        "last_used": parts[2]
                    })
            report["recent_commands"] = recent_commands
    except Exception:
        pass

def extract_system_report(block):
    """Extract extended device information for system report"""
    info = {}
    for l in block:
        row = l.strip()
        # Basic Info
        if "DeviceName:" in row:
            info["device_name"] = row.split("DeviceName:",1)[1].strip()
        if "OSVersion:" in row:
            info["os_version"] = row.split("OSVersion:",1)[1].strip()
        if "BuildVersion:" in row:
            info["build_version"] = row.split("BuildVersion:",1)[1].strip()
        if "ModelName:" in row:
            info["model_name"] = row.split("ModelName:",1)[1].strip()
        if "Model:" in row and "ModelName:" not in row:
            info["model"] = row.split("Model:",1)[1].strip()
        if "ProductName:" in row:
            info["product_name"] = row.split("ProductName:",1)[1].strip()
        if "SerialNumber:" in row:
            info["serial_number"] = row.split("SerialNumber:",1)[1].strip()

        # Storage
        if "DeviceCapacity:" in row:
            capacity_bytes = row.split("DeviceCapacity:",1)[1].strip()
            try:
                capacity_gb = float(capacity_bytes) / (1024**3)
                info["device_capacity"] = f"{capacity_gb:.2f} GB"
            except:
                info["device_capacity"] = capacity_bytes
        if "AvailableDeviceCapacity:" in row:
            available_bytes = row.split("AvailableDeviceCapacity:",1)[1].strip()
            try:
                available_gb = float(available_bytes) / (1024**3)
                info["available_capacity"] = f"{available_gb:.2f} GB"
            except:
                info["available_capacity"] = available_bytes

        # Battery
        if "BatteryLevel:" in row:
            battery = row.split("BatteryLevel:",1)[1].strip()
            try:
                battery_pct = float(battery) * 100
                info["battery_level"] = f"{battery_pct:.0f}%"
            except:
                info["battery_level"] = battery

        # Network
        if "WiFiMAC:" in row:
            info["wifi_mac"] = row.split("WiFiMAC:",1)[1].strip()
        if "BluetoothMAC:" in row:
            info["bluetooth_mac"] = row.split("BluetoothMAC:",1)[1].strip()
        if "EthernetMAC:" in row:
            info["ethernet_mac"] = row.split("EthernetMAC:",1)[1].strip()
        if "LocalHostName:" in row:
            info["local_hostname"] = row.split("LocalHostName:",1)[1].strip()
        if "HostName:" in row and "LocalHostName:" not in row:
            info["hostname"] = row.split("HostName:",1)[1].strip()

        # Cellular
        if "CellularTechnology:" in row:
            info["cellular_technology"] = row.split("CellularTechnology:",1)[1].strip()
        if "IMEI:" in row:
            info["imei"] = row.split("IMEI:",1)[1].strip()
        if "MEID:" in row:
            info["meid"] = row.split("MEID:",1)[1].strip()
        if "ModemFirmwareVersion:" in row:
            info["modem_firmware"] = row.split("ModemFirmwareVersion:",1)[1].strip()

        # Security & Management
        if "IsSupervised:" in row:
            info["is_supervised"] = row.split("IsSupervised:",1)[1].strip()
        if "SystemIntegrityProtectionEnabled:" in row:
            info["sip_enabled"] = row.split("SystemIntegrityProtectionEnabled:",1)[1].strip()
        if "IsActivationLockEnabled:" in row:
            info["activation_lock"] = row.split("IsActivationLockEnabled:",1)[1].strip()
        if "IsDeviceLocatorServiceEnabled:" in row:
            info["find_my_enabled"] = row.split("IsDeviceLocatorServiceEnabled:",1)[1].strip()
        if "IsCloudBackupEnabled:" in row:
            info["cloud_backup"] = row.split("IsCloudBackupEnabled:",1)[1].strip()
        if "IsMDMLostModeEnabled:" in row:
            info["mdm_lost_mode"] = row.split("IsMDMLostModeEnabled:",1)[1].strip()
        if "IsDoNotDisturbInEffect:" in row:
            info["dnd_enabled"] = row.split("IsDoNotDisturbInEffect:",1)[1].strip()

        if "Status:" in row:
            info["status"] = row.split("Status:",1)[1].strip()

        # Timestamp
        if block and len(block) > 0:
            parts = block[0].split(' [', 1)[0].strip()
            info["checkin_time"] = parts

    return info

@app.route('/api/device-system-report-live', methods=['POST'])
def device_system_report_live():
    """Get live system report with extended device information"""
    data = request.json
    field = data.get('field', 'hostname')
    value = data.get('value', '')

    if not value:
        return jsonify({"error": "Missing search value"}), 400

    # Search for device
    device = universal_device_search("json", field, value)
    if not device:
        return jsonify({"error": "Device not found"}), 404

    udid = device.get("uuid")

    # Trigger system report command
    try:
        result = subprocess.run(
            ['/opt/nanohub/tools/api/commands/system_report', udid],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        match = re.search(r'[a-f0-9\-]{36}', result.stdout)
        command_uuid = match.group(0) if match else None
        if not command_uuid:
            return jsonify({"error": "No command_uuid found from shell!"}), 500
    except Exception as e:
        return jsonify({"error": f"Failed to trigger system report: {e}"}), 500

    # Poll for result
    block = universal_webhook_poll(command_uuid, "uuid", initial_sleep=5, max_polls=15, poll_wait=1)
    system_info = extract_system_report(block) if block else {}

    if not system_info:
        return jsonify({"error": "No system report data received from device"}), 404

    # Combine with database info
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
            "last_seen": device.get("last_seen", "N/A")
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



def extract_security_info_detailed(block):
    """Extract detailed security information"""
    info = {}

    for line in block:
        row = line.strip()

        # FileVault / FDE
        if "FDE_Enabled:" in row:
            value = row.split("FDE_Enabled:", 1)[1].strip()
            info["filevault_enabled"] = value
        if "FDE_HasPersonalRecoveryKey:" in row:
            value = row.split("FDE_HasPersonalRecoveryKey:", 1)[1].strip()
            info["filevault_has_recovery_key"] = value
        if "FDE_HasInstitutionalRecoveryKey:" in row:
            value = row.split("FDE_HasInstitutionalRecoveryKey:", 1)[1].strip()
            info["filevault_has_institutional_key"] = value

        # Firewall - parse from FirewallSettings dictionary
        if "FirewallSettings:" in row:
            # Extract FirewallEnabled
            if "'FirewallEnabled': True" in row:
                info["firewall_enabled"] = "True"
            elif "'FirewallEnabled': False" in row:
                info["firewall_enabled"] = "False"
            # Extract BlockAllIncoming
            if "'BlockAllIncoming': True" in row:
                info["firewall_block_all"] = "True"
            elif "'BlockAllIncoming': False" in row:
                info["firewall_block_all"] = "False"
            # Extract StealthMode
            if "'StealthMode': True" in row:
                info["firewall_stealth"] = "True"
            elif "'StealthMode': False" in row:
                info["firewall_stealth"] = "False"

        # Remote Desktop
        if "RemoteDesktopEnabled:" in row:
            value = row.split("RemoteDesktopEnabled:", 1)[1].strip()
            info["remote_desktop_enabled"] = value

        # SIP
        if "SystemIntegrityProtectionEnabled:" in row and "SecurityInfo" in str(block):
            value = row.split("SystemIntegrityProtectionEnabled:", 1)[1].strip()
            info["sip_enabled"] = value

        # Secure Boot
        if "SecureBootLevel:" in row or "'SecureBootLevel':" in row:
            if "'full'" in row or "full" in row:
                info["secure_boot_level"] = "full"
            elif "'medium'" in row or "medium" in row:
                info["secure_boot_level"] = "medium"
            elif "'none'" in row or "none" in row:
                info["secure_boot_level"] = "none"

        # Bootstrap Token
        if "BootstrapTokenAllowedForAuthentication:" in row:
            value = row.split("BootstrapTokenAllowedForAuthentication:", 1)[1].strip()
            info["bootstrap_token_auth"] = value

        # Recovery Lock
        if "IsRecoveryLockEnabled:" in row:
            value = row.split("IsRecoveryLockEnabled:", 1)[1].strip()
            info["recovery_lock_enabled"] = value

    return info

def extract_device_info_detailed(block):
    """Extract detailed device information with proper parsing"""
    info = {}

    for line in block:
        row = line.strip()

        # Basic Info
        if "DeviceName:" in row:
            info["device_name"] = row.split("DeviceName:", 1)[1].strip()
        if "OSVersion:" in row:
            info["os_version"] = row.split("OSVersion:", 1)[1].strip()
        if "BuildVersion:" in row:
            info["build_version"] = row.split("BuildVersion:", 1)[1].strip()
        if "ModelName:" in row:
            info["model_name"] = row.split("ModelName:", 1)[1].strip()
        if "Model:" in row and "ModelName:" not in row:
            info["model"] = row.split("Model:", 1)[1].strip()
        if "ProductName:" in row:
            info["product_name"] = row.split("ProductName:", 1)[1].strip()
        if "SerialNumber:" in row:
            info["serial_number"] = row.split("SerialNumber:", 1)[1].strip()

        # Storage - parse as float GB values
        if "DeviceCapacity:" in row:
            try:
                capacity = float(row.split("DeviceCapacity:", 1)[1].strip())
                info["device_capacity"] = f"{capacity:.2f} GB"
            except:
                info["device_capacity"] = row.split("DeviceCapacity:", 1)[1].strip()

        if "AvailableDeviceCapacity:" in row:
            try:
                available = float(row.split("AvailableDeviceCapacity:", 1)[1].strip())
                info["available_capacity"] = f"{available:.2f} GB"
            except:
                info["available_capacity"] = row.split("AvailableDeviceCapacity:", 1)[1].strip()

        # Battery - parse as decimal (0.0-1.0)
        if "BatteryLevel:" in row:
            try:
                battery = float(row.split("BatteryLevel:", 1)[1].strip())
                battery_pct = battery * 100
                info["battery_level"] = f"{battery_pct:.0f}%"
            except:
                info["battery_level"] = row.split("BatteryLevel:", 1)[1].strip()

        # Network
        if "WiFiMAC:" in row:
            info["wifi_mac"] = row.split("WiFiMAC:", 1)[1].strip()
        if "BluetoothMAC:" in row:
            info["bluetooth_mac"] = row.split("BluetoothMAC:", 1)[1].strip()
        if "EthernetMAC:" in row:
            info["ethernet_mac"] = row.split("EthernetMAC:", 1)[1].strip()
        if "LocalHostName:" in row:
            info["local_hostname"] = row.split("LocalHostName:", 1)[1].strip()
        if "HostName:" in row and "LocalHostName:" not in row:
            info["hostname"] = row.split("HostName:", 1)[1].strip()

        # Cellular
        if "CellularTechnology:" in row:
            info["cellular_technology"] = row.split("CellularTechnology:", 1)[1].strip()
        if "IMEI:" in row:
            info["imei"] = row.split("IMEI:", 1)[1].strip()
        if "MEID:" in row:
            info["meid"] = row.split("MEID:", 1)[1].strip()
        if "ModemFirmwareVersion:" in row:
            info["modem_firmware"] = row.split("ModemFirmwareVersion:", 1)[1].strip()

        # Management
        if "IsSupervised:" in row:
            info["is_supervised"] = row.split("IsSupervised:", 1)[1].strip()
        if "IsActivationLockEnabled:" in row:
            info["activation_lock"] = row.split("IsActivationLockEnabled:", 1)[1].strip()
        if "IsDeviceLocatorServiceEnabled:" in row:
            info["find_my_enabled"] = row.split("IsDeviceLocatorServiceEnabled:", 1)[1].strip()
        if "IsCloudBackupEnabled:" in row:
            info["cloud_backup"] = row.split("IsCloudBackupEnabled:", 1)[1].strip()
        if "IsMDMLostModeEnabled:" in row:
            info["mdm_lost_mode"] = row.split("IsMDMLostModeEnabled:", 1)[1].strip()
        if "IsDoNotDisturbInEffect:" in row:
            info["dnd_enabled"] = row.split("IsDoNotDisturbInEffect:", 1)[1].strip()

    return info

@app.route('/api/device-system-report-full', methods=['POST'])
def device_system_report_full():
    """Get comprehensive system report with all available information (no shell commands)"""
    data = request.json
    field = data.get('field', 'hostname')
    value = data.get('value', '')

    if not value:
        return jsonify({"error": "Missing search value"}), 400

    # Search for device
    device = universal_device_search("json", field, value)
    if not device:
        return jsonify({"error": "Device not found"}), 404

    udid = device.get("uuid")

    # Trigger full system report command (DeviceInformation + SecurityInfo only)
    try:
        result = subprocess.run(
            ['/opt/nanohub/tools/api/commands/system_report_full', udid],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10
        )

        # Parse the two command UUIDs (device and security)
        output = result.stdout.strip()
        match = re.search(r'([a-f0-9\-]{36})\|([a-f0-9\-]{36})', output)
        if not match:
            return jsonify({"error": "Failed to get command UUIDs"}), 500

        cmd_uuid_device = match.group(1)
        cmd_uuid_security = match.group(2)

    except Exception as e:
        return jsonify({"error": f"Failed to trigger system report: {e}"}), 500

    # Poll for DeviceInformation result
    block_device = universal_webhook_poll(cmd_uuid_device, "uuid", initial_sleep=5, max_polls=12, poll_wait=2)
    device_info = extract_device_info_detailed(block_device) if block_device else {}

    # Poll for SecurityInfo result
    block_security = universal_webhook_poll(cmd_uuid_security, "uuid", initial_sleep=5, max_polls=10, poll_wait=2)
    security_info = extract_security_info_detailed(block_security) if block_security else {}

    # Build comprehensive report (without shell command data)
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
            "last_seen": device.get("last_seen", "N/A")
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

    # Add cellular info only if available
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
