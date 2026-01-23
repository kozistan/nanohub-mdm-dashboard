"""
NanoHUB Admin - Devices Routes
==============================
Device inventory list and device detail pages.
"""

import json
import logging

from flask import Blueprint, render_template_string, session, request, jsonify

from db_utils import db
from nanohub_admin.utils import login_required_admin
from nanohub_admin.core import (
    get_manifests_list,
    get_devices_full,
    validate_device_access,
    get_device_detail,
    get_device_command_history,
    execute_device_query,
    get_device_details,
)

logger = logging.getLogger('nanohub_admin')

# Create a blueprint for Devices routes
devices_bp = Blueprint('admin_devices', __name__)


# =============================================================================
# ADMIN DEVICES LIST TEMPLATE
# =============================================================================

ADMIN_DEVICES_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Devices - NanoHUB Admin</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="/static/dashboard.css">
    <link rel="stylesheet" href="/static/css/qbone.css">
    <link rel="stylesheet" href="/static/css/admin.css?v=4">
    <link rel="shortcut icon" href="/static/favicon.ico">
</head>
<body class="page-with-table">
    <div id="wrap">
        <div style="display: flex; justify-content: center; align-items: center;">
            <img id="logo" src="{{ current_logo }}" alt="Logo" style="max-height:60px;max-width:200px;"/>
        </div>
        <h1>Device Inventory</h1>

        <div class="panel">
            <div class="admin-header">
                <h2>Devices <span class="device-count" id="device-count"></span></h2>
                <div class="nav-tabs" style="margin:0;">
                    <a href="/admin" class="btn">Commands</a>
                    <a href="/admin/devices" class="btn active">Devices</a>
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

            <div class="filter-form">
                <div class="filter-group">
                    <label>Search</label>
                    <input type="text" id="search-input" placeholder="Hostname, serial, UUID..." onkeyup="filterDevices()">
                </div>
                <div class="filter-group">
                    <label>OS</label>
                    <select id="os-filter" onchange="filterDevices()">
                        <option value="">All</option>
                        <option value="macos">macOS</option>
                        <option value="ios">iOS</option>
                    </select>
                </div>
                <div class="filter-group">
                    <label>Status</label>
                    <select id="status-filter" onchange="filterDevices()">
                        <option value="">All</option>
                        <option value="online">Online</option>
                        <option value="active">Active</option>
                        <option value="offline">Offline</option>
                    </select>
                </div>
                <div class="filter-group">
                    <label>Supervised</label>
                    <select id="supervised-filter" onchange="filterDevices()">
                        <option value="">All</option>
                        <option value="Yes">Yes</option>
                        <option value="No">No</option>
                    </select>
                </div>
                <div class="filter-group">
                    <label>Encrypted</label>
                    <select id="encrypted-filter" onchange="filterDevices()">
                        <option value="">All</option>
                        <option value="Yes">Yes</option>
                        <option value="No">No</option>
                    </select>
                </div>
                <div class="filter-group">
                    <label>Outdated</label>
                    <select id="outdated-filter" onchange="filterDevices()">
                        <option value="">All</option>
                        <option value="Yes">Yes</option>
                        <option value="No">No</option>
                    </select>
                </div>
                <div class="filter-group">
                    <label>Manifest</label>
                    <select id="manifest-filter" onchange="filterDevices()">
                        <option value="">All</option>
                        {% for m in manifests %}<option value="{{ m }}">{{ m }}</option>{% endfor %}
                    </select>
                </div>
                <div class="filter-buttons" style="margin-left:auto;">
                    <button class="btn" onclick="selectAllFiltered()">Select All</button>
                    <button class="btn" onclick="deselectAll()">Deselect</button>
                    <span class="selected-count" id="selectedCount">0 selected</span>
                    <button class="btn btn-warning" onclick="refreshDeviceData()">Refresh Data</button>
                </div>
            </div>

            <div id="loading" style="display:none;text-align:center;padding:15px;background:#1E1E1E;border:1px solid #5FC812;border-radius:5px;margin-bottom:10px;">
                <span style="color:#5FC812;">Processing...</span>
            </div>
            <div id="resultPanel" style="display:none;padding:12px;border-radius:5px;margin-bottom:10px;">
                <div style="display:flex;justify-content:space-between;align-items:center;">
                    <strong id="resultTitle">Result</strong>
                    <button class="btn btn-small" onclick="closeResult()">Close</button>
                </div>
                <div id="resultContent" style="margin-top:8px;white-space:pre-wrap;"></div>
            </div>

            <div class="table-wrapper">
                <table class="device-table" id="adminDevicesTable">
                    <thead>
                        <tr>
                            <th style="width:30px;"><input type="checkbox" id="selectAllCheckbox" onchange="toggleSelectAll()"></th>
                            <th class="sortable" data-col="hostname" onclick="sortDevices('hostname')">Hostname <span class="sort-arrow"></span></th>
                            <th class="sortable" data-col="serial" onclick="sortDevices('serial')">Serial <span class="sort-arrow"></span></th>
                            <th class="sortable" data-col="os" onclick="sortDevices('os')">OS <span class="sort-arrow"></span></th>
                            <th class="sortable" data-col="os_version" onclick="sortDevices('os_version')">Version <span class="sort-arrow"></span></th>
                            <th class="sortable" data-col="model" onclick="sortDevices('model')">Model <span class="sort-arrow"></span></th>
                            <th class="sortable" data-col="manifest" onclick="sortDevices('manifest')">Manifest <span class="sort-arrow"></span></th>
                            <th class="sortable" data-col="dep" onclick="sortDevices('dep')">DEP <span class="sort-arrow"></span></th>
                            <th class="sortable" data-col="supervised" onclick="sortDevices('supervised')">Supervised <span class="sort-arrow"></span></th>
                            <th class="sortable" data-col="encrypted" onclick="sortDevices('encrypted')">Encrypted <span class="sort-arrow"></span></th>
                            <th class="sortable" data-col="outdated" onclick="sortDevices('outdated')">Outdated <span class="sort-arrow"></span></th>
                            <th class="sortable" data-col="last_seen" onclick="sortDevices('last_seen')">Last Check-in <span class="sort-arrow"></span></th>
                            <th class="sortable" data-col="status" onclick="sortDevices('status')" style="text-align:center;">Status <span class="sort-arrow"></span></th>
                        </tr>
                    </thead>
                    <tbody id="device-tbody">
                        <tr><td colspan="13" style="text-align:center;color:#B0B0B0;">Loading devices...</td></tr>
                    </tbody>
                </table>
            </div>
            <div id="pagination-container" style="margin-top:15px;padding:10px 0;border-top:1px solid #e7eaf2;">
                <div id="page-info" style="font-size:0.85em;color:#6b7280;margin-bottom:8px;"></div>
                <div class="pagination" id="pagination"></div>
            </div>
        </div>
    </div>

    <script>
        let allDevices = [];
        let filteredDevices = [];
        let selectedUuids = new Set();
        let currentSort = {col: 'hostname', dir: 'asc'};
        let currentPage = 1;
        const itemsPerPage = 50;

        async function loadDevices() {
            try {
                const response = await fetch('/admin/api/devices');
                if (!response.ok) throw new Error('Failed to load devices');
                allDevices = await response.json();
                filterDevices();
            } catch (error) {
                document.getElementById('device-tbody').innerHTML =
                    '<tr><td colspan="13" style="text-align:center;color:#dc2626;">Error loading devices</td></tr>';
            }
        }

        function sortDevices(col) {
            if (currentSort.col === col) {
                currentSort.dir = currentSort.dir === 'asc' ? 'desc' : 'asc';
            } else {
                currentSort.col = col;
                currentSort.dir = 'asc';
            }
            document.querySelectorAll('#adminDevicesTable th').forEach(th => {
                th.classList.remove('sorted-asc', 'sorted-desc');
                if (th.dataset.col === col) {
                    th.classList.add(currentSort.dir === 'asc' ? 'sorted-asc' : 'sorted-desc');
                }
            });
            filterDevices();
        }

        function filterDevices() {
            const search = document.getElementById('search-input').value.toLowerCase();
            const osFilter = document.getElementById('os-filter').value;
            const statusFilter = document.getElementById('status-filter').value;
            const supervisedFilter = document.getElementById('supervised-filter').value;
            const encryptedFilter = document.getElementById('encrypted-filter').value;
            const outdatedFilter = document.getElementById('outdated-filter').value;
            const manifestFilter = document.getElementById('manifest-filter').value;

            filteredDevices = allDevices.filter(dev => {
                const matchSearch = !search ||
                    (dev.hostname && dev.hostname.toLowerCase().includes(search)) ||
                    (dev.serial && dev.serial.toLowerCase().includes(search)) ||
                    (dev.uuid && dev.uuid.toLowerCase().includes(search));
                const matchOS = !osFilter || dev.os === osFilter;
                const matchStatus = !statusFilter || dev.status === statusFilter;
                const matchSupervised = !supervisedFilter || dev.supervised === supervisedFilter;
                const matchEncrypted = !encryptedFilter || dev.encrypted === encryptedFilter;
                const matchOutdated = !outdatedFilter || dev.outdated === outdatedFilter;
                const matchManifest = !manifestFilter || dev.manifest === manifestFilter;
                return matchSearch && matchOS && matchStatus && matchSupervised && matchEncrypted && matchOutdated && matchManifest;
            });

            // Sort
            filteredDevices.sort((a, b) => {
                let va = a[currentSort.col] || '';
                let vb = b[currentSort.col] || '';
                if (typeof va === 'string') va = va.toLowerCase();
                if (typeof vb === 'string') vb = vb.toLowerCase();
                if (va < vb) return currentSort.dir === 'asc' ? -1 : 1;
                if (va > vb) return currentSort.dir === 'asc' ? 1 : -1;
                return 0;
            });

            currentPage = 1;
            renderDevices();
            document.getElementById('device-count').textContent = '(' + filteredDevices.length + ' of ' + allDevices.length + ')';
        }

        // Helper: normalize boolean-like values to Yes/No
        function isYesValue(val) {
            if (val === null || val === undefined || val === '') return false;
            const v = String(val).toLowerCase().trim();
            return v === 'yes' || v === '1' || v === 'true' || v === 'enabled';
        }
        function toYesNo(val) {
            return isYesValue(val) ? 'Yes' : 'No';
        }

        function renderDevices() {
            const tbody = document.getElementById('device-tbody');
            if (!filteredDevices.length) {
                tbody.innerHTML = '<tr><td colspan="13" style="text-align:center;color:#B0B0B0;">No devices found</td></tr>';
                updatePagination(0);
                return;
            }

            const totalPages = Math.ceil(filteredDevices.length / itemsPerPage);
            const start = (currentPage - 1) * itemsPerPage;
            const end = start + itemsPerPage;
            const pageDevices = filteredDevices.slice(start, end);

            let html = '';
            pageDevices.forEach(dev => {
                const checked = selectedUuids.has(dev.uuid) ? 'checked' : '';
                const statusClass = dev.status || 'offline';
                const osClass = (dev.os || '').toLowerCase();
                html += `<tr>
                    <td><input type="checkbox" class="device-checkbox" value="${dev.uuid}" ${checked} onchange="toggleDevice('${dev.uuid}')"></td>
                    <td><a href="/admin/device/${dev.uuid}" class="device-link">${dev.hostname || '-'}</a></td>
                    <td>${dev.serial || '-'}</td>
                    <td><span class="os-badge ${osClass}">${dev.os || '-'}</span></td>
                    <td>${dev.os_version || '-'}</td>
                    <td>${dev.model || '-'}</td>
                    <td>${dev.manifest || '-'}</td>
                    <td><span class="${isYesValue(dev.dep) ? 'yes-badge' : 'no-badge'}">${toYesNo(dev.dep)}</span></td>
                    <td><span class="${dev.supervised === 'Yes' ? 'yes-badge' : 'no-badge'}">${dev.supervised || '-'}</span></td>
                    <td><span class="${dev.encrypted === 'Yes' ? 'yes-badge' : 'no-badge'}">${dev.encrypted || '-'}</span></td>
                    <td><span class="${dev.outdated === 'Yes' ? 'no-badge' : 'yes-badge'}">${dev.outdated || '-'}</span></td>
                    <td>${dev.last_seen || '-'}</td>
                    <td style="text-align:center;"><span class="status-dot ${statusClass}" title="${statusClass}"></span></td>
                </tr>`;
            });
            tbody.innerHTML = html;
            updatePagination(totalPages);
            updateSelectedCount();
        }

        function updatePagination(totalPages) {
            const pagination = document.getElementById('pagination');
            const pageInfo = document.getElementById('page-info');

            if (totalPages <= 1) {
                pagination.innerHTML = '';
                pageInfo.innerHTML = filteredDevices.length > 0 ? `Showing ${filteredDevices.length} devices` : '';
                return;
            }

            const start = (currentPage - 1) * itemsPerPage + 1;
            const end = Math.min(currentPage * itemsPerPage, filteredDevices.length);
            pageInfo.innerHTML = `Showing ${start}-${end} of ${filteredDevices.length} (Page ${currentPage} of ${totalPages})`;

            let html = '';
            // Prev
            if (currentPage > 1) {
                html += `<a onclick="goToPage(${currentPage - 1})">&laquo; Prev</a>`;
            } else {
                html += '<span class="disabled">&laquo; Prev</span>';
            }
            // Page numbers
            for (let p = 1; p <= totalPages; p++) {
                if (p === currentPage) {
                    html += `<span class="current">${p}</span>`;
                } else if (p <= 3 || p > totalPages - 2 || (p >= currentPage - 1 && p <= currentPage + 1)) {
                    html += `<a onclick="goToPage(${p})">${p}</a>`;
                } else if (p === 4 || p === totalPages - 2) {
                    html += '<span>...</span>';
                }
            }
            // Next
            if (currentPage < totalPages) {
                html += `<a onclick="goToPage(${currentPage + 1})">Next &raquo;</a>`;
            } else {
                html += '<span class="disabled">Next &raquo;</span>';
            }
            pagination.innerHTML = html;
        }

        function goToPage(page) {
            const totalPages = Math.ceil(filteredDevices.length / itemsPerPage);
            if (page < 1 || page > totalPages) return;
            currentPage = page;
            renderDevices();
        }

        function toggleDevice(uuid) {
            if (selectedUuids.has(uuid)) {
                selectedUuids.delete(uuid);
            } else {
                selectedUuids.add(uuid);
            }
            updateSelectedCount();
        }

        function toggleSelectAll() {
            const checked = document.getElementById('selectAllCheckbox').checked;
            const start = (currentPage - 1) * itemsPerPage;
            const end = start + itemsPerPage;
            const pageDevices = filteredDevices.slice(start, end);
            pageDevices.forEach(dev => {
                if (checked) selectedUuids.add(dev.uuid);
                else selectedUuids.delete(dev.uuid);
            });
            renderDevices();
        }

        function selectAllPage() {
            const start = (currentPage - 1) * itemsPerPage;
            const end = start + itemsPerPage;
            filteredDevices.slice(start, end).forEach(dev => selectedUuids.add(dev.uuid));
            renderDevices();
        }

        function selectAllFiltered() {
            filteredDevices.forEach(dev => selectedUuids.add(dev.uuid));
            renderDevices();
        }

        function deselectAll() {
            selectedUuids.clear();
            document.getElementById('selectAllCheckbox').checked = false;
            renderDevices();
        }

        function updateSelectedCount() {
            document.getElementById('selectedCount').textContent = selectedUuids.size + ' selected';
        }

        function showLoading(show, text) {
            const el = document.getElementById('loading');
            if (show) {
                el.querySelector('span').textContent = text || 'Processing...';
                el.style.display = 'block';
            } else {
                el.style.display = 'none';
            }
        }

        function showResult(type, message, title) {
            const panel = document.getElementById('resultPanel');
            panel.style.display = 'block';
            panel.style.background = type === 'success' ? 'rgba(95,200,18,0.15)' : 'rgba(217,31,37,0.15)';
            panel.style.border = '1px solid ' + (type === 'success' ? '#5FC812' : '#D91F25');
            panel.style.color = type === 'success' ? '#5FC812' : '#D91F25';
            document.getElementById('resultTitle').textContent = title || 'Result';
            document.getElementById('resultContent').textContent = message;
        }

        function closeResult() {
            document.getElementById('resultPanel').style.display = 'none';
        }

        function refreshDeviceData() {
            if (selectedUuids.size === 0) {
                alert('Please select at least one device');
                return;
            }

            const devices = Array.from(selectedUuids);
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
                    showResult('success', data.message || 'Refresh command sent to ' + devices.length + ' device(s). Data will be updated when devices respond.', 'Refresh Device Data');
                } else {
                    showResult('error', data.error, 'Error');
                }
            })
            .catch(err => {
                showLoading(false);
                showResult('error', err.message, 'Error');
            });
        }

        loadDevices();
    </script>
</body>
</html>
'''


# =============================================================================
# ROUTES
# =============================================================================

@devices_bp.route('/devices')
@login_required_admin
def admin_devices():
    """Device inventory list page"""
    user = session.get('user', {})
    manifest_filter = user.get('manifest_filter')
    manifests = get_manifests_list(manifest_filter)
    return render_template_string(ADMIN_DEVICES_TEMPLATE, user=user, manifests=manifests)
# =============================================================================
# DEVICE DETAIL TEMPLATE
# =============================================================================

DEVICE_DETAIL_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ device.hostname or device.uuid }} - Device Detail</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="/static/dashboard.css">
    <link rel="stylesheet" href="/static/css/qbone.css">
    <link rel="stylesheet" href="/static/css/admin.css">
    <link rel="shortcut icon" href="/static/favicon.ico">
    <style>
        /* Device Detail page-specific styles */
        .tabs {
            display: flex;
            gap: 5px;
            margin-bottom: 20px;
            border-bottom: 2px solid #3A3A3A;
            padding-bottom: 0;
        }
        .tab-btn {
            padding: 10px 20px;
            background: transparent;
            border: none;
            cursor: pointer;
            font-size: 0.95em;
            color: #B0B0B0;
            border-bottom: 2px solid transparent;
            margin-bottom: -2px;
            transition: all 0.2s;
        }
        .tab-btn:hover { color: #5FC812; }
        .tab-btn.active {
            color: #FFFFFF;
            border-bottom-color: #5FC812;
            font-weight: 600;
        }
        .tab-btn .badge {
            background: #3A3A3A;
            color: #B0B0B0;
            padding: 2px 8px;
            border-radius: 10px;
            font-size: 0.8em;
            margin-left: 5px;
        }
        .tab-btn.active .badge { background: #5FC812; color: #0D0D0D; }

        .tab-content { display: none; }
        .tab-content.active { display: block; }

        .info-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
            gap: 12px;
        }
        .info-card {
            background: #2A2A2A;
            border: 1px solid #3A3A3A;
            padding: 12px;
            border-radius: 8px;
            overflow: hidden;
            text-align: left;
        }
        .info-card.wide {
            grid-column: span 2;
        }
        .info-card.full-width {
            grid-column: 1 / -1;
        }
        .info-card.wide .value,
        .info-card.full-width .value {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
            gap: 0 20px;
        }
        .info-card label {
            display: block;
            font-size: 0.8em;
            color: #B0B0B0;
            margin-bottom: 4px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .info-card .value {
            font-size: 0.95em;
            font-weight: 500;
            color: #FFFFFF;
            word-break: break-word;
            overflow-wrap: break-word;
        }
        .info-card .nested-item {
            display: flex;
            padding: 3px 0;
            gap: 8px;
            font-size: 0.85em;
            border-bottom: 1px solid #3A3A3A;
        }
        .info-card .nested-item:last-child {
            border-bottom: none;
        }
        .info-card .nested-item .nested-key {
            color: #B0B0B0;
            min-width: 240px;
            flex-shrink: 0;
        }
        .info-card .nested-item .nested-val {
            color: #FFFFFF;
            word-break: break-all;
        }

        .security-badge {
            display: inline-block;
            padding: 4px 10px;
            border-radius: 4px;
            font-size: 0.85em;
            font-weight: 500;
        }
        .security-badge.ok { background: rgba(95,200,18,0.15); color: #5FC812; border: 1px solid #5FC812; }
        .security-badge.warn { background: rgba(245,166,35,0.15); color: #F5A623; border: 1px solid #F5A623; }
        .security-badge.bad { background: rgba(217,31,37,0.15); color: #D91F25; border: 1px solid #D91F25; }

        .quick-actions {
            display: flex;
            gap: 10px;
            margin-top: 20px;
            padding-top: 20px;
            border-top: 1px solid #3A3A3A;
        }
        .quick-actions .btn { min-width: 100px; }

        .loading-spinner {
            display: inline-block;
            width: 16px;
            height: 16px;
            border: 2px solid #3A3A3A;
            border-top-color: #5FC812;
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
            margin-right: 8px;
        }
        @keyframes spin {
            to { transform: rotate(360deg); }
        }

        .refresh-btn {
            float: right;
            padding: 5px 12px;
            font-size: 0.85em;
        }

        .output-box {
            background: #1e293b;
            color: #e2e8f0;
            padding: 15px;
            border-radius: 8px;
            font-family: monospace;
            font-size: 0.85em;
            max-height: 400px;
            overflow-y: auto;
            white-space: pre-wrap;
            word-break: break-all;
        }

        .error-box {
            background: rgba(217,31,37,0.1);
            border: 1px solid #D91F25;
            color: #D91F25;
            padding: 15px;
            border-radius: 8px;
            text-align: center;
        }
        .badge-ddm {
            background: rgba(147,51,234,0.15);
            color: #9333EA;
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 0.75em;
            font-weight: 600;
            margin-right: 6px;
        }
        /* Table wrapper inside tabs - responsive scrollable area */
        .tab-content .table-wrapper {
            max-height: calc(100vh - 500px);
            max-width: calc(100vw - 100px);
            overflow: auto;
            border: 1px solid #3A3A3A;
            border-radius: 5px;
        }
    </style>
</head>
<body class="page-with-table">
    <div id="wrap">
        <div style="display: flex; justify-content: center; align-items: center;">
            <img id="logo" src="{{ current_logo }}" alt="Logo" style="max-height:60px;max-width:200px;"/>
        </div>
        <h1>Device Detail</h1>

        <div class="panel">
            <div class="admin-header">
                <h2>
                    <span class="status-dot {{ device.status }}"></span>
                    {{ device.hostname or 'Unknown' }}
                    <span class="os-badge {{ device.os }}">{{ device.os }}</span>
                </h2>
                <a href="/admin/devices" class="btn">Back to Devices</a>
            </div>

            <div class="tabs">
                <button class="tab-btn active" onclick="showTab('info', this)">Info</button>
                <button class="tab-btn" onclick="showTab('hardware', this)" id="tab-hardware">Hardware</button>
                <button class="tab-btn" onclick="showTab('security', this)" id="tab-security">Security</button>
                <button class="tab-btn" onclick="showTab('profiles', this)" id="tab-profiles">Profiles <span class="badge" id="profiles-count">-</span></button>
                <button class="tab-btn" onclick="showTab('apps', this)" id="tab-apps">Apps <span class="badge" id="apps-count">-</span></button>
                <button class="tab-btn" onclick="showTab('ddm', this)" id="tab-ddm">DDM <span class="badge" id="ddm-count">-</span></button>
                <button class="tab-btn" onclick="showTab('history', this)">History <span class="badge">{{ history|length }}</span></button>
            </div>

            <!-- Info Tab -->
            <div id="tab-content-info" class="tab-content active">
                <div class="info-grid">
                    <div class="info-card">
                        <label>UUID</label>
                        <div class="value" style="font-size:0.9em; font-family:monospace;">{{ device.uuid }}</div>
                    </div>
                    <div class="info-card">
                        <label>Serial Number</label>
                        <div class="value">{{ device.serial or '-' }}</div>
                    </div>
                    <div class="info-card">
                        <label>Hostname</label>
                        <div class="value">{{ device.hostname or '-' }}</div>
                    </div>
                    <div class="info-card">
                        <label>Operating System</label>
                        <div class="value">{{ device.os | upper }}</div>
                    </div>
                    <div class="info-card">
                        <label>Manifest</label>
                        <div class="value">{{ device.manifest or 'default' }}</div>
                    </div>
                    <div class="info-card">
                        <label>DEP Enrolled</label>
                        <div class="value">{{ 'Yes' if device.dep in ['1', 'enabled', True] else 'No' }}</div>
                    </div>
                    <div class="info-card">
                        <label>Status</label>
                        <div class="value">
                            <span class="status-dot {{ device.status }}"></span>
                            {{ device.status | capitalize }}
                        </div>
                    </div>
                    <div class="info-card">
                        <label>Last Seen</label>
                        <div class="value">{{ device.last_seen_at or 'Never' }}</div>
                    </div>
                </div>

                <div class="quick-actions">
                    <button class="btn" onclick="executeDeviceAction('lock')">Lock</button>
                    <button class="btn" onclick="executeDeviceAction('restart')">Restart</button>
                    <button class="btn btn-danger" onclick="showEraseModal()" style="margin-left:auto;">Erase Device</button>
                </div>
            </div>

            <!-- Erase Confirmation Modal -->
            <div id="erase-modal" style="display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.4);z-index:1000;align-items:center;justify-content:center;">
                <div style="background:white;padding:15px;border-radius:8px;max-width:400px;width:90%;box-shadow:0 4px 20px rgba(0,0,0,0.15);font-size:0.85em;">
                    <h3 style="margin:0 0 10px 0;color:#dc2626;font-size:0.95em;">Erase Device</h3>
                    <p style="color:#B0B0B0;margin-bottom:12px;">
                        <strong>WARNING:</strong> This will permanently erase ALL DATA on the device. This action cannot be undone!
                    </p>
                    <p style="color:#B0B0B0;margin-bottom:8px;">
                        Device: <strong>{{ device.hostname }}</strong> ({{ device.serial }})
                    </p>
                    <p style="color:#6b7280;margin-bottom:10px;">
                        To confirm, type <strong style="color:#dc2626;">ERASE</strong> below:
                    </p>
                    <input type="text" id="erase-confirm-input" placeholder="Type ERASE to confirm"
                           style="width:100%;padding:8px;border:1px solid #d1d5db;border-radius:4px;font-size:0.9em;margin-bottom:12px;box-sizing:border-box;"
                           oninput="checkEraseInput()">
                    <div style="display:flex;gap:8px;justify-content:flex-end;">
                        <button class="btn" onclick="hideEraseModal()" style="font-size:0.85em;padding:6px 14px;">Cancel</button>
                        <button class="btn btn-danger" id="erase-confirm-btn" onclick="confirmErase()" disabled
                                style="opacity:0.5;cursor:not-allowed;font-size:0.85em;padding:6px 14px;">Erase Device</button>
                    </div>
                </div>
            </div>

            <!-- Hardware Tab -->
            <div id="tab-content-hardware" class="tab-content">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:15px;">
                    <div>
                        <h3 style="margin:0;display:inline;">Hardware Information</h3>
                        <span id="hardware-timestamp" style="margin-left:15px;"></span>
                    </div>
                    <button class="btn" onclick="refreshData('hardware')">Refresh from Device</button>
                </div>
                <div id="hardware-loading" style="display:none;"><span class="loading-spinner"></span> Querying device...</div>
                <div id="hardware-content" class="info-grid"></div>
            </div>

            <!-- Security Tab -->
            <div id="tab-content-security" class="tab-content">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:15px;">
                    <div>
                        <h3 style="margin:0;display:inline;">Security Information</h3>
                        <span id="security-timestamp" style="margin-left:15px;"></span>
                    </div>
                    <button class="btn" onclick="refreshData('security')">Refresh from Device</button>
                </div>
                <div id="security-loading" style="display:none;"><span class="loading-spinner"></span> Querying device...</div>
                <div id="security-content" class="info-grid"></div>
            </div>

            <!-- Profiles Tab -->
            <div id="tab-content-profiles" class="tab-content">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:15px;">
                    <div>
                        <h3 style="margin:0;display:inline;">Installed Profiles</h3>
                        <span id="profiles-timestamp" style="margin-left:15px;"></span>
                    </div>
                    <button class="btn" onclick="refreshData('profiles')">Refresh from Device</button>
                </div>

                <!-- Required Profiles Status Box -->
                {% if required_profiles_status and required_profiles_status.required > 0 %}
                <div class="info-box">
                    <h4>Required Profiles for {{ device.manifest or 'default' }}</h4>
                    <div style="display:flex;gap:15px;margin-bottom:10px;font-size:0.85em;">
                        <span style="color:#5FC812;"><strong>{{ required_profiles_status.installed }}</strong> installed</span>
                        <span style="color:#D91F25;"><strong>{{ required_profiles_status.missing }}</strong> missing</span>
                    </div>
                    <div style="display:flex;flex-wrap:wrap;gap:8px;">
                        {% for p in required_profiles_status.all_profiles %}
                        <span style="padding:4px 10px;border-radius:4px;font-size:0.85em;{% if p.installed %}background:rgba(95,200,18,0.15);color:#5FC812;border:1px solid #5FC812;{% else %}background:rgba(217,31,37,0.15);color:#D91F25;border:1px solid #D91F25;{% endif %}">
                            {{ p.name }}
                        </span>
                        {% endfor %}
                    </div>
                </div>
                {% endif %}

                <div id="profiles-loading" style="display:none;"><span class="loading-spinner"></span> Querying device...</div>
                <div id="profiles-content"></div>
            </div>

            <!-- Apps Tab -->
            <div id="tab-content-apps" class="tab-content">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
                    <div>
                        <h3 style="margin:0;display:inline;">Installed Applications</h3>
                        <span id="apps-timestamp" style="margin-left:15px;"></span>
                    </div>
                    <button class="btn" onclick="refreshData('apps')">Refresh from Device</button>
                </div>
                <div class="filter-form" style="margin-bottom:10px;padding:8px 12px;">
                    <div class="filter-group">
                        <label>Search</label>
                        <input type="text" id="apps-search" placeholder="App name or bundle ID..." onkeyup="filterApps()">
                    </div>
                    <div class="filter-group">
                        <label>Type</label>
                        <select id="apps-type-filter" onchange="filterApps()">
                            <option value="all">All Apps</option>
                            <option value="user">User Apps</option>
                            <option value="system">System Apps</option>
                        </select>
                    </div>
                    <div class="filter-group">
                        <label>Stats</label>
                        <span id="apps-stats" style="font-size:0.72em;color:#B0B0B0;padding:4px 0;">-</span>
                    </div>
                </div>
                <div id="apps-loading" style="display:none;"><span class="loading-spinner"></span> Querying device...</div>
                <div id="apps-content"></div>
            </div>

            <!-- DDM Tab -->
            <div id="tab-content-ddm" class="tab-content">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:15px;">
                    <div>
                        <h3 style="margin:0;display:inline;">DDM Declarations</h3>
                        <span id="ddm-timestamp" style="margin-left:15px;"></span>
                    </div>
                    <button class="btn" onclick="refreshData('ddm')">Refresh</button>
                </div>
                <div id="ddm-loading" style="display:none;"><span class="loading-spinner"></span> Querying DDM status...</div>
                <div id="ddm-content"></div>
            </div>

            <!-- History Tab -->
            <div id="tab-content-history" class="tab-content">
                <h3>Command History</h3>
                {% if history %}
                <table class="history-table">
                    <thead>
                        <tr>
                            <th>Timestamp</th>
                            <th>User</th>
                            <th>Command</th>
                            <th>Status</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for entry in history %}
                        <tr>
                            <td>{{ entry.timestamp }}</td>
                            <td>{{ entry.user }}</td>
                            <td>{{ entry.command_name }}</td>
                            <td class="{{ 'status-success' if entry.success else 'status-failed' }}">
                                {{ 'Success' if entry.success else 'Failed' }}
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
                <div style="margin-top:15px;">
                    <a href="/admin/history?device={{ device.uuid }}" class="btn">View Full History</a>
                </div>
                {% else %}
                <p>No command history for this device.</p>
                {% endif %}
            </div>
        </div>
    </div>

    <script>
        const deviceUuid = '{{ device.uuid }}';
        const itemsPerPage = 50;
        let appsData = [];
        let profilesData = [];
        let ddmData = [];
        let appsPage = 1;
        let profilesPage = 1;
        let ddmPage = 1;

        function showTab(tabName, btn) {
            document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
            document.getElementById('tab-content-' + tabName).classList.add('active');
            btn.classList.add('active');
            updatePanelLayout();
        }

        // Updates panel layout class based on whether active data tab has content
        function updatePanelLayout() {
            const panel = document.querySelector('.panel');
            const dataTabs = ['apps', 'profiles', 'ddm'];
            let shouldExpand = false;

            for (const tab of dataTabs) {
                const tabContent = document.getElementById('tab-content-' + tab);
                const content = document.getElementById(tab + '-content');
                if (tabContent && tabContent.classList.contains('active') &&
                    content && content.querySelector('.table-wrapper')) {
                    shouldExpand = true;
                    break;
                }
            }

            if (shouldExpand) {
                panel.classList.add('has-data-table');
            } else {
                panel.classList.remove('has-data-table');
            }
        }

        function loadData(type, forceRefresh = false) {
            const loadingEl = document.getElementById(type + '-loading');
            const contentEl = document.getElementById(type + '-content');
            const timestampEl = document.getElementById(type + '-timestamp');

            loadingEl.style.display = 'block';
            if (forceRefresh) contentEl.innerHTML = '';

            fetch('/admin/api/device/' + deviceUuid + '/query', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({query_type: type, force_refresh: forceRefresh})
            })
            .then(r => r.json())
            .then(data => {
                loadingEl.style.display = 'none';
                if (data.success && data.data) {
                    renderData(type, data.data, contentEl);
                    // Show timestamp
                    if (timestampEl) {
                        if (data.cached && data.updated_at) {
                            timestampEl.innerHTML = '<span style="color:#6b7280;font-size:0.85em;">Cached: ' + data.updated_at + '</span>';
                        } else if (!data.cached) {
                            timestampEl.innerHTML = '<span style="color:#27ae60;font-size:0.85em;">Updated just now</span>';
                        }
                    }
                } else {
                    contentEl.innerHTML = '<div class="error-box">' + (data.error || 'No data received') + '</div>';
                    if (timestampEl) timestampEl.innerHTML = '';
                }
            })
            .catch(err => {
                loadingEl.style.display = 'none';
                contentEl.innerHTML = '<div class="error-box">Error: ' + err.message + '</div>';
            });
        }

        function refreshData(type) {
            loadData(type, true);  // Force refresh from MDM
        }

        function renderData(type, data, container) {
            if (type === 'hardware' || type === 'security') {
                // Render key-value pairs as info cards
                let html = '';
                for (const [key, value] of Object.entries(data)) {
                    let displayVal;
                    let cardClass = 'info-card';

                    if (typeof value === 'boolean') {
                        displayVal = value ? '<span style="color:#27ae60">Yes</span>' : '<span style="color:#dc2626">No</span>';
                    } else if (Array.isArray(value)) {
                        displayVal = value.length + ' items';
                        if (value.length > 5) cardClass += ' wide';
                    } else if (typeof value === 'object' && value !== null) {
                        // Handle nested objects - display as nice list
                        const entries = Object.entries(value);
                        const parts = [];
                        for (const [k, v] of entries) {
                            if (typeof v === 'boolean') {
                                parts.push('<div class="nested-item"><span class="nested-key">' + formatKey(k) + '</span><span class="nested-val">' + (v ? '<span style="color:#27ae60">Yes</span>' : '<span style="color:#dc2626">No</span>') + '</span></div>');
                            } else if (typeof v !== 'object') {
                                let displayV = String(v);
                                if (displayV.length > 60) {
                                    displayV = '<span title="' + displayV.replace(/"/g, '&quot;') + '">' + displayV.substring(0, 57) + '...</span>';
                                }
                                parts.push('<div class="nested-item"><span class="nested-key">' + formatKey(k) + '</span><span class="nested-val">' + displayV + '</span></div>');
                            }
                        }
                        displayVal = parts.length > 0 ? parts.join('') : '-';
                        // Dynamic sizing based on content
                        if (entries.length >= 3) {
                            cardClass += ' wide';
                        }
                    } else {
                        displayVal = value || '-';
                        // Wide card for long text values
                        if (String(value).length > 30) cardClass += ' wide';
                    }
                    html += `<div class="${cardClass}"><label>${formatKey(key)}</label><div class="value">${displayVal}</div></div>`;
                }
                container.innerHTML = html || '<div class="error-box">No data available</div>';

            } else if (type === 'profiles') {
                profilesData = data.profiles || [];
                document.getElementById('profiles-count').textContent = profilesData.length;
                profilesPage = 1;
                renderProfilesPage();

            } else if (type === 'apps') {
                appsData = data.applications || [];
                document.getElementById('apps-count').textContent = appsData.length;
                appsPage = 1;
                renderAppsPage();

            } else if (type === 'ddm') {
                ddmData = data.declarations || [];
                document.getElementById('ddm-count').textContent = ddmData.length;
                ddmPage = 1;
                renderDdmPage();
            }
        }

        function renderProfilesPage() {
            const container = document.getElementById('profiles-content');
            if (profilesData.length === 0) {
                container.innerHTML = '<div class="error-box">No profiles installed</div>';
                return;
            }
            const totalPages = Math.ceil(profilesData.length / itemsPerPage);
            const start = (profilesPage - 1) * itemsPerPage;
            const end = Math.min(start + itemsPerPage, profilesData.length);
            const pageData = profilesData.slice(start, end);

            let html = '<div class="table-wrapper"><table class="history-table"><thead><tr><th>#</th><th>Name</th><th>Identifier</th><th>Status</th></tr></thead><tbody>';
            pageData.forEach((p, i) => {
                const ddmBadge = p.is_ddm ? '<span class="badge-ddm">DDM</span>' : '';
                const displayId = p.is_ddm && p.ddm_identifier ? p.ddm_identifier : p.identifier;
                html += `<tr><td>${start + i + 1}</td><td>${ddmBadge}${p.name}</td><td style="font-size:0.85em;color:#6b7280;">${displayId}</td><td>${p.status}</td></tr>`;
            });
            html += '</tbody></table></div>';
            html += renderPagination('profiles', profilesPage, totalPages, profilesData.length);
            container.innerHTML = html;
            updatePanelLayout();
        }

        let filteredAppsData = [];

        function filterApps() {
            appsPage = 1;
            renderAppsPage();
        }

        function getFilteredApps() {
            const search = (document.getElementById('apps-search')?.value || '').toLowerCase();
            const typeFilter = document.getElementById('apps-type-filter')?.value || 'all';

            let filtered = appsData;

            // Filter by type
            if (typeFilter === 'user') {
                filtered = filtered.filter(a => a.bundle_id && !a.bundle_id.startsWith('com.apple.'));
            } else if (typeFilter === 'system') {
                filtered = filtered.filter(a => a.bundle_id && a.bundle_id.startsWith('com.apple.'));
            }

            // Filter by search
            if (search) {
                filtered = filtered.filter(a =>
                    (a.name && a.name.toLowerCase().includes(search)) ||
                    (a.bundle_id && a.bundle_id.toLowerCase().includes(search))
                );
            }

            return filtered;
        }

        function updateAppsStats() {
            const total = appsData.length;
            const userApps = appsData.filter(a => a.bundle_id && !a.bundle_id.startsWith('com.apple.')).length;
            const systemApps = total - userApps;
            const statsEl = document.getElementById('apps-stats');
            if (statsEl) {
                statsEl.textContent = 'Total: ' + total + ' | User: ' + userApps + ' | System: ' + systemApps;
            }
        }

        function renderAppsPage() {
            const container = document.getElementById('apps-content');

            if (appsData.length === 0) {
                container.innerHTML = '<div class="error-box">No applications found</div>';
                return;
            }

            updateAppsStats();
            filteredAppsData = getFilteredApps();

            if (filteredAppsData.length === 0) {
                container.innerHTML = '<div class="info-box" style="background:rgba(245,166,35,0.1);border-color:#F5A623;"><span style="color:#F5A623;">No apps match the filter</span></div>';
                return;
            }

            const totalPages = Math.ceil(filteredAppsData.length / itemsPerPage);
            const start = (appsPage - 1) * itemsPerPage;
            const end = Math.min(start + itemsPerPage, filteredAppsData.length);
            const pageData = filteredAppsData.slice(start, end);

            let html = '<div class="table-wrapper"><table class="history-table" id="apps-table"><thead><tr><th>#</th><th>Name</th><th>Bundle ID</th><th>Version</th></tr></thead><tbody>';
            pageData.forEach((a, i) => {
                html += `<tr><td>${start + i + 1}</td><td>${a.name}</td><td style="font-size:0.85em;color:#6b7280;">${a.bundle_id}</td><td>${a.version}</td></tr>`;
            });
            html += '</tbody></table></div>';
            html += renderPagination('apps', appsPage, totalPages, filteredAppsData.length);
            container.innerHTML = html;
            updatePanelLayout();
        }

        function renderDdmPage() {
            const container = document.getElementById('ddm-content');
            if (ddmData.length === 0) {
                container.innerHTML = '<div class="info-box" style="background:rgba(245,166,35,0.1);border-color:#F5A623;"><span style="color:#F5A623;">No DDM declarations reported for this device</span></div>';
                return;
            }
            const totalPages = Math.ceil(ddmData.length / itemsPerPage);
            const start = (ddmPage - 1) * itemsPerPage;
            const end = Math.min(start + itemsPerPage, ddmData.length);
            const pageData = ddmData.slice(start, end);

            let html = '<div class="table-wrapper"><table class="history-table"><thead><tr><th>Identifier</th><th style="text-align:center;">Active</th><th style="text-align:center;">Valid</th><th>Last Update</th></tr></thead><tbody>';
            pageData.forEach(d => {
                const activeBadge = d.active ? '<span class="badge badge-yes">Yes</span>' : '<span class="badge badge-no">No</span>';
                const validBadge = d.valid ? '<span class="badge badge-yes">Yes</span>' : '<span class="badge badge-no">No</span>';
                html += '<tr>';
                html += '<td><span style="font-family:monospace;font-size:0.9em;">' + d.identifier + '</span></td>';
                html += '<td style="text-align:center;">' + activeBadge + '</td>';
                html += '<td style="text-align:center;">' + validBadge + '</td>';
                html += '<td style="font-size:0.85em;color:#B0B0B0;">' + (d.updated_at || '-') + '</td>';
                html += '</tr>';
            });
            html += '</tbody></table></div>';
            html += renderPagination('ddm', ddmPage, totalPages, ddmData.length);
            container.innerHTML = html;
            updatePanelLayout();
        }

        function renderPagination(type, currentPage, totalPages, totalItems) {
            if (totalPages <= 1) return '';
            const start = (currentPage - 1) * itemsPerPage + 1;
            const end = Math.min(currentPage * itemsPerPage, totalItems);
            let html = '<div style="margin-top:15px;padding:10px 0;border-top:1px solid #3A3A3A;flex-shrink:0;">';
            html += '<div style="font-size:0.85em;color:#B0B0B0;margin-bottom:8px;">Showing ' + start + '-' + end + ' of ' + totalItems + ' (Page ' + currentPage + ' of ' + totalPages + ')</div>';
            html += '<div class="pagination">';
            if (currentPage > 1) {
                html += "<a href='#' onclick='goToPage(\\"" + type + "\\", " + (currentPage - 1) + "); return false;'>&laquo; Prev</a>";
            } else {
                html += '<span class="disabled">&laquo; Prev</span>';
            }
            for (let p = 1; p <= totalPages; p++) {
                if (p === currentPage) {
                    html += '<span class="current">' + p + '</span>';
                } else if (p <= 3 || p > totalPages - 2 || (p >= currentPage - 1 && p <= currentPage + 1)) {
                    html += "<a href='#' onclick='goToPage(\\"" + type + "\\", " + p + "); return false;'>" + p + "</a>";
                } else if (p === 4 || p === totalPages - 2) {
                    html += '<span>...</span>';
                }
            }
            if (currentPage < totalPages) {
                html += "<a href='#' onclick='goToPage(\\"" + type + "\\", " + (currentPage + 1) + "); return false;'>Next &raquo;</a>";
            } else {
                html += '<span class="disabled">Next &raquo;</span>';
            }
            html += '</div></div>';
            return html;
        }

        function goToPage(type, page) {
            if (type === 'profiles') { profilesPage = page; renderProfilesPage(); }
            else if (type === 'apps') { appsPage = page; renderAppsPage(); }
            else if (type === 'ddm') { ddmPage = page; renderDdmPage(); }
        }

        function formatKey(key) {
            // Handle common acronyms
            let result = key
                .replace(/([a-z])([A-Z])/g, '$1 $2')  // camelCase to spaces
                .replace(/([A-Z]+)([A-Z][a-z])/g, '$1 $2')  // Handle consecutive caps
                .replace(/^./, s => s.toUpperCase());
            // Fix known acronyms
            result = result.replace(/O S /g, 'OS ').replace(/I D/g, 'ID').replace(/M A C/g, 'MAC')
                          .replace(/D E P/g, 'DEP').replace(/S I P/g, 'SIP').replace(/U R L/g, 'URL');
            return result.trim();
        }

        function showEraseModal() {
            document.getElementById('erase-modal').style.display = 'flex';
            document.getElementById('erase-confirm-input').value = '';
            document.getElementById('erase-confirm-btn').disabled = true;
            document.getElementById('erase-confirm-btn').style.opacity = '0.5';
            document.getElementById('erase-confirm-btn').style.cursor = 'not-allowed';
        }

        function hideEraseModal() {
            document.getElementById('erase-modal').style.display = 'none';
        }

        function checkEraseInput() {
            const input = document.getElementById('erase-confirm-input').value;
            const btn = document.getElementById('erase-confirm-btn');
            if (input === 'ERASE') {
                btn.disabled = false;
                btn.style.opacity = '1';
                btn.style.cursor = 'pointer';
            } else {
                btn.disabled = true;
                btn.style.opacity = '0.5';
                btn.style.cursor = 'not-allowed';
            }
        }

        function confirmErase() {
            hideEraseModal();
            fetch('/admin/execute', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    command: 'device_action',
                    params: {action: 'erase', udid: deviceUuid, confirm_erase: 'ERASE'}
                })
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    alert('Erase command sent successfully. Device will be wiped.');
                } else {
                    alert('Error: ' + (data.error || data.output || 'Unknown error'));
                }
            })
            .catch(err => alert('Error: ' + err.message));
        }

        function executeDeviceAction(action) {
            fetch('/admin/execute', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({command: 'device_action', params: {action: action, udid: deviceUuid}})
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    alert('Command sent successfully');
                } else {
                    alert('Error: ' + (data.error || data.output || 'Unknown error'));
                }
            })
            .catch(err => alert('Error: ' + err.message));
        }

        function executeAction(action) {
            // For system_report, use the query API to get full data
            if (action === 'system_report') {
                showTab('hardware');
                document.querySelector('.tab-btn[onclick*="hardware"]').classList.add('active');
                refreshData('hardware');
                return;
            }

            fetch('/admin/execute', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({command: action, params: {udid: deviceUuid}})
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    alert('Command sent successfully');
                } else {
                    alert('Error: ' + (data.error || data.output || 'Unknown error'));
                }
            })
            .catch(err => alert('Error: ' + err.message));
        }

        // Auto-load data on page load
        // Load cached data on page load (fast), user can click Refresh for live data
        document.addEventListener('DOMContentLoaded', function() {
            setTimeout(() => loadData('hardware'), 100);
            setTimeout(() => loadData('security'), 200);
            setTimeout(() => loadData('profiles'), 300);
            setTimeout(() => loadData('apps'), 400);
            setTimeout(() => loadData('ddm'), 500);
        });
    </script>
</body>
</html>
'''
@devices_bp.route('/api/devices')
@login_required_admin
def api_devices():
    """Get full devices list (JSON) with all fields, filtered by user's manifest_filter if any"""
    user = session.get('user', {})
    manifest_filter = user.get('manifest_filter')  # e.g. 'site-%' for site-admin
    devices = get_devices_full(manifest_filter=manifest_filter)
    return jsonify(devices)


@devices_bp.route('/api/device-search', methods=['POST'])
@login_required_admin
def api_device_search():
    """Search devices (JSON) with all fields, filtered by user's manifest_filter if any"""
    user = session.get('user', {})
    manifest_filter = user.get('manifest_filter')

    data = request.get_json()
    search_term = data.get('value', '')

    devices = get_devices_full(manifest_filter=manifest_filter, search_term=search_term)
    return jsonify(devices)


@devices_bp.route('/api/applications/<manifest>')
@login_required_admin
def api_applications_for_manifest(manifest):
    """Get applications for a specific manifest (both macos and ios)"""
    try:
        apps = db.query_all("""
            SELECT id, manifest, os, app_name, manifest_url, install_order, is_optional
            FROM required_applications
            WHERE manifest = %s
            ORDER BY os, install_order
        """, (manifest,))
        return jsonify({'success': True, 'applications': apps or []})
    except Exception as e:
        logger.error(f"Failed to get applications for manifest {manifest}: {e}")
        return jsonify({'success': False, 'applications': [], 'error': str(e)})


# =============================================================================
# DEVICE DETAIL ROUTES
# =============================================================================

@devices_bp.route('/device/<device_uuid>')
@login_required_admin
def device_detail(device_uuid):
    """Device detail page with tabs for hardware, security, profiles, apps, history"""
    user = session.get('user', {})

    # Validate device access for users with manifest filter
    if user.get('manifest_filter'):
        if not validate_device_access(device_uuid, user):
            return render_template_string('''
                <html><body>
                <h1>Access Denied</h1>
                <p>You do not have permission to view this device.</p>
                <a href="/admin">Back to Admin</a>
                </body></html>
            '''), 403

    # Get device info from database
    device = get_device_detail(device_uuid)
    if not device:
        return render_template_string('''
            <html><body>
            <h1>Device Not Found</h1>
            <p>Device with UUID {{ uuid }} was not found in the database.</p>
            <a href="/admin">Back to Admin</a>
            </body></html>
        ''', uuid=device_uuid), 404

    # Get command history for this device
    history = get_device_command_history(device_uuid, limit=20)

    # Get required profiles status for this device (same approach as Reports page)
    required_profiles_status = None
    try:
        manifest = device.get('manifest') or ''
        os_type = (device.get('os') or '').lower()

        # Get profiles_data from device_details table (same as Reports)
        row = db.query_one("""
            SELECT profiles_data FROM device_details WHERE uuid = %s
        """, (device_uuid,))

        profiles = []
        if row and row.get('profiles_data'):
            profiles_data = row.get('profiles_data')
            if isinstance(profiles_data, str):
                profiles = json.loads(profiles_data)
            else:
                profiles = profiles_data or []

        # Get required profiles and check compliance (same as Reports)
        profile_check = required_profiles.check_device_profiles(manifest, os_type, profiles)

        if profile_check['required'] > 0:
            # Build all_profiles list with installed status
            req_list = required_profiles.get_for_manifest(manifest, os_type)
            missing_names = {m['name'] for m in profile_check.get('missing_list', [])}

            all_profiles = []
            for req in req_list:
                all_profiles.append({
                    'name': req['profile_name'],
                    'identifier': req['profile_identifier'],
                    'installed': req['profile_name'] not in missing_names
                })

            required_profiles_status = {
                'required': profile_check['required'],
                'installed': profile_check['installed'],
                'missing': profile_check['missing'],
                'all_profiles': all_profiles
            }
    except Exception as e:
        logger.error(f"Failed to get required profiles status: {e}")

    return render_template_string(
        DEVICE_DETAIL_TEMPLATE,
        user=user,
        device=device,
        history=history,
        required_profiles_status=required_profiles_status
    )


@devices_bp.route('/api/device/<device_uuid>/profile-check')
@login_required_admin
def api_device_profile_check(device_uuid):
    """Debug endpoint to check profile compliance for a device"""
    try:
        row = db.query_one("""
            SELECT di.uuid, di.hostname, di.serial, di.os, di.manifest, dd.profiles_data
            FROM device_inventory di
            LEFT JOIN device_details dd ON di.uuid = dd.uuid
            WHERE di.uuid = %s OR di.serial = %s
        """, (device_uuid, device_uuid))

        if not row:
            return jsonify({'error': 'Device not found'})

        profiles_data = row.get('profiles_data')
        if profiles_data and isinstance(profiles_data, str):
            profiles = json.loads(profiles_data)
        else:
            profiles = profiles_data or []

        manifest = row.get('manifest', '')
        os_type = (row.get('os') or '').lower()

        # Get required profiles
        req = required_profiles.get_for_manifest(manifest, os_type)

        # Extract installed identifiers
        installed_ids = []
        for p in profiles:
            if isinstance(p, dict):
                ident = p.get('identifier') or p.get('PayloadIdentifier') or p.get('Identifier', '')
                if ident:
                    installed_ids.append(ident)

        # Run check
        result = required_profiles.check_device_profiles(manifest, os_type, profiles)

        return jsonify({
            'device': {
                'hostname': row.get('hostname'),
                'serial': row.get('serial'),
                'os': os_type,
                'manifest': manifest
            },
            'required_profiles': [{'name': r['profile_name'], 'id': r['profile_identifier'], 'pattern': bool(r['match_pattern'])} for r in req],
            'installed_identifiers': sorted(installed_ids),
            'result': result
        })
    except Exception as e:
        return jsonify({'error': str(e)})


@devices_bp.route('/api/device/<device_uuid>/query', methods=['POST'])
@login_required_admin
def api_device_query(device_uuid):
    """API endpoint to query device data (hardware, security, profiles, apps)"""
    user = session.get('user', {})

    # Validate device access
    if user.get('manifest_filter'):
        if not validate_device_access(device_uuid, user):
            return jsonify({'success': False, 'error': 'Access denied'}), 403

    data = request.get_json() or {}
    query_type = data.get('query_type')
    force_refresh = data.get('force_refresh', False)

    if not query_type:
        return jsonify({'success': False, 'error': 'Missing query_type parameter'})

    # Try to get cached data from DB first (unless force_refresh)
    if not force_refresh:
        cached = get_device_details(device_uuid, query_type)
        if cached and cached.get('data'):
            # Transform cached data to match frontend expectations
            # Webhook saves different field names than parse_webhook_output returns
            cached_data = cached['data']

            if query_type == 'profiles' and isinstance(cached_data, list):
                # Transform: display_name -> name, add status field
                # Detect DDM profiles and decode their identifiers
                profiles = []
                for p in cached_data:
                    identifier = p.get('identifier', 'N/A')
                    is_ddm = (not p.get('is_managed') and
                              identifier.startswith('com.apple.RemoteManagement.'))
                    ddm_identifier = None
                    if is_ddm and ':' in identifier:
                        try:
                            # Extract base64 part after ':' and before '.'
                            b64_part = identifier.split(':')[1]
                            if '.' in b64_part:
                                b64_part = b64_part.split('.')[0]
                            ddm_identifier = base64.b64decode(b64_part).decode('utf-8')
                        except Exception:
                            ddm_identifier = None
                    profiles.append({
                        'name': p.get('display_name', p.get('name', 'N/A')),
                        'identifier': identifier,
                        'status': 'Managed' if p.get('is_managed') else 'Installed',
                        'is_ddm': is_ddm,
                        'ddm_identifier': ddm_identifier
                    })
                cached_data = {'profiles': profiles, 'count': len(profiles)}

            elif query_type == 'apps' and isinstance(cached_data, list):
                # Transform: identifier -> bundle_id
                apps = []
                for a in cached_data:
                    apps.append({
                        'name': a.get('name', 'Unknown'),
                        'bundle_id': a.get('identifier', a.get('bundle_id', 'N/A')),
                        'version': a.get('version', 'N/A')
                    })
                cached_data = {'applications': apps, 'count': len(apps)}

            elif query_type == 'ddm' and isinstance(cached_data, list):
                # DDM declarations status - validate cache against status_declarations
                # If device has no entries in status_declarations but cache has data, invalidate cache
                actual_count = db.query_one(
                    "SELECT COUNT(*) as cnt FROM status_declarations WHERE enrollment_id = %s",
                    (device_uuid,)
                )
                if actual_count and actual_count.get('cnt', 0) == 0 and len(cached_data) > 0:
                    # Cache is stale - device has no declarations but cache has data
                    # Clear cache and return empty
                    db.execute(
                        "UPDATE device_details SET ddm_data = NULL, ddm_updated_at = NOW() WHERE uuid = %s",
                        (device_uuid,)
                    )
                    cached_data = {'declarations': [], 'count': 0}
                else:
                    cached_data = {'declarations': cached_data, 'count': len(cached_data)}

            return jsonify({
                'success': True,
                'data': cached_data,
                'query_type': query_type,
                'cached': True,
                'updated_at': cached.get('updated_at')
            })

    # Special handling for DDM
    if query_type == 'ddm':
        try:
            ddm_sync_sent = False

            # If force_refresh, send DeclarativeManagement command to trigger device sync
            if force_refresh:
                try:
                    import uuid as uuid_module
                    cmd_uuid = str(uuid_module.uuid4())
                    plist = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Command</key>
    <dict>
        <key>RequestType</key>
        <string>DeclarativeManagement</string>
    </dict>
    <key>CommandUUID</key>
    <string>{cmd_uuid}</string>
</dict>
</plist>'''
                    # Get API credentials
                    api_key = Config.MDM_API_KEY
                    try:
                        with open(Config.ENVIRONMENT_FILE, 'r') as f:
                            for line in f:
                                if line.startswith('export NANOHUB_API_KEY='):
                                    api_key = line.split('=', 1)[1].strip().strip('"\'')
                                    break
                    except Exception:
                        pass

                    auth_string = base64.b64encode(f'{Config.MDM_API_USER}:{api_key}'.encode()).decode()
                    url = f'{Config.MDM_ENQUEUE_URL}/{device_uuid}'
                    req = urllib.request.Request(url, data=plist.encode('utf-8'), method='PUT')
                    req.add_header('Content-Type', 'application/xml')
                    req.add_header('Authorization', f'Basic {auth_string}')

                    with urllib.request.urlopen(req, timeout=10) as resp:
                        if resp.status == 200:
                            ddm_sync_sent = True
                            logger.info(f"DeclarativeManagement command sent to {device_uuid}")
                except Exception as e:
                    logger.warning(f"Failed to send DeclarativeManagement to {device_uuid}: {e}")

            # Read current DDM status from status_declarations table
            status_rows = db.query_all("""
                SELECT declaration_identifier, active, valid, server_token, updated_at
                FROM status_declarations
                WHERE enrollment_id = %s
                ORDER BY declaration_identifier
            """, (device_uuid,))

            declarations = []
            for row in status_rows or []:
                is_active = row.get('active') == 1 or row.get('active') == True
                is_valid = row.get('valid') == 1 or row.get('valid') == True or row.get('valid') == 'valid'
                declarations.append({
                    'identifier': row.get('declaration_identifier', ''),
                    'active': is_active,
                    'valid': is_valid,
                    'updated_at': row['updated_at'].strftime('%Y-%m-%d %H:%M') if row.get('updated_at') else '-'
                })

            # Cache in device_details
            if declarations:
                db.execute("""
                    INSERT INTO device_details (uuid, ddm_data, ddm_updated_at)
                    VALUES (%s, %s, NOW())
                    ON DUPLICATE KEY UPDATE ddm_data = VALUES(ddm_data), ddm_updated_at = NOW()
                """, (device_uuid, json.dumps(declarations)))

            result = {
                'success': True,
                'data': {'declarations': declarations, 'count': len(declarations)},
                'query_type': 'ddm',
                'cached': False
            }
            if ddm_sync_sent:
                result['message'] = 'DDM sync command sent. Data will update when device responds.'

            return jsonify(result)
        except Exception as e:
            logger.error(f"Failed to get DDM status for {device_uuid}: {e}")
            return jsonify({'success': False, 'error': str(e)})

    # Execute MDM query (and save to DB)
    result = execute_device_query(device_uuid, query_type)

    if result.get('success'):
        result['cached'] = False

    return jsonify(result)


@devices_bp.route('/api/device/<device_uuid>/cached', methods=['GET'])
@login_required_admin
def api_device_cached(device_uuid):
    """API endpoint to get all cached device data from DB"""
    user = session.get('user', {})

    # Validate device access
    if user.get('manifest_filter'):
        if not validate_device_access(device_uuid, user):
            return jsonify({'success': False, 'error': 'Access denied'}), 403

    cached = get_device_details(device_uuid)
    if cached:
        return jsonify({
            'success': True,
            'data': cached
        })
    else:
        return jsonify({
            'success': True,
            'data': None,
            'message': 'No cached data available'
        })
