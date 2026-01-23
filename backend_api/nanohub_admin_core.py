"""
NanoHUB Admin Panel
Web interface for MDM command execution
Refactored to use centralized utility modules.
"""

import os
import re
import ssl
import ast
import glob
import base64
import subprocess
import json
import logging
import uuid
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import Blueprint, render_template_string, session, redirect, url_for, request, jsonify

from command_registry import (
    COMMANDS, CATEGORIES, COMMANDS_DIR, PROFILE_DIRS,
    get_commands_by_category, get_command, get_available_profiles, check_role_permission
)
from web_config import get_munki_profile, get_value

# Import centralized modules
from config import Config
from db_utils import db, devices, command_history, device_details, required_profiles, ddm_compliance, app_settings
from command_executor import executor as cmd_executor
from webhook_poller import poller, poll_webhook_for_command
from cache_utils import device_cache
from nanohub_admin.utils import login_required_admin, admin_required

# Import command execution functions from commands module
from nanohub_admin.commands import (
    execute_command,
    execute_bulk_command,
)

# Import shared functions from core module
from nanohub_admin.core import (
    get_manifests_list,
    get_devices_list,
)

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('nanohub_admin')

# Paths from centralized config
AUDIT_LOG_PATH = Config.AUDIT_LOG_PATH
WEBHOOK_LOG_PATH = Config.WEBHOOK_LOG_PATH

# Create Blueprint
admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


@admin_bp.context_processor
def inject_logo():
    """Inject current logo path into all templates"""
    try:
        current_logo = app_settings.get('header_logo', '/static/logos/slotegrator_green.png')
        return {'current_logo': current_logo}
    except Exception:
        return {'current_logo': '/static/logos/slotegrator_green.png'}


# Thread pool for parallel execution (separate from cmd_executor)
thread_pool = ThreadPoolExecutor(max_workers=Config.THREAD_POOL_WORKERS)

# Legacy compatibility - DB_CONFIG from centralized config
DB_CONFIG = Config.DB


# =============================================================================
# NOTE: Functions moved to separate modules for better maintainability
# =============================================================================
# - Device data functions -> nanohub_admin.core
# - Command execution (execute_*) -> nanohub_admin.commands  
# - Device detail routes/templates -> nanohub_admin.routes.devices
# - Profile management -> nanohub_admin.profiles

ADMIN_DASHBOARD_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Admin Panel - NanoHUB MDM</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="/static/dashboard.css">
    <link rel="stylesheet" href="/static/css/qbone.css">
    <link rel="stylesheet" href="/static/css/admin.css">
    <link rel="apple-touch-icon" sizes="180x180" href="/static/apple-touch-icon.png">
    <link rel="icon" type="image/png" sizes="32x32" href="/static/favicon-32x32.png">
    <link rel="shortcut icon" href="/static/favicon.ico">
</head>
<body class="page-with-table">
    <div id="wrap">
        <div style="display: flex; justify-content: center; align-items: center;">
            <img id="logo" src="{{ current_logo }}" alt="Logo" style="max-height:60px;max-width:200px;"/>
        </div>
        <h1>NanoHUB MDM Admin Panel</h1>

        <div class="panel">
            <div class="admin-header">
                <h2>Commands</h2>
                <div class="nav-tabs" style="margin:0;">
                    <a href="/admin" class="btn active">Commands</a>
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
                    <a href="/admin/help" class="btn" style="margin-left:10px;">Help</a>
                    <a href="/" class="btn" style="margin-left:10px;">Dashboard</a>
                </div>
            </div>

            <div class="category-grid">
                {% for cat_id, cat_data in categories.items() %}
                {% if cat_data.commands %}
                <div class="category-card">
                    <h3>{{ cat_data.info.name }}</h3>
                    <ul class="command-list">
                        {% for cmd_id, cmd in cat_data.commands.items() %}
                        {% if can_access(user.role, cmd.min_role) %}
                        <li>
                            <a href="/admin/command/{{ cmd_id }}" class="{% if cmd.dangerous %}dangerous{% endif %}">
                                {{ cmd.name }}
                                {% if cmd.min_role == 'admin' %}<span class="role-badge">admin</span>{% endif %}
                            </a>
                        </li>
                        {% endif %}
                        {% endfor %}
                    </ul>
                </div>
                {% endif %}
                {% endfor %}
            </div>
        </div>
    </div>
</body>
</html>
'''

ADMIN_COMMAND_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ command.name }} - NanoHUB Admin</title>
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
        <h1>{{ command.name }}</h1>

        <div class="panel">
            <div class="admin-header">
                <h2>{{ command.description }}</h2>
                {% if command.dangerous %}
                <span style="color:#D91F25;font-size:0.9em;">This is a potentially dangerous operation.</span>
                {% endif %}
                <a href="/admin" class="btn">Back to Commands</a>
            </div>

            {% if os_versions %}
            <div style="margin-bottom:15px;padding:8px 12px;background:#1a1a1a;border:1px solid #333;border-radius:4px;font-size:0.85em;color:#B0B0B0;">
                {% if os_versions.ios %}iOS <strong style="color:#fff;">{{ os_versions.ios.version }}</strong> <code style="color:#666;">{{ os_versions.ios.product_key }}</code>{% endif %}{% if os_versions.ipados %} · iPadOS <strong style="color:#fff;">{{ os_versions.ipados.version }}</strong> <code style="color:#666;">{{ os_versions.ipados.product_key }}</code>{% endif %}{% if os_versions.macos %} · macOS <strong style="color:#fff;">{{ os_versions.macos.version }}</strong> <code style="color:#666;">{{ os_versions.macos.product_key }}</code>{% endif %}
            </div>
            {% endif %}

            <form id="commandForm" onsubmit="return executeCommand(event)" style="text-align:left;">
                {% for param in command.parameters %}
                <div class="form-group">
                    <label>{{ param.label }}{% if param.required %} <span style="color:#e92128;">*</span>{% endif %}</label>

                    {% if param.type == 'device' %}
                    <div class="filter-form">
                        <div class="filter-group">
                            <label>Search</label>
                            <input type="text" id="device-search" placeholder="Hostname, serial, UUID...">
                        </div>
                        <div class="filter-group">
                            <label>OS</label>
                            <select id="os-filter">
                                <option value="all">All</option>
                                <option value="ios">iOS</option>
                                <option value="macos">macOS</option>
                            </select>
                        </div>
                        <div class="filter-group">
                            <label>Manifest</label>
                            <select id="manifest-filter">
                                <option value="all">All</option>
                                {% for manifest in manifests %}
                                <option value="{{ manifest }}">{{ manifest }}</option>
                                {% endfor %}
                            </select>
                        </div>
                        <div class="filter-buttons">
                            <button type="button" onclick="searchDevices()" class="filter-btn">Search</button>
                            <button type="button" onclick="showAllDevices()" class="filter-btn">Show All</button>
                        </div>
                    </div>
                    <div class="device-table-container">
                        <table class="device-table" id="device-table">
                            <thead>
                                <tr><th>Hostname</th><th>Serial</th><th>OS</th><th>Version</th><th>Model</th><th>Manifest</th><th>DEP</th><th>Supervised</th><th>Encrypted</th><th>Outdated</th><th>Last Check-in</th><th>Status</th></tr>
                            </thead>
                            <tbody id="device-tbody">
                                <tr><td colspan="12" style="text-align:center;color:#B0B0B0;">Click "Show All" or search for devices</td></tr>
                            </tbody>
                        </table>
                    </div>
                    <input type="hidden" name="udid" id="selected-udid" {% if param.required %}required{% endif %}>

                    {% elif param.type == 'devices' %}
                    <div class="filter-form">
                        <div class="filter-group">
                            <label>Search</label>
                            <input type="text" id="device-search" placeholder="Hostname, serial, UUID...">
                        </div>
                        <div class="filter-group">
                            <label>OS</label>
                            <select id="os-filter">
                                <option value="all">All</option>
                                <option value="ios">iOS</option>
                                <option value="macos">macOS</option>
                            </select>
                        </div>
                        <div class="filter-group">
                            <label>Manifest</label>
                            <select id="manifest-filter">
                                <option value="all">All</option>
                                {% for manifest in manifests %}
                                <option value="{{ manifest }}">{{ manifest }}</option>
                                {% endfor %}
                            </select>
                        </div>
                        <div class="filter-buttons">
                            <button type="button" onclick="searchDevices()" class="filter-btn">Search</button>
                            <button type="button" onclick="showAllDevices()" class="filter-btn">Show All</button>
                        </div>
                    </div>
                    <div class="device-table-container">
                        <table class="device-table" id="device-table">
                            <thead>
                                <tr><th><input type="checkbox" id="select-all" onchange="toggleSelectAll()"></th><th>Hostname</th><th>Serial</th><th>OS</th><th>Version</th><th>Model</th><th>Manifest</th><th>DEP</th><th>Supervised</th><th>Encrypted</th><th>Outdated</th><th>Last Check-in</th><th>Status</th></tr>
                            </thead>
                            <tbody id="device-tbody">
                                <tr><td colspan="13" style="text-align:center;color:#B0B0B0;">Click "Show All" or search for devices</td></tr>
                            </tbody>
                        </table>
                    </div>
                    <div id="selected-count" style="margin-top:8px;color:#276beb;font-weight:500;"></div>

                    {% elif param.type == 'profile' %}
                    <div class="profile-select-group">
                        <label>Profile:</label>
                        <select name="{{ param.name }}" id="{{ param.name }}" {% if param.required %}required{% endif %}>
                            <option value="">-- Select Profile --</option>
                            <optgroup label="System Profiles">
                            {% for profile in profiles.system %}
                            <option value="{{ profile.path }}">{{ profile.name }}</option>
                            {% endfor %}
                            </optgroup>
                            <optgroup label="WireGuard Profiles">
                            {% for profile in profiles.wireguard %}
                            <option value="{{ profile.path }}">{{ profile.name }}</option>
                            {% endfor %}
                            </optgroup>
                        </select>
                    </div>

                    {% elif param.type == 'device_autofill' %}
                    <div class="panel-actions" style="margin-bottom:8px;">
                        <input type="text" id="autofill-device-search" placeholder="Search hostname / serial / UUID" style="width:220px;">
                        <select id="autofill-os-filter" style="width:100px;margin-left:5px;">
                            <option value="all">All OS</option>
                            <option value="ios">iOS</option>
                            <option value="macos">macOS</option>
                        </select>
                        <button type="button" onclick="searchAutofillDevices()" class="btn" style="margin-left:5px;">Search</button>
                        <button type="button" onclick="showAllAutofillDevices()" class="btn" style="margin-left:5px;">Show All</button>
                    </div>
                    <div class="device-table-container">
                        <table class="device-table" id="autofill-device-table">
                            <thead>
                                <tr><th>Hostname</th><th>Serial</th><th>OS</th><th>Version</th><th>Model</th><th>Manifest</th><th>DEP</th><th>Supervised</th><th>Encrypted</th><th>Outdated</th><th>Last Check-in</th><th>Status</th></tr>
                            </thead>
                            <tbody id="autofill-device-tbody">
                                <tr><td colspan="12" style="text-align:center;color:#B0B0B0;">Click "Show All" or search for devices</td></tr>
                            </tbody>
                        </table>
                    </div>

                    {% elif param.type == 'select' %}
                    <select name="{{ param.name }}" id="{{ param.name }}" {% if param.required %}required{% endif %}>
                        {% for opt in param.options %}
                        <option value="{{ opt.value }}">{{ opt.label }}</option>
                        {% endfor %}
                    </select>

                    {% elif param.type == 'select_multiple' %}
                    <div id="applications-container" style="background:#1a1a1a;border:1px solid #333;border-radius:4px;padding:8px;">
                        <span style="color:#888;font-size:12px;">Select manifest to load applications</span>
                    </div>

                    {% else %}
                    <input type="text" name="{{ param.name }}" id="{{ param.name }}"
                           placeholder="{{ param.placeholder or '' }}"
                           {% if param.required %}required{% endif %}>
                    {% endif %}
                </div>
                {% endfor %}

                <div style="margin-top:20px;">
                    <button type="submit" class="btn {% if command.dangerous %}red{% endif %}">
                        Execute {{ command.name }}
                    </button>
                </div>
            </form>

            <div id="loading" style="display:none;margin:14px auto 10px auto;max-width:600px;text-align:center;padding:6px 22px;background:#1E1E1E;border:1px solid #5FC812;border-radius:5px;color:#5FC812;box-shadow:0 3px 12px -3px rgba(95,200,18,0.15);">
                Executing command, please wait...
            </div>

            <div id="output-container"></div>
        </div>
    </div>

    {% if command.danger_level == 'critical' %}
    <div class="confirm-overlay" id="confirmOverlay">
        <div class="confirm-box">
            <h3>Confirm Dangerous Operation</h3>
            <p>You are about to execute: <strong>{{ command.name }}</strong></p>
            <p>{{ command.description }}</p>
            <div style="margin:15px 0;">
                <label>Type <strong>{{ command.confirm_text or 'CONFIRM' }}</strong> to proceed:</label>
                <input type="text" id="confirmInput" style="margin-top:8px;width:200px;">
            </div>
            <div>
                <button class="btn" onclick="closeConfirm()">Cancel</button>
                <button class="btn btn-danger" onclick="confirmExecute()" style="margin-left:10px;">Confirm</button>
            </div>
        </div>
    </div>
    {% endif %}

    <script>
    const commandId = '{{ cmd_id }}';
    const isDangerous = {{ 'true' if command.dangerous else 'false' }};
    const dangerLevel = '{{ command.danger_level or "" }}';
    const confirmText = '{{ command.confirm_text or "CONFIRM" }}';
    const isMultiSelect = {{ 'true' if has_devices_param else 'false' }};
    let allDevices = [];
    let pendingFormData = null;

    function detectFieldType(input) {
        if (/^[a-f0-9\\-]{36}$/i.test(input)) return 'uuid';
        else if (/^\\d+$/.test(input)) return 'serial';
        else return 'hostname';
    }

    function showAllDevices() {
        fetch('/admin/api/devices')
            .then(r => r.json())
            .then(devices => {
                allDevices = devices || [];
                renderDevices(filterDevices(allDevices));
            })
            .catch(err => {
                console.error('Failed to load devices:', err);
                allDevices = [];
                renderDevices([]);
            });
    }

    function searchDevices() {
        const input = document.getElementById('device-search').value.trim();
        if (!input) {
            showAllDevices();
            return;
        }
        const field = detectFieldType(input);
        fetch('/admin/api/device-search', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({field, value: input})
        })
        .then(r => r.json())
        .then(devices => {
            allDevices = Array.isArray(devices) ? devices : [];
            renderDevices(filterDevices(allDevices));
        })
        .catch(err => {
            console.error('Search failed:', err);
            allDevices = [];
            renderDevices([]);
        });
    }

    function filterDevices(devices) {
        const osFilter = document.getElementById('os-filter').value;
        const manifestFilter = document.getElementById('manifest-filter')?.value || 'all';
        let filtered = devices;
        if (osFilter !== 'all') {
            filtered = filtered.filter(d => d.os === osFilter);
        }
        if (manifestFilter !== 'all') {
            filtered = filtered.filter(d => d.manifest === manifestFilter);
        }
        return filtered;
    }

    document.getElementById('os-filter')?.addEventListener('change', function() {
        renderDevices(filterDevices(allDevices));
    });

    document.getElementById('manifest-filter')?.addEventListener('change', function() {
        renderDevices(filterDevices(allDevices));
    });

    function renderDevices(devices) {
        const tbody = document.getElementById('device-tbody');
        if (!devices.length) {
            tbody.innerHTML = '<tr><td colspan="' + (isMultiSelect ? '13' : '12') + '" style="text-align:center;color:#B0B0B0;">No devices found</td></tr>';
            return;
        }

        let html = '';
        devices.forEach(dev => {
            const statusClass = dev.status || 'offline';
            const osClass = (dev.os || '').toLowerCase();
            const yesClass = 'color:#16a34a;font-weight:500;';
            const noClass = 'color:#dc2626;font-weight:500;';
            if (isMultiSelect) {
                html += `<tr onclick="toggleDeviceCheckbox('${dev.uuid}', this)">
                    <td><input type="checkbox" name="devices" value="${dev.uuid}" onclick="event.stopPropagation()"></td>
                    <td><a href="/admin/device/${dev.uuid}" class="device-link" onclick="event.stopPropagation()">${dev.hostname || '-'}</a></td>
                    <td>${dev.serial || '-'}</td>
                    <td><span class="os-badge ${osClass}">${dev.os || '-'}</span></td>
                    <td>${dev.os_version || '-'}</td>
                    <td>${dev.model || '-'}</td>
                    <td>${dev.manifest || '-'}</td>
                    <td><span style="${dev.dep === 'Yes' ? yesClass : noClass}">${dev.dep || '-'}</span></td>
                    <td><span style="${dev.supervised === 'Yes' ? yesClass : noClass}">${dev.supervised || '-'}</span></td>
                    <td><span style="${dev.encrypted === 'Yes' ? yesClass : noClass}">${dev.encrypted || '-'}</span></td>
                    <td><span style="${dev.outdated === 'Yes' ? noClass : yesClass}">${dev.outdated || '-'}</span></td>
                    <td>${dev.last_seen || '-'}</td>
                    <td style="text-align:center;"><span class="status-dot ${statusClass}" title="${statusClass}"></span></td>
                </tr>`;
            } else {
                html += `<tr onclick="selectDevice('${dev.uuid}', '${dev.hostname || dev.serial}', this)">
                    <td><a href="/admin/device/${dev.uuid}" class="device-link" onclick="event.stopPropagation()">${dev.hostname || '-'}</a></td>
                    <td>${dev.serial || '-'}</td>
                    <td><span class="os-badge ${osClass}">${dev.os || '-'}</span></td>
                    <td>${dev.os_version || '-'}</td>
                    <td>${dev.model || '-'}</td>
                    <td>${dev.manifest || '-'}</td>
                    <td><span style="${dev.dep === 'Yes' ? yesClass : noClass}">${dev.dep || '-'}</span></td>
                    <td><span style="${dev.supervised === 'Yes' ? yesClass : noClass}">${dev.supervised || '-'}</span></td>
                    <td><span style="${dev.encrypted === 'Yes' ? yesClass : noClass}">${dev.encrypted || '-'}</span></td>
                    <td><span style="${dev.outdated === 'Yes' ? noClass : yesClass}">${dev.outdated || '-'}</span></td>
                    <td>${dev.last_seen || '-'}</td>
                    <td style="text-align:center;"><span class="status-dot ${statusClass}" title="${statusClass}"></span></td>
                </tr>`;
            }
        });
        tbody.innerHTML = html;
    }

    function selectDevice(uuid, name, row) {
        document.querySelectorAll('#device-table tr').forEach(r => r.classList.remove('selected'));
        row.classList.add('selected');
        document.getElementById('selected-udid').value = uuid;
    }

    function clearSelectedDevice() {
        document.querySelectorAll('#device-table tr').forEach(r => r.classList.remove('selected'));
        document.getElementById('selected-udid').value = '';
    }

    function toggleDeviceCheckbox(uuid, row) {
        const cb = row.querySelector('input[type="checkbox"]');
        cb.checked = !cb.checked;
        row.classList.toggle('selected', cb.checked);
        updateSelectedCount();
    }

    function toggleSelectAll() {
        const checked = document.getElementById('select-all').checked;
        document.querySelectorAll('#device-tbody input[type="checkbox"]').forEach(cb => {
            cb.checked = checked;
            cb.closest('tr').classList.toggle('selected', checked);
        });
        updateSelectedCount();
    }

    function updateSelectedCount() {
        const count = document.querySelectorAll('#device-tbody input[type="checkbox"]:checked').length;
        const el = document.getElementById('selected-count');
        if (el) el.textContent = count > 0 ? count + ' device(s) selected' : '';
    }

    // =========================================================================
    // AUTOFILL DEVICE FUNCTIONS (for Device Manager update/delete)
    // =========================================================================
    let allAutofillDevices = [];

    function showAllAutofillDevices() {
        fetch('/admin/api/devices')
            .then(r => r.json())
            .then(devices => {
                allAutofillDevices = devices || [];
                renderAutofillDevices(filterAutofillByOS(allAutofillDevices));
            })
            .catch(err => {
                console.error('Failed to load devices:', err);
                allAutofillDevices = [];
                renderAutofillDevices([]);
            });
    }

    function searchAutofillDevices() {
        const input = document.getElementById('autofill-device-search').value.trim();
        if (!input) {
            showAllAutofillDevices();
            return;
        }
        const field = detectFieldType(input);
        fetch('/admin/api/device-search', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({field, value: input})
        })
        .then(r => r.json())
        .then(devices => {
            allAutofillDevices = Array.isArray(devices) ? devices : [];
            renderAutofillDevices(filterAutofillByOS(allAutofillDevices));
        })
        .catch(err => {
            console.error('Search failed:', err);
            allAutofillDevices = [];
            renderAutofillDevices([]);
        });
    }

    function filterAutofillByOS(devices) {
        const filterEl = document.getElementById('autofill-os-filter');
        if (!filterEl) return devices;
        const filter = filterEl.value;
        if (filter === 'all') return devices;
        return devices.filter(d => d.os === filter);
    }

    document.getElementById('autofill-os-filter')?.addEventListener('change', function() {
        renderAutofillDevices(filterAutofillByOS(allAutofillDevices));
    });

    function renderAutofillDevices(devices) {
        const tbody = document.getElementById('autofill-device-tbody');
        if (!tbody) return;

        if (!devices.length) {
            tbody.innerHTML = '<tr><td colspan="12" style="text-align:center;color:#B0B0B0;">No devices found</td></tr>';
            return;
        }

        let html = '';
        devices.forEach(dev => {
            const statusClass = dev.status || 'offline';
            const osClass = (dev.os || '').toLowerCase();
            const yesClass = 'color:#16a34a;font-weight:500;';
            const noClass = 'color:#dc2626;font-weight:500;';
            // Store device data as JSON in data attribute for autofill
            const devJson = JSON.stringify(dev).replace(/'/g, "\\'").replace(/"/g, '&quot;');
            html += `<tr onclick="selectAutofillDevice(this)" data-device="${devJson}">
                <td><a href="/admin/device/${dev.uuid}" class="device-link" onclick="event.stopPropagation()">${dev.hostname || '-'}</a></td>
                <td>${dev.serial || '-'}</td>
                <td><span class="os-badge ${osClass}">${dev.os || '-'}</span></td>
                <td>${dev.os_version || '-'}</td>
                <td>${dev.model || '-'}</td>
                <td>${dev.manifest || '-'}</td>
                <td><span style="${dev.dep === 'Yes' ? yesClass : noClass}">${dev.dep || '-'}</span></td>
                <td><span style="${dev.supervised === 'Yes' ? yesClass : noClass}">${dev.supervised || '-'}</span></td>
                <td><span style="${dev.encrypted === 'Yes' ? yesClass : noClass}">${dev.encrypted || '-'}</span></td>
                <td><span style="${dev.outdated === 'Yes' ? noClass : yesClass}">${dev.outdated || '-'}</span></td>
                <td>${dev.last_seen || '-'}</td>
                <td><span class="status-dot ${statusClass}" title="${statusClass}"></span></td>
            </tr>`;
        });
        tbody.innerHTML = html;
    }

    function selectAutofillDevice(row) {
        // Clear previous selection
        document.querySelectorAll('#autofill-device-table tr').forEach(r => r.classList.remove('selected'));
        row.classList.add('selected');

        // Parse device data from row
        const devJson = row.getAttribute('data-device');
        const dev = JSON.parse(devJson.replace(/&quot;/g, '"'));

        // Auto-fill form fields
        const uuidField = document.getElementById('uuid');
        const serialField = document.getElementById('serial');
        const hostnameField = document.getElementById('hostname');
        const osField = document.getElementById('os');
        const manifestField = document.getElementById('manifest');
        const accountField = document.getElementById('account');
        const depField = document.getElementById('dep');

        if (uuidField) uuidField.value = dev.uuid || '';
        if (serialField) serialField.value = dev.serial || '';
        if (hostnameField) hostnameField.value = dev.hostname || '';
        if (osField) osField.value = dev.os || '';
        if (manifestField) manifestField.value = dev.manifest || '';
        if (accountField) accountField.value = dev.account || '';
        if (depField) depField.value = (dev.dep === 'enabled' || dev.dep === '1' || dev.dep === 1) ? '1' : '0';

    }

    function clearAutofillDevice() {
        document.querySelectorAll('#autofill-device-table tr').forEach(r => r.classList.remove('selected'));

        // Clear form fields
        const fields = ['uuid', 'serial', 'hostname', 'os', 'manifest', 'account', 'dep'];
        fields.forEach(f => {
            const el = document.getElementById(f);
            if (el) el.value = '';
        });
    }

    function executeCommand(event) {
        event.preventDefault();
        const form = document.getElementById('commandForm');
        const formData = new FormData(form);

        if (dangerLevel === 'critical') {
            pendingFormData = formData;
            document.getElementById('confirmOverlay').classList.add('show');
            return false;
        }

        submitCommand(formData);
        return false;
    }

    // Load applications based on selected manifest
    function loadApplicationsForManifest(manifest) {
        const container = document.getElementById('applications-container');
        if (!container) return;

        if (!manifest) {
            container.innerHTML = '<span style="color:#888;font-size:12px;">Select manifest to load applications</span>';
            return;
        }

        container.innerHTML = '<span style="color:#888;font-size:12px;">Loading...</span>';

        fetch('/admin/api/applications/' + encodeURIComponent(manifest))
            .then(r => r.json())
            .then(data => {
                if (!data.applications || data.applications.length === 0) {
                    container.innerHTML = '<span style="color:#888;font-size:12px;">No applications for this manifest</span>';
                    return;
                }

                let html = '<table style="width:100%;">';
                data.applications.forEach(app => {
                    html += '<tr>';
                    html += '<td style="padding:2px;width:20px;"><input type="checkbox" name="applications" value="' + app.manifest_url + '" checked></td>';
                    html += '<td style="padding:2px 10px 2px 4px;white-space:nowrap;">' + app.app_name + '</td>';
                    html += '<td style="padding:2px;color:#666;font-size:11px;">' + app.manifest_url + '</td>';
                    html += '</tr>';
                });
                html += '</table>';
                container.innerHTML = html;
            })
            .catch(err => {
                container.innerHTML = '<span style="color:#e92128;font-size:12px;">Failed to load applications</span>';
            });
    }

    // Load applications into app_id select (for Manage Applications)
    function loadApplicationsForAppIdSelect(manifest) {
        const appIdSelect = document.getElementById('app_id');
        if (!appIdSelect) return;

        if (!manifest) {
            appIdSelect.innerHTML = '<option value="">-- Select Manifest first --</option>';
            return;
        }

        appIdSelect.innerHTML = '<option value="">Loading...</option>';

        fetch('/admin/api/applications/' + encodeURIComponent(manifest))
            .then(r => r.json())
            .then(data => {
                if (!data.applications || data.applications.length === 0) {
                    appIdSelect.innerHTML = '<option value="">-- No applications for this manifest --</option>';
                    return;
                }

                let html = '<option value="">-- Select Application --</option>';
                data.applications.forEach(app => {
                    html += '<option value="' + app.id + '">' + app.app_name + ' (' + app.os + ')</option>';
                });
                appIdSelect.innerHTML = html;
            })
            .catch(err => {
                appIdSelect.innerHTML = '<option value="">-- Failed to load --</option>';
            });
    }

    // Listen for manifest change
    const manifestSelect = document.getElementById('manifest');
    if (manifestSelect) {
        manifestSelect.addEventListener('change', function() {
            loadApplicationsForManifest(this.value);
            loadApplicationsForAppIdSelect(this.value);
        });
        // Load on page init if manifest is pre-selected
        if (manifestSelect.value) {
            loadApplicationsForManifest(manifestSelect.value);
            loadApplicationsForAppIdSelect(manifestSelect.value);
        }
    }

    function closeConfirm() {
        document.getElementById('confirmOverlay').classList.remove('show');
        document.getElementById('confirmInput').value = '';
        pendingFormData = null;
    }

    function confirmExecute() {
        const input = document.getElementById('confirmInput').value;
        if (input !== confirmText) {
            alert('Confirmation text does not match. Please type: ' + confirmText);
            return;
        }
        closeConfirm();
        submitCommand(pendingFormData);
    }

    function submitCommand(formData) {
        document.getElementById('loading').style.display = 'block';
        document.getElementById('output-container').innerHTML = '';

        // Lock device table height before adding scroll class
        const deviceTable = document.querySelector('.device-table-container');
        if (deviceTable) {
            const h = deviceTable.offsetHeight + 'px';
            deviceTable.style.setProperty('height', h, 'important');
            deviceTable.style.setProperty('max-height', h, 'important');
            deviceTable.style.setProperty('min-height', h, 'important');
            deviceTable.style.setProperty('overflow', 'auto', 'important');
        }
        // Also lock parent form-group
        const formGroup = document.querySelector('.form-group:has(.device-table-container)');
        if (formGroup) {
            const fh = formGroup.offsetHeight + 'px';
            formGroup.style.setProperty('height', fh, 'important');
            formGroup.style.setProperty('max-height', fh, 'important');
            formGroup.style.setProperty('overflow', 'hidden', 'important');
        }

        const params = {};
        for (let [key, value] of formData.entries()) {
            if (key === 'devices' || key === 'applications') {
                if (!params[key]) params[key] = [];
                params[key].push(value);
            } else {
                params[key] = value;
            }
        }

        fetch('/admin/execute', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({command: commandId, params: params})
        })
        .then(r => r.json())
        .then(data => {
            document.getElementById('loading').style.display = 'none';

            let outputHtml = '<div class="output-panel ' + (data.success ? 'success' : 'error') + '">';

            // Show script output
            outputHtml += '<strong>Script Output:</strong>\\n';
            if (data.output) {
                outputHtml += escapeHtml(data.output);
            } else if (data.error) {
                outputHtml += 'Error: ' + escapeHtml(data.error);
            } else if (data.results) {
                data.results.forEach(r => {
                    outputHtml += '=== ' + r.device + ' ===\\n';
                    outputHtml += (r.success ? 'SUCCESS' : 'FAILED') + '\\n';
                    outputHtml += escapeHtml(r.output || r.error || '') + '\\n\\n';
                    if (r.webhook_response) {
                        outputHtml += '\\n<strong>Device Response:</strong>\\n';
                        outputHtml += formatWebhookResponse(r.webhook_response);
                    }
                });
            }

            // Show webhook response if available
            if (data.webhook_response) {
                outputHtml += '\\n\\n<strong>Device Response (webhook):</strong>\\n';
                outputHtml += formatWebhookResponse(data.webhook_response);
            }

            outputHtml += '</div>';
            document.getElementById('output-container').innerHTML = outputHtml;
            // Enable page scroll and scroll to output
            document.body.classList.add('has-command-output');
            document.getElementById('output-container').scrollIntoView({behavior: 'smooth', block: 'start'});
        })
        .catch(err => {
            document.getElementById('loading').style.display = 'none';
            document.getElementById('output-container').innerHTML =
                '<div class="output-panel error">Request failed: ' + escapeHtml(err.toString()) + '</div>';
            document.body.classList.add('has-command-output');
        });
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    function formatWebhookResponse(webhook) {
        if (!webhook) return 'No response received from device.\\n';

        // Always show full raw webhook block
        if (webhook.raw) {
            // Clean up the raw output - remove timestamps and [INFO] prefix for readability
            let lines = webhook.raw.split('\\n');
            let cleanLines = lines.map(line => {
                // Remove timestamp and [INFO] prefix: "2025-12-12 21:15:01,181 [INFO]   Status: Acknowledged"
                let match = line.match(/^\\d{4}-\\d{2}-\\d{2}\\s+\\d{2}:\\d{2}:\\d{2},\\d+\\s+\\[INFO\\]\\s*(.*)$/);
                if (match) {
                    return match[1];
                }
                return line;
            });
            return escapeHtml(cleanLines.join('\\n'));
        }

        return 'No response received from device.\\n';
    }
    </script>
</body>
</html>
'''

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

@admin_bp.route('/')
@login_required_admin
def admin_dashboard():
    """Admin panel dashboard"""
    user = session.get('user', {})
    categories = get_commands_by_category()

    return render_template_string(
        ADMIN_DASHBOARD_TEMPLATE,
        user=user,
        categories=categories,
        can_access=check_role_permission
    )




@admin_bp.route('/command/<cmd_id>')
@login_required_admin
def admin_command(cmd_id):
    """Command execution page"""
    user = session.get('user', {})
    command = get_command(cmd_id)

    if not command:
        return redirect(url_for('admin.admin_dashboard'))

    if not check_role_permission(user.get('role'), command.get('min_role', 'admin')):
        return render_template_string('''
            <h1>Access Denied</h1>
            <p>You do not have permission to execute this command.</p>
            <a href="/admin">Back to Admin</a>
        '''), 403

    # Refresh manifest options from DB for commands with manifest parameter
    import copy
    command = copy.deepcopy(command)  # Don't modify cached command
    manifest_filter = user.get('manifest_filter')
    fresh_manifests = get_manifests_list(manifest_filter)
    for param in command.get('parameters', []):
        if param.get('name') == 'manifest' and param.get('type') == 'select':
            # Build fresh options from DB
            param['options'] = [{'value': '', 'label': '-- Select Manifest --'}]
            param['options'].extend([{'value': m, 'label': m} for m in fresh_manifests])
        # Load applications list for Manage Applications command - empty by default, loaded via JS
        if param.get('name') == 'app_id' and param.get('type') == 'select':
            param['options'] = [{'value': '', 'label': '-- Select Manifest first --'}]
    profiles = get_profiles_by_category()

    # Check if command has 'devices' type parameter (multi-select)
    has_devices_param = any(p['type'] == 'devices' for p in command.get('parameters', []))

    # Get latest OS versions for schedule_os_update command
    os_versions = None
    if cmd_id == 'schedule_os_update':
        os_versions = get_latest_os_versions()

    return render_template_string(
        ADMIN_COMMAND_TEMPLATE,
        user=user,
        manifests=fresh_manifests,
        command=command,
        cmd_id=cmd_id,
        profiles=profiles,
        has_devices_param=has_devices_param,
        os_versions=os_versions
    )


@admin_bp.route('/execute', methods=['POST'])
@login_required_admin
def admin_execute():
    """Execute a command"""
    user = session.get('user', {})
    data = request.get_json()

    cmd_id = data.get('command')
    params = data.get('params', {})

    command = get_command(cmd_id)
    if not command:
        return jsonify({'success': False, 'error': 'Unknown command'})

    if not check_role_permission(user.get('role'), command.get('min_role', 'admin')):
        return jsonify({'success': False, 'error': 'Insufficient permissions'})

    # Check for bulk operation
    # Some commands handle device iteration internally (native bulk commands)
    native_bulk_commands = ['bulk_schedule_os_update', 'bulk_new_device_installation', 'bulk_install_application']
    if 'devices' in params and isinstance(params.get('devices'), list) and cmd_id not in native_bulk_commands:
        results = execute_bulk_command(cmd_id, params['devices'], params, user)
        return jsonify({'success': True, 'results': results})

    result = execute_command(cmd_id, params, user)
    return jsonify(result)


@admin_bp.route('/history')
@login_required_admin
def admin_history():
    """View execution history from MySQL with filters"""
    from math import ceil

    user = session.get('user', {})
    manifest_filter = user.get('manifest_filter')  # e.g. 'site-%' for site-admin
    history = []
    total_count = 0
    users_list = []

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
        import random
        if random.randint(1, 100) == 1:
            cleanup_old_history(90)

    except Exception as e:
        logger.error(f"Failed to read command history: {e}")

    return render_template_string(
        ADMIN_HISTORY_TEMPLATE,
        user=user,
        history=history,
        total_count=total_count,
        total_pages=total_pages if 'total_pages' in dir() else 1,
        page=page,
        date_from=date_from,
        date_to=date_to,
        device_filter=device_filter,
        user_filter=user_filter,
        status_filter=status_filter,
        users=users_list
    )


@admin_bp.route('/api/commands')
@login_required_admin
def api_commands():
    """Get all commands (JSON)"""
    user = session.get('user', {})
    user_role = user.get('role', 'report')

    available_commands = {}
    for cmd_id, cmd in COMMANDS.items():
        if check_role_permission(user_role, cmd.get('min_role', 'admin')):
            available_commands[cmd_id] = cmd

    return jsonify(available_commands)




# Register route blueprints
from nanohub_admin import register_routes
register_routes()
