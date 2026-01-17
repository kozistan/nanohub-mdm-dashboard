#!/usr/bin/env python3
"""
NanoHUB Daily Inventory Update
==============================
Queries all devices for hardware, security, profiles, apps and caches in DB.

Run via cron:
    0 14 * * * /opt/nanohub/venv/bin/python /opt/nanohub/tools/inventory_update.py

Features:
    - Uses centralized config and db_utils
    - Parallel processing for faster execution
    - Configurable concurrency and delays
"""

import sys
import os
import time
import logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add backend_api to path for imports
sys.path.insert(0, '/opt/nanohub/backend_api')

from config import Config
from db_utils import db

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('inventory_update')

# Configuration
MAX_WORKERS = 5          # Parallel device processing (don't overwhelm MDM)
QUERY_DELAY = 0.3        # Delay between queries on same device (seconds)
DEVICE_DELAY = 0.5       # Delay between devices in same worker (seconds)
QUERY_TYPES = ['hardware', 'security', 'profiles', 'apps']


def get_all_devices():
    """Get all devices from device_inventory using db_utils."""
    try:
        devices = db.query_all(
            "SELECT uuid, hostname, serial, os FROM device_inventory ORDER BY hostname"
        )
        return devices
    except Exception as e:
        logger.error(f"Failed to get devices: {e}")
        return []


def update_single_device(device, query_func):
    """
    Update inventory for a single device.

    Args:
        device: Dict with uuid, hostname, serial, os
        query_func: Function to execute device query

    Returns:
        Dict with results for each query type
    """
    uuid_val = device['uuid']
    hostname = device.get('hostname', 'Unknown')

    results = {
        'uuid': uuid_val,
        'hostname': hostname,
        'queries': {}
    }

    for query_type in QUERY_TYPES:
        try:
            result = query_func(uuid_val, query_type)
            success = result.get('success', False)
            results['queries'][query_type] = success

            if success:
                logger.debug(f"  {hostname}: {query_type} OK")
            else:
                error = result.get('error', 'Unknown error')
                logger.debug(f"  {hostname}: {query_type} FAILED - {error}")

        except Exception as e:
            results['queries'][query_type] = False
            logger.warning(f"  {hostname}: {query_type} ERROR - {e}")

        # Small delay between queries to not overwhelm MDM
        time.sleep(QUERY_DELAY)

    # Delay before next device in this worker
    time.sleep(DEVICE_DELAY)

    return results


def main():
    start_time = datetime.now()

    logger.info("=" * 60)
    logger.info("NanoHUB Inventory Update Started")
    logger.info(f"Workers: {MAX_WORKERS}, Query types: {QUERY_TYPES}")
    logger.info("=" * 60)

    # Get devices
    devices = get_all_devices()
    total = len(devices)

    if total == 0:
        logger.warning("No devices found, exiting")
        return

    logger.info(f"Found {total} devices to update")

    # Import execute_device_query here to avoid circular imports
    # and to delay Flask-related initialization
    try:
        from nanohub_admin import execute_device_query
    except Exception as e:
        logger.error(f"Failed to import execute_device_query: {e}")
        logger.error("Make sure nanohub_admin.py is accessible")
        return

    # Statistics
    stats = {
        'success': 0,
        'partial': 0,
        'failed': 0,
        'queries': {t: {'success': 0, 'failed': 0} for t in QUERY_TYPES}
    }

    # Process devices in parallel
    completed = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Submit all tasks
        futures = {
            executor.submit(update_single_device, device, execute_device_query): device
            for device in devices
        }

        # Process completed tasks
        for future in as_completed(futures):
            device = futures[future]
            completed += 1

            try:
                result = future.result()
                hostname = result['hostname']
                queries = result['queries']

                # Count successes and failures
                successes = sum(1 for v in queries.values() if v)
                failures = len(queries) - successes

                # Update per-query stats
                for qt, success in queries.items():
                    if success:
                        stats['queries'][qt]['success'] += 1
                    else:
                        stats['queries'][qt]['failed'] += 1

                # Update device stats
                if failures == 0:
                    stats['success'] += 1
                    status = "OK"
                elif successes == 0:
                    stats['failed'] += 1
                    status = "FAILED"
                else:
                    stats['partial'] += 1
                    status = f"PARTIAL ({successes}/{len(queries)})"

                logger.info(f"[{completed}/{total}] {hostname}: {status}")

            except Exception as e:
                stats['failed'] += 1
                logger.error(f"[{completed}/{total}] {device.get('hostname', '?')}: ERROR - {e}")

    # Summary
    elapsed = datetime.now() - start_time

    logger.info("")
    logger.info("=" * 60)
    logger.info("INVENTORY UPDATE COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Duration: {elapsed}")
    logger.info(f"Devices: {stats['success']} OK, {stats['partial']} partial, {stats['failed']} failed")
    logger.info("")
    logger.info("Per-query statistics:")
    for qt in QUERY_TYPES:
        ok = stats['queries'][qt]['success']
        fail = stats['queries'][qt]['failed']
        pct = (ok / total * 100) if total > 0 else 0
        logger.info(f"  {qt:12}: {ok:3} OK, {fail:3} failed ({pct:.1f}% success)")
    logger.info("=" * 60)

    # Exit code based on results
    if stats['failed'] > total * 0.5:  # More than 50% failed
        sys.exit(1)
    sys.exit(0)


if __name__ == '__main__':
    main()
