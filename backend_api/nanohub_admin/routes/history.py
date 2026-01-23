"""
NanoHUB Admin Panel - History Routes
=====================================

Provides:
- /history - Command execution history with filters
"""

import json
import logging
import random
from math import ceil

from flask import Blueprint, render_template_string, session, request

from nanohub_admin.utils import login_required_admin
from nanohub_admin.core import cleanup_old_history
from db_utils import db

logger = logging.getLogger('nanohub_admin')

# Create Blueprint
history_bp = Blueprint('history', __name__)


# =============================================================================
# TEMPLATE
# =============================================================================

ADMIN_HISTORY_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Execution History - NanoHUB Admin</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="/static/dashboard.css">
    <link rel="stylesheet" href="/static/css/qbone.css">
    <link rel="stylesheet" href="/static/css/admin.css">
    <link rel="shortcut icon" href="/static/favicon.ico">
</head>
<body class="page-with-table">
    <div id="wrap">
        <div style="display: flex; justify-content: center; align-items: center;">
            <img id="logo" src="{{ current_logo }}" alt="Logo" style="max-height:60px;max-width:200px;"/>
        </div>
        <h1>Execution History</h1>

        <div class="panel">
            <div class="admin-header">
                <h2>History</h2>
                <div class="nav-tabs" style="margin:0;">
                    <a href="/admin" class="btn">Commands</a>
                    <a href="/admin/devices" class="btn">Devices</a>
                    <a href="/admin/profiles" class="btn">Profiles</a>
                    <a href="/admin/ddm" class="btn">DDM</a>
                    <a href="/admin/vpp" class="btn">VPP</a>
                    <a href="/admin/reports" class="btn">Reports</a>
                    <a href="/admin/history" class="btn active">History</a>
                </div>
                <div>
                    <span style="color:#B0B0B0;font-size:0.85em;">{{ user.display_name }}</span>
                    <span class="role-badge">{{ user.role }}</span>
                    {% if user.role == 'admin' %}<a href="/admin/settings" class="btn" style="margin-left:10px;">Settings</a>{% endif %}
                    <a href="/admin/help" class="btn" style="margin-left:10px;">Help</a>
                    <a href="/" class="btn" style="margin-left:10px;">Dashboard</a>
                </div>
            </div>

            <form method="GET" class="filter-form">
                <div class="filter-group">
                    <label>Date From</label>
                    <input type="date" name="date_from" value="{{ date_from or '' }}" onchange="this.form.submit()">
                </div>
                <div class="filter-group">
                    <label>Date To</label>
                    <input type="date" name="date_to" value="{{ date_to or '' }}" onchange="this.form.submit()">
                </div>
                <div class="filter-group">
                    <label>Device (UDID/Serial/Hostname)</label>
                    <input type="text" name="device" value="{{ device_filter or '' }}" placeholder="Search device..." onkeypress="if(event.key==='Enter'){this.form.submit();}">
                </div>
                <div class="filter-group">
                    <label>User</label>
                    <select name="user_filter" onchange="this.form.submit()">
                        <option value="">All users</option>
                        {% for u in users %}
                        <option value="{{ u }}" {% if u == user_filter %}selected{% endif %}>{{ u }}</option>
                        {% endfor %}
                    </select>
                </div>
                <div class="filter-group">
                    <label>Status</label>
                    <select name="status" onchange="this.form.submit()">
                        <option value="">All</option>
                        <option value="1" {% if status_filter == '1' %}selected{% endif %}>Success</option>
                        <option value="0" {% if status_filter == '0' %}selected{% endif %}>Failed</option>
                    </select>
                </div>
                <div class="filter-buttons">
                    <button type="button" class="btn" onclick="window.location.href='/admin/history'">Clear</button>
                </div>
            </form>

            <div class="result-info">
                Showing {{ history|length }} of {{ total_count }} records
                {% if total_count > 0 %}(Page {{ page }} of {{ total_pages }}){% endif %}
            </div>

            <div class="table-wrapper">
            <table class="history-table">
                <thead>
                    <tr>
                        <th>Timestamp</th>
                        <th>User</th>
                        <th>Command</th>
                        <th>Details</th>
                        <th>Device</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody>
                    {% for entry in history %}
                    <tr>
                        <td>{{ entry.timestamp.strftime('%Y-%m-%d %H:%M:%S') if entry.timestamp else '' }}</td>
                        <td><strong style="color:#fff;">{{ entry.user or '' }}</strong></td>
                        <td>{{ entry.command_name }}</td>
                        <td class="details-cell">
                            {% if entry.params %}
                                {% for key, val in entry.params.items() %}
                                    {% if val and key not in ['devices', 'udid'] %}
                                        <strong>{{ key }}:</strong> {{ val }}<br>
                                    {% endif %}
                                {% endfor %}
                            {% endif %}
                            {% if entry.result_summary %}<div class="result-summary">{{ entry.result_summary }}</div>{% endif %}
                        </td>
                        <td class="device-cell">
                            {% if entry.device_hostname %}
                            <div class="device-hostname">{{ entry.device_hostname }}</div>
                            {% endif %}
                            {% if entry.device_udid %}
                            <div class="device-udid">{{ entry.device_udid }}</div>
                            {% endif %}
                        </td>
                        <td class="{% if entry.success %}status-success{% else %}status-failed{% endif %}">
                            {% if entry.success %}Success{% else %}Failed{% endif %}
                        </td>
                    </tr>
                    {% endfor %}
                    {% if not history %}
                    <tr>
                        <td colspan="6" style="text-align:center;color:#B0B0B0;">No execution history found</td>
                    </tr>
                    {% endif %}
                </tbody>
            </table>
            </div>

            {% if total_pages > 1 %}
            <div id="pagination-container" style="margin-top:15px;padding:10px 0;border-top:1px solid #e7eaf2;">
                <div style="font-size:0.85em;color:#6b7280;margin-bottom:8px;">
                    Showing {{ ((page - 1) * 50) + 1 }}-{{ [page * 50, total_count] | min }} of {{ total_count }} (Page {{ page }} of {{ total_pages }})
                </div>
                <div class="pagination">
                    {% if page > 1 %}
                    <a href="?page={{ page - 1 }}&date_from={{ date_from or '' }}&date_to={{ date_to or '' }}&device={{ device_filter or '' }}&user_filter={{ user_filter or '' }}&status={{ status_filter or '' }}">&laquo; Prev</a>
                    {% else %}
                    <span class="disabled">&laquo; Prev</span>
                    {% endif %}

                    {% for p in range(1, total_pages + 1) %}
                        {% if p == page %}
                        <span class="current">{{ p }}</span>
                        {% elif p <= 3 or p > total_pages - 2 or (p >= page - 1 and p <= page + 1) %}
                        <a href="?page={{ p }}&date_from={{ date_from or '' }}&date_to={{ date_to or '' }}&device={{ device_filter or '' }}&user_filter={{ user_filter or '' }}&status={{ status_filter or '' }}">{{ p }}</a>
                        {% elif p == 4 or p == total_pages - 2 %}
                        <span>...</span>
                        {% endif %}
                    {% endfor %}

                    {% if page < total_pages %}
                    <a href="?page={{ page + 1 }}&date_from={{ date_from or '' }}&date_to={{ date_to or '' }}&device={{ device_filter or '' }}&user_filter={{ user_filter or '' }}&status={{ status_filter or '' }}">Next &raquo;</a>
                    {% else %}
                    <span class="disabled">Next &raquo;</span>
                    {% endif %}
                </div>
            </div>
            {% endif %}
        </div>
    </div>
</body>
</html>
'''


# =============================================================================
# ROUTES
# =============================================================================

@history_bp.route('/history')
@login_required_admin
def admin_history():
    """View execution history from MySQL with filters"""
    user = session.get('user', {})
    manifest_filter = user.get('manifest_filter')  # e.g. 'site-%' for site-admin
    history = []
    total_count = 0
    users_list = []
    total_pages = 1

    # Pagination
    page = request.args.get('page', 1, type=int)
    per_page = 50

    # Filters
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    device_filter = request.args.get('device', '')
    user_filter = request.args.get('user_filter', '')
    status_filter = request.args.get('status', '')

    try:
        # Get list of users for filter dropdown (filter out None values)
        users_rows = db.query_all("SELECT DISTINCT user FROM command_history WHERE user IS NOT NULL AND user != '' ORDER BY user")
        users_list = [row['user'] for row in users_rows if row['user']]

        # Build query with filters
        where_clauses = ["ch.timestamp >= DATE_SUB(NOW(), INTERVAL 90 DAY)"]
        params = []

        # Add manifest filter for site-admin (join with device_inventory)
        join_clause = ""
        if manifest_filter:
            join_clause = "LEFT JOIN device_inventory di ON ch.device_udid = di.uuid"
            where_clauses.append("di.manifest LIKE %s")
            params.append(manifest_filter)

        if date_from:
            where_clauses.append("DATE(ch.timestamp) >= %s")
            params.append(date_from)

        if date_to:
            where_clauses.append("DATE(ch.timestamp) <= %s")
            params.append(date_to)

        if device_filter:
            where_clauses.append(
                "(ch.device_udid LIKE %s OR ch.device_serial LIKE %s OR ch.device_hostname LIKE %s)"
            )
            like_val = f"%{device_filter}%"
            params.extend([like_val, like_val, like_val])

        if user_filter:
            where_clauses.append("ch.user = %s")
            params.append(user_filter)

        if status_filter in ('0', '1'):
            where_clauses.append("ch.success = %s")
            params.append(int(status_filter))

        where_sql = " AND ".join(where_clauses)

        # Get total count
        total_count = db.query_value(f"""
            SELECT COUNT(*) FROM command_history ch {join_clause} WHERE {where_sql}
        """, params) or 0

        # Calculate pagination
        total_pages = ceil(total_count / per_page) if total_count > 0 else 1
        page = min(max(1, page), total_pages)
        offset_val = (page - 1) * per_page

        # Get paginated results
        history = db.query_all(f"""
            SELECT ch.id, ch.timestamp, ch.user, ch.command_id, ch.command_name, ch.device_udid,
                   ch.device_serial, ch.device_hostname, ch.params, ch.result_summary, ch.success
            FROM command_history ch
            {join_clause}
            WHERE {where_sql}
            ORDER BY ch.timestamp DESC
            LIMIT %s OFFSET %s
        """, params + [per_page, offset_val])

        # Parse params JSON for each entry
        for entry in history:
            if entry.get('params'):
                try:
                    entry['params'] = json.loads(entry['params'])
                except Exception:
                    entry['params'] = {}

        # Run cleanup periodically (every 100 requests approximately)
        if random.randint(1, 100) == 1:
            cleanup_old_history(90)

    except Exception as e:
        logger.error(f"Failed to read command history: {e}")

    return render_template_string(
        ADMIN_HISTORY_TEMPLATE,
        user=user,
        history=history,
        total_count=total_count,
        total_pages=total_pages,
        page=page,
        date_from=date_from,
        date_to=date_to,
        device_filter=device_filter,
        user_filter=user_filter,
        status_filter=status_filter,
        users=users_list
    )
