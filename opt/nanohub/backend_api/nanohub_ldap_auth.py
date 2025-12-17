"""
NanoHUB LDAP Authentication Module
Autentizace proti Active Directory pro mdm.example.com
"""

import ldap3
from ldap3 import Server, Connection, ALL, SUBTREE
from ldap3.core.exceptions import LDAPException
from functools import wraps
from flask import session, redirect, url_for, request, render_template_string, flash
import logging

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('nanohub_ldap')

# =============================================================================
# LDAP KONFIGURACE (z radius serveru)
# =============================================================================

LDAP_CONFIG = {
    'servers': [
        {'host': 'dc01.example.com', 'port': 389},
        {'host': 'dc02.example.com', 'port': 389},  # failover
    ],
    'use_ssl': False,
    'use_starttls': True,
    'bind_dn': 'CN=ldapadmin,OU=ServiceAccounts,DC=example,DC=com',
    'bind_password': 'YOUR_LDAP_BIND_PASSWORD',
    'base_dn': 'DC=example,DC=com',
    'user_search_filter': '(sAMAccountName={username})',
    'timeout': 4,
}

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
    'bel-admin': 'bel-%',  # SQL LIKE pattern - only bel-* manifests
}

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
    <link rel="stylesheet" href="/static/dashboard.css">
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
            color: #4b5563;
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
            color: #21243b;
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
            background: #e92128;
            color: #fff;
        }
        .btn-login.red:hover {
            background: #cb2128;
        }
        .login-footer {
            margin-top: 20px;
            font-size: 0.85em;
            color: #4b5563;
        }
    </style>
</head>
<body>
    <div class="panel login-panel">
        <div class="logo-wrap">
            <img src="/static/logo.svg" alt="Logo">
        </div>
        <h1>NanoHUB MDM</h1>
        <p class="subtitle">Mobile Device Management</p>

        {% if error %}
        <div class="panel-error" style="display:block;">{{ error }}</div>
        {% endif %}

        <form method="POST" action="{{ url_for('login') }}">
            <input type="hidden" name="next" value="{{ next }}">
            <div class="form-group">
                <label for="username">Username</label>
                <input type="text" id="username" name="username" placeholder="firstname.lastname" required autofocus>
            </div>
            <div class="form-group">
                <label for="password">Password</label>
                <input type="password" id="password" name="password" placeholder="Your domain password" required>
            </div>
            <button type="submit" class="btn btn-login red">Sign In</button>
        </form>
        <p class="login-footer">Sign in with your SLOTO.SPACE domain account</p>
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
    @app.route('/login', methods=['GET', 'POST'])
    def login():
        error = None
        next_url = request.args.get('next') or request.form.get('next') or url_for('index')

        if request.method == 'POST':
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '')

            user_info, groups = ldap_authenticate(username, password)

            if user_info:
                session['user'] = user_info
                session.permanent = True
                logger.info(f"User {username} logged in successfully")
                return redirect(next_url)
            else:
                error = 'Invalid credentials or you are not a member of an authorized group'
                logger.warning(f"Failed login attempt for user: {username}")

        return render_template_string(LOGIN_TEMPLATE, error=error, next=next_url)

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
