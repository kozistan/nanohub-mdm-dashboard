"""
NanoHUB Admin - VPP Routes
==========================
VPP (Volume Purchase Program) / ABM app license management.
"""

import os
import json
import logging
import subprocess
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import Blueprint, render_template_string, session, request, jsonify

from config import Config
from db_utils import db, devices
from nanohub_admin.utils import login_required_admin

logger = logging.getLogger('nanohub_admin')

# Create a blueprint for VPP routes
vpp_bp = Blueprint('admin_vpp', __name__)


def _get_vpp_token_info():
    """Lazy import to avoid circular imports"""
    from nanohub_admin.core import get_vpp_token_info
    return get_vpp_token_info()


def _get_vpp_apps_with_names():
    """Lazy import to avoid circular imports"""
    from nanohub_admin.core import get_vpp_apps_with_names
    return get_vpp_apps_with_names()


def _get_manifests_list(manifest_filter=None):
    """Lazy import to avoid circular imports"""
    from nanohub_admin.core import get_manifests_list
    return get_manifests_list(manifest_filter)


def _audit_log(**kwargs):
    """Lazy import audit_log"""
    from nanohub_admin.utils import audit_log
    return audit_log(**kwargs)


ADMIN_VPP_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>VPP Licenses - NanoHUB Admin</title>
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
        <h1>VPP Licenses</h1>

        <div class="panel">
            <div class="admin-header">
                <h2>VPP</h2>
                <div class="nav-tabs" style="margin:0;">
                    <a href="/admin" class="btn">Commands</a>
                    <a href="/admin/devices" class="btn">Devices</a>
                    <a href="/admin/profiles" class="btn">Profiles</a>
                    <a href="/admin/ddm" class="btn">DDM</a>
                    <a href="/admin/vpp" class="btn active">VPP</a>
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

            <div class="sub-tabs">
                <a href="/admin/vpp" class="active">Licenses</a>
                <a href="/admin/vpp/updates">Updates</a>
            </div>

            {% if error %}
            <div class="token-info error">
                <span>Error: {{ error }}</span>
            </div>
            {% else %}
            <div class="token-info {% if token_warning %}warning{% endif %}">
                <div>
                    <span class="token-org">{{ org_name }}</span>
                </div>
                <div class="token-expiry">
                    Token expires: {{ token_expiry }}
                    {% if token_warning %}<strong>(expires soon!)</strong>{% endif %}
                </div>
            </div>

            <div class="stats-bar">
                <div class="stat-item">
                    <div class="stat-value">{{ total_apps }}</div>
                    <div class="stat-label">Total Apps</div>
                </div>
                <div class="stat-item">
                    <div class="stat-value">{{ total_licenses }}</div>
                    <div class="stat-label">Total Licenses</div>
                </div>
                <div class="stat-item">
                    <div class="stat-value">{{ assigned_licenses }}</div>
                    <div class="stat-label">Assigned</div>
                </div>
                <div class="stat-item">
                    <div class="stat-value">{{ available_licenses }}</div>
                    <div class="stat-label">Available</div>
                </div>
            </div>

            <div class="filter-form">
                <div class="filter-group">
                    <label>Platform</label>
                    <select id="platformFilter" onchange="filterApps()">
                        <option value="">All Platforms</option>
                        <option value="iOS">iOS</option>
                        <option value="macOS">macOS</option>
                        <option value="watchOS">watchOS</option>
                        <option value="tvOS">tvOS</option>
                        <option value="visionOS">visionOS</option>
                    </select>
                </div>
                <div class="filter-group">
                    <label>Search</label>
                    <input type="text" id="searchFilter" placeholder="App name..." onkeyup="filterApps()">
                </div>
                <div class="filter-group" style="justify-content:flex-end;">
                    <label style="display:flex;align-items:center;gap:5px;margin-top:auto;">
                        <input type="checkbox" id="lowLicenses" onchange="filterApps()"> Low licenses only
                    </label>
                </div>
            </div>

            <div class="table-wrapper">
                <table id="appsTable">
                    <thead>
                        <tr>
                            <th class="sortable" data-col="name" onclick="sortAppsTable('name')">Application <span class="sort-arrow"></span></th>
                            <th class="sortable" data-col="platforms" onclick="sortAppsTable('platforms')">Platforms <span class="sort-arrow"></span></th>
                            <th class="sortable" data-col="licenses" onclick="sortAppsTable('licenses')">Licenses <span class="sort-arrow"></span></th>
                            <th style="width:120px;">Usage</th>
                            <th style="width:150px;">Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for app in apps %}
                        <tr data-platforms="{{ app.platforms | join(',') }}" data-name="{{ app.name | lower }}" data-available="{{ app.availableCount }}" data-assigned="{{ app.assignedCount }}" data-total="{{ app.totalCount }}">
                        <td>
                            <div style="display:flex; align-items:center; gap:6px;">
                                {% if app.icon %}
                                <img src="{{ app.icon }}" alt="" style="width:20px; height:20px; border-radius:4px;">
                                {% else %}
                                <div style="width:20px; height:20px; border-radius:4px; background:#2A2A2A; display:flex; align-items:center; justify-content:center; color:#B0B0B0; font-size:0.6em;">?</div>
                                {% endif %}
                                <span class="app-name">{{ app.name }}</span> <span class="app-bundle">({{ app.bundleId or app.adamId }})</span>
                            </div>
                        </td>
                        <td>{% for platform in app.platforms %}<span class="platform-badge platform-{{ platform | lower }}">{{ platform }}</span>{% endfor %}</td>
                        <td><span {% if app.availableCount < 10 %}class="low-licenses"{% endif %}>{{ app.assignedCount }} / {{ app.totalCount }}</span> <span class="license-info">({{ app.availableCount }} avail)</span></td>
                        <td><div class="license-bar"><div class="license-used" style="width: {{ (app.assignedCount / app.totalCount * 100) if app.totalCount > 0 else 0 }}%"></div></div></td>
                        <td style="white-space:nowrap;">
                            <button class="btn btn-small" onclick="openVppModal('install', '{{ app.adamId }}', '{{ app.name }}', '{{ app.bundleId }}')">Install</button>
                            <button class="btn btn-small btn-danger" onclick="openVppModal('remove', '{{ app.adamId }}', '{{ app.name }}', '{{ app.bundleId }}')">Remove</button>
                        </td>
                    </tr>
                    {% endfor %}
                    </tbody>
                </table>
            </div>
            <div id="pagination" style="margin-top:15px;padding:10px 0;border-top:1px solid #3A3A3A;">
                <div id="pageInfo" style="font-size:0.85em;color:#B0B0B0;margin-bottom:8px;"></div>
                <div id="pageNumbers" class="pagination"></div>
            </div>
            {% endif %}
        </div>
    </div>

    <!-- VPP Action Modal -->
    <div id="vppModal" class="modal-overlay" style="display:none;">
        <div class="modal-box">
            <h3 id="modalTitle">Install VPP App</h3>
            <div class="modal-body">
                <p><strong>App:</strong> <span id="modalAppName"></span></p>
                <p><strong>Bundle ID:</strong> <span id="modalBundleId"></span></p>
                <label>Select Devices:</label>
                <select id="deviceSelect" multiple size="8">
                    {% for device in devices %}
                    <option value="{{ device.uuid }}|{{ device.serial }}">{{ device.hostname }} ({{ device.os }})</option>
                    {% endfor %}
                </select>
                <small>Ctrl/Cmd + click for multiple selection</small>
                <div id="modalResult" class="result-box" style="display:none;"></div>
            </div>
            <div class="modal-footer">
                <button class="btn" onclick="closeVppModal()">Cancel</button>
                <button class="btn btn-primary" id="modalSubmit" onclick="executeVppAction()">Execute</button>
            </div>
        </div>
    </div>

    <style>
    /* VPP-specific: sortable table headers */
    #appsTable th.sortable { cursor: pointer; user-select: none; }
    #appsTable th.sortable:hover { background: #3A3A3A; }
    #appsTable th .sort-arrow { margin-left: 4px; color: #B0B0B0; }
    #appsTable th.sorted-asc .sort-arrow::after { content: "\\25B2"; color: #5FC812; }
    #appsTable th.sorted-desc .sort-arrow::after { content: "\\25BC"; color: #5FC812; }
    /* VPP-specific: result box for modal actions */
    .result-box { margin-top: 8px; padding: 8px 10px; border-radius: 4px; font-size: 0.85em; }
    .result-box.success { background: rgba(95,200,18,0.15); color: #5FC812; border: 1px solid #5FC812; }
    .result-box.error { background: rgba(217,31,37,0.15); color: #D91F25; border: 1px solid #D91F25; }
    </style>

    <script>
    let currentAction = '';
    let currentAdamId = '';
    let currentBundleId = '';
    let currentPage = 1;
    const itemsPerPage = 50;
    let filteredRows = [];
    let currentSort = {col: null, dir: 'asc'};

    function sortAppsTable(col) {
        const tbody = document.querySelector('#appsTable tbody');
        const rows = Array.from(tbody.querySelectorAll('tr'));

        // Toggle direction
        if (currentSort.col === col) {
            currentSort.dir = currentSort.dir === 'asc' ? 'desc' : 'asc';
        } else {
            currentSort.col = col;
            currentSort.dir = 'asc';
        }

        rows.sort((a, b) => {
            let va, vb;
            if (col === 'name') {
                va = a.dataset.name || '';
                vb = b.dataset.name || '';
            } else if (col === 'platforms') {
                va = a.dataset.platforms || '';
                vb = b.dataset.platforms || '';
            } else if (col === 'licenses') {
                va = parseInt(a.dataset.available) || 0;
                vb = parseInt(b.dataset.available) || 0;
                return currentSort.dir === 'asc' ? va - vb : vb - va;
            }
            if (va < vb) return currentSort.dir === 'asc' ? -1 : 1;
            if (va > vb) return currentSort.dir === 'asc' ? 1 : -1;
            return 0;
        });

        // Reorder rows in DOM
        rows.forEach(row => tbody.appendChild(row));

        // Update header styles
        document.querySelectorAll('#appsTable th').forEach(th => {
            th.classList.remove('sorted-asc', 'sorted-desc');
            if (th.dataset.col === col) {
                th.classList.add(currentSort.dir === 'asc' ? 'sorted-asc' : 'sorted-desc');
            }
        });

        // Re-apply filters and pagination
        filterApps();
    }

    function filterApps() {
        const platform = document.getElementById('platformFilter').value;
        const search = document.getElementById('searchFilter').value.toLowerCase();
        const lowOnly = document.getElementById('lowLicenses').checked;

        const rows = document.querySelectorAll('#appsTable tbody tr');
        filteredRows = [];

        rows.forEach(row => {
            const platforms = row.dataset.platforms || '';
            const name = row.dataset.name || '';
            const available = parseInt(row.dataset.available) || 0;

            let show = true;

            if (platform && !platforms.includes(platform)) {
                show = false;
            }
            if (search && !name.includes(search)) {
                show = false;
            }
            if (lowOnly && available >= 10) {
                show = false;
            }

            if (show) {
                filteredRows.push(row);
            }
            row.style.display = 'none';
        });

        currentPage = 1;
        showPage();
    }

    function showPage() {
        const start = (currentPage - 1) * itemsPerPage;
        const end = start + itemsPerPage;
        const totalPages = Math.ceil(filteredRows.length / itemsPerPage);

        filteredRows.forEach((row, idx) => {
            row.style.display = (idx >= start && idx < end) ? '' : 'none';
        });

        document.getElementById('pageInfo').textContent =
            filteredRows.length > 0
            ? `Showing ${start + 1}-${Math.min(end, filteredRows.length)} of ${filteredRows.length} (Page ${currentPage} of ${totalPages})`
            : 'No apps found';

        renderPageNumbers(totalPages);
    }

    function renderPageNumbers(totalPages) {
        const container = document.getElementById('pageNumbers');
        if (totalPages <= 1) { container.innerHTML = ''; return; }

        let html = '';
        // Prev
        if (currentPage > 1) {
            html += '<a onclick="goToPage(' + (currentPage - 1) + ')">&laquo; Prev</a>';
        } else {
            html += '<span class="disabled">&laquo; Prev</span>';
        }
        // Page numbers
        for (let p = 1; p <= totalPages; p++) {
            if (p === currentPage) {
                html += '<span class="current">' + p + '</span>';
            } else if (p <= 3 || p > totalPages - 2 || (p >= currentPage - 1 && p <= currentPage + 1)) {
                html += '<a onclick="goToPage(' + p + ')">' + p + '</a>';
            } else if (p === 4 || p === totalPages - 2) {
                html += '<span>...</span>';
            }
        }
        // Next
        if (currentPage < totalPages) {
            html += '<a onclick="goToPage(' + (currentPage + 1) + ')">Next &raquo;</a>';
        } else {
            html += '<span class="disabled">Next &raquo;</span>';
        }
        container.innerHTML = html;
    }

    function goToPage(page) {
        const totalPages = Math.ceil(filteredRows.length / itemsPerPage);
        currentPage = Math.max(1, Math.min(totalPages, page));
        showPage();
    }

    // Initialize on load
    document.addEventListener('DOMContentLoaded', function() {
        const rows = document.querySelectorAll('#appsTable tbody tr');
        filteredRows = Array.from(rows);
        showPage();
    });

    function openVppModal(action, adamId, appName, bundleId) {
        currentAction = action;
        currentAdamId = adamId;
        currentBundleId = bundleId;

        document.getElementById('modalTitle').textContent = action === 'install' ? 'Install VPP App' : 'Remove VPP App';
        document.getElementById('modalAppName').textContent = appName;
        document.getElementById('modalBundleId').textContent = bundleId || adamId;
        const submitBtn = document.getElementById('modalSubmit');
        submitBtn.textContent = action === 'install' ? 'Install' : 'Remove';
        submitBtn.style.background = action === 'install' ? '#e89898' : '#dc2626';
        document.getElementById('modalResult').style.display = 'none';
        document.getElementById('deviceSelect').selectedIndex = -1;

        document.getElementById('vppModal').style.display = 'flex';
    }

    function closeVppModal() {
        document.getElementById('vppModal').style.display = 'none';
    }

    function executeVppAction() {
        const select = document.getElementById('deviceSelect');
        const selectedOptions = Array.from(select.selectedOptions);

        if (selectedOptions.length === 0) {
            alert('Please select at least one device');
            return;
        }

        const devices = selectedOptions.map(opt => {
            const [uuid, serial] = opt.value.split('|');
            return { uuid, serial };
        });

        document.getElementById('modalSubmit').disabled = true;
        document.getElementById('modalSubmit').textContent = 'Processing...';

        fetch('/admin/api/vpp-action', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                action: currentAction,
                adamId: currentAdamId,
                bundleId: currentBundleId,
                devices: devices
            })
        })
        .then(response => response.json())
        .then(data => {
            const resultDiv = document.getElementById('modalResult');
            resultDiv.style.display = 'block';

            if (data.success) {
                resultDiv.className = 'result-box success';
                resultDiv.innerHTML = '<strong>Success!</strong><br>' + (data.output || '').replace(/\\n/g, '<br>');
            } else {
                resultDiv.className = 'result-box error';
                resultDiv.innerHTML = '<strong>Error:</strong> ' + (data.error || 'Unknown error');
            }

            document.getElementById('modalSubmit').disabled = false;
            document.getElementById('modalSubmit').textContent = currentAction === 'install' ? 'Install' : 'Remove';
        })
        .catch(err => {
            const resultDiv = document.getElementById('modalResult');
            resultDiv.style.display = 'block';
            resultDiv.className = 'result-box error';
            resultDiv.innerHTML = '<strong>Error:</strong> ' + err.message;

            document.getElementById('modalSubmit').disabled = false;
            document.getElementById('modalSubmit').textContent = currentAction === 'install' ? 'Install' : 'Remove';
        });
    }
    </script>
</body>
</html>
'''


# =============================================================================
# VPP UPDATES TEMPLATE
# =============================================================================

ADMIN_VPP_UPDATES_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>VPP Updates - NanoHUB Admin</title>
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
        <h1>VPP Updates</h1>

        <div class="panel">
            <div class="admin-header">
                <h2>VPP</h2>
                <div class="nav-tabs" style="margin:0;">
                    <a href="/admin" class="btn">Commands</a>
                    <a href="/admin/devices" class="btn">Devices</a>
                    <a href="/admin/profiles" class="btn">Profiles</a>
                    <a href="/admin/ddm" class="btn">DDM</a>
                    <a href="/admin/vpp" class="btn active">VPP</a>
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

            <div class="sub-tabs">
                <a href="/admin/vpp">Licenses</a>
                <a href="/admin/vpp/updates" class="active">Updates</a>
            </div>

            <!-- Filters -->
            <div class="filter-form">
                <div class="filter-group">
                    <label>OS</label>
                    <select id="filterOS" onchange="filterDevices()">
                        <option value="">All</option>
                        <option value="macos">macOS</option>
                        <option value="ios">iOS</option>
                    </select>
                </div>
                <div class="filter-group">
                    <label>Manifest</label>
                    <select id="filterManifest" onchange="filterDevices()">
                        <option value="">All</option>
                        {% for manifest in manifests %}
                        <option value="{{ manifest }}">{{ manifest }}</option>
                        {% endfor %}
                    </select>
                </div>
                <div class="filter-group">
                    <label>Search</label>
                    <input type="text" id="filterSearch" placeholder="Device name..." onkeyup="filterDevices()">
                </div>
                <div class="filter-buttons" style="margin-left:auto;">
                    <button class="btn btn-purple" onclick="checkUpdates()">Check Updates</button>
                    <button class="btn btn-primary" onclick="applyUpdates()">Apply Updates</button>
                    <button class="btn btn-warning" onclick="refreshAppsData()">Refresh Data</button>
                    <button class="btn" onclick="openManageAppsModal()">Manage Apps</button>
                    <button class="btn" onclick="selectAllPages()">Select All</button>
                    <button class="btn" onclick="deselectAll()">Deselect</button>
                    <span id="selectedCount" class="selected-count">0 selected</span>
                    <label style="display:flex;align-items:center;gap:5px;">
                        <input type="checkbox" id="forceInstall"> Force Install
                    </label>
                </div>
            </div>

            <!-- Loading indicator -->
            <div id="loading" style="display:none;text-align:center;padding:15px;background:#1E1E1E;border:1px solid #5FC812;border-radius:5px;margin-bottom:10px;color:#5FC812;">Processing...</div>

            <!-- Result panel -->
            <div id="resultPanel" class="result-panel">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
                    <strong id="resultTitle">Result</strong>
                    <button class="btn btn-small" onclick="closeResult()">Close</button>
                </div>
                <div class="result-content" id="resultContent"></div>
            </div>

            <!-- Devices table -->
            <div class="table-wrapper">
            <table class="device-table" id="devicesTable">
                <thead>
                    <tr class="select-all-row">
                        <th style="width:40px;"><input type="checkbox" id="selectAll" onchange="toggleSelectAll()"></th>
                        <th class="sortable" data-col="hostname" onclick="sortDevicesTable('hostname')">Device <span class="sort-arrow"></span></th>
                        <th class="sortable" data-col="os" onclick="sortDevicesTable('os')">OS <span class="sort-arrow"></span></th>
                        <th class="sortable" data-col="apps_updated" onclick="sortDevicesTable('apps_updated')">Apps Data <span class="sort-arrow"></span></th>
                        <th class="sortable" data-col="outdated" onclick="sortDevicesTable('outdated')">Outdated Apps <span class="sort-arrow"></span></th>
                        <th class="sortable" data-col="pending" onclick="sortDevicesTable('pending')">Queue <span class="sort-arrow"></span></th>
                    </tr>
                </thead>
                <tbody>
                    {% for device in devices %}
                    <tr data-uuid="{{ device.uuid }}" data-os="{{ device.os }}" data-manifest="{{ device.manifest or '' }}" data-hostname="{{ device.hostname | lower }}" data-apps-updated="{{ device.apps_updated_at.timestamp() if device.apps_updated_at else 0 }}" data-outdated="{{ device.outdated_count if device.outdated_count is defined else -1 }}" data-pending="{{ device.pending_count or 0 }}">
                        <td><input type="checkbox" class="device-checkbox" value="{{ device.uuid }}"></td>
                        <td>
                            <strong>{{ device.hostname }}</strong> <span style="font-size:0.85em;color:#B0B0B0;">({{ device.serial }})</span>
                        </td>
                        <td>
                            <span class="platform-badge platform-{{ device.os }}">{{ 'macOS' if device.os == 'macos' else 'iOS' }}</span>
                        </td>
                        <td>
                            {% if device.apps_updated_at %}
                            <span class="data-age {% if device.hours_old > 168 %}stale{% endif %}">
                                {{ device.apps_updated_at.strftime('%Y-%m-%d %H:%M') if device.apps_updated_at else 'Never' }}{% if device.hours_old %} ({{ device.hours_old }}h ago){% endif %}
                            </span>
                            {% else %}
                            <span class="status-badge status-missing">No data</span>
                            {% endif %}
                        </td>
                        <td>
                            {% if device.outdated_count is defined %}
                                {% if device.outdated_count > 0 %}
                                <span class="badge badge-no outdated-tooltip" data-apps="{{ device.outdated_apps | join('; ') }}" style="cursor:help;">{{ device.outdated_count }} outdated</span>
                                {% else %}
                                <span class="badge badge-yes">All current</span>
                                {% endif %}
                            {% else %}
                            <span style="color:#B0B0B0;">loading..</span>
                            {% endif %}
                        </td>
                        <td>
                            {% if device.pending_count > 0 %}
                            <span class="queue-badge">{{ device.pending_count }} pending</span>
                            {% else %}
                            <span style="color:#B0B0B0;">-</span>
                            {% endif %}
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
            </div>
            <div id="devicePagination" style="margin-top:15px;padding:10px 0;border-top:1px solid #3A3A3A;">
                <div id="devicePageInfo" style="font-size:0.85em;color:#B0B0B0;margin-bottom:8px;"></div>
                <div id="devicePageNumbers" class="pagination"></div>
            </div>
        </div>
    </div>

    <!-- Manage Apps Modal -->
    <div id="manageAppsModal" class="modal-overlay" style="display:none;">
        <div class="modal-box" style="width:500px;">
            <h3>Manage VPP Apps</h3>
            <div class="modal-body">
                <p>Add or remove apps from the managed VPP list.</p>
                <div id="managedAppsList">
                    <h4>macOS Apps:</h4>
                    <div id="macosAppsList" class="managed-apps-list"></div>
                    <div class="app-input-row" style="margin-top:10px;">
                        <input type="text" id="newMacosAdamId" placeholder="Adam ID">
                        <input type="text" id="newMacosBundleId" placeholder="Bundle ID">
                        <input type="text" id="newMacosName" placeholder="App Name">
                        <button class="btn" onclick="addApp('macos')">Add</button>
                    </div>

                    <h4 style="margin-top:20px;">iOS Apps:</h4>
                    <div id="iosAppsList" class="managed-apps-list"></div>
                    <div class="app-input-row" style="margin-top:10px;">
                        <input type="text" id="newIosAdamId" placeholder="Adam ID">
                        <input type="text" id="newIosBundleId" placeholder="Bundle ID">
                        <input type="text" id="newIosName" placeholder="App Name">
                        <button class="btn" onclick="addApp('ios')">Add</button>
                    </div>
                </div>
            </div>
            <div class="modal-footer">
                <button class="btn" onclick="closeManageAppsModal()">Close</button>
                <button class="btn btn-primary" onclick="saveApps()">Save Changes</button>
            </div>
        </div>
    </div>

    <style>
    .custom-tooltip {
        display: none;
        position: fixed;
        background: #2A2A2A;
        color: #B0B0B0;
        padding: 4px 8px;
        border-radius: 3px;
        font-size: 0.75em;
        white-space: nowrap;
        z-index: 99999;
        border: 1px solid #3A3A3A;
        box-shadow: 0 2px 6px rgba(0,0,0,0.25);
        text-align: left;
        pointer-events: none;
    }
    .outdated-tooltip { cursor: help; }
    .custom-tooltip div { padding: 1px 0; }
    </style>

    <script>
    // Global tooltip for VPP
    let vppTooltip = null;

    function showVppTooltip(el, content) {
        if (!vppTooltip) {
            vppTooltip = document.createElement('div');
            vppTooltip.className = 'custom-tooltip';
            document.body.appendChild(vppTooltip);
        }
        vppTooltip.innerHTML = '';
        content.split('; ').forEach(item => {
            if (item.trim()) {
                const line = document.createElement('div');
                line.textContent = item;
                vppTooltip.appendChild(line);
            }
        });
        const rect = el.getBoundingClientRect();
        vppTooltip.style.visibility = 'hidden';
        vppTooltip.style.display = 'block';
        const tooltipHeight = vppTooltip.offsetHeight;
        let top = rect.top - tooltipHeight - 5;
        if (top < 10) top = rect.bottom + 5;
        vppTooltip.style.left = rect.left + 'px';
        vppTooltip.style.top = top + 'px';
        vppTooltip.style.visibility = 'visible';
    }

    function hideVppTooltip() {
        if (vppTooltip) vppTooltip.style.display = 'none';
    }

    // Initialize tooltip events
    document.addEventListener('DOMContentLoaded', function() {
        document.querySelectorAll('.outdated-tooltip').forEach(el => {
            const apps = el.dataset.apps;
            if (apps && apps.trim()) {
                el.addEventListener('mouseenter', () => showVppTooltip(el, apps));
                el.addEventListener('mouseleave', hideVppTooltip);
            }
        });
    });

    let managedApps = { macos: [], ios: [] };
    let devicePage = 1;
    const devicesPerPage = 50;
    let filteredDevices = [];
    let deviceSort = {col: null, dir: 'asc'};

    function sortDevicesTable(col) {
        const tbody = document.querySelector('#devicesTable tbody');
        const rows = Array.from(tbody.querySelectorAll('tr'));

        if (deviceSort.col === col) {
            deviceSort.dir = deviceSort.dir === 'asc' ? 'desc' : 'asc';
        } else {
            deviceSort.col = col;
            deviceSort.dir = 'asc';
        }

        rows.sort((a, b) => {
            let va, vb;
            if (col === 'hostname') {
                va = a.dataset.hostname || '';
                vb = b.dataset.hostname || '';
            } else if (col === 'os') {
                va = a.dataset.os || '';
                vb = b.dataset.os || '';
            } else if (col === 'apps_updated') {
                va = parseFloat(a.dataset.appsUpdated) || 0;
                vb = parseFloat(b.dataset.appsUpdated) || 0;
                return deviceSort.dir === 'asc' ? va - vb : vb - va;
            } else if (col === 'outdated') {
                va = parseInt(a.dataset.outdated) || 0;
                vb = parseInt(b.dataset.outdated) || 0;
                return deviceSort.dir === 'asc' ? va - vb : vb - va;
            } else if (col === 'pending') {
                va = parseInt(a.dataset.pending) || 0;
                vb = parseInt(b.dataset.pending) || 0;
                return deviceSort.dir === 'asc' ? va - vb : vb - va;
            }
            if (va < vb) return deviceSort.dir === 'asc' ? -1 : 1;
            if (va > vb) return deviceSort.dir === 'asc' ? 1 : -1;
            return 0;
        });

        rows.forEach(row => tbody.appendChild(row));

        document.querySelectorAll('#devicesTable th').forEach(th => {
            th.classList.remove('sorted-asc', 'sorted-desc');
            if (th.dataset.col === col) {
                th.classList.add(deviceSort.dir === 'asc' ? 'sorted-asc' : 'sorted-desc');
            }
        });

        filterDevices();
    }

    function filterDevices() {
        const os = document.getElementById('filterOS').value.toLowerCase();
        const manifest = document.getElementById('filterManifest').value;
        const search = document.getElementById('filterSearch').value.toLowerCase();

        const rows = document.querySelectorAll('#devicesTable tbody tr');
        filteredDevices = [];

        rows.forEach(row => {
            const rowOs = row.dataset.os;
            const rowManifest = row.dataset.manifest;
            const rowHostname = row.dataset.hostname;

            let show = true;
            if (os && rowOs !== os) show = false;
            if (manifest && rowManifest !== manifest) show = false;
            if (search && !rowHostname.includes(search)) show = false;

            if (show) {
                filteredDevices.push(row);
            }
            row.style.display = 'none';
        });

        devicePage = 1;
        showDevicePage();
    }

    function showDevicePage() {
        const start = (devicePage - 1) * devicesPerPage;
        const end = start + devicesPerPage;
        const totalPages = Math.ceil(filteredDevices.length / devicesPerPage);

        filteredDevices.forEach((row, idx) => {
            row.style.display = (idx >= start && idx < end) ? '' : 'none';
        });

        document.getElementById('devicePageInfo').textContent =
            filteredDevices.length > 0
            ? `Showing ${start + 1}-${Math.min(end, filteredDevices.length)} of ${filteredDevices.length} (Page ${devicePage} of ${totalPages})`
            : 'No devices found';

        renderDevicePageNumbers(totalPages);
    }

    function renderDevicePageNumbers(totalPages) {
        const container = document.getElementById('devicePageNumbers');
        if (totalPages <= 1) { container.innerHTML = ''; return; }

        let html = '';
        // Prev
        if (devicePage > 1) {
            html += '<a onclick="goToDevicePage(' + (devicePage - 1) + ')">&laquo; Prev</a>';
        } else {
            html += '<span class="disabled">&laquo; Prev</span>';
        }
        // Page numbers
        for (let p = 1; p <= totalPages; p++) {
            if (p === devicePage) {
                html += '<span class="current">' + p + '</span>';
            } else if (p <= 3 || p > totalPages - 2 || (p >= devicePage - 1 && p <= devicePage + 1)) {
                html += '<a onclick="goToDevicePage(' + p + ')">' + p + '</a>';
            } else if (p === 4 || p === totalPages - 2) {
                html += '<span>...</span>';
            }
        }
        // Next
        if (devicePage < totalPages) {
            html += '<a onclick="goToDevicePage(' + (devicePage + 1) + ')">Next &raquo;</a>';
        } else {
            html += '<span class="disabled">Next &raquo;</span>';
        }
        container.innerHTML = html;
    }

    function goToDevicePage(page) {
        const totalPages = Math.ceil(filteredDevices.length / devicesPerPage);
        devicePage = Math.max(1, Math.min(totalPages, page));
        showDevicePage();
    }

    document.addEventListener('DOMContentLoaded', function() {
        const rows = document.querySelectorAll('#devicesTable tbody tr');
        filteredDevices = Array.from(rows);
        showDevicePage();
    });

    function toggleSelectAll() {
        const checked = document.getElementById('selectAll').checked;
        document.querySelectorAll('.device-checkbox').forEach(cb => {
            if (cb.closest('tr').style.display !== 'none') {
                cb.checked = checked;
            }
        });
        updateSelectedCount();
    }

    function selectAllPages() {
        // Select ALL devices across all pages (including hidden/filtered)
        document.querySelectorAll('.device-checkbox').forEach(cb => {
            cb.checked = true;
        });
        document.getElementById('selectAll').checked = true;
        updateSelectedCount();
    }

    function deselectAll() {
        document.querySelectorAll('.device-checkbox').forEach(cb => {
            cb.checked = false;
        });
        document.getElementById('selectAll').checked = false;
        updateSelectedCount();
    }

    function updateSelectedCount() {
        const count = document.querySelectorAll('.device-checkbox:checked').length;
        const el = document.getElementById('selectedCount');
        if (el) el.textContent = count + ' selected';
    }

    // Update count when individual checkbox changes
    document.addEventListener('change', function(e) {
        if (e.target.classList.contains('device-checkbox')) {
            updateSelectedCount();
        }
    });

    function getSelectedDevices() {
        const selected = [];
        // Return ALL checked devices, including those on other pages
        document.querySelectorAll('.device-checkbox:checked').forEach(cb => {
            selected.push(cb.value);
        });
        return selected;
    }

    function showResult(type, content, title) {
        const panel = document.getElementById('resultPanel');
        const contentDiv = document.getElementById('resultContent');
        const titleDiv = document.getElementById('resultTitle');
        panel.className = 'result-panel ' + type;
        panel.style.display = 'block';
        contentDiv.textContent = content;
        titleDiv.textContent = title || 'Result';
    }

    function closeResult() {
        document.getElementById('resultPanel').style.display = 'none';
    }

    function showLoading(show, text) {
        const loading = document.getElementById('loading');
        loading.style.display = show ? 'block' : 'none';
        loading.textContent = text || 'Processing...';
    }

    function checkUpdates() {
        const devices = getSelectedDevices();
        if (devices.length === 0) {
            alert('Please select at least one device');
            return;
        }

        showLoading(true, 'Checking updates for ' + devices.length + ' device(s)...');
        fetch('/admin/api/vpp-updates/check', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ devices: devices })
        })
        .then(r => r.json())
        .then(data => {
            showLoading(false);
            if (data.success) {
                showResult('info', data.report, 'Update Check Results');
            } else {
                showResult('error', data.error, 'Error');
            }
        })
        .catch(err => {
            showLoading(false);
            showResult('error', err.message, 'Error');
        });
    }

    function applyUpdates() {
        const devices = getSelectedDevices();
        const forceInstall = document.getElementById('forceInstall').checked;

        if (devices.length === 0) {
            alert('Please select at least one device');
            return;
        }

        showLoading(true, 'Applying updates to ' + devices.length + ' device(s)...');
        fetch('/admin/api/vpp-updates/apply', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ devices: devices, force: forceInstall })
        })
        .then(r => r.json())
        .then(data => {
            showLoading(false);
            if (data.success) {
                showResult('success', data.report, 'VPP Update Report');
            } else {
                showResult('error', data.error, 'Error');
            }
        })
        .catch(err => {
            showLoading(false);
            showResult('error', err.message, 'Error');
        });
    }

    function refreshAppsData() {
        const devices = getSelectedDevices();
        if (devices.length === 0) {
            alert('Please select at least one device');
            return;
        }

        showLoading(true, 'Sending refresh command to ' + devices.length + ' device(s)...');
        fetch('/admin/api/vpp-updates/refresh', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ devices: devices })
        })
        .then(r => r.json())
        .then(data => {
            showLoading(false);
            if (data.success) {
                showResult('success', data.message || 'Refresh command sent.', 'Refresh Device Data');
            } else {
                showResult('error', data.error, 'Error');
            }
        })
        .catch(err => {
            showLoading(false);
            showResult('error', err.message, 'Error');
        });
    }

    function openManageAppsModal() {
        fetch('/admin/api/vpp-updates/managed-apps')
        .then(r => r.json())
        .then(data => {
            managedApps = data;
            renderManagedApps();
            document.getElementById('manageAppsModal').style.display = 'flex';
        });
    }

    function closeManageAppsModal() {
        document.getElementById('manageAppsModal').style.display = 'none';
    }

    function renderManagedApps() {
        ['macos', 'ios'].forEach(os => {
            const container = document.getElementById(os + 'AppsList');
            container.innerHTML = '';
            (managedApps[os] || []).forEach((app, idx) => {
                const tag = document.createElement('span');
                tag.className = 'managed-app-tag';
                tag.innerHTML = app.name + ' <span class="remove-btn" onclick="removeApp(\\''+os+'\\', '+idx+')">&times;</span>';
                container.appendChild(tag);
            });
        });
    }

    function addApp(os) {
        const adamId = document.getElementById('new' + os.charAt(0).toUpperCase() + os.slice(1) + 'AdamId').value;
        const bundleId = document.getElementById('new' + os.charAt(0).toUpperCase() + os.slice(1) + 'BundleId').value;
        const name = document.getElementById('new' + os.charAt(0).toUpperCase() + os.slice(1) + 'Name').value;

        if (!adamId || !bundleId || !name) {
            alert('Please fill all fields');
            return;
        }

        managedApps[os].push({ adamId, bundleId, name });
        renderManagedApps();

        // Clear inputs
        document.getElementById('new' + os.charAt(0).toUpperCase() + os.slice(1) + 'AdamId').value = '';
        document.getElementById('new' + os.charAt(0).toUpperCase() + os.slice(1) + 'BundleId').value = '';
        document.getElementById('new' + os.charAt(0).toUpperCase() + os.slice(1) + 'Name').value = '';
    }

    function removeApp(os, idx) {
        managedApps[os].splice(idx, 1);
        renderManagedApps();
    }

    function saveApps() {
        fetch('/admin/api/vpp-updates/managed-apps', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(managedApps)
        })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                alert('Apps saved successfully');
                closeManageAppsModal();
            } else {
                alert('Error: ' + data.error);
            }
        });
    }
    </script>
</body>
</html>
'''
@vpp_bp.route('/vpp')
@login_required_admin
def admin_vpp():
    """VPP Licenses page - shows ABM app licenses"""
    from datetime import datetime

    user = session.get('user', {})

    # Get token info
    token_info = _get_vpp_token_info()
    org_name = token_info.get('orgName', 'Unknown') if token_info else 'Unknown'
    token_expiry = token_info.get('expDate', 'Unknown') if token_info else 'Unknown'

    # Check if token expires within 30 days
    token_warning = False
    if token_info and token_info.get('expDate'):
        try:
            exp_date = datetime.strptime(token_info['expDate'][:19], '%Y-%m-%dT%H:%M:%S')
            days_until_expiry = (exp_date - datetime.now()).days
            token_warning = days_until_expiry < 30
        except Exception:
            pass

    # Format expiry date nicely
    if token_expiry and token_expiry != 'Unknown':
        try:
            exp_date = datetime.strptime(token_expiry[:19], '%Y-%m-%dT%H:%M:%S')
            token_expiry = exp_date.strftime('%Y-%m-%d')
        except Exception:
            pass

    # Get devices for install/remove modal
    devices = []
    try:
        devices = db.query_all("SELECT uuid, serial, os, hostname FROM device_inventory ORDER BY hostname")
    except Exception as e:
        logger.error(f"Failed to get devices: {e}")

    # Get VPP apps
    vpp_data = _get_vpp_apps_with_names()

    if 'error' in vpp_data:
        return render_template_string(
            ADMIN_VPP_TEMPLATE,
            user=user,
            error=vpp_data['error'],
            apps=[],
            devices=devices,
            org_name=org_name,
            token_expiry=token_expiry,
            token_warning=token_warning,
            total_apps=0,
            total_licenses=0,
            assigned_licenses=0,
            available_licenses=0
        )

    apps = vpp_data.get('apps', [])

    # Calculate totals
    total_licenses = sum(app.get('totalCount', 0) for app in apps)
    assigned_licenses = sum(app.get('assignedCount', 0) for app in apps)
    available_licenses = sum(app.get('availableCount', 0) for app in apps)

    return render_template_string(
        ADMIN_VPP_TEMPLATE,
        user=user,
        apps=apps,
        devices=devices,
        org_name=org_name,
        token_expiry=token_expiry,
        token_warning=token_warning,
        total_apps=len(apps),
        total_licenses=total_licenses,
        assigned_licenses=assigned_licenses,
        available_licenses=available_licenses,
        error=None
    )


@vpp_bp.route('/vpp/updates')
@login_required_admin
def admin_vpp_updates():
    """VPP Updates page - manage app updates across devices"""
    import json
    from datetime import datetime

    user = session.get('user', {})
    manifest_filter = user.get('manifest_filter')  # e.g. 'bel-%' for bel-admin

    # Get manifests for filter from DB (filtered by user's manifest_filter if applicable)
    manifests = _get_manifests_list(manifest_filter)

    # Build WHERE clause for manifest filter
    where_clause = ""
    query_params = []
    if manifest_filter:
        where_clause = "WHERE di.manifest LIKE %s"
        query_params.append(manifest_filter)

    # Get devices with apps data and pending command counts
    devices = []
    try:
        rows = db.query_all(f"""
            SELECT
                di.uuid,
                di.serial,
                di.os,
                di.hostname,
                di.manifest,
                dd.apps_data,
                dd.apps_updated_at,
                TIMESTAMPDIFF(HOUR, dd.apps_updated_at, NOW()) as hours_old,
                (SELECT COUNT(*) FROM commands c
                 JOIN enrollment_queue eq ON c.command_uuid = eq.command_uuid
                 LEFT JOIN command_results cr ON c.command_uuid = cr.command_uuid AND cr.id = eq.id
                 WHERE eq.id = di.uuid AND c.request_type = 'InstallApplication' AND cr.command_uuid IS NULL) as pending_count
            FROM device_inventory di
            LEFT JOIN device_details dd ON di.uuid = dd.uuid
            {where_clause}
            ORDER BY di.hostname
        """, query_params if query_params else None)

        # Load expected versions from JSON (with app names)
        expected_versions = {'macos': {}, 'ios': {}}
        for os_type in ['macos', 'ios']:
            json_path = os.path.join(Config.DATA_DIR, f'apps_{os_type}_with_versions.json')
            try:
                with open(json_path, 'r') as f:
                    apps_data = json.load(f)
                    for app in apps_data.get('apps', []):
                        expected_versions[os_type][app['bundleId']] = {
                            'version': app.get('version', 'unknown'),
                            'name': app.get('name', app['bundleId'])
                        }
            except Exception:
                pass

        for row in rows:
            device = dict(row)

            # Count outdated apps and track which ones
            outdated_count = 0
            outdated_apps = []
            if row['apps_data'] and row['os'] in expected_versions:
                try:
                    installed_apps = json.loads(row['apps_data']) if isinstance(row['apps_data'], str) else row['apps_data']
                    expected = expected_versions[row['os']]
                    for app in installed_apps:
                        bundle_id = app.get('identifier', '')
                        if bundle_id in expected:
                            installed_ver = app.get('version', '')
                            expected_ver = expected[bundle_id]['version']
                            app_name = expected[bundle_id]['name']
                            if installed_ver and expected_ver and installed_ver != expected_ver:
                                # Simple version comparison
                                if expected_ver > installed_ver:
                                    outdated_count += 1
                                    outdated_apps.append(f"{app_name}: {installed_ver} → {expected_ver}")
                except Exception:
                    pass

            device['outdated_count'] = outdated_count
            device['outdated_apps'] = outdated_apps
            devices.append(device)

    except Exception as e:
        logger.error(f"Failed to get devices: {e}")

    return render_template_string(
        ADMIN_VPP_UPDATES_TEMPLATE,
        user=user,
        devices=devices,
        manifests=manifests
    )


@vpp_bp.route('/api/vpp-updates/check', methods=['POST'])
@login_required_admin
def api_vpp_updates_check():
    """Check for VPP updates (dry run)"""
    import json

    data = request.get_json()
    device_uuids = data.get('devices', [])

    if not device_uuids:
        return jsonify({'success': False, 'error': 'No devices selected'})

    # Load expected versions
    expected_versions = {'macos': {}, 'ios': {}}
    for os_type in ['macos', 'ios']:
        json_path = os.path.join(Config.DATA_DIR, f'apps_{os_type}_with_versions.json')
        try:
            with open(json_path, 'r') as f:
                apps_data = json.load(f)
                for app in apps_data.get('apps', []):
                    expected_versions[os_type][app['bundleId']] = {
                        'version': app.get('version', 'unknown'),
                        'name': app.get('name', app['bundleId']),
                        'adamId': app.get('adamId')
                    }
        except Exception as e:
            logger.error(f"Failed to load {os_type} apps: {e}")

    report_lines = ["VPP UPDATE CHECK REPORT", "=" * 50, ""]

    for uuid in device_uuids:
        # Get device info
        device = db.query_one("""
            SELECT di.hostname, di.os, dd.apps_data
            FROM device_inventory di
            LEFT JOIN device_details dd ON di.uuid = dd.uuid
            WHERE di.uuid = %s
        """, (uuid,))

        if not device:
            report_lines.append(f"[SKIP] Device {uuid} not found")
            continue

        hostname = device['hostname']
        os_type = device['os']
        apps_data = device['apps_data']

        if not apps_data:
            report_lines.append(f"[SKIP] {hostname} - No apps data")
            continue

        expected = expected_versions.get(os_type, {})
        if not expected:
            report_lines.append(f"[SKIP] {hostname} - No managed apps for {os_type}")
            continue

        try:
            installed_apps = json.loads(apps_data) if isinstance(apps_data, str) else apps_data
            installed_map = {app.get('identifier', ''): app.get('version', '') for app in installed_apps}
        except Exception:
            report_lines.append(f"[ERROR] {hostname} - Failed to parse apps data")
            continue

        report_lines.append(f"{hostname} ({os_type}):")

        device_updates = []
        device_installs = []
        device_current = []

        for bundle_id, app_info in expected.items():
            app_name = app_info['name']
            expected_ver = app_info['version']
            installed_ver = installed_map.get(bundle_id)

            if not installed_ver:
                device_installs.append(f"  [INSTALL] {app_name} v{expected_ver}")
            elif installed_ver != expected_ver and expected_ver > installed_ver:
                device_updates.append(f"  [UPDATE] {app_name}: v{installed_ver} -> v{expected_ver}")
            else:
                device_current.append(f"  [CURRENT] {app_name} v{installed_ver}")

        for line in device_installs + device_updates:
            report_lines.append(line)

        if not device_installs and not device_updates:
            report_lines.append("  All apps are current")

        report_lines.append("")

    return jsonify({'success': True, 'report': '\n'.join(report_lines)})


@vpp_bp.route('/api/vpp-updates/apply', methods=['POST'])
@login_required_admin
def api_vpp_updates_apply():
    """Apply VPP updates"""
    import json
    import subprocess

    user_info = session.get('user', {})
    data = request.get_json()
    device_uuids = data.get('devices', [])
    force_install = data.get('force', False)

    if not device_uuids:
        return jsonify({'success': False, 'error': 'No devices selected'})

    # Load expected versions
    expected_versions = {'macos': {}, 'ios': {}}
    for os_type in ['macos', 'ios']:
        json_path = os.path.join(Config.DATA_DIR, f'apps_{os_type}_with_versions.json')
        try:
            with open(json_path, 'r') as f:
                apps_data = json.load(f)
                for app in apps_data.get('apps', []):
                    expected_versions[os_type][app['bundleId']] = {
                        'version': app.get('version', 'unknown'),
                        'name': app.get('name', app['bundleId']),
                        'adamId': app.get('adamId')
                    }
        except Exception as e:
            logger.error(f"Failed to load {os_type} apps: {e}")

    install_script = os.path.join(Config.COMMANDS_DIR, 'install_vpp_app')
    report_lines = ["VPP UPDATE APPLY REPORT", "=" * 50, ""]

    total_installed = 0
    total_updated = 0

    for uuid in device_uuids:
        device = db.query_one("""
            SELECT di.hostname, di.os, di.serial, dd.apps_data
            FROM device_inventory di
            LEFT JOIN device_details dd ON di.uuid = dd.uuid
            WHERE di.uuid = %s
        """, (uuid,))

        if not device:
            continue

        hostname = device['hostname']
        os_type = device['os']
        serial = device['serial']
        apps_data = device['apps_data']

        expected = expected_versions.get(os_type, {})
        if not expected:
            continue

        installed_map = {}
        if apps_data:
            try:
                installed_apps = json.loads(apps_data) if isinstance(apps_data, str) else apps_data
                installed_map = {app.get('identifier', ''): app.get('version', '') for app in installed_apps}
            except Exception:
                pass

        report_lines.append(f"{hostname}:")

        for bundle_id, app_info in expected.items():
            app_name = app_info['name']
            expected_ver = app_info['version']
            adam_id = app_info['adamId']
            installed_ver = installed_map.get(bundle_id)

            should_install = False
            action_type = None

            if not installed_ver:
                should_install = True
                action_type = "INSTALL"
            elif force_install:
                should_install = True
                action_type = "FORCE"
            elif installed_ver != expected_ver and expected_ver > installed_ver:
                should_install = True
                action_type = "UPDATE"

            if should_install and adam_id:
                try:
                    # Remove pending commands for this app first
                    db.execute("""
                        DELETE eq FROM enrollment_queue eq
                        JOIN commands c ON eq.command_uuid = c.command_uuid
                        LEFT JOIN command_results cr ON c.command_uuid = cr.command_uuid AND cr.id = eq.id
                        WHERE eq.id = %s
                        AND c.request_type = 'InstallApplication'
                        AND c.command LIKE %s
                        AND cr.command_uuid IS NULL
                    """, (uuid, f'%<integer>{adam_id}</integer>%'))

                    # Execute install script
                    result = subprocess.run(
                        [install_script, uuid, str(adam_id), serial, bundle_id],
                        capture_output=True,
                        text=True,
                        timeout=60
                    )

                    # Check if success by looking at output
                    output = result.stdout + result.stderr
                    if 'successfully' in output.lower() or 'license assigned' in output.lower():
                        report_lines.append(f"  [{action_type}] {app_name} - queued")
                        if action_type == "INSTALL":
                            total_installed += 1
                        else:
                            total_updated += 1
                    else:
                        error_msg = output[:100] if output else f"Exit code {result.returncode}"
                        report_lines.append(f"  [ERROR] {app_name} - {error_msg}")

                except Exception as e:
                    report_lines.append(f"  [ERROR] {app_name} - {str(e)[:50]}")

        report_lines.append("")

    report_lines.append("=" * 50)
    report_lines.append(f"Total: {total_installed} installed, {total_updated} updated")

    _audit_log(
        user=user_info.get('username'),
        action='vpp_updates_apply',
        command='vpp_updates_apply',
        params={'devices': device_uuids, 'force': force_install},
        result=f'{total_installed} installed, {total_updated} updated',
        success=True
    )

    return jsonify({'success': True, 'report': '\n'.join(report_lines)})


@vpp_bp.route('/api/vpp-updates/refresh', methods=['POST'])
@login_required_admin
def api_vpp_updates_refresh():
    """Send all device query commands to refresh all device data (hardware, security, profiles, apps)"""
    import uuid as uuid_module
    import urllib.request
    import base64

    user_info = session.get('user', {})
    data = request.get_json()
    device_uuids = data.get('devices', [])

    if not device_uuids:
        return jsonify({'success': False, 'error': 'No devices selected'})

    # Load API key from environment file (service may not have env vars)
    api_key = Config.MDM_API_KEY
    try:
        with open(Config.ENVIRONMENT_FILE, 'r') as f:
            for line in f:
                if line.startswith('export NANOHUB_API_KEY='):
                    api_key = line.split('=', 1)[1].strip().strip('"\'')
                    break
    except Exception:
        pass

    # MDM API config
    mdm_api = Config.MDM_ENQUEUE_URL
    mdm_push = Config.MDM_PUSH_URL
    auth_string = base64.b64encode(f'{Config.MDM_API_USER}:{api_key}'.encode()).decode()

    # All MDM commands to send for complete device data refresh
    commands = [
        ('DeviceInformation', ['DeviceName', 'OSVersion', 'BuildVersion', 'ModelName', 'Model', 'ProductName', 'SerialNumber', 'UDID', 'IsSupervised', 'IsMultiUser', 'DeviceCapacity', 'AvailableDeviceCapacity', 'BatteryLevel', 'WiFiMAC', 'BluetoothMAC', 'EthernetMAC']),
        ('SecurityInfo', None),
        ('ProfileList', None),
        ('InstalledApplicationList', None),
        ('DeclarativeManagement', None),  # Triggers DDM sync - device sends declaration status
    ]

    success_count = 0
    total_commands = 0
    errors = []

    for device_uuid in device_uuids:
        device_success = True
        try:
            # Send push to wake device
            try:
                push_req = urllib.request.Request(f'{mdm_push}/{device_uuid}', method='POST')
                push_req.add_header('Authorization', f'Basic {auth_string}')
                urllib.request.urlopen(push_req, timeout=5)
            except Exception:
                pass  # Push failure is not critical

            # Send all commands for this device
            for cmd_type, queries in commands:
                cmd_uuid = str(uuid_module.uuid4())

                if cmd_type == 'DeviceInformation' and queries:
                    queries_xml = ''.join([f'<string>{q}</string>' for q in queries])
                    plist = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Command</key>
    <dict>
        <key>RequestType</key>
        <string>{cmd_type}</string>
        <key>Queries</key>
        <array>{queries_xml}</array>
    </dict>
    <key>CommandUUID</key>
    <string>{cmd_uuid}</string>
</dict>
</plist>'''
                else:
                    plist = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Command</key>
    <dict>
        <key>RequestType</key>
        <string>{cmd_type}</string>
    </dict>
    <key>CommandUUID</key>
    <string>{cmd_uuid}</string>
</dict>
</plist>'''

                try:
                    url = f'{mdm_api}/{device_uuid}'
                    req = urllib.request.Request(url, data=plist.encode('utf-8'), method='PUT')
                    req.add_header('Content-Type', 'application/xml')
                    req.add_header('Authorization', f'Basic {auth_string}')

                    with urllib.request.urlopen(req, timeout=10) as resp:
                        if resp.status == 200:
                            total_commands += 1
                        else:
                            device_success = False
                except Exception as e:
                    device_success = False
                    logger.error(f"Failed {cmd_type} for {device_uuid}: {e}")

            if device_success:
                success_count += 1
                logger.info(f"All refresh commands queued for {device_uuid}")

        except Exception as e:
            logger.error(f"Failed to queue refresh for {device_uuid}: {e}")
            errors.append(f"{device_uuid}: {str(e)[:50]}")

    _audit_log(
        user=user_info.get('username'),
        action='refresh_device_data',
        command='refresh_device_data',
        params={'devices': device_uuids},
        result=f'{success_count}/{len(device_uuids)} devices, {total_commands} commands queued',
        success=True
    )

    message = f'Refresh commands queued for {success_count}/{len(device_uuids)} devices ({total_commands} total commands: DeviceInfo, Security, Profiles, Apps, DDM).'
    if errors:
        message += f' Errors: {"; ".join(errors[:5])}'
        if len(errors) > 5:
            message += f' (+{len(errors)-5} more)'

    # Also refresh DDM cache for each device
    ddm_refreshed = 0
    for device_uuid in device_uuids:
        try:
            # Get DDM status from status_declarations table
            status_rows = db.query_all("""
                SELECT declaration_identifier, active, valid, server_token, updated_at
                FROM status_declarations
                WHERE enrollment_id = %s
            """, (device_uuid,))

            if status_rows:
                declarations = []
                for row in status_rows:
                    is_active = row.get('active') == 1 or row.get('active') == True
                    is_valid = row.get('valid') == 1 or row.get('valid') == True or row.get('valid') == 'valid'
                    declarations.append({
                        'identifier': row.get('declaration_identifier', ''),
                        'active': is_active,
                        'valid': is_valid
                    })

                # Cache in device_details
                db.execute("""
                    INSERT INTO device_details (uuid, ddm_data, ddm_updated_at)
                    VALUES (%s, %s, NOW())
                    ON DUPLICATE KEY UPDATE ddm_data = VALUES(ddm_data), ddm_updated_at = NOW()
                """, (device_uuid, json.dumps(declarations)))
                ddm_refreshed += 1
        except Exception as e:
            logger.warning(f"Failed to refresh DDM cache for {device_uuid}: {e}")

    if ddm_refreshed > 0:
        message += f' DDM cache updated for {ddm_refreshed} devices.'

    return jsonify({
        'success': success_count > 0 or len(device_uuids) == 0,
        'message': message
    })


@vpp_bp.route('/api/vpp-updates/managed-apps', methods=['GET', 'POST'])
@login_required_admin
def api_vpp_managed_apps():
    """Get or update managed VPP apps list"""
    import json

    macos_path = Config.APPS_MACOS_JSON
    ios_path = Config.APPS_IOS_JSON

    if request.method == 'GET':
        result = {'macos': [], 'ios': []}
        for os_type, path in [('macos', macos_path), ('ios', ios_path)]:
            try:
                with open(path, 'r') as f:
                    data = json.load(f)
                    result[os_type] = data.get('apps', [])
            except Exception:
                pass
        return jsonify(result)

    else:  # POST
        user_info = session.get('user', {})
        data = request.get_json()

        try:
            # Save macOS apps
            with open(macos_path, 'w') as f:
                json.dump({'apps': data.get('macos', [])}, f, indent=2)

            # Save iOS apps
            with open(ios_path, 'w') as f:
                json.dump({'apps': data.get('ios', [])}, f, indent=2)

            macos_count = len(data.get('macos', []))
            ios_count = len(data.get('ios', []))

            _audit_log(
                user=user_info.get('username'),
                action='vpp_managed_apps_save',
                command='vpp_managed_apps_save',
                params={'macos_apps': macos_count, 'ios_apps': ios_count},
                result=f'Saved {macos_count} macOS apps, {ios_count} iOS apps',
                success=True
            )

            return jsonify({'success': True})

        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})


@vpp_bp.route('/api/vpp-action', methods=['POST'])
@login_required_admin
def api_vpp_action():
    """Execute VPP install/remove action"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    user_info = session.get('user', {})
    data = request.get_json()

    action = data.get('action')  # 'install' or 'remove'
    adam_id = data.get('adamId')
    bundle_id = data.get('bundleId')
    devices = data.get('devices', [])  # [{uuid, serial}, ...]

    if not action or action not in ['install', 'remove']:
        return jsonify({'success': False, 'error': 'Invalid action'})
    if not adam_id:
        return jsonify({'success': False, 'error': 'Missing adamId'})
    if not devices:
        return jsonify({'success': False, 'error': 'No devices selected'})

    # Scripts
    install_script = os.path.join(Config.COMMANDS_DIR, 'install_vpp_app')
    remove_script = os.path.join(Config.COMMANDS_DIR, 'remove_vpp_app')
    script_path = install_script if action == 'install' else remove_script

    output_lines = []
    success_count = 0
    fail_count = 0

    def run_vpp_cmd(device):
        udid = device.get('uuid')
        serial = device.get('serial')
        try:
            env = os.environ.copy()
            env['PATH'] = '/usr/local/bin:/usr/bin:/bin:' + env.get('PATH', '')

            # Load VPP_TOKEN
            try:
                with open(Config.ENVIRONMENT_FILE, 'r') as f:
                    for line in f:
                        if line.startswith('export VPP_TOKEN='):
                            env['VPP_TOKEN'] = line.split('=', 1)[1].strip().strip('"\'')
                        elif line.startswith('export NANOHUB_API_KEY='):
                            env['NANOHUB_API_KEY'] = line.split('=', 1)[1].strip().strip('"\'')
            except Exception:
                pass

            if action == 'install':
                # install_vpp_app <UDID> <ADAM_ID> <SERIAL> <BUNDLE_ID>
                args = [script_path, udid, adam_id, serial, bundle_id or adam_id]
            else:
                # remove_vpp_app <UDID> <ADAM_ID> <SERIAL> <BUNDLE_ID>
                args = [script_path, udid, adam_id, serial, bundle_id or adam_id]

            result = subprocess.run(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=60,
                env=env
            )

            if result.returncode == 0:
                return {'success': True, 'udid': udid, 'output': result.stdout}
            else:
                return {'success': False, 'udid': udid, 'error': result.stderr or result.stdout or 'Command failed'}

        except subprocess.TimeoutExpired:
            return {'success': False, 'udid': udid, 'error': 'Timeout'}
        except Exception as e:
            return {'success': False, 'udid': udid, 'error': str(e)}

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(run_vpp_cmd, d): d for d in devices}
        for future in as_completed(futures):
            result = future.result()
            if result['success']:
                success_count += 1
                output_lines.append(f"[OK] {result['udid']}")
            else:
                fail_count += 1
                output_lines.append(f"[FAIL] {result['udid']}: {result.get('error', 'Unknown')}")

    output_lines.append(f"\nSummary: {success_count} success, {fail_count} failed")

    _audit_log(
        user=user_info.get('username'),
        action=f'vpp_{action}',
        command=f'vpp_{action}',
        params={'adamId': adam_id, 'bundleId': bundle_id, 'devices': [d.get('uuid') for d in devices]},
        result=f'{success_count} success, {fail_count} failed',
        success=(fail_count == 0)
    )

    return jsonify({
        'success': fail_count == 0,
        'output': '\n'.join(output_lines)
    })
