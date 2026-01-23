#!/usr/bin/env python3
"""
NanoHUB Web Frontend with LDAP Authentication
Flask aplikace pro webove rozhrani s AD prihlasenim
"""

from flask import Flask, render_template_string, session, redirect, url_for, request, jsonify
from datetime import timedelta
import os

# Import LDAP auth modulu
from nanohub_ldap_auth import (
    register_auth_routes,
    login_required,
    role_required,
    ldap_authenticate
)

# Import Admin panel
from nanohub_admin_core import admin_bp

app = Flask(__name__, static_folder='/opt/nanohub/backend_api/static', static_url_path='/static')
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'nanohub-secret-key-change-in-production-abc123xyz')
app.permanent_session_lifetime = timedelta(hours=8)

# Cesta k originalnimu index.html
ORIGINAL_INDEX_PATH = '/var/www/mdm-web/index.html'

# Registrace auth rout (/login, /logout)
register_auth_routes(app)

# Registrace admin panelu (/admin/*)
app.register_blueprint(admin_bp)

# =============================================================================
# SESSION PANEL - vlozi se do originalniho HTML (ve stylu stranky)
# =============================================================================

SESSION_PANEL_STYLE = '''
<style>
.session-panel {
  max-width: 1500px;
  margin: 0 auto 10px auto;
  padding: 8px 2rem;
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
}
.session-panel .session-info {
  color: #B0B0B0;
}
.session-panel .session-info strong {
  color: #FFFFFF;
}
.session-panel .session-role {
  background: #2A2A2A;
  color: #5FC812;
  border: 1px solid #5FC812;
  padding: 2px 10px;
  border-radius: 10px;
  margin-left: 10px;
  font-size: 0.9em;
}
@media (min-width: 1920px) {
  .session-panel {
    max-width: calc(100vw - 500px);
  }
}
</style>
'''

SESSION_PANEL_HTML = '''
<div class="panel session-panel">
  <div class="session-info">
    Logged in as: <strong>{display_name}</strong>
    <span class="session-role">{role}</span>
  </div>
  <div>
    {admin_link}
    <a href="/logout" class="btn btn-danger" style="margin:0;padding:6px 16px;">Sign Out</a>
  </div>
</div>
'''


def inject_session_panel(html_content, user_info):
    """Vlozi session panel do HTML obsahu"""
    # Admin link only for admin, bel-admin and operator roles
    admin_link = ''
    user_role = user_info.get('role', 'report')
    if user_role in ['admin', 'bel-admin', 'operator']:
        admin_link = '<a href="/admin" class="btn" style="margin:0 10px 0 0;padding:6px 16px;">Admin Panel</a>'

    session_panel = SESSION_PANEL_HTML.format(
        display_name=user_info.get('display_name', 'Unknown'),
        role=user_info.get('role', 'unknown'),
        admin_link=admin_link,
    )

    # Vloz style do <head>
    html_content = html_content.replace('</head>', SESSION_PANEL_STYLE + '</head>')

    # Vloz session panel za </h1>
    html_content = html_content.replace('</h1>', '</h1>\n' + session_panel)

    return html_content


# =============================================================================
# ROUTES
# =============================================================================

@app.route('/')
@login_required
def index():
    """Hlavni stranka - nacte puvodni index.html a vlozi session panel"""
    try:
        with open(ORIGINAL_INDEX_PATH, 'r', encoding='utf-8') as f:
            html_content = f.read()

        # Vloz session panel
        html_content = inject_session_panel(html_content, session.get('user', {}))

        return html_content
    except Exception as e:
        return f"Error loading dashboard: {e}", 500


@app.route('/dashboard')
@login_required
def dashboard():
    return redirect(url_for('index'))


@app.route('/auth/check')
def auth_check():
    """Endpoint pro kontrolu zda je uzivatel prihlasen (pro AJAX)"""
    if 'user' in session:
        return jsonify({
            'authenticated': True,
            'user': session['user']['username'],
            'role': session['user']['role']
        })
    return jsonify({'authenticated': False}), 401


# =============================================================================
# ERROR HANDLERS
# =============================================================================

@app.errorhandler(403)
def forbidden(e):
    return render_template_string('''
<!DOCTYPE html>
<html>
<head><title>403 - Pristup odepren</title>
<style>
body { font-family: sans-serif; background: #f5f5f5; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }
.box { background: white; padding: 40px; border-radius: 8px; text-align: center; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
h1 { color: #e74c3c; }
a { color: #3572e3; }
</style>
</head>
<body>
<div class="box">
<h1>403 - Pristup odepren</h1>
<p>Nemate opravneni pro pristup k teto strance.</p>
<p><a href="/">Zpet na dashboard</a></p>
</div>
</body>
</html>
    '''), 403


@app.errorhandler(404)
def not_found(e):
    return render_template_string('''
<!DOCTYPE html>
<html>
<head><title>404 - Stranka nenalezena</title>
<style>
body { font-family: sans-serif; background: #f5f5f5; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }
.box { background: white; padding: 40px; border-radius: 8px; text-align: center; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
h1 { color: #e74c3c; }
a { color: #3572e3; }
</style>
</head>
<body>
<div class="box">
<h1>404 - Stranka nenalezena</h1>
<p><a href="/">Zpet na dashboard</a></p>
</div>
</body>
</html>
    '''), 404


# =============================================================================
# MAIN
# =============================================================================

if __name__ == '__main__':
    print("NanoHUB Web starting with LDAP authentication...")
    print("Allowed groups: it, mdm-admin, mdm-bel-admin, mdm-operator, mdm-report")
    print(f"Loading dashboard from: {ORIGINAL_INDEX_PATH}")
    app.run(host='127.0.0.1', port=9007, debug=False)
