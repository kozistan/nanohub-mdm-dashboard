"""
NanoHUB Admin - Devices Routes
==============================
Device inventory list page.
"""

import logging
from functools import wraps

from flask import Blueprint, render_template_string, session, redirect, url_for, request, jsonify

logger = logging.getLogger('nanohub_admin')

# Create a blueprint for Devices routes
devices_bp = Blueprint('admin_devices', __name__)


def login_required_admin(f):
    """Require any authenticated user for admin panel"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'error': 'Session expired. Please log in again.'}), 401
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function


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
    <link rel="stylesheet" href="/static/css/admin.css">
    <link rel="shortcut icon" href="/static/favicon.ico">
</head>
<body>
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
                <div class="filter-buttons" style="margin-left:auto;">
                    <button class="btn" onclick="selectAllFiltered()">Select All</button>
                    <button class="btn" onclick="deselectAll()">Deselect</button>
                    <span class="selected-count" id="selectedCount">0 selected</span>
                    <button class="btn" onclick="refreshDeviceData()" style="background:#F5A623;color:#0D0D0D;border-color:#F5A623;">Refresh Data</button>
                </div>
            </div>

            <div id="loading" style="display:none;text-align:center;padding:15px;background:#1E1E1E;border:1px solid #5FC812;border-radius:5px;margin-bottom:10px;">
                <span style="color:#5FC812;">Processing...</span>
            </div>
            <div id="resultPanel" style="display:none;padding:12px;border-radius:5px;margin-bottom:10px;">
                <div style="display:flex;justify-content:space-between;align-items:center;">
                    <strong id="resultTitle">Result</strong>
                    <button onclick="closeResult()" style="padding:4px 10px;cursor:pointer;">Close</button>
                </div>
                <div id="resultContent" style="margin-top:8px;white-space:pre-wrap;"></div>
            </div>

            <div style="overflow-x:auto;">
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
        const itemsPerPage = 30;

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
                return matchSearch && matchOS && matchStatus && matchSupervised && matchEncrypted && matchOutdated;
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
    return render_template_string(ADMIN_DEVICES_TEMPLATE, user=user)
