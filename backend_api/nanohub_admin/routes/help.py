"""
NanoHUB Admin Panel - Help Routes
=================================
Renders markdown documentation as HTML.
"""

import os
from flask import Blueprint, render_template_string, session
from ..utils import login_required_admin

try:
    import markdown
    MARKDOWN_AVAILABLE = True
except ImportError:
    MARKDOWN_AVAILABLE = False

help_bp = Blueprint('help', __name__, url_prefix='/help')

# Documentation directory
DOCS_DIR = '/opt/nanohub/docs'

# Available pages
HELP_PAGES = {
    'index': 'Overview',
    'commands': 'Commands',
    'ddm': 'DDM',
    'vpp': 'VPP',
    'devices': 'Devices',
    'reports': 'Reports',
    'settings': 'Settings',
    'database': 'Database',
    'scripts': 'Scripts',
    'troubleshooting': 'Troubleshooting',
}

# HTML template - consistent with admin panel style
HELP_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Help - {{ title }} | NanoHUB Admin</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="/static/dashboard.css">
    <link rel="stylesheet" href="/static/css/qbone.css">
    <link rel="stylesheet" href="/static/css/admin.css">
    <link rel="shortcut icon" href="/static/favicon.ico">
    <style>
    /* Help page-specific styles - Dark Theme */
    .help-tabs { display: flex; gap: 5px; margin-bottom: 20px; border-bottom: 2px solid #3A3A3A; padding-bottom: 10px; flex-wrap: wrap; }
    .help-tabs a { padding: 8px 16px; text-decoration: none; color: #B0B0B0; border-radius: 5px 5px 0 0; font-size: 0.9em; background: #2A2A2A; border: 1px solid #3A3A3A; font-family: var(--font-heading); }
    .help-tabs a.active { background: #5FC812; color: #0D0D0D; border-color: #5FC812; }
    .help-tabs a:hover:not(.active) { background: #3A3A3A; border-color: #5FC812; }
    .help-content { background: #1E1E1E; border: 1px solid #3A3A3A; border-radius: 8px; padding: 20px 25px; text-align: left; font-family: var(--font-body); max-height: calc(100vh - 320px); overflow-y: auto; }
    .help-content h1 { margin-top: 0; padding-bottom: 10px; border-bottom: 2px solid #5FC812; color: #FFFFFF; font-size: 1.5em; text-align: left; font-family: var(--font-heading); }
    .help-content h2 { margin-top: 25px; color: #FFFFFF; font-size: 1.2em; border-bottom: 1px solid #3A3A3A; padding-bottom: 8px; text-align: left; font-family: var(--font-heading); }
    .help-content h3 { margin-top: 20px; color: #B0B0B0; font-size: 1em; text-align: left; font-family: var(--font-heading); }
    .help-content p { color: #B0B0B0; line-height: 1.6; text-align: left; }
    .help-content table { width: 100%; border-collapse: collapse; margin: 15px 0; font-size: 0.9em; text-align: left; }
    .help-content th, .help-content td { padding: 10px 12px; border: 1px solid #3A3A3A; text-align: left; color: #B0B0B0; }
    .help-content th { background: #2A2A2A; font-weight: 600; color: #FFFFFF; font-family: var(--font-heading); }
    .help-content td { font-family: var(--font-body); }
    .help-content tr:hover { background: #2A2A2A; }
    .help-content code { background: #2A2A2A; padding: 2px 6px; border-radius: 3px; font-family: 'Monaco', 'Consolas', monospace; font-size: 0.85em; color: #5FC812; }
    .help-content pre { background: #0D0D0D; color: #f8f8f2; padding: 15px; border-radius: 6px; overflow-x: auto; margin: 15px 0; text-align: left; border: 1px solid #3A3A3A; }
    .help-content pre code { background: transparent; padding: 0; color: #f8f8f2; }
    .help-content a { color: #5FC812; }
    .help-content a:hover { text-decoration: underline; color: #A5F36C; }
    .help-content ul, .help-content ol { color: #B0B0B0; line-height: 1.8; text-align: left; padding-left: 20px; }
    .help-content li { text-align: left; }
    .help-content blockquote { border-left: 4px solid #5FC812; margin: 15px 0; padding: 10px 20px; background: #2A2A2A; text-align: left; color: #B0B0B0; }
    </style>
</head>
<body class="page-with-table">
    <div id="wrap">
        <div style="display: flex; justify-content: center;">
            <img id="logo" src="{{ current_logo }}" alt="Logo" style="max-height:60px;max-width:200px;"/>
        </div>
        <h1>Help & Documentation</h1>

        <div class="panel">
            <div class="admin-header">
                <h2>Help</h2>
                <div class="nav-tabs" style="margin:0;">
                    <a href="/admin" class="btn">Commands</a>
                    <a href="/admin/devices" class="btn">Devices</a>
                    <a href="/admin/profiles" class="btn">Profiles</a>
                    <a href="/admin/ddm" class="btn">DDM</a>
                    <a href="/admin/vpp" class="btn">VPP</a>
                    <a href="/admin/reports" class="btn">Reports</a>
                    <a href="/admin/history" class="btn">History</a>
                </div>
                <div>
                    <span style="color:#B0B0B0;font-size:0.85em;">{{ user.display_name }}</span>
                    <span class="role-badge">{{ user.role }}</span>
                    {% if user.role == 'admin' %}<a href="/admin/settings" class="btn" style="margin-left:10px;">Settings</a>{% endif %}
                    <a href="/admin/help" class="btn active" style="margin-left:10px;">Help</a>
                    <a href="/" class="btn" style="margin-left:10px;">Dashboard</a>
                </div>
            </div>

            <div class="help-tabs">
                {% for page_id, page_title in pages.items() %}
                <a href="/admin/help/{{ page_id }}" class="{{ 'active' if current_page == page_id else '' }}">{{ page_title }}</a>
                {% endfor %}
            </div>

            <div class="help-content">
                {{ content|safe }}
            </div>
        </div>
    </div>
</body>
</html>
"""


@help_bp.route('/')
@help_bp.route('/<page>')
@login_required_admin
def help_page(page='index'):
    """Render markdown documentation page."""
    # Get user from session (same as other routes)
    user = session.get('user', {})

    # Validate page exists
    if page not in HELP_PAGES:
        page = 'index'

    # Read markdown file
    md_path = os.path.join(DOCS_DIR, f'{page}.md')

    if os.path.exists(md_path):
        with open(md_path, 'r', encoding='utf-8') as f:
            md_content = f.read()
    else:
        md_content = f"# Page Not Found\n\nThe documentation page '{page}' was not found."

    # Convert markdown to HTML
    if MARKDOWN_AVAILABLE:
        html_content = markdown.markdown(
            md_content,
            extensions=['tables', 'fenced_code', 'toc']
        )
    else:
        html_content = f'<pre style="white-space: pre-wrap;">{md_content}</pre>'
        html_content += '<p><em>Note: Install markdown library for better formatting: pip install markdown</em></p>'

    return render_template_string(
        HELP_TEMPLATE,
        content=html_content,
        title=HELP_PAGES.get(page, 'Help'),
        pages=HELP_PAGES,
        current_page=page,
        user=user
    )
