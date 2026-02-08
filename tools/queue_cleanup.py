#!/usr/bin/env python3
"""
NanoHUB Queue Cleanup
=====================
Cleans up processed commands from NanoMDM tables.

Cleanup rules:
  enrollment_queue:
    - Acknowledged/Error/CommandFormatError: delete after 1 hour
    - NotNow: delete after 5 days (device won't process it anymore)
    - No response: delete after 14 days (device was offline too long)

  command_results:
    - All entries older than 30 days (results already captured in command_history)

  commands:
    - Orphaned entries older than 30 days (not referenced by active queue)

Run via cron:
    0 4 * * * /opt/nanohub/venv/bin/python /opt/nanohub/tools/queue_cleanup.py

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

# Retention periods
COMMAND_DATA_RETENTION_DAYS = 30
BATCH_SIZE = 5000


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
        cursor.execute("""
            SELECT COUNT(*) FROM enrollment_queue eq
            INNER JOIN command_results cr ON eq.command_uuid = cr.command_uuid
            WHERE cr.status IN ('Acknowledged', 'Error', 'CommandFormatError')
            AND cr.created_at < NOW() - INTERVAL 1 HOUR
        """)
        count = cursor.fetchone()[0]
        logger.info(f"[DRY-RUN] Would delete {count} Acknowledged/Error queue entries")
        return count
    else:
        cursor.execute(sql)
        count = cursor.rowcount
        logger.info(f"Deleted {count} Acknowledged/Error queue entries")
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
        logger.info(f"[DRY-RUN] Would delete {count} NotNow queue entries")
        return count
    else:
        cursor.execute(sql)
        count = cursor.rowcount
        logger.info(f"Deleted {count} NotNow queue entries")
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
        logger.info(f"[DRY-RUN] Would delete {count} no-response queue entries")
        return count
    else:
        cursor.execute(sql)
        count = cursor.rowcount
        logger.info(f"Deleted {count} no-response queue entries")
        return count


def cleanup_command_results(cursor, conn, dry_run=False):
    """Delete command_results older than retention period, in batches."""
    cursor.execute(f"""
        SELECT COUNT(*) FROM command_results
        WHERE created_at < NOW() - INTERVAL {COMMAND_DATA_RETENTION_DAYS} DAY
    """)
    total = cursor.fetchone()[0]

    if total == 0:
        logger.info("No old command_results to clean")
        return 0

    if dry_run:
        cursor.execute(f"""
            SELECT ROUND(SUM(LENGTH(result))/1024/1024, 1)
            FROM command_results
            WHERE created_at < NOW() - INTERVAL {COMMAND_DATA_RETENTION_DAYS} DAY
        """)
        size_mb = cursor.fetchone()[0] or 0
        logger.info(f"[DRY-RUN] Would delete {total} command_results ({size_mb} MB)")
        return total

    deleted = 0
    while True:
        cursor.execute(f"""
            DELETE FROM command_results
            WHERE created_at < NOW() - INTERVAL {COMMAND_DATA_RETENTION_DAYS} DAY
            LIMIT {BATCH_SIZE}
        """)
        batch = cursor.rowcount
        conn.commit()
        deleted += batch
        if batch > 0:
            logger.info(f"  command_results: deleted batch {batch} (total {deleted}/{total})")
        if batch < BATCH_SIZE:
            break

    logger.info(f"Deleted {deleted} command_results (>{COMMAND_DATA_RETENTION_DAYS}d)")
    return deleted


def cleanup_commands(cursor, conn, dry_run=False):
    """Delete orphaned commands older than retention period, in batches."""
    cursor.execute(f"""
        SELECT COUNT(*) FROM commands c
        WHERE c.created_at < NOW() - INTERVAL {COMMAND_DATA_RETENTION_DAYS} DAY
        AND c.command_uuid NOT IN (
            SELECT command_uuid FROM enrollment_queue WHERE active = 1
        )
    """)
    total = cursor.fetchone()[0]

    if total == 0:
        logger.info("No old commands to clean")
        return 0

    if dry_run:
        logger.info(f"[DRY-RUN] Would delete {total} commands")
        return total

    deleted = 0
    while True:
        cursor.execute(f"""
            DELETE FROM commands
            WHERE created_at < NOW() - INTERVAL {COMMAND_DATA_RETENTION_DAYS} DAY
            AND command_uuid NOT IN (
                SELECT command_uuid FROM enrollment_queue WHERE active = 1
            )
            LIMIT {BATCH_SIZE}
        """)
        batch = cursor.rowcount
        conn.commit()
        deleted += batch
        if batch > 0:
            logger.info(f"  commands: deleted batch {batch} (total {deleted}/{total})")
        if batch < BATCH_SIZE:
            break

    logger.info(f"Deleted {deleted} commands (>{COMMAND_DATA_RETENTION_DAYS}d)")
    return deleted


def main():
    parser = argparse.ArgumentParser(description='Cleanup NanoMDM queue and command data')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be deleted without actually deleting')
    args = parser.parse_args()

    start_time = datetime.now()

    logger.info("=" * 60)
    logger.info("NanoHUB Queue & Command Cleanup")
    if args.dry_run:
        logger.info("MODE: DRY-RUN (no changes will be made)")
    logger.info(f"Retention: queue (1h/5d/14d), command data ({COMMAND_DATA_RETENTION_DAYS}d)")
    logger.info("=" * 60)

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # --- Phase 1: Enrollment Queue ---
        logger.info("")
        logger.info("--- Phase 1: Enrollment Queue ---")
        stats_before = get_queue_stats(cursor)
        logger.info(f"Queue before: {stats_before[0]} total")
        logger.info(f"  Acknowledged: {stats_before[1]}, Error: {stats_before[2]}, "
                     f"NotNow: {stats_before[3]}, FormatError: {stats_before[4]}, "
                     f"No response: {stats_before[5]}")

        queue_deleted = 0
        queue_deleted += cleanup_acknowledged(cursor, args.dry_run)
        queue_deleted += cleanup_notnow(cursor, args.dry_run)
        queue_deleted += cleanup_no_response(cursor, args.dry_run)

        if not args.dry_run:
            conn.commit()
            stats_after = get_queue_stats(cursor)
            logger.info(f"Queue after: {stats_after[0]} total")

        # --- Phase 2: Command Results ---
        logger.info("")
        logger.info("--- Phase 2: Command Results ---")
        cursor.execute("SELECT COUNT(*) FROM command_results")
        cr_before = cursor.fetchone()[0]
        logger.info(f"command_results before: {cr_before}")

        cr_deleted = cleanup_command_results(cursor, conn, args.dry_run)

        if not args.dry_run:
            cursor.execute("SELECT COUNT(*) FROM command_results")
            cr_after = cursor.fetchone()[0]
            logger.info(f"command_results after: {cr_after}")

        # --- Phase 3: Commands ---
        logger.info("")
        logger.info("--- Phase 3: Commands ---")
        cursor.execute("SELECT COUNT(*) FROM commands")
        cmd_before = cursor.fetchone()[0]
        logger.info(f"commands before: {cmd_before}")

        cmd_deleted = cleanup_commands(cursor, conn, args.dry_run)

        if not args.dry_run:
            cursor.execute("SELECT COUNT(*) FROM commands")
            cmd_after = cursor.fetchone()[0]
            logger.info(f"commands after: {cmd_after}")

        # --- Summary ---
        total_deleted = queue_deleted + cr_deleted + cmd_deleted
        logger.info("")
        logger.info("=" * 60)
        elapsed = datetime.now() - start_time
        action = "Would delete" if args.dry_run else "Deleted"
        logger.info(f"{action}: queue={queue_deleted}, results={cr_deleted}, commands={cmd_deleted}")
        logger.info(f"Duration: {elapsed}")
        logger.info("=" * 60)

        cursor.close()
        conn.close()

    except Exception as e:
        logger.error(f"Cleanup failed: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
