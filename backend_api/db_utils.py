"""
NanoHUB Database Utilities
==========================
Centralized database access with connection pooling and prepared statements.
Prevents SQL injection by using parameterized queries.

Usage:
    from db_utils import db

    # Single row
    device = db.query_one("SELECT * FROM device_inventory WHERE uuid = %s", (uuid,))

    # Multiple rows
    devices = db.query_all("SELECT * FROM device_inventory WHERE os = %s", ('macos',))

    # Execute (INSERT/UPDATE/DELETE)
    db.execute("UPDATE device_inventory SET hostname = %s WHERE uuid = %s", (hostname, uuid))

    # With transaction
    with db.transaction() as cursor:
        cursor.execute("INSERT INTO ...", (...))
        cursor.execute("UPDATE ...", (...))
"""

import logging
import mysql.connector
from mysql.connector import pooling, Error as MySQLError
from contextlib import contextmanager
from typing import Optional, List, Dict, Any, Tuple, Union

from config import Config

logger = logging.getLogger('nanohub_db')


class DatabaseManager:
    """Database manager with connection pooling and helper methods."""

    def __init__(self):
        self._pool: Optional[pooling.MySQLConnectionPool] = None
        self._init_pool()

    def _init_pool(self):
        """Initialize connection pool."""
        try:
            pool_config = Config.get_db_config()
            pool_config['pool_name'] = Config.DB_POOL_NAME
            pool_config['pool_size'] = Config.DB_POOL_SIZE
            pool_config['pool_reset_session'] = Config.DB_POOL_RESET_SESSION

            self._pool = pooling.MySQLConnectionPool(**pool_config)
            logger.info(f"Database pool '{Config.DB_POOL_NAME}' initialized with {Config.DB_POOL_SIZE} connections")
        except MySQLError as e:
            logger.error(f"Failed to initialize database pool: {e}")
            self._pool = None

    def _get_connection(self) -> mysql.connector.MySQLConnection:
        """Get connection from pool or create new one."""
        if self._pool:
            try:
                return self._pool.get_connection()
            except MySQLError as e:
                logger.warning(f"Pool connection failed, creating direct connection: {e}")

        # Fallback to direct connection
        return mysql.connector.connect(**Config.get_db_config())

    @contextmanager
    def connection(self):
        """Context manager for database connection."""
        conn = None
        try:
            conn = self._get_connection()
            yield conn
        finally:
            if conn and conn.is_connected():
                conn.close()

    @contextmanager
    def cursor(self, dictionary: bool = True):
        """Context manager for cursor with auto-close."""
        with self.connection() as conn:
            cursor = conn.cursor(dictionary=dictionary)
            try:
                yield cursor
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                cursor.close()

    @contextmanager
    def transaction(self):
        """Context manager for transaction with commit/rollback."""
        with self.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            try:
                yield cursor
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                cursor.close()

    def query_one(self, sql: str, params: Tuple = None) -> Optional[Dict[str, Any]]:
        """
        Execute query and return single row as dict.

        Args:
            sql: SQL query with %s placeholders
            params: Tuple of parameters

        Returns:
            Dict with column names as keys, or None if no result
        """
        with self.cursor() as cursor:
            cursor.execute(sql, params or ())
            return cursor.fetchone()

    def query_all(self, sql: str, params: Tuple = None) -> List[Dict[str, Any]]:
        """
        Execute query and return all rows as list of dicts.

        Args:
            sql: SQL query with %s placeholders
            params: Tuple of parameters

        Returns:
            List of dicts, empty list if no results
        """
        with self.cursor() as cursor:
            cursor.execute(sql, params or ())
            return cursor.fetchall() or []

    def query_value(self, sql: str, params: Tuple = None) -> Any:
        """
        Execute query and return single value.

        Args:
            sql: SQL query with %s placeholders
            params: Tuple of parameters

        Returns:
            Single value or None
        """
        with self.cursor(dictionary=False) as cursor:
            cursor.execute(sql, params or ())
            row = cursor.fetchone()
            return row[0] if row else None

    def execute(self, sql: str, params: Tuple = None) -> int:
        """
        Execute INSERT/UPDATE/DELETE and return affected rows.

        Args:
            sql: SQL statement with %s placeholders
            params: Tuple of parameters

        Returns:
            Number of affected rows
        """
        with self.cursor() as cursor:
            cursor.execute(sql, params or ())
            return cursor.rowcount

    def execute_many(self, sql: str, params_list: List[Tuple]) -> int:
        """
        Execute statement for multiple parameter sets.

        Args:
            sql: SQL statement with %s placeholders
            params_list: List of parameter tuples

        Returns:
            Total affected rows
        """
        with self.cursor() as cursor:
            cursor.executemany(sql, params_list)
            return cursor.rowcount

    def insert(self, table: str, data: Dict[str, Any]) -> int:
        """
        Insert row into table.

        Args:
            table: Table name
            data: Dict of column: value pairs

        Returns:
            Last insert ID
        """
        columns = ', '.join(data.keys())
        placeholders = ', '.join(['%s'] * len(data))
        sql = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"

        with self.cursor() as cursor:
            cursor.execute(sql, tuple(data.values()))
            return cursor.lastrowid

    def update(self, table: str, data: Dict[str, Any], where: str, where_params: Tuple) -> int:
        """
        Update rows in table.

        Args:
            table: Table name
            data: Dict of column: value pairs to update
            where: WHERE clause (e.g., "uuid = %s")
            where_params: Parameters for WHERE clause

        Returns:
            Number of affected rows
        """
        set_clause = ', '.join([f"{k} = %s" for k in data.keys()])
        sql = f"UPDATE {table} SET {set_clause} WHERE {where}"
        params = tuple(data.values()) + where_params

        with self.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.rowcount

    def delete(self, table: str, where: str, where_params: Tuple) -> int:
        """
        Delete rows from table.

        Args:
            table: Table name
            where: WHERE clause (e.g., "uuid = %s")
            where_params: Parameters for WHERE clause

        Returns:
            Number of affected rows
        """
        sql = f"DELETE FROM {table} WHERE {where}"

        with self.cursor() as cursor:
            cursor.execute(sql, where_params)
            return cursor.rowcount

    def table_exists(self, table: str) -> bool:
        """Check if table exists."""
        sql = "SHOW TABLES LIKE %s"
        return self.query_value(sql, (table,)) is not None


# =============================================================================
# DEVICE-SPECIFIC HELPERS
# =============================================================================

class DeviceDB:
    """Device-specific database operations."""

    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def get_all(self, manifest_filter: str = None) -> List[Dict]:
        """Get all devices with status from enrollments."""
        sql = """
            SELECT
                di.uuid, di.serial, di.os, di.hostname, di.manifest,
                di.account, di.dep,
                e.max_last_seen as last_seen,
                CASE
                    WHEN e.max_last_seen IS NULL THEN 'offline'
                    WHEN TIMESTAMPDIFF(MINUTE, e.max_last_seen, NOW()) <= 15 THEN 'online'
                    WHEN TIMESTAMPDIFF(MINUTE, e.max_last_seen, NOW()) <= 60 THEN 'active'
                    ELSE 'offline'
                END as status
            FROM device_inventory di
            LEFT JOIN (
                SELECT device_id, MAX(last_seen_at) as max_last_seen
                FROM enrollments
                GROUP BY device_id
            ) e ON di.uuid = e.device_id
        """
        params = ()

        if manifest_filter:
            sql += " WHERE di.manifest LIKE %s"
            params = (manifest_filter,)

        sql += " ORDER BY di.hostname"

        return self.db.query_all(sql, params)

    def search(self, field: str, value: str, manifest_filter: str = None) -> List[Dict]:
        """Search devices by field with optional manifest filter."""
        # Whitelist allowed fields to prevent SQL injection
        allowed_fields = ['uuid', 'serial', 'hostname', 'os', 'manifest', 'account']
        if field not in allowed_fields:
            field = 'hostname'

        sql = f"""
            SELECT
                di.uuid, di.serial, di.os, di.hostname, di.manifest,
                di.account, di.dep,
                e.max_last_seen as last_seen,
                CASE
                    WHEN e.max_last_seen IS NULL THEN 'offline'
                    WHEN TIMESTAMPDIFF(MINUTE, e.max_last_seen, NOW()) <= 15 THEN 'online'
                    WHEN TIMESTAMPDIFF(MINUTE, e.max_last_seen, NOW()) <= 60 THEN 'active'
                    ELSE 'offline'
                END as status
            FROM device_inventory di
            LEFT JOIN (
                SELECT device_id, MAX(last_seen_at) as max_last_seen
                FROM enrollments
                GROUP BY device_id
            ) e ON di.uuid = e.device_id
            WHERE di.{field} LIKE %s
        """
        params = [f'%{value}%']

        if manifest_filter:
            sql += " AND di.manifest LIKE %s"
            params.append(manifest_filter)

        sql += " ORDER BY di.hostname"

        return self.db.query_all(sql, tuple(params))

    def get_by_uuid(self, uuid: str) -> Optional[Dict]:
        """Get single device by UUID."""
        sql = """
            SELECT
                di.uuid, di.serial, di.os, di.hostname, di.manifest,
                di.account, di.dep, di.created_at, di.updated_at,
                e.last_seen_at,
                CASE
                    WHEN e.last_seen_at IS NULL THEN 'offline'
                    WHEN TIMESTAMPDIFF(MINUTE, e.last_seen_at, NOW()) <= 15 THEN 'online'
                    WHEN TIMESTAMPDIFF(MINUTE, e.last_seen_at, NOW()) <= 60 THEN 'active'
                    ELSE 'offline'
                END as status
            FROM device_inventory di
            LEFT JOIN (
                SELECT device_id, MAX(last_seen_at) as last_seen_at
                FROM enrollments
                GROUP BY device_id
            ) e ON di.uuid = e.device_id
            WHERE di.uuid = %s
        """
        return self.db.query_one(sql, (uuid,))

    def get_hostname(self, uuid: str) -> Optional[str]:
        """Get hostname for device UUID."""
        return self.db.query_value(
            "SELECT hostname FROM device_inventory WHERE uuid = %s",
            (uuid,)
        )

    def get_manifest(self, uuid: str) -> Optional[str]:
        """Get manifest for device UUID."""
        return self.db.query_value(
            "SELECT manifest FROM device_inventory WHERE uuid = %s",
            (uuid,)
        )

    def add(self, uuid: str, serial: str, os: str, hostname: str,
            manifest: str = 'default', account: str = 'disabled', dep: str = 'enabled') -> bool:
        """Add new device to inventory."""
        try:
            self.db.insert('device_inventory', {
                'uuid': uuid,
                'serial': serial,
                'os': os,
                'hostname': hostname,
                'manifest': manifest,
                'account': account,
                'dep': dep
            })
            return True
        except MySQLError as e:
            logger.error(f"Failed to add device: {e}")
            return False

    def update(self, uuid: str, **fields) -> bool:
        """Update device fields."""
        if not fields:
            return False

        # Filter only allowed fields
        allowed = {'serial', 'os', 'hostname', 'manifest', 'account', 'dep'}
        update_data = {k: v for k, v in fields.items() if k in allowed and v is not None}

        if not update_data:
            return False

        try:
            affected = self.db.update('device_inventory', update_data, 'uuid = %s', (uuid,))
            return affected > 0
        except MySQLError as e:
            logger.error(f"Failed to update device: {e}")
            return False

    def delete(self, uuid: str) -> bool:
        """Delete device from inventory."""
        try:
            affected = self.db.delete('device_inventory', 'uuid = %s', (uuid,))
            return affected > 0
        except MySQLError as e:
            logger.error(f"Failed to delete device: {e}")
            return False

    def exists(self, uuid: str) -> bool:
        """Check if device exists."""
        count = self.db.query_value(
            "SELECT COUNT(*) FROM device_inventory WHERE uuid = %s",
            (uuid,)
        )
        return count > 0


# =============================================================================
# COMMAND HISTORY HELPERS
# =============================================================================

class CommandHistoryDB:
    """Command history database operations."""

    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def add(self, user: str, command_id: str, command_name: str,
            device_udid: str = None, device_serial: str = None, device_hostname: str = None,
            params: str = None, result_summary: str = None, success: bool = True,
            execution_time_ms: int = None) -> int:
        """Add command history entry."""
        return self.db.insert('command_history', {
            'user': user,
            'command_id': command_id,
            'command_name': command_name,
            'device_udid': device_udid,
            'device_serial': device_serial,
            'device_hostname': device_hostname,
            'params': params,
            'result_summary': result_summary[:2000] if result_summary else None,
            'success': 1 if success else 0,
            'execution_time_ms': execution_time_ms
        })

    def get_for_device(self, uuid: str, limit: int = 20) -> List[Dict]:
        """Get command history for device."""
        sql = """
            SELECT id, timestamp, user, command_id, command_name,
                   params, result_summary, success, execution_time_ms
            FROM command_history
            WHERE device_udid = %s
            ORDER BY timestamp DESC
            LIMIT %s
        """
        return self.db.query_all(sql, (uuid, limit))

    def get_recent(self, limit: int = 50) -> List[Dict]:
        """Get recent command history."""
        sql = """
            SELECT id, timestamp, user, command_id, command_name,
                   device_hostname, device_udid, success
            FROM command_history
            ORDER BY timestamp DESC
            LIMIT %s
        """
        return self.db.query_all(sql, (limit,))

    def cleanup(self, days: int = 90) -> int:
        """Delete history older than specified days."""
        return self.db.execute(
            "DELETE FROM command_history WHERE timestamp < DATE_SUB(NOW(), INTERVAL %s DAY)",
            (days,)
        )


# =============================================================================
# DEVICE DETAILS CACHE
# =============================================================================

class DeviceDetailsDB:
    """Device details cache (hardware, security, profiles, apps)."""

    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def save(self, uuid: str, query_type: str, data: str) -> bool:
        """Save device details to cache and invalidate in-memory cache."""
        column_map = {
            'hardware': 'hardware_data',
            'security': 'security_data',
            'profiles': 'profiles_data',
            'apps': 'apps_data'
        }

        if query_type not in column_map:
            return False

        data_column = column_map[query_type]
        timestamp_column = f"{query_type}_updated_at"

        sql = f"""
            INSERT INTO device_details (uuid, {data_column}, {timestamp_column})
            VALUES (%s, %s, NOW())
            ON DUPLICATE KEY UPDATE
                {data_column} = VALUES({data_column}),
                {timestamp_column} = NOW()
        """

        try:
            self.db.execute(sql, (uuid, data))

            # Invalidate in-memory cache for this device (lazy import to avoid circular)
            try:
                from cache_utils import device_cache
                device_cache.invalidate(uuid)
                device_cache.invalidate(f"reports:{uuid}")  # Also invalidate reports cache
            except ImportError:
                pass  # Cache module not available

            return True
        except MySQLError as e:
            logger.error(f"Failed to save device details: {e}")
            return False

    def get(self, uuid: str, query_type: str = None) -> Optional[Dict]:
        """Get cached device details."""
        import json

        row = self.db.query_one("""
            SELECT hardware_data, security_data, profiles_data, apps_data, ddm_data,
                   hardware_updated_at, security_updated_at, profiles_updated_at, apps_updated_at, ddm_updated_at
            FROM device_details WHERE uuid = %s
        """, (uuid,))

        if not row:
            return None

        def parse_json_field(value):
            """Parse JSON string to dict/list, return as-is if already parsed or on error."""
            if value is None:
                return None
            if isinstance(value, (dict, list)):
                return value
            if isinstance(value, str):
                try:
                    return json.loads(value)
                except (json.JSONDecodeError, TypeError):
                    return value
            return value

        if query_type:
            data_col = f"{query_type}_data"
            ts_col = f"{query_type}_updated_at"
            return {
                'data': parse_json_field(row.get(data_col)),
                'updated_at': str(row.get(ts_col)) if row.get(ts_col) else None
            }

        # Parse all JSON fields for full response
        result = {}
        for field in ['hardware_data', 'security_data', 'profiles_data', 'apps_data', 'ddm_data']:
            result[field] = parse_json_field(row.get(field))
        for ts_field in ['hardware_updated_at', 'security_updated_at', 'profiles_updated_at', 'apps_updated_at', 'ddm_updated_at']:
            result[ts_field] = str(row.get(ts_field)) if row.get(ts_field) else None

        return result


# =============================================================================
# REQUIRED PROFILES
# =============================================================================

class RequiredProfilesDB:
    """Helper class for required_profiles table operations."""

    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def get_for_manifest(self, manifest: str, os: str) -> List[Dict[str, Any]]:
        """Get required profiles for specific manifest and OS.
        Only returns non-optional profiles (is_optional=0) for compliance checking.
        Optional profiles (is_optional=1) are only used for new device installation.
        """
        rows = self.db.query_all("""
            SELECT id, profile_identifier, profile_name, match_pattern
            FROM required_profiles
            WHERE manifest = %s AND os = %s AND is_optional = 0
            ORDER BY profile_name
        """, (manifest, os.lower()))
        return rows or []

    def get_all(self) -> List[Dict[str, Any]]:
        """Get all required profiles."""
        rows = self.db.query_all("""
            SELECT id, manifest, os, profile_identifier, profile_name, match_pattern, created_at
            FROM required_profiles
            ORDER BY manifest, os, profile_name
        """)
        return rows or []

    def get_by_id(self, profile_id: int) -> Optional[Dict[str, Any]]:
        """Get a required profile by ID."""
        return self.db.query_one("""
            SELECT id, manifest, os, profile_identifier, profile_name, match_pattern, created_at
            FROM required_profiles
            WHERE id = %s
        """, (profile_id,))

    def get_grouped(self) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
        """Get required profiles grouped by manifest and os."""
        rows = self.get_all()
        result = {}
        for row in rows:
            manifest = row['manifest']
            os = row['os']
            if manifest not in result:
                result[manifest] = {}
            if os not in result[manifest]:
                result[manifest][os] = []
            result[manifest][os].append(row)
        return result

    def add(self, manifest: str, os: str, profile_identifier: str, profile_name: str, match_pattern: bool = False) -> bool:
        """Add a required profile."""
        try:
            self.db.execute("""
                INSERT INTO required_profiles (manifest, os, profile_identifier, profile_name, match_pattern)
                VALUES (%s, %s, %s, %s, %s)
            """, (manifest, os.lower(), profile_identifier, profile_name, match_pattern))
            return True
        except Exception as e:
            logger.error(f"Failed to add required profile: {e}")
            return False

    def remove(self, profile_id: int) -> bool:
        """Remove a required profile by ID."""
        try:
            self.db.execute("DELETE FROM required_profiles WHERE id = %s", (profile_id,))
            return True
        except Exception as e:
            logger.error(f"Failed to remove required profile: {e}")
            return False

    def check_device_profiles(self, manifest: str, os: str, installed_profiles: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Check installed profiles against required profiles.

        Args:
            manifest: Device manifest
            os: Device OS (ios/macos)
            installed_profiles: List of installed profiles with 'identifier' key

        Returns:
            Dict with required, installed, missing counts and missing_list
        """
        import fnmatch

        required = self.get_for_manifest(manifest, os)
        if not required:
            return {'required': 0, 'installed': 0, 'missing': 0, 'missing_list': [], 'complete': True}

        # Extract installed identifiers (handle both identifier and PayloadIdentifier keys)
        installed_ids = set()
        for p in installed_profiles:
            if isinstance(p, dict):
                # Try multiple possible keys for identifier
                ident = p.get('identifier') or p.get('PayloadIdentifier') or p.get('Identifier', '')
                if ident:
                    installed_ids.add(ident)

        # Check each required profile
        missing_list = []
        installed_count = 0

        for req in required:
            req_id = req['profile_identifier']
            req_name = req['profile_name']
            is_pattern = bool(req['match_pattern'])  # MySQL returns 0/1

            found = False
            if is_pattern:
                # Pattern matching (SQL LIKE style % -> fnmatch style *)
                pattern = req_id.replace('%', '*')
                for inst_id in installed_ids:
                    if fnmatch.fnmatch(inst_id, pattern):
                        found = True
                        break
            else:
                # Exact match
                found = req_id in installed_ids

            if found:
                installed_count += 1
            else:
                missing_list.append({'identifier': req_id, 'name': req_name})

        missing_count = len(missing_list)
        return {
            'required': len(required),
            'installed': installed_count,
            'missing': missing_count,
            'missing_list': missing_list,
            'complete': missing_count == 0
        }


# =============================================================================
# USER ROLES
# =============================================================================

class UserRolesDB:
    """Helper class for user_roles table operations.

    This provides database-stored user roles that can override LDAP-derived roles.
    Useful for:
    - Giving specific users different roles than their AD group membership
    - Creating local users with specific permissions
    - Temporarily elevating or restricting user access
    """

    # Available roles and their hierarchy
    ROLES = {
        'admin': {'level': 4, 'permissions': ['admin', 'operator', 'report', 'settings', 'users']},
        'bel-admin': {'level': 3, 'permissions': ['admin', 'operator', 'report', 'settings', 'users']},
        'operator': {'level': 2, 'permissions': ['operator', 'report', 'devices', 'profiles', 'apps']},
        'report': {'level': 1, 'permissions': ['report', 'view']},
    }

    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
        self._ensure_table()

    def _ensure_table(self):
        """Create user_roles table if it doesn't exist."""
        try:
            self.db.execute("""
                CREATE TABLE IF NOT EXISTS user_roles (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(100) NOT NULL UNIQUE,
                    role VARCHAR(50) NOT NULL DEFAULT 'report',
                    manifest_filter VARCHAR(100) DEFAULT NULL,
                    is_active TINYINT(1) DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    created_by VARCHAR(100) DEFAULT NULL,
                    notes TEXT DEFAULT NULL,
                    INDEX idx_username (username),
                    INDEX idx_role (role),
                    INDEX idx_active (is_active)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            logger.debug("user_roles table ensured")
        except Exception as e:
            logger.error(f"Failed to create user_roles table: {e}")

    def get_user_role(self, username: str) -> Optional[Dict[str, Any]]:
        """Get role override for a user from database.

        Returns None if no override exists (use LDAP-derived role).
        """
        return self.db.query_one("""
            SELECT id, username, role, manifest_filter, is_active, created_at, updated_at, created_by, notes
            FROM user_roles
            WHERE username = %s AND is_active = 1
        """, (username.lower(),))

    def get_all_users(self, include_inactive: bool = False) -> List[Dict[str, Any]]:
        """Get all user role overrides."""
        if include_inactive:
            return self.db.query_all("""
                SELECT id, username, role, manifest_filter, is_active, created_at, updated_at, created_by, notes
                FROM user_roles
                ORDER BY username
            """) or []
        else:
            return self.db.query_all("""
                SELECT id, username, role, manifest_filter, is_active, created_at, updated_at, created_by, notes
                FROM user_roles
                WHERE is_active = 1
                ORDER BY username
            """) or []

    def set_user_role(self, username: str, role: str, manifest_filter: str = None,
                      created_by: str = None, notes: str = None) -> bool:
        """Set or update role for a user.

        Args:
            username: The username (case-insensitive)
            role: One of: admin, bel-admin, operator, report
            manifest_filter: SQL LIKE pattern for manifest restriction (e.g., 'bel-%')
            created_by: Username of admin making the change
            notes: Optional notes about this role assignment

        Returns:
            True if successful, False otherwise
        """
        if role not in self.ROLES:
            logger.error(f"Invalid role: {role}. Must be one of: {list(self.ROLES.keys())}")
            return False

        try:
            self.db.execute("""
                INSERT INTO user_roles (username, role, manifest_filter, created_by, notes)
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    role = VALUES(role),
                    manifest_filter = VALUES(manifest_filter),
                    created_by = VALUES(created_by),
                    notes = VALUES(notes),
                    is_active = 1,
                    updated_at = CURRENT_TIMESTAMP
            """, (username.lower(), role, manifest_filter, created_by, notes))
            logger.info(f"User role set: {username} -> {role} (by {created_by})")
            return True
        except Exception as e:
            logger.error(f"Failed to set user role for {username}: {e}")
            return False

    def remove_user_role(self, username: str) -> bool:
        """Remove role override for a user (soft delete)."""
        try:
            self.db.execute("""
                UPDATE user_roles SET is_active = 0, updated_at = CURRENT_TIMESTAMP
                WHERE username = %s
            """, (username.lower(),))
            logger.info(f"User role removed: {username}")
            return True
        except Exception as e:
            logger.error(f"Failed to remove user role for {username}: {e}")
            return False

    def delete_user_role(self, username: str) -> bool:
        """Permanently delete role override for a user."""
        try:
            self.db.execute("DELETE FROM user_roles WHERE username = %s", (username.lower(),))
            logger.info(f"User role deleted: {username}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete user role for {username}: {e}")
            return False

    def get_permissions_for_role(self, role: str) -> List[str]:
        """Get list of permissions for a role."""
        return self.ROLES.get(role, {}).get('permissions', [])

    def check_role_level(self, user_role: str, required_role: str) -> bool:
        """Check if user_role has sufficient level for required_role."""
        user_level = self.ROLES.get(user_role, {}).get('level', 0)
        required_level = self.ROLES.get(required_role, {}).get('level', 0)
        return user_level >= required_level


# =============================================================================
# LOCAL USERS
# =============================================================================

class LocalUsersDB:
    """Database-backed local user management for fallback authentication."""

    SALT = 'nanohub-salt'

    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
        self._ensure_table()
        self._ensure_default_admin()

    def _ensure_table(self):
        """Create local_users table if it doesn't exist."""
        try:
            self.db.execute("""
                CREATE TABLE IF NOT EXISTS local_users (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(100) NOT NULL UNIQUE,
                    password_hash VARCHAR(64) NOT NULL,
                    display_name VARCHAR(200) DEFAULT NULL,
                    role VARCHAR(50) NOT NULL DEFAULT 'operator',
                    manifest_filter VARCHAR(100) DEFAULT NULL,
                    is_active TINYINT(1) DEFAULT 1,
                    must_change_password TINYINT(1) DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    created_by VARCHAR(100) DEFAULT NULL,
                    last_login TIMESTAMP NULL DEFAULT NULL,
                    notes TEXT DEFAULT NULL,
                    INDEX idx_username (username),
                    INDEX idx_active (is_active)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            logger.debug("local_users table ensured")
        except Exception as e:
            logger.error(f"Failed to create local_users table: {e}")

    def _ensure_default_admin(self):
        """Seed default admin user if no users exist."""
        try:
            existing = self.db.query_one(
                "SELECT id FROM local_users WHERE username = %s", ('admin',)
            )
            if not existing:
                self.db.execute("""
                    INSERT INTO local_users (username, password_hash, display_name, role, must_change_password, created_by)
                    VALUES (%s, %s, %s, %s, 1, %s)
                """, (
                    'admin',
                    self.compute_hash('admin', 'password'),
                    'Local Admin',
                    'admin',
                    'system'
                ))
                logger.info("Default admin local user created (admin/password)")
        except Exception as e:
            logger.error(f"Failed to ensure default admin: {e}")

    @staticmethod
    def compute_hash(username, password):
        """Compute SHA256 hash for authentication."""
        import hashlib
        return hashlib.sha256(f'{username}:{password}:{LocalUsersDB.SALT}'.encode()).hexdigest()

    def authenticate(self, username, password):
        """Authenticate local user. Returns user row dict or None."""
        if not username or not password:
            return None

        username = username.strip().lower()
        password_hash = self.compute_hash(username, password)

        try:
            row = self.db.query_one("""
                SELECT id, username, password_hash, display_name, role,
                       manifest_filter, is_active, must_change_password, last_login, notes
                FROM local_users
                WHERE username = %s AND is_active = 1
            """, (username,))

            if not row:
                return None

            if row['password_hash'] != password_hash:
                logger.warning(f"Invalid password for local user: {username}")
                return None

            # Update last_login
            self.db.execute(
                "UPDATE local_users SET last_login = NOW() WHERE username = %s",
                (username,)
            )

            logger.info(f"Local user {username} authenticated successfully")
            return row

        except Exception as e:
            logger.error(f"Local user authentication error: {e}")
            return None

    def get_user(self, username):
        """Get single user by username."""
        return self.db.query_one("""
            SELECT id, username, display_name, role, manifest_filter,
                   is_active, must_change_password, created_at, updated_at,
                   created_by, last_login, notes
            FROM local_users WHERE username = %s
        """, (username.lower(),))

    def get_all_users(self, include_inactive=False):
        """Get all local users."""
        if include_inactive:
            return self.db.query_all("""
                SELECT id, username, display_name, role, manifest_filter,
                       is_active, must_change_password, created_at, updated_at,
                       created_by, last_login, notes
                FROM local_users ORDER BY username
            """) or []
        else:
            return self.db.query_all("""
                SELECT id, username, display_name, role, manifest_filter,
                       is_active, must_change_password, created_at, updated_at,
                       created_by, last_login, notes
                FROM local_users WHERE is_active = 1 ORDER BY username
            """) or []

    def create_user(self, username, password, role='operator', display_name=None,
                    manifest_filter=None, must_change_password=True, created_by=None, notes=None):
        """Create a new local user."""
        username = username.strip().lower()
        password_hash = self.compute_hash(username, password)

        try:
            self.db.execute("""
                INSERT INTO local_users (username, password_hash, display_name, role,
                    manifest_filter, must_change_password, created_by, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (username, password_hash, display_name, role,
                  manifest_filter or None, 1 if must_change_password else 0,
                  created_by, notes or None))
            logger.info(f"Local user created: {username} (role: {role}, by: {created_by})")
            return True
        except Exception as e:
            logger.error(f"Failed to create local user {username}: {e}")
            return False

    def update_user(self, username, role=None, display_name=None,
                    manifest_filter=None, is_active=None, notes=None):
        """Update local user fields (not password)."""
        username = username.strip().lower()
        updates = {}
        if role is not None:
            updates['role'] = role
        if display_name is not None:
            updates['display_name'] = display_name
        if manifest_filter is not None:
            updates['manifest_filter'] = manifest_filter if manifest_filter else None
        if is_active is not None:
            updates['is_active'] = 1 if is_active else 0
        if notes is not None:
            updates['notes'] = notes if notes else None

        if not updates:
            return True

        try:
            self.db.update('local_users', updates, 'username = %s', (username,))
            logger.info(f"Local user updated: {username}")
            return True
        except Exception as e:
            logger.error(f"Failed to update local user {username}: {e}")
            return False

    def change_password(self, username, new_password):
        """Change password and clear must_change_password flag."""
        username = username.strip().lower()
        password_hash = self.compute_hash(username, new_password)

        try:
            self.db.execute("""
                UPDATE local_users SET password_hash = %s, must_change_password = 0
                WHERE username = %s
            """, (password_hash, username))
            logger.info(f"Password changed for local user: {username}")
            return True
        except Exception as e:
            logger.error(f"Failed to change password for {username}: {e}")
            return False

    def reset_password(self, username, new_password, force_change=True):
        """Admin password reset. Sets must_change_password flag."""
        username = username.strip().lower()
        password_hash = self.compute_hash(username, new_password)

        try:
            self.db.execute("""
                UPDATE local_users SET password_hash = %s, must_change_password = %s
                WHERE username = %s
            """, (password_hash, 1 if force_change else 0, username))
            logger.info(f"Password reset for local user: {username} (force_change={force_change})")
            return True
        except Exception as e:
            logger.error(f"Failed to reset password for {username}: {e}")
            return False

    def delete_user(self, username):
        """Delete a local user. Cannot delete the admin user."""
        username = username.strip().lower()
        if username == 'admin':
            logger.warning("Cannot delete the default admin user")
            return False

        try:
            self.db.execute("DELETE FROM local_users WHERE username = %s", (username,))
            logger.info(f"Local user deleted: {username}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete local user {username}: {e}")
            return False


# =============================================================================
# APP SETTINGS DATABASE
# =============================================================================

class AppSettingsDB:
    """Manager for application settings stored in database."""

    def __init__(self, db: DatabaseManager):
        self.db = db
        self._ensure_table()

    def _ensure_table(self):
        """Create app_settings table if it doesn't exist."""
        try:
            self.db.execute("""
                CREATE TABLE IF NOT EXISTS app_settings (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    setting_key VARCHAR(100) NOT NULL UNIQUE,
                    setting_value TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    updated_by VARCHAR(100) DEFAULT NULL,
                    INDEX idx_key (setting_key)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            logger.debug("app_settings table ensured")
        except Exception as e:
            logger.error(f"Failed to create app_settings table: {e}")

    def get(self, key: str, default: str = None) -> Optional[str]:
        """Get a setting value by key."""
        try:
            result = self.db.query_one(
                "SELECT setting_value FROM app_settings WHERE setting_key = %s",
                (key,)
            )
            if result:
                return result.get('setting_value', default)
            return default
        except Exception as e:
            logger.error(f"Failed to get setting {key}: {e}")
            return default

    def set(self, key: str, value: str, updated_by: str = None) -> bool:
        """Set a setting value."""
        try:
            self.db.execute("""
                INSERT INTO app_settings (setting_key, setting_value, updated_by)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    setting_value = VALUES(setting_value),
                    updated_by = VALUES(updated_by),
                    updated_at = CURRENT_TIMESTAMP
            """, (key, value, updated_by))
            return True
        except Exception as e:
            logger.error(f"Failed to set setting {key}: {e}")
            return False

    def get_all(self) -> Dict[str, str]:
        """Get all settings as a dictionary."""
        try:
            rows = self.db.query_all("SELECT setting_key, setting_value FROM app_settings")
            return {row['setting_key']: row['setting_value'] for row in rows} if rows else {}
        except Exception as e:
            logger.error(f"Failed to get all settings: {e}")
            return {}


# =============================================================================
# DDM COMPLIANCE
# =============================================================================

class DDMComplianceDB:
    """Helper class for DDM compliance checking."""

    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def get_required_set(self, manifest: str, os: str) -> Optional[Dict[str, Any]]:
        """Get required DDM set for a manifest+os combination."""
        if not manifest or not os:
            return None
        try:
            row = self.db.query_one("""
                SELECT r.id, r.manifest, r.os, r.set_id, s.name as set_name
                FROM ddm_required_sets r
                JOIN ddm_sets s ON r.set_id = s.id
                WHERE r.manifest = %s AND r.os = %s
            """, (manifest, os.lower()))
            return row
        except:
            return None

    def get_set_declarations(self, set_id: int) -> List[Dict[str, Any]]:
        """Get all declarations in a set."""
        try:
            rows = self.db.query_all("""
                SELECT d.id, d.identifier, d.type
                FROM ddm_declarations d
                JOIN ddm_set_declarations sd ON d.id = sd.declaration_id
                WHERE sd.set_id = %s
                ORDER BY d.identifier
            """, (set_id,))
            return rows or []
        except:
            return []

    def check_device_ddm(self, manifest: str, os: str, ddm_status: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Check DDM compliance for a device.

        Args:
            manifest: Device manifest
            os: Device OS (ios/macos)
            ddm_status: Optional DDM status from device_details (declarations list)

        Returns:
            Dict with required, active, valid counts and status
        """
        required_set = self.get_required_set(manifest, os)
        if not required_set:
            return {
                'required': 0,
                'active': 0,
                'valid': 0,
                'complete': True,
                'set_name': None,
                'missing_list': []
            }

        set_id = required_set['set_id']
        set_name = required_set['set_name']
        required_declarations = self.get_set_declarations(set_id)

        if not required_declarations:
            return {
                'required': 0,
                'active': 0,
                'valid': 0,
                'complete': True,
                'set_name': set_name,
                'missing_list': []
            }

        required_count = len(required_declarations)
        active_count = 0
        valid_count = 0
        missing_list = []

        # Check against device DDM status if provided
        if ddm_status and isinstance(ddm_status, list):
            status_map = {}
            for decl in ddm_status:
                if isinstance(decl, dict):
                    ident = decl.get('identifier', decl.get('Identifier', ''))
                    if ident:
                        status_map[ident] = {
                            'active': decl.get('active', decl.get('Active', False)),
                            'valid': decl.get('valid', decl.get('Valid', False))
                        }

            for req in required_declarations:
                req_id = req['identifier']
                if req_id in status_map:
                    status = status_map[req_id]
                    if status['active']:
                        active_count += 1
                    if status['valid']:
                        valid_count += 1
                    if not status['active'] or not status['valid']:
                        missing_list.append({'identifier': req_id, 'active': status['active'], 'valid': status['valid']})
                else:
                    missing_list.append({'identifier': req_id, 'active': False, 'valid': False})
        else:
            # No status data - all required declarations are "missing"
            for req in required_declarations:
                missing_list.append({'identifier': req['identifier'], 'active': False, 'valid': False})

        return {
            'required': required_count,
            'active': active_count,
            'valid': valid_count,
            'complete': valid_count == required_count,
            'set_name': set_name,
            'missing_list': missing_list
        }


# =============================================================================
# SINGLETON INSTANCES
# =============================================================================

# Global database manager instance
db = DatabaseManager()

# Helper instances
devices = DeviceDB(db)
command_history = CommandHistoryDB(db)
device_details = DeviceDetailsDB(db)
required_profiles = RequiredProfilesDB(db)
ddm_compliance = DDMComplianceDB(db)
user_roles = UserRolesDB(db)
local_users = LocalUsersDB(db)
app_settings = AppSettingsDB(db)
