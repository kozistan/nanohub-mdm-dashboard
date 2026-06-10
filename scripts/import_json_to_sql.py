#!/usr/bin/env python3
"""
Import devices.json to device_inventory SQL table

Usage:
    python3 /opt/nanohub/scripts/import_json_to_sql.py

This script reads /home/microm/nanohub/data/devices.json and imports
all devices into the device_inventory MySQL table.
"""

import json
import mysql.connector
import sys
import os

# Configuration
JSON_FILE = "/home/microm/nanohub/data/devices.json"
DB_CONFIG = {
    'host': os.environ.get('DB_HOST', '127.0.0.1'),
    'user': os.environ.get('DB_USER', 'nanohub'),
    'password': os.environ.get('DB_PASSWORD'),
    'database': os.environ.get('DB_NAME', 'nanohub')
}

def main():
    print("="*60)
    print("  NANOHUB - Import devices.json to MySQL")
    print("="*60)
    print(f"JSON file: {JSON_FILE}")
    print(f"Database: {DB_CONFIG['database']}")
    print("")

    # Check if JSON file exists
    if not os.path.exists(JSON_FILE):
        print(f"❌ Error: JSON file not found: {JSON_FILE}")
        sys.exit(1)

    # Read JSON file
    print("[1/4] Reading JSON file...")
    try:
        with open(JSON_FILE, 'r') as f:
            devices = json.load(f)
        print(f"✓ Loaded {len(devices)} devices from JSON")
    except Exception as e:
        print(f"❌ Error reading JSON: {e}")
        sys.exit(1)

    # Connect to MySQL
    print("\n[2/4] Connecting to MySQL...")
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()
        print("✓ Connected to MySQL")
    except Exception as e:
        print(f"❌ Error connecting to MySQL: {e}")
        sys.exit(1)

    # Import devices
    print("\n[3/4] Importing devices to device_inventory table...")
    success_count = 0
    error_count = 0
    update_count = 0

    sql = """
    INSERT INTO device_inventory (uuid, serial, os, hostname, manifest, account, dep)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
        serial = VALUES(serial),
        os = VALUES(os),
        hostname = VALUES(hostname),
        manifest = VALUES(manifest),
        account = VALUES(account),
        dep = VALUES(dep),
        updated_at = CURRENT_TIMESTAMP
    """

    for idx, device in enumerate(devices, 1):
        try:
            uuid = device.get('uuid', '')
            serial = device.get('serial', '')
            os = device.get('os', '')
            hostname = device.get('hostname', '')
            manifest = device.get('manifest', '')
            account = device.get('account', '')
            dep = device.get('dep', '')

            # Validate required fields
            if not uuid or not serial or not os or not hostname:
                print(f"  ⚠ Skipping device {idx}: missing required fields")
                error_count += 1
                continue

            cursor.execute(sql, (uuid, serial, os, hostname, manifest, account, dep))

            if cursor.rowcount == 1:
                success_count += 1
                print(f"  ✓ [{idx}/{len(devices)}] Inserted: {hostname} ({uuid})")
            elif cursor.rowcount == 2:
                update_count += 1
                print(f"  ↻ [{idx}/{len(devices)}] Updated: {hostname} ({uuid})")

        except Exception as e:
            error_count += 1
            print(f"  ❌ [{idx}/{len(devices)}] Error importing device: {e}")

    # Commit changes
    conn.commit()

    # Verify import
    print("\n[4/4] Verifying import...")
    cursor.execute("SELECT COUNT(*) FROM device_inventory")
    total_in_db = cursor.fetchone()[0]
    print(f"✓ Total devices in database: {total_in_db}")

    # Close connection
    cursor.close()
    conn.close()

    # Summary
    print("\n" + "="*60)
    print("  IMPORT SUMMARY")
    print("="*60)
    print(f"Total devices in JSON:    {len(devices)}")
    print(f"Successfully inserted:    {success_count}")
    print(f"Successfully updated:     {update_count}")
    print(f"Errors:                   {error_count}")
    print(f"Total in database:        {total_in_db}")
    print("="*60)

    if error_count > 0:
        print("⚠ Warning: Some devices were not imported!")
        sys.exit(1)
    else:
        print("✓ Import completed successfully!")
        sys.exit(0)

if __name__ == "__main__":
    main()
