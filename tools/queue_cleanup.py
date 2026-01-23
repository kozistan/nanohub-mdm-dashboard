#!/usr/bin/env python3
"""
NanoHUB Queue Cleanup
=====================
Cleans up processed commands from NanoMDM enrollment_queue.

Cleanup rules:
- Acknowledged/Error/CommandFormatError: delete after 1 hour
- NotNow: delete after 5 days (device won't process it anymore)
- No response: delete after 14 days (device was offline too long)

Run via cron:
    0 3 * * * /opt/nanohub/venv/bin/python /opt/nanohub/tools/queue_cleanup.py

Manual run:
    python queue_cleanup.py [--dry-run]
"""

import sys
import argparse
import logging
from datetime import datetime

# Add backend_api to path for imports
sys.path.insert(0, '/opt/nanohub/backend_api')

from config import Config

import mysql.connector

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('queue_cleanup')


def get_db_connection():
    """Get direct MySQL connection to NanoMDM database."""
    # Read password from environment file
    db_password = None
    try:
        with open('/opt/nanohub/environment.sh', 'r') as f:
            for line in f:
                if 'NANOHUB_DB_PASSWORD=' in line or 'DB_PASSWORD=' in line:
                    db_password = line.split('=', 1)[1].strip().strip('"\'')
                    break
    except:
        pass

    # Fallback to Config
    if not db_password:
        db_password = Config.DB.get('password', '')

    return mysql.connector.connect(
        host='127.0.0.1',
        user='nanohub',
        password=db_password,
        database='nanohub'
    )


def get_queue_stats(cursor):
    """Get current queue statistics."""
    cursor.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN cr.status = 'Acknowledged' THEN 1 ELSE 0 END) as acknowledged,
            SUM(CASE WHEN cr.status = 'Error' THEN 1 ELSE 0 END) as error,
            SUM(CASE WHEN cr.status = 'NotNow' THEN 1 ELSE 0 END) as notnow,
            SUM(CASE WHEN cr.status = 'CommandFormatError' THEN 1 ELSE 0 END) as format_error,
            SUM(CASE WHEN cr.command_uuid IS NULL THEN 1 ELSE 0 END) as no_response
        FROM enrollment_queue eq
        LEFT JOIN command_results cr ON eq.command_uuid = cr.command_uuid
        WHERE eq.active = 1
    """)
    return cursor.fetchone()


def cleanup_acknowledged(cursor, dry_run=False):
    """Delete Acknowledged/Error/CommandFormatError older than 1 hour."""
    sql = """
        DELETE eq FROM enrollment_queue eq
        INNER JOIN command_results cr ON eq.command_uuid = cr.command_uuid
        WHERE cr.status IN ('Acknowledged', 'Error', 'CommandFormatError')
        AND cr.created_at < NOW() - INTERVAL 1 HOUR
    """

    if dry_run:
        # Count instead of delete
        cursor.execute("""
            SELECT COUNT(*) FROM enrollment_queue eq
            INNER JOIN command_results cr ON eq.command_uuid = cr.command_uuid
            WHERE cr.status IN ('Acknowledged', 'Error', 'CommandFormatError')
            AND cr.created_at < NOW() - INTERVAL 1 HOUR
        """)
        count = cursor.fetchone()[0]
        logger.info(f"[DRY-RUN] Would delete {count} Acknowledged/Error commands")
        return count
    else:
        cursor.execute(sql)
        count = cursor.rowcount
        logger.info(f"Deleted {count} Acknowledged/Error commands")
        return count


def cleanup_notnow(cursor, dry_run=False):
    """Delete NotNow older than 5 days."""
    sql = """
        DELETE eq FROM enrollment_queue eq
        INNER JOIN command_results cr ON eq.command_uuid = cr.command_uuid
        WHERE cr.status = 'NotNow'
        AND cr.created_at < NOW() - INTERVAL 5 DAY
    """

    if dry_run:
        cursor.execute("""
            SELECT COUNT(*) FROM enrollment_queue eq
            INNER JOIN command_results cr ON eq.command_uuid = cr.command_uuid
            WHERE cr.status = 'NotNow'
            AND cr.created_at < NOW() - INTERVAL 5 DAY
        """)
        count = cursor.fetchone()[0]
        logger.info(f"[DRY-RUN] Would delete {count} NotNow commands")
        return count
    else:
        cursor.execute(sql)
        count = cursor.rowcount
        logger.info(f"Deleted {count} NotNow commands")
        return count


def cleanup_no_response(cursor, dry_run=False):
    """Delete commands without response older than 14 days."""
    sql = """
        DELETE eq FROM enrollment_queue eq
        LEFT JOIN command_results cr ON eq.command_uuid = cr.command_uuid
        WHERE cr.command_uuid IS NULL
        AND eq.created_at < NOW() - INTERVAL 14 DAY
    """

    if dry_run:
        cursor.execute("""
            SELECT COUNT(*) FROM enrollment_queue eq
            LEFT JOIN command_results cr ON eq.command_uuid = cr.command_uuid
            WHERE cr.command_uuid IS NULL
            AND eq.created_at < NOW() - INTERVAL 14 DAY
        """)
        count = cursor.fetchone()[0]
        logger.info(f"[DRY-RUN] Would delete {count} no-response commands")
        return count
    else:
        cursor.execute(sql)
        count = cursor.rowcount
        logger.info(f"Deleted {count} no-response commands")
        return count


def main():
    parser = argparse.ArgumentParser(description='Cleanup NanoMDM enrollment queue')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be deleted without actually deleting')
    args = parser.parse_args()

    start_time = datetime.now()

    logger.info("=" * 60)
    logger.info("NanoHUB Queue Cleanup")
    if args.dry_run:
        logger.info("MODE: DRY-RUN (no changes will be made)")
    logger.info("=" * 60)

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Get stats before
        stats_before = get_queue_stats(cursor)
        logger.info(f"Queue before: {stats_before[0]} total")
        logger.info(f"  - Acknowledged: {stats_before[1]}")
        logger.info(f"  - Error: {stats_before[2]}")
        logger.info(f"  - NotNow: {stats_before[3]}")
        logger.info(f"  - CommandFormatError: {stats_before[4]}")
        logger.info(f"  - No response: {stats_before[5]}")
        logger.info("")

        # Run cleanup
        total_deleted = 0
        total_deleted += cleanup_acknowledged(cursor, args.dry_run)
        total_deleted += cleanup_notnow(cursor, args.dry_run)
        total_deleted += cleanup_no_response(cursor, args.dry_run)

        if not args.dry_run:
            conn.commit()

            # Get stats after
            stats_after = get_queue_stats(cursor)
            logger.info("")
            logger.info(f"Queue after: {stats_after[0]} total")

        logger.info("")
        logger.info("=" * 60)
        elapsed = datetime.now() - start_time
        logger.info(f"{'Would delete' if args.dry_run else 'Deleted'}: {total_deleted} commands")
        logger.info(f"Duration: {elapsed}")
        logger.info("=" * 60)

        cursor.close()
        conn.close()

    except Exception as e:
        logger.error(f"Cleanup failed: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
