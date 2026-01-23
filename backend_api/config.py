"""
NanoHUB Central Configuration
=============================
Centralized configuration for all backend_api modules.
Loads settings from environment variables with fallbacks.

Usage:
    from config import Config

    # Database
    conn = mysql.connector.connect(**Config.DB)

    # Paths
    script = os.path.join(Config.COMMANDS_DIR, 'install_profile')

    # API
    url = f"{Config.MDM_API_URL}/push/{udid}"
"""

import os


class Config:
    """Central configuration class with environment variable support."""

    # ==========================================================================
    # DATABASE CONFIGURATION
    # ==========================================================================

    DB_HOST = os.environ.get('NANOHUB_DB_HOST', '127.0.0.1')
    DB_PORT = int(os.environ.get('NANOHUB_DB_PORT', '3306'))
    DB_USER = os.environ.get('NANOHUB_DB_USER', 'nanohub')
    DB_PASSWORD = os.environ.get('NANOHUB_DB_PASSWORD', '')
    DB_NAME = os.environ.get('NANOHUB_DB_NAME', 'nanohub')

    # Connection dict for mysql.connector
    DB = {
        'host': DB_HOST,
        'port': DB_PORT,
        'user': DB_USER,
        'password': DB_PASSWORD,
        'database': DB_NAME,
        'charset': 'utf8mb4',
        'autocommit': False,
    }

    # Connection pool settings
    DB_POOL_NAME = 'nanohub_pool'
    DB_POOL_SIZE = 25  # Increased from 10 to handle concurrent operations
    DB_POOL_RESET_SESSION = True

    # ==========================================================================
    # MDM API CONFIGURATION
    # ==========================================================================

    MDM_API_URL = os.environ.get('NANOHUB_URL', 'http://localhost:9004')
    MDM_API_KEY = os.environ.get('NANOHUB_API_KEY', 'CHANGE_ME_API_KEY')
    MDM_API_USER = os.environ.get('NANOHUB_API_USER', 'nanohub')

    # Derived MDM endpoints
    MDM_ENQUEUE_URL = f"{MDM_API_URL}/api/v1/nanomdm/enqueue"
    MDM_PUSH_URL = f"{MDM_API_URL}/api/v1/nanomdm/push"

    # ==========================================================================
    # WEBHOOK CONFIGURATION
    # ==========================================================================

    WEBHOOK_URL = os.environ.get('NANOHUB_WEBHOOK_URL', 'http://localhost:5001/webhook')
    WEBHOOK_SECRET = os.environ.get('NANOHUB_WEBHOOK_SECRET', '')
    WEBHOOK_LOG_PATH = os.environ.get('WEBHOOK_LOG_PATH', '/var/log/nanohub/webhook.log')

    # Polling settings
    WEBHOOK_POLL_INITIAL_SLEEP = 3  # seconds before first poll
    WEBHOOK_POLL_MAX_ATTEMPTS = 20  # maximum poll attempts
    WEBHOOK_POLL_INTERVAL = 1  # seconds between polls
    WEBHOOK_POLL_WINDOW = 1000  # lines to read from end of log

    # ==========================================================================
    # PATHS
    # ==========================================================================

    # Base paths - /opt/nanohub is the production path
    NANOHUB_HOME = os.environ.get('NANOHUB_HOME', '/opt/nanohub')
    BACKEND_API_DIR = NANOHUB_HOME + '/backend_api'

    # Command scripts
    COMMANDS_DIR = os.environ.get('COMMANDS_DIR', NANOHUB_HOME + '/tools/api/commands')
    DDM_SCRIPTS_DIR = os.path.join(NANOHUB_HOME, 'ddm/scripts')
    TOOLS_DIR = os.path.join(NANOHUB_HOME, 'tools')

    # Profiles
    PROFILES_DIR = os.environ.get('PROFILES_DIR', os.path.join(NANOHUB_HOME, 'profiles'))
    WIREGUARD_DIR = os.path.join(PROFILES_DIR, 'wireguard_configs')

    # Certificates
    CERTS_DIR = os.environ.get('CERTS_DIR', os.path.join(NANOHUB_HOME, 'certs'))

    # Data
    DATA_DIR = os.path.join(NANOHUB_HOME, 'data')

    # Logs
    LOG_DIR = '/var/log/nanohub'
    AUDIT_LOG_PATH = os.path.join(LOG_DIR, 'admin_audit.log')

    # ==========================================================================
    # GOOGLE OAUTH CONFIGURATION
    # ==========================================================================

    GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID', '')
    GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', '')
    # Comma-separated list of allowed domains (e.g., 'slotegrator.com,company.com')
    GOOGLE_ALLOWED_DOMAINS = [d.strip() for d in os.environ.get('GOOGLE_ALLOWED_DOMAINS', '').split(',') if d.strip()]
    # Default role for Google SSO users (can be overridden in user_roles table)
    GOOGLE_DEFAULT_ROLE = os.environ.get('GOOGLE_DEFAULT_ROLE', 'operator')

    # ==========================================================================
    # LDAP CONFIGURATION
    # ==========================================================================

    LDAP_SERVERS = [
        {'host': os.environ.get('LDAP_HOST_1', ''), 'port': 389},
        {'host': os.environ.get('LDAP_HOST_2', ''), 'port': 389},
    ]
    LDAP_USE_SSL = False
    LDAP_USE_STARTTLS = True
    LDAP_BIND_DN = os.environ.get('LDAP_BIND_DN', '')
    LDAP_BIND_PASSWORD = os.environ.get('LDAP_BIND_PASSWORD', '')
    LDAP_BASE_DN = os.environ.get('LDAP_BASE_DN', '')
    LDAP_TIMEOUT = 4

    # ==========================================================================
    # VPP / ABM CONFIGURATION
    # ==========================================================================

    VPP_TOKEN = os.environ.get('VPP_TOKEN', '')
    VPP_API_URL = 'https://vpp.itunes.apple.com/mdm/v2'

    # Local app definition files
    APPS_IOS_JSON = os.path.join(DATA_DIR, 'apps_ios.json')
    APPS_MACOS_JSON = os.path.join(DATA_DIR, 'apps_macos.json')

    # ==========================================================================
    # COMMAND EXECUTION
    # ==========================================================================

    # Default timeout for command execution (seconds)
    COMMAND_TIMEOUT = 60
    COMMAND_TIMEOUT_BULK = 300

    # Delay between bulk operations (seconds)
    BULK_COMMAND_DELAY = 2

    # PATH for subprocess execution
    SUBPROCESS_PATH = '/usr/local/bin:/usr/bin:/bin:/usr/local/sbin:/usr/sbin:/sbin'

    # MySQL binary path
    MYSQL_BIN = '/usr/bin/mysql'

    # ==========================================================================
    # WEB CONFIGURATION
    # ==========================================================================

    FLASK_SECRET_KEY = os.environ.get('FLASK_SECRET_KEY', 'nanohub-secret-key-change-in-production-abc123xyz')
    SESSION_LIFETIME_HOURS = 8

    # Static files
    STATIC_DIR = '/var/www/mdm-web/static'
    LOGO_DIR = os.path.join(STATIC_DIR, 'logos')
    ORIGINAL_INDEX_PATH = '/var/www/mdm-web/index.html'

    # Backup directory
    BACKUP_DIR = os.path.join(BACKEND_API_DIR, 'backups')

    # ==========================================================================
    # ADMIN PANEL SETTINGS
    # ==========================================================================

    # Thread pool for parallel operations
    THREAD_POOL_WORKERS = 10

    # Device status thresholds (minutes)
    DEVICE_STATUS_ONLINE_MINUTES = 15   # Last seen within X minutes = online
    DEVICE_STATUS_ACTIVE_MINUTES = 60   # Last seen within X minutes = active

    # Default values
    DEFAULT_HISTORY_RETENTION_DAYS = 90
    DEFAULT_COMMAND_HISTORY_LIMIT = 20
    DEVICE_QUERY_MAX_RETRIES = 3

    # ==========================================================================
    # ENVIRONMENT FILE (for dynamic config loading)
    # ==========================================================================

    WEB_ENVIRONMENT_FILE = os.path.join(NANOHUB_HOME, 'web_environment.sh')
    ENVIRONMENT_FILE = os.path.join(NANOHUB_HOME, 'environment.sh')

    # ==========================================================================
    # HELPER METHODS
    # ==========================================================================

    @classmethod
    def get_db_config(cls):
        """Return database configuration dict."""
        return cls.DB.copy()

    @classmethod
    def get_subprocess_env(cls):
        """Return environment dict for subprocess calls."""
        env = os.environ.copy()
        env['PATH'] = cls.SUBPROCESS_PATH + ':' + env.get('PATH', '')
        return env

    @classmethod
    def load_vpp_token(cls):
        """Load VPP token from environment.sh if not set."""
        if cls.VPP_TOKEN:
            return cls.VPP_TOKEN

        try:
            with open(cls.ENVIRONMENT_FILE, 'r') as f:
                for line in f:
                    if line.startswith('export VPP_TOKEN='):
                        token = line.split('=', 1)[1].strip().strip('"\'')
                        cls.VPP_TOKEN = token
                        return token
        except Exception:
            pass
        return None


# Backward compatibility - expose DB_CONFIG dict
DB_CONFIG = Config.DB
