#!/usr/bin/env python3
from flask import Flask, request, jsonify
import subprocess, json, os, re, time

app = Flask(__name__)

DEVICES_JSON_PATH = "/path/to/devices.json"
WEBHOOK_LOG_PATH = "/path/to/webhook.log"

def run_command(command, args=None):
    cmd = [command] + (args or [])
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return result.stdout, result.stderr

def search_devices_json(field, value):
    with open(DEVICES_JSON_PATH, "r") as f:
        devices = json.load(f)
    value = value.lower()
    for dev in devices:
        if dev.get(field, "").lower() == value:
            return dev
    return None

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
    if source == "json":
        return search_devices_json(field, value)
    else:
        return None

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
    source = data.get('source', 'json')
    field = data.get('field', 'hostname')
    value = data.get('value', '')
    device = universal_device_search(source, field, value)
    if not device:
        return jsonify({"error": f"No device found for {field}={value}"}), 404
    return jsonify(device)

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
        result = subprocess.run(["/opt/nanohub/tools/api/commands/mdm_analyzer", uuid], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
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

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=9006)
