"""
NanoHUB Authentication Module
Supports: LDAP/AD, Google OAuth SSO, Local fallback user
"""

import ldap3
from ldap3 import Server, Connection, ALL, SUBTREE
from ldap3.core.exceptions import LDAPException
from functools import wraps
from flask import session, redirect, url_for, request, render_template_string, flash
import logging
import hashlib
import os
import secrets

from config import Config
from db_utils import app_settings

# Google OAuth imports (optional - graceful fallback if not installed)
try:
    from authlib.integrations.flask_client import OAuth
    GOOGLE_OAUTH_AVAILABLE = True
except ImportError:
    GOOGLE_OAUTH_AVAILABLE = False
    OAuth = None

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('nanohub_ldap')

# Import database user roles (for overrides)
try:
    from db_utils import user_roles as db_user_roles
except ImportError:
    db_user_roles = None
    logger.warning("db_utils.user_roles not available, database role overrides disabled")

# =============================================================================
# LDAP KONFIGURACE - using Config class
# =============================================================================

LDAP_CONFIG = {
    'servers': Config.LDAP_SERVERS,
    'use_ssl': Config.LDAP_USE_SSL,
    'use_starttls': Config.LDAP_USE_STARTTLS,
    'bind_dn': Config.LDAP_BIND_DN,
    'bind_password': Config.LDAP_BIND_PASSWORD,
    'base_dn': Config.LDAP_BASE_DN,
    'user_search_filter': '(sAMAccountName={username})',
    'timeout': Config.LDAP_TIMEOUT,
}

# =============================================================================
# LOCAL FALLBACK USER (when AD is unavailable)
# =============================================================================

# Hash: sha256(username + password + salt)
# To generate: python3 -c "import hashlib; print(hashlib.sha256('username:PASSWORD:nanohub-salt'.encode()).hexdigest())"
# Set NANOHUB_LOCAL_ADMIN_HASH env var to enable local fallback login
LOCAL_USERS = {
    'hdadmin': {
        'password_hash': os.environ.get('NANOHUB_LOCAL_ADMIN_HASH',
                         '5a67173b0c77a27c82bc66aad91d84ab9d50710b6dc3dddc53a5f6841a047489'),
        'role': 'admin',
        'display_name': 'Local Admin',
        'permissions': ['admin', 'operator', 'report', 'settings', 'users'],
    }
}

# =============================================================================
# GOOGLE OAUTH CONFIGURATION
# =============================================================================

# OAuth client instance (initialized in register_auth_routes)
oauth = None

def init_google_oauth(app):
    """Initialize Google OAuth client."""
    global oauth

    if not GOOGLE_OAUTH_AVAILABLE:
        logger.warning("authlib not installed - Google OAuth disabled")
        return None

    if not Config.GOOGLE_CLIENT_ID or not Config.GOOGLE_CLIENT_SECRET:
        logger.info("Google OAuth credentials not configured")
        return None

    oauth = OAuth(app)
    oauth.register(
        name='google',
        client_id=Config.GOOGLE_CLIENT_ID,
        client_secret=Config.GOOGLE_CLIENT_SECRET,
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={
            'scope': 'openid email profile'
        }
    )
    logger.info("Google OAuth initialized successfully")
    return oauth


def google_authenticate(google_user_info):
    """
    Process Google OAuth user info and create session user_info.

    Args:
        google_user_info: Dict from Google with 'email', 'name', 'sub', etc.

    Returns:
        user_info dict or None if authentication fails
    """
    if not google_user_info:
        return None

    email = google_user_info.get('email', '').lower()
    if not email:
        logger.warning("Google auth: No email in user info")
        return None

    # Check email verification
    if not google_user_info.get('email_verified', False):
        logger.warning(f"Google auth: Email not verified for {email}")
        return None

    # Check allowed domains
    if Config.GOOGLE_ALLOWED_DOMAINS:
        domain = email.split('@')[-1] if '@' in email else ''
        if domain not in Config.GOOGLE_ALLOWED_DOMAINS:
            logger.warning(f"Google auth: Domain {domain} not in allowed list for {email}")
            return None

    # Extract username from email (part before @)
    username = email.split('@')[0] if '@' in email else email

    # Get default role from config
    default_role = Config.GOOGLE_DEFAULT_ROLE
    if default_role not in ROLE_PERMISSIONS:
        default_role = 'operator'

    user_info = {
        'username': username,
        'display_name': google_user_info.get('name', username),
        'email': email,
        'dn': f'GOOGLE:{google_user_info.get("sub", email)}',
        'role': default_role,
        'groups': ['google-sso'],
        'permissions': ROLE_PERMISSIONS.get(default_role, []),
        'manifest_filter': ROLE_MANIFEST_FILTER.get(default_role),
        'is_google': True,
        'google_sub': google_user_info.get('sub'),
    }

    logger.info(f"Google user {email} authenticated with role: {default_role}")
    return user_info


def is_google_oauth_enabled():
    """Check if Google OAuth is properly configured and available."""
    return (
        GOOGLE_OAUTH_AVAILABLE and
        oauth is not None and
        Config.GOOGLE_CLIENT_ID and
        Config.GOOGLE_CLIENT_SECRET
    )


# =============================================================================
# SKUPINY A OPRAVNENI
# =============================================================================

GROUP_ROLE_MAPPING = {
    'it': 'admin',
    'mdm-admin': 'admin',
    'mdm-bel-admin': 'bel-admin',
    'mdm-operator': 'operator',
    'mdm-report': 'report',
}

ROLE_PERMISSIONS = {
    'admin': ['admin', 'operator', 'report', 'settings', 'users'],
    'bel-admin': ['admin', 'operator', 'report', 'settings', 'users'],  # Same as admin but filtered
    'operator': ['operator', 'report', 'devices', 'profiles', 'apps'],
    'report': ['report', 'view'],
}

# Manifest filters for restricted roles
ROLE_MANIFEST_FILTER = {
    'bel-admin': '%-bel',  # SQL LIKE pattern - only *-bel manifests
}


# =============================================================================
# DATABASE ROLE OVERRIDE
# =============================================================================

def apply_database_role_override(user_info: dict) -> dict:
    """
    Check if user has a database role override and apply it.

    Database roles take precedence over LDAP-derived roles.
    This allows admins to:
    - Grant elevated permissions to specific users
    - Restrict users who would otherwise have higher access
    - Create users with custom manifest filters

    Args:
        user_info: User info dict from LDAP or local auth

    Returns:
        Updated user_info dict with database role override applied (if any)
    """
    if not db_user_roles:
        return user_info

    username = user_info.get('username', '').lower()
    if not username:
        return user_info

    try:
        db_override = db_user_roles.get_user_role(username)
        if db_override:
            original_role = user_info.get('role', 'unknown')
            new_role = db_override['role']
            new_manifest_filter = db_override.get('manifest_filter')

            # Apply override
            user_info['role'] = new_role
            user_info['permissions'] = ROLE_PERMISSIONS.get(new_role, [])

            # Manifest filter from DB takes precedence
            if new_manifest_filter:
                user_info['manifest_filter'] = new_manifest_filter
            elif new_role in ROLE_MANIFEST_FILTER:
                user_info['manifest_filter'] = ROLE_MANIFEST_FILTER[new_role]
            else:
                user_info['manifest_filter'] = None

            user_info['role_source'] = 'database'
            user_info['role_override_notes'] = db_override.get('notes')

            logger.info(f"Database role override applied for {username}: {original_role} -> {new_role}")
        else:
            user_info['role_source'] = 'ldap' if not user_info.get('is_local') else 'local'

    except Exception as e:
        logger.error(f"Failed to check database role override for {username}: {e}")
        user_info['role_source'] = 'ldap' if not user_info.get('is_local') else 'local'

    return user_info

# =============================================================================
# LOCAL AUTHENTICATION FUNCTION
# =============================================================================

def local_authenticate(username, password):
    """
    Authenticate against local users (fallback when AD is unavailable).
    Returns user_info dict or None.
    """
    if not username or not password:
        return None

    username = username.strip().lower()

    if username not in LOCAL_USERS:
        return None

    local_user = LOCAL_USERS[username]

    # Compute hash and compare
    password_hash = hashlib.sha256(f'{username}:{password}:nanohub-salt'.encode()).hexdigest()

    if password_hash != local_user['password_hash']:
        logger.warning(f"Invalid password for local user: {username}")
        return None

    user_info = {
        'username': username,
        'display_name': local_user.get('display_name', username),
        'email': None,
        'dn': f'LOCAL:{username}',
        'role': local_user['role'],
        'groups': ['local-admin'],
        'permissions': local_user['permissions'],
        'manifest_filter': None,  # Local admin has full access
        'is_local': True,  # Flag to identify local user
    }

    logger.info(f"Local user {username} authenticated successfully")
    return user_info


# =============================================================================
# LDAP FUNKCE
# =============================================================================

def get_ldap_connection(bind_dn=None, bind_password=None):
    bind_dn = bind_dn or LDAP_CONFIG['bind_dn']
    bind_password = bind_password or LDAP_CONFIG['bind_password']

    for server_config in LDAP_CONFIG['servers']:
        try:
            server = Server(
                server_config['host'],
                port=server_config['port'],
                use_ssl=LDAP_CONFIG['use_ssl'],
                get_info=ALL,
                connect_timeout=LDAP_CONFIG['timeout']
            )

            conn = Connection(
                server,
                user=bind_dn,
                password=bind_password,
                auto_bind=False,
                raise_exceptions=False  # Nehazt vyjimky, kontrolujeme result
            )

            # Otevreni spojeni
            conn.open()

            # STARTTLS pred bindem
            if LDAP_CONFIG['use_starttls']:
                conn.start_tls()

            # Bind s credentials
            if conn.bind():
                logger.info(f"LDAP connected to {server_config['host']}")
                return conn
            else:
                logger.warning(f"LDAP bind failed for {server_config['host']}: {conn.result}")

        except Exception as e:
            logger.warning(f"LDAP connection to {server_config['host']} failed: {e}")
            continue

    logger.error("All LDAP servers unavailable")
    return None


def ldap_authenticate(username, password):
    if not username or not password:
        return None, []

    username = username.strip()
    if '\\' in username:
        username = username.split('\\')[-1]
    if '@' in username:
        username = username.split('@')[0]

    service_conn = get_ldap_connection()
    if not service_conn:
        logger.error("Cannot connect to LDAP with service account")
        return None, []

    try:
        search_filter = LDAP_CONFIG['user_search_filter'].format(username=username)
        service_conn.search(
            search_base=LDAP_CONFIG['base_dn'],
            search_filter=search_filter,
            search_scope=SUBTREE,
            attributes=['distinguishedName', 'sAMAccountName', 'displayName',
                       'mail', 'memberOf', 'userPrincipalName']
        )

        if not service_conn.entries:
            logger.warning(f"User not found: {username}")
            service_conn.unbind()
            return None, []

        user_entry = service_conn.entries[0]
        user_dn = str(user_entry.distinguishedName)
        service_conn.unbind()

        user_conn = get_ldap_connection(bind_dn=user_dn, bind_password=password)
        if not user_conn:
            logger.warning(f"Invalid password for user: {username}")
            return None, []

        user_conn.unbind()

        groups = []
        allowed_groups = []

        if hasattr(user_entry, 'memberOf') and user_entry.memberOf:
            for group_dn in user_entry.memberOf.values:
                cn_part = group_dn.split(',')[0]
                if cn_part.upper().startswith('CN='):
                    group_name = cn_part[3:].lower()
                    groups.append(group_name)

                    if group_name in GROUP_ROLE_MAPPING:
                        allowed_groups.append(group_name)

        logger.info(f"User {username} groups: {groups}")
        logger.info(f"User {username} allowed groups: {allowed_groups}")

        if not allowed_groups:
            logger.warning(f"User {username} is not in any allowed group")
            return None, []

        role = 'report'
        for group in allowed_groups:
            group_role = GROUP_ROLE_MAPPING.get(group)
            if group_role == 'admin':
                role = 'admin'
                break
            elif group_role == 'bel-admin' and role not in ['admin']:
                role = 'bel-admin'
            elif group_role == 'operator' and role not in ['admin', 'bel-admin']:
                role = 'operator'

        # Check if role has manifest filter
        manifest_filter = ROLE_MANIFEST_FILTER.get(role)

        user_info = {
            'username': str(user_entry.sAMAccountName),
            'display_name': str(user_entry.displayName) if hasattr(user_entry, 'displayName') else username,
            'email': str(user_entry.mail) if hasattr(user_entry, 'mail') and user_entry.mail else None,
            'dn': user_dn,
            'role': role,
            'groups': allowed_groups,
            'permissions': ROLE_PERMISSIONS.get(role, []),
            'manifest_filter': manifest_filter,  # e.g. 'bel-%' for bel-admin
        }

        logger.info(f"User {username} authenticated successfully with role: {role}")
        return user_info, allowed_groups

    except LDAPException as e:
        logger.error(f"LDAP error during authentication: {e}")
        return None, []
    finally:
        if service_conn and service_conn.bound:
            service_conn.unbind()


def get_user_groups(username):
    conn = get_ldap_connection()
    if not conn:
        return []

    try:
        search_filter = LDAP_CONFIG['user_search_filter'].format(username=username)
        conn.search(
            search_base=LDAP_CONFIG['base_dn'],
            search_filter=search_filter,
            search_scope=SUBTREE,
            attributes=['memberOf']
        )

        if not conn.entries:
            return []

        groups = []
        if hasattr(conn.entries[0], 'memberOf'):
            for group_dn in conn.entries[0].memberOf.values:
                cn_part = group_dn.split(',')[0]
                if cn_part.upper().startswith('CN='):
                    groups.append(cn_part[3:].lower())

        return groups

    finally:
        conn.unbind()


# =============================================================================
# FLASK DECORATORY
# =============================================================================

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function


def role_required(required_role):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user' not in session:
                return redirect(url_for('login', next=request.url))

            user_role = session.get('user', {}).get('role')

            if user_role == 'admin':
                return f(*args, **kwargs)

            role_hierarchy = {'admin': 3, 'operator': 2, 'report': 1}
            if role_hierarchy.get(user_role, 0) >= role_hierarchy.get(required_role, 0):
                return f(*args, **kwargs)

            return render_template_string(ERROR_403_TEMPLATE,
                                         required_role=required_role,
                                         user_role=user_role), 403
        return decorated_function
    return decorator


def permission_required(permission):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user' not in session:
                return redirect(url_for('login', next=request.url))

            user_permissions = session.get('user', {}).get('permissions', [])

            if permission in user_permissions or 'admin' in user_permissions:
                return f(*args, **kwargs)

            return render_template_string(ERROR_403_TEMPLATE,
                                         required_permission=permission), 403
        return decorated_function
    return decorator


# =============================================================================
# HTML TEMPLATES
# =============================================================================

LOGIN_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NanoHUB - Login</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="/static/dashboard.css">
    <link rel="stylesheet" href="/static/css/qbone.css">
    <link rel="stylesheet" href="/static/css/admin.css">
    <link rel="apple-touch-icon" sizes="180x180" href="/static/apple-touch-icon.png">
    <link rel="icon" type="image/png" sizes="32x32" href="/static/favicon-32x32.png">
    <link rel="icon" type="image/png" sizes="16x16" href="/static/favicon-16x16.png">
    <link rel="shortcut icon" href="/static/favicon.ico">
    <style>
        body {
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
        }
        .login-panel {
            max-width: 420px;
            width: 100%;
        }
        .login-panel .logo-wrap {
            text-align: center;
            margin-bottom: 25px;
        }
        .login-panel .logo-wrap img {
            max-width: 180px;
            height: auto;
        }
        .login-panel h1 {
            margin-bottom: 8px;
        }
        .login-panel .subtitle {
            color: #B0B0B0;
            font-size: 0.95em;
            margin-bottom: 25px;
        }
        .form-group {
            margin-bottom: 18px;
            text-align: left;
        }
        .form-group label {
            display: block;
            margin-bottom: 6px;
            color: #FFFFFF;
            font-weight: 500;
            font-size: 0.95em;
        }
        .form-group input {
            width: 100%;
            box-sizing: border-box;
        }
        .btn-login {
            width: 100%;
            margin-top: 10px;
            padding: 12px 20px;
            font-size: 1em;
        }
        .btn-login.red {
            background: #5FC812;
            color: #0D0D0D;
        }
        .btn-login.red:hover {
            background: #A5F36C;
        }
        .login-footer {
            margin-top: 20px;
            font-size: 0.85em;
            color: #B0B0B0;
        }
    </style>
</head>
<body>
    <div class="panel login-panel">
        <div class="logo-wrap">
            <img src="{{ current_logo }}" alt="Logo" style="max-height:60px;max-width:200px;">
        </div>
        <h1>NanoHUB MDM</h1>
        <p class="subtitle">Mobile Device Management</p>

        {% if error %}
        <div class="panel-error" style="display:block;">{{ error }}</div>
        {% endif %}

        {% if google_enabled %}
        <a href="{{ url_for('google_login') }}?next={{ next }}" class="btn btn-login google-btn" style="display:flex;align-items:center;justify-content:center;gap:10px;background:#fff;color:#333;border:1px solid #ddd;margin-bottom:20px;">
            <svg width="18" height="18" viewBox="0 0 48 48"><path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/><path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/><path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/><path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/></svg>
            Sign in with Google
        </a>
        <div class="divider" style="display:flex;align-items:center;margin:20px 0;color:#666;">
            <span style="flex:1;height:1px;background:#333;"></span>
            <span style="padding:0 15px;font-size:0.85em;">or use domain account</span>
            <span style="flex:1;height:1px;background:#333;"></span>
        </div>
        {% endif %}

        <form method="POST" action="{{ url_for('login') }}">
            <input type="hidden" name="next" value="{{ next }}">
            <div class="form-group">
                <label for="username">Username</label>
                <input type="text" id="username" name="username" placeholder="firstname.lastname" {% if not google_enabled %}autofocus{% endif %}>
            </div>
            <div class="form-group">
                <label for="password">Password</label>
                <input type="password" id="password" name="password" placeholder="Your domain password">
            </div>
            <button type="submit" class="btn btn-login red">Sign In with Domain</button>
        </form>
        <p class="login-footer">{% if google_enabled %}Use Google SSO or your{% else %}Sign in with your{% endif %} SLOTO.SPACE domain account</p>
    </div>
</body>
</html>
'''

ERROR_403_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Access Denied - NanoHUB</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="/static/dashboard.css">
    <link rel="shortcut icon" href="/static/favicon.ico">
    <style>
        body { display: flex; align-items: center; justify-content: center; min-height: 100vh; }
        .error-panel { max-width: 450px; }
        .error-panel h1 { color: #e92128; }
    </style>
</head>
<body>
    <div class="panel error-panel">
        <h1>403 - Access Denied</h1>
        <p>You do not have permission to access this page.</p>
        {% if required_role %}<p>Required role: <strong>{{ required_role }}</strong></p>{% endif %}
        {% if user_role %}<p>Your role: <strong>{{ user_role }}</strong></p>{% endif %}
        <p><a href="/">Back to Dashboard</a></p>
    </div>
</body>
</html>
'''


# =============================================================================
# FLASK ROUTES
# =============================================================================

def register_auth_routes(app):
    # Initialize Google OAuth
    init_google_oauth(app)

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        error = None
        next_url = request.args.get('next') or request.form.get('next') or url_for('index')

        if request.method == 'POST':
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '')

            user_info = None

            # 1. Try local authentication first (always works, even when AD is down)
            user_info = local_authenticate(username, password)

            # 2. If not a local user, try LDAP
            if not user_info:
                ldap_user_info, groups = ldap_authenticate(username, password)
                if ldap_user_info:
                    user_info = ldap_user_info

            # 3. If authenticated, apply database role override and create session
            if user_info:
                # Check for database role override
                user_info = apply_database_role_override(user_info)

                session['user'] = user_info
                session.permanent = True
                auth_type = 'local' if user_info.get('is_local') else 'LDAP'
                role_source = user_info.get('role_source', auth_type)
                logger.info(f"User {username} logged in successfully via {auth_type} (role: {user_info.get('role')} from {role_source})")
                return redirect(next_url)
            else:
                error = 'Invalid credentials or you are not a member of an authorized group'
                logger.warning(f"Failed login attempt for user: {username}")

        current_logo = app_settings.get('header_logo', '/static/logos/slotegrator_green.png')
        google_enabled = is_google_oauth_enabled()
        return render_template_string(LOGIN_TEMPLATE, error=error, next=next_url, current_logo=current_logo, google_enabled=google_enabled)

    # =========================================================================
    # GOOGLE OAUTH ROUTES
    # =========================================================================

    @app.route('/login/google')
    def google_login():
        """Initiate Google OAuth flow."""
        if not is_google_oauth_enabled():
            flash('Google SSO is not configured', 'error')
            return redirect(url_for('login'))

        # Store next URL in session for callback
        next_url = request.args.get('next') or url_for('index')
        session['oauth_next'] = next_url

        # Generate OAuth state for CSRF protection
        state = secrets.token_urlsafe(32)
        session['oauth_state'] = state

        # Build callback URL
        redirect_uri = url_for('google_callback', _external=True)

        return oauth.google.authorize_redirect(redirect_uri, state=state)

    @app.route('/login/google/callback')
    def google_callback():
        """Handle Google OAuth callback."""
        if not is_google_oauth_enabled():
            flash('Google SSO is not configured', 'error')
            return redirect(url_for('login'))

        # Verify state for CSRF protection
        state = request.args.get('state')
        stored_state = session.pop('oauth_state', None)
        if not state or state != stored_state:
            logger.warning("Google OAuth: Invalid state parameter (CSRF check failed)")
            flash('Authentication failed - please try again', 'error')
            return redirect(url_for('login'))

        try:
            # Exchange code for token
            token = oauth.google.authorize_access_token()

            # Get user info from Google
            google_user_info = token.get('userinfo')
            if not google_user_info:
                # Fallback: fetch from userinfo endpoint
                google_user_info = oauth.google.userinfo()

            if not google_user_info:
                logger.error("Google OAuth: Failed to get user info")
                flash('Failed to get user information from Google', 'error')
                return redirect(url_for('login'))

            # Process Google user and create session
            user_info = google_authenticate(google_user_info)

            if not user_info:
                flash('Your Google account is not authorized to access this application', 'error')
                return redirect(url_for('login'))

            # Apply database role override (same as LDAP/local)
            user_info = apply_database_role_override(user_info)

            # Create session
            session['user'] = user_info
            session.permanent = True

            logger.info(f"User {user_info['email']} logged in via Google SSO (role: {user_info['role']} from {user_info.get('role_source', 'google')})")

            # Redirect to original destination
            next_url = session.pop('oauth_next', url_for('index'))
            return redirect(next_url)

        except Exception as e:
            logger.error(f"Google OAuth error: {e}")
            flash('Authentication failed - please try again', 'error')
            return redirect(url_for('login'))

    @app.route('/logout')
    def logout():
        username = session.get('user', {}).get('username', 'unknown')
        session.clear()
        logger.info(f"User {username} logged out")
        return redirect(url_for('login'))

    @app.context_processor
    def inject_user():
        return {
            'current_user': session.get('user'),
            'is_admin': session.get('user', {}).get('role') in ['admin', 'bel-admin'],
            'is_operator': session.get('user', {}).get('role') in ['admin', 'bel-admin', 'operator'],
        }


# =============================================================================
# TESTOVACI FUNKCE
# =============================================================================

def test_ldap_connection():
    print("Testing LDAP connection...")
    conn = get_ldap_connection()
    if conn:
        print(f"SUCCESS: Connected to LDAP")
        print(f"Server: {conn.server.host}")
        conn.unbind()
        return True
    else:
        print("FAILED: Cannot connect to LDAP")
        return False


def test_user_auth(username, password):
    print(f"Testing authentication for user: {username}")
    user_info, groups = ldap_authenticate(username, password)

    if user_info:
        print(f"SUCCESS: User authenticated")
        print(f"  Display name: {user_info['display_name']}")
        print(f"  Role: {user_info['role']}")
        print(f"  Groups: {groups}")
        print(f"  Permissions: {user_info['permissions']}")
        return True
    else:
        print("FAILED: Authentication failed")
        return False


if __name__ == '__main__':
    print("=" * 50)
    test_ldap_connection()
    print("=" * 50)
