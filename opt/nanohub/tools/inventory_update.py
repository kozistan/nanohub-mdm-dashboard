#!/usr/bin/env python3
"""
NanoHUB Daily Inventory Update
Queries all devices for hardware, security, profiles, apps and caches in DB.
Run via cron: 0 6 * * * /opt/nanohub/venv/bin/python /opt/nanohub/tools/inventory_update.py
"""

import sys
import os
import time
import json
import logging
from datetime import datetime

# Add backend_api to path
sys.path.insert(0, '/opt/nanohub/backend_api')

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# DB Config
DB_CONFIG = {
    'host': '127.0.0.1',
    'user': 'nanohub',
    'password': 'YOUR_DATABASE_PASSWORD',
    'database': 'nanohub'
}


def get_all_devices():
    """Get all devices from device_inventory"""
    import mysql.connector

    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT uuid, hostname, serial, os FROM device_inventory ORDER BY hostname")
        devices = cursor.fetchall()
        cursor.close()
        conn.close()
        return devices
    except Exception as e:
        logger.error(f"Failed to get devices: {e}")
        return []


def update_device_inventory(uuid_val, query_type):
    """Execute MDM query and save to device_details"""
    # Import from nanohub_admin
    from nanohub_admin import execute_device_query

    result = execute_device_query(uuid_val, query_type)
    return result.get('success', False)


def main():
    start_time = datetime.now()
    logger.info("=" * 60)
    logger.info("NanoHUB Inventory Update Started")
    logger.info("=" * 60)

    devices = get_all_devices()
    total = len(devices)
    logger.info(f"Found {total} devices to update")

    if total == 0:
        logger.warning("No devices found, exiting")
        return

    query_types = ['hardware', 'security', 'profiles', 'apps']

    stats = {
        'success': 0,
        'failed': 0,
        'queries': {t: {'success': 0, 'failed': 0} for t in query_types}
    }

    for i, device in enumerate(devices, 1):
        uuid = device['uuid']
        hostname = device.get('hostname', 'Unknown')

        logger.info(f"[{i}/{total}] Processing {hostname} ({uuid[:8]}...)")

        device_success = True
        for query_type in query_types:
            success = update_device_inventory(uuid, query_type)
            if success:
                stats['queries'][query_type]['success'] += 1
                logger.info(f"  {query_type}: OK")
            else:
                stats['queries'][query_type]['failed'] += 1
                device_success = False
                logger.warning(f"  {query_type}: FAILED")

            # Small delay between queries to not overwhelm MDM
            time.sleep(0.5)

        if device_success:
            stats['success'] += 1
        else:
            stats['failed'] += 1

        # Delay between devices
        if i < total:
            time.sleep(2)

    # Summary
    elapsed = datetime.now() - start_time
    logger.info("=" * 60)
    logger.info("Inventory Update Complete")
    logger.info(f"Duration: {elapsed}")
    logger.info(f"Devices: {stats['success']} success, {stats['failed']} failed")
    for qt in query_types:
        logger.info(f"  {qt}: {stats['queries'][qt]['success']} OK, {stats['queries'][qt]['failed']} failed")
    logger.info("=" * 60)


if __name__ == '__main__':
    main()
