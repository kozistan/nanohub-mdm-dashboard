"""
NanoHUB Admin - Profile Management
===================================
Routes and functions for managing required profiles.
"""

import os
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import Blueprint, render_template_string, session, request, jsonify

from db_utils import required_profiles
from command_registry import COMMANDS_DIR, PROFILE_DIRS

from .utils import login_required_admin, admin_required
from .core import (
    get_manifests_list,
    get_profiles_by_category,
    normalize_devices_param,
    audit_log,
)

import logging
logger = logging.getLogger('nanohub_admin')

# Create Blueprint
profiles_bp = Blueprint('profiles', __name__)


# =============================================================================
# PROFILE EXECUTION
# =============================================================================

def execute_manage_profiles(params, user_info):
    """Handle Manage Profiles command (install/remove/list on one or more devices)"""

    action = params.get('action')
    devices = normalize_devices_param(params.get('devices'))
    profile = params.get('profile')
    identifier = params.get('identifier')

    if not action:
        return {'success': False, 'error': 'Missing required parameter: action'}
    if not devices:
        return {'success': False, 'error': 'Missing required parameter: devices'}

    # Validate action-specific requirements
    if action == 'install' and not profile:
        return {'success': False, 'error': 'Profile is required for Install action'}
    if action == 'remove' and not identifier:
        return {'success': False, 'error': 'Profile Identifier is required for Remove action'}

    # Map action to script
    script_map = {
        'install': 'install_profile',
        'remove': 'remove_profile',
        'list': 'profile_list'
    }
    script_name = script_map.get(action)
    if not script_name:
        return {'success': False, 'error': f'Invalid action: {action}'}

    script_path = os.path.join(COMMANDS_DIR, script_name)

    output_lines = []
    output_lines.append("=" * 60)
    output_lines.append(f"MANAGE PROFILES - {action.upper()}")
    output_lines.append(f"Devices: {len(devices)}")
    output_lines.append("=" * 60)

    success_count = 0
    fail_count = 0

    def run_profile_cmd(udid):
        try:
            env = os.environ.copy()
            env['PATH'] = '/usr/local/bin:/usr/bin:/bin:' + env.get('PATH', '')

            args = [script_path, udid]
            if action == 'install':
                # Resolve profile path
                profile_path = profile
                if not profile_path.startswith('/'):
                    for pdir in PROFILE_DIRS.values():
                        full_path = os.path.join(pdir, profile_path)
                        if os.path.exists(full_path):
                            profile_path = full_path
                            break
                args.append(profile_path)
            elif action == 'remove':
                args.append(identifier)

            result = subprocess.run(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=60,
                cwd=COMMANDS_DIR,
                env=env
            )

            if result.returncode == 0:
                return {'success': True, 'udid': udid, 'output': result.stdout}
            else:
                return {'success': False, 'udid': udid, 'error': result.stderr or 'Command failed'}

        except subprocess.TimeoutExpired:
            return {'success': False, 'udid': udid, 'error': 'Timeout'}
        except Exception as e:
            return {'success': False, 'udid': udid, 'error': str(e)}

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(run_profile_cmd, udid): udid for udid in devices}
        for future in as_completed(futures):
            result = future.result()
            if result['success']:
                success_count += 1
                output_lines.append(f"[OK] {result['udid']}")
                if action == 'list' and result.get('output'):
                    output_lines.append(result['output'])
            else:
                fail_count += 1
                output_lines.append(f"[FAIL] {result['udid']}: {result.get('error', 'Unknown error')}")

    output_lines.append("")
    output_lines.append("=" * 60)
    output_lines.append(f"SUMMARY: {success_count} success, {fail_count} failed")
    output_lines.append("=" * 60)

    audit_log(
        user=user_info.get('username'),
        action='manage_profiles',
        command='manage_profiles',
        params=params,
        result=f'{success_count} success, {fail_count} failed',
        success=(fail_count == 0)
    )

    return {
        'success': fail_count == 0,
        'output': '\n'.join(output_lines)
    }


# =============================================================================
# ROUTES
# =============================================================================

@profiles_bp.route('/profiles')
@login_required_admin
def admin_profiles():
    """Manage profiles page"""
    user = session.get('user', {})
    manifest_filter = user.get('manifest_filter')

    # Get required profiles grouped by manifest
    req_profiles = required_profiles.get_grouped()

    # Get list of manifests from DB (filtered for site-admin)
    manifests = get_manifests_list(manifest_filter)
    if manifest_filter:
        # Filter req_profiles to only show allowed manifests
        req_profiles = {k: v for k, v in req_profiles.items() if k in manifests}

    # Get available profiles with identifiers for dropdown
    profiles = get_profiles_by_category()
    profile_options = []
    for p in profiles.get('system', []):
        if p.get('identifier'):
            profile_options.append({'name': p['name'], 'identifier': p['identifier']})
    for p in profiles.get('wireguard', []):
        if p.get('identifier'):
            profile_options.append({'name': p['name'], 'identifier': p['identifier']})

    return render_template_string(
        ADMIN_PROFILES_TEMPLATE,
        user=user,
        required_profiles=req_profiles,
        manifests=manifests,
        profile_options=profile_options
    )


@profiles_bp.route('/api/profiles')
@login_required_admin
def api_profiles():
    """Get profiles list (JSON)"""
    profiles = get_profiles_by_category()
    return jsonify(profiles)


@profiles_bp.route('/api/required-profiles')
@login_required_admin
def api_required_profiles():
    """Get required profiles grouped by manifest/os"""
    return jsonify(required_profiles.get_grouped())


@profiles_bp.route('/api/profile-options')
@login_required_admin
def api_profile_options():
    """Debug endpoint - get available profile options"""
    profiles = get_profiles_by_category()

    # Debug: show raw profile data
    system_raw = profiles.get('system', [])[:3]
    wireguard_raw = profiles.get('wireguard', [])[:3]

    profile_options = []
    for p in profiles.get('system', []):
        if p.get('identifier'):
            profile_options.append({'name': p['name'], 'identifier': p['identifier']})
    for p in profiles.get('wireguard', []):
        if p.get('identifier'):
            profile_options.append({'name': p['name'], 'identifier': p['identifier']})

    return jsonify({
        'count': len(profile_options),
        'options': profile_options[:10],
        'debug': {
            'system_count': len(profiles.get('system', [])),
            'wireguard_count': len(profiles.get('wireguard', [])),
            'system_sample': system_raw,
            'wireguard_sample': wireguard_raw
        }
    })


@profiles_bp.route('/api/required-profiles/add', methods=['POST'])
@admin_required
def api_required_profiles_add():
    """Add a new required profile"""
    import fnmatch as fnmatch_mod
    user = session.get('user', {})
    manifest_filter = user.get('manifest_filter')

    data = request.get_json()
    manifest = data.get('manifest', '').strip()
    os_type = data.get('os', '').strip().lower()
    profile_identifier = data.get('profile_identifier', '').strip()
    profile_name = data.get('profile_name', '').strip()
    match_pattern = data.get('match_pattern', False)

    if not all([manifest, os_type, profile_identifier, profile_name]):
        return jsonify({'success': False, 'error': 'Missing required fields'})

    if os_type not in ['ios', 'macos']:
        return jsonify({'success': False, 'error': 'Invalid OS (must be ios or macos)'})

    # Validate manifest access for users with manifest_filter
    if manifest_filter:
        pattern = manifest_filter.replace('%', '*')
        if not fnmatch_mod.fnmatch(manifest, pattern):
            return jsonify({'success': False, 'error': 'Access denied for this manifest'})

    success = required_profiles.add(manifest, os_type, profile_identifier, profile_name, match_pattern)
    if success:
        audit_log(
            user=session.get('user', {}).get('username', 'unknown'),
            action='add_required_profile',
            command='required_profiles_add',
            params={'manifest': manifest, 'os': os_type, 'profile_name': profile_name, 'profile_identifier': profile_identifier},
            result=f"Added {profile_name}",
            success=True
        )
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'Failed to add profile (may already exist)'})


@profiles_bp.route('/api/required-profiles/remove', methods=['POST'])
@admin_required
def api_required_profiles_remove():
    """Remove a required profile by ID"""
    import fnmatch as fnmatch_mod
    user = session.get('user', {})
    manifest_filter = user.get('manifest_filter')

    data = request.get_json()
    profile_id = data.get('id')

    if not profile_id:
        return jsonify({'success': False, 'error': 'Missing profile ID'})

    # Validate manifest access for users with manifest_filter
    if manifest_filter:
        profile = required_profiles.get_by_id(int(profile_id))
        if not profile:
            return jsonify({'success': False, 'error': 'Profile not found'})
        pattern = manifest_filter.replace('%', '*')
        if not fnmatch_mod.fnmatch(profile['manifest'], pattern):
            return jsonify({'success': False, 'error': 'Access denied for this manifest'})

    success = required_profiles.remove(int(profile_id))
    if success:
        audit_log(
            user=session.get('user', {}).get('username', 'unknown'),
            action='remove_required_profile',
            command='required_profiles_remove',
            params={'profile_id': profile_id},
            result=f"Removed profile ID {profile_id}",
            success=True
        )
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'Failed to remove profile'})


# =============================================================================
# TEMPLATE
# =============================================================================

ADMIN_PROFILES_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Required Profiles - NanoHUB Admin</title>
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
        <div style="display: flex; justify-content: center;">
            <img id="logo" src="{{ current_logo }}" alt="Logo" style="max-height:60px;max-width:200px;"/>
        </div>
        <h1>Required Profiles</h1>

        <div class="panel">
            <div class="admin-header">
                <h2>Profile Requirements</h2>
                <div class="nav-tabs" style="margin:0;">
                    <a href="/admin" class="btn">Commands</a>
                    <a href="/admin/devices" class="btn">Devices</a>
                    <a href="/admin/profiles" class="btn active">Profiles</a>
                    <a href="/admin/ddm" class="btn">DDM</a>
                    <a href="/admin/vpp" class="btn">VPP</a>
                    <a href="/admin/reports" class="btn">Reports</a>
                    <a href="/admin/history" class="btn">History</a>
                </div>
                <div>
                    <span style="color:#B0B0B0;font-size:0.85em;">{{ user.display_name or user.username }}</span>
                    <span class="role-badge">{{ user.role }}</span>
                    {% if user.role == 'admin' %}<a href="/admin/settings" class="btn" style="margin-left:10px;">Settings</a>{% endif %}
                    <a href="/admin/help" class="btn" style="margin-left:10px;">Help</a>
                    <a href="/" class="btn" style="margin-left:10px;">Dashboard</a>
                </div>
            </div>

            <!-- Filter row -->
            <div class="filter-form">
                <div class="filter-group">
                    <label>Manifest</label>
                    <select id="filterManifest" onchange="filterProfiles()">
                        <option value="">All Manifests</option>
                        {% for m in manifests %}
                        <option value="{{ m }}">{{ m }}</option>
                        {% endfor %}
                    </select>
                </div>
                <div class="filter-group">
                    <label>OS</label>
                    <select id="filterOS" onchange="filterProfiles()">
                        <option value="">All</option>
                        <option value="macos">macOS</option>
                        <option value="ios">iOS</option>
                    </select>
                </div>
                <div class="filter-group">
                    <label>Search</label>
                    <input type="text" id="filterSearch" placeholder="Profile name..." onkeyup="filterProfiles()">
                </div>
                <div class="filter-buttons" style="margin-left:auto;">
                    <button class="btn btn-primary" onclick="openAddModal()">Add Profile</button>
                </div>
            </div>

            <!-- Profiles Table -->
            <div class="table-wrapper">
            <table class="device-table" id="profilesTable">
                <thead>
                    <tr>
                        <th>Profile Name</th>
                        <th>Identifier</th>
                        <th>OS</th>
                        <th>Manifest</th>
                        <th style="text-align:center;">Pattern</th>
                        <th style="width:80px;text-align:center;">Actions</th>
                    </tr>
                </thead>
                <tbody>
                    {% for m, os_data in required_profiles.items() %}
                        {% for os, profiles in os_data.items() %}
                            {% for p in profiles %}
                    <tr data-manifest="{{ m }}" data-os="{{ os }}" data-name="{{ p.profile_name | lower }}" data-id="{{ p.id }}">
                        <td><span class="app-name">{{ p.profile_name }}</span></td>
                        <td><span class="app-bundle">{{ p.profile_identifier }}</span></td>
                        <td><span class="platform-badge platform-{{ os }}">{{ os }}</span></td>
                        <td>{{ m }}</td>
                        <td style="text-align:center;">{% if p.match_pattern %}<span style="background:rgba(136,38,227,0.2);color:#8826E3;border:1px solid #8826E3;padding:2px 6px;border-radius:3px;font-size:0.8em;">Wildcard</span>{% else %}-{% endif %}</td>
                        <td style="text-align:center;"><button class="btn btn-small btn-danger" style="margin:0;" onclick="removeProfile({{ p.id }})">Remove</button></td>
                    </tr>
                            {% endfor %}
                        {% endfor %}
                    {% endfor %}
                    {% if not required_profiles %}
                    <tr class="no-data"><td colspan="6" style="text-align:center;color:#B0B0B0;padding:20px;">No profiles configured</td></tr>
                    {% endif %}
                </tbody>
            </table>
            </div>

            <div id="pagination-container" style="margin-top:15px;padding:10px 0;border-top:1px solid #3A3A3A;">
                <div id="pageInfo" style="font-size:0.85em;color:#B0B0B0;margin-bottom:8px;"></div>
                <div id="pageNumbers" class="pagination"></div>
            </div>

            <div style="margin-top:15px;padding:10px;background:rgba(245,166,35,0.15);border:1px solid #F5A623;border-radius:5px;font-size:0.85em;color:#F5A623;">
                <strong>Note:</strong> Wildcard pattern matches any profile identifier starting with the given prefix (e.g. <code style="background:#2A2A2A;padding:2px 5px;border-radius:3px;">com.wireguard.%</code>).
            </div>
        </div>
    </div>

    <!-- Add Profile Modal -->
    <div id="addModal" class="modal-overlay" style="display:none;">
        <div class="modal-box">
            <h3>Add Required Profile</h3>
            <div class="modal-body">
                <label>Manifest</label>
                <select id="addManifest">
                    {% for m in manifests %}
                    <option value="{{ m }}">{{ m }}</option>
                    {% endfor %}
                </select>
                <label style="margin-top:10px;">OS</label>
                <select id="addOS">
                    <option value="macos">macOS</option>
                    <option value="ios">iOS</option>
                </select>
                <label style="margin-top:10px;">Profile</label>
                <select id="addProfileSelect" onchange="onProfileSelect()">
                    <option value="">-- Select Profile --</option>
                    {% for p in profile_options %}
                    <option value="{{ p.name }}" data-id="{{ p.identifier }}">{{ p.name }}</option>
                    {% endfor %}
                    <option value="_custom">Custom...</option>
                </select>
                <div id="customFields" style="display:none;margin-top:10px;">
                    <label>Custom Profile Name</label>
                    <input type="text" id="addCustomName" placeholder="Profile Name">
                </div>
                <label style="margin-top:10px;">Identifier</label>
                <input type="text" id="addIdentifier" placeholder="com.example.profile">
                <label style="margin-top:10px;display:flex;align-items:center;gap:8px;font-weight:normal;">
                    <input type="checkbox" id="addPattern" onchange="onPatternChange()"> Use wildcard pattern (%)
                </label>
            </div>
            <div class="modal-footer">
                <button class="btn" onclick="closeAddModal()">Cancel</button>
                <button class="btn btn-primary" onclick="addProfile()">Add Profile</button>
            </div>
        </div>
    </div>

    <script>
    let allRows = [];
    let filteredRows = [];
    let currentPage = 1;
    const itemsPerPage = 50;

    document.addEventListener('DOMContentLoaded', function() {
        allRows = Array.from(document.querySelectorAll('#profilesTable tbody tr:not(.no-data)'));
        filteredRows = allRows;
        showPage();
    });

    function filterProfiles() {
        const manifest = document.getElementById('filterManifest').value;
        const os = document.getElementById('filterOS').value;
        const search = document.getElementById('filterSearch').value.toLowerCase();

        filteredRows = allRows.filter(row => {
            if (manifest && row.dataset.manifest !== manifest) return false;
            if (os && row.dataset.os !== os) return false;
            if (search && !row.dataset.name.includes(search)) return false;
            return true;
        });

        currentPage = 1;
        showPage();
    }

    function showPage() {
        const start = (currentPage - 1) * itemsPerPage;
        const end = start + itemsPerPage;
        const totalPages = Math.ceil(filteredRows.length / itemsPerPage) || 1;

        allRows.forEach(row => row.style.display = 'none');
        filteredRows.slice(start, end).forEach(row => row.style.display = '');

        document.getElementById('pageInfo').textContent = filteredRows.length > 0
            ? `Showing ${start + 1}-${Math.min(end, filteredRows.length)} of ${filteredRows.length} (Page ${currentPage} of ${totalPages})`
            : 'No profiles found';

        renderPageNumbers(totalPages);
    }

    function renderPageNumbers(totalPages) {
        const container = document.getElementById('pageNumbers');
        if (totalPages <= 1) { container.innerHTML = ''; return; }

        let html = '';
        if (currentPage > 1) {
            html += '<a onclick="goToPage(' + (currentPage - 1) + ')">&laquo; Prev</a>';
        } else {
            html += '<span class="disabled">&laquo; Prev</span>';
        }
        for (let p = 1; p <= totalPages; p++) {
            if (p === currentPage) {
                html += '<span class="current">' + p + '</span>';
            } else if (p <= 3 || p > totalPages - 2 || (p >= currentPage - 1 && p <= currentPage + 1)) {
                html += '<a onclick="goToPage(' + p + ')">' + p + '</a>';
            } else if (p === 4 || p === totalPages - 2) {
                html += '<span>...</span>';
            }
        }
        if (currentPage < totalPages) {
            html += '<a onclick="goToPage(' + (currentPage + 1) + ')">Next &raquo;</a>';
        } else {
            html += '<span class="disabled">Next &raquo;</span>';
        }
        container.innerHTML = html;
    }

    function goToPage(page) {
        currentPage = page;
        showPage();
    }

    function openAddModal() {
        document.getElementById('addModal').style.display = 'flex';
        document.getElementById('addProfileSelect').value = '';
        document.getElementById('addIdentifier').value = '';
        document.getElementById('addIdentifier').readOnly = true;
        document.getElementById('addPattern').checked = false;
        document.getElementById('customFields').style.display = 'none';
        document.getElementById('addCustomName').value = '';
    }

    function closeAddModal() {
        document.getElementById('addModal').style.display = 'none';
    }

    function onProfileSelect() {
        const sel = document.getElementById('addProfileSelect');
        const idInput = document.getElementById('addIdentifier');
        const customFields = document.getElementById('customFields');

        if (sel.value === '_custom') {
            customFields.style.display = 'block';
            idInput.readOnly = false;
            idInput.value = '';
        } else if (sel.value) {
            customFields.style.display = 'none';
            idInput.readOnly = true;
            idInput.value = sel.options[sel.selectedIndex].dataset.id || '';
        } else {
            customFields.style.display = 'none';
            idInput.readOnly = true;
            idInput.value = '';
        }
    }

    function onPatternChange() {
        const pattern = document.getElementById('addPattern').checked;
        const idInput = document.getElementById('addIdentifier');
        if (pattern) {
            idInput.readOnly = false;
        }
    }

    function addProfile() {
        const manifest = document.getElementById('addManifest').value;
        const os = document.getElementById('addOS').value;
        const sel = document.getElementById('addProfileSelect');
        const customName = document.getElementById('addCustomName').value.trim();
        const identifier = document.getElementById('addIdentifier').value.trim();
        const pattern = document.getElementById('addPattern').checked;

        const name = sel.value === '_custom' ? customName : sel.value;

        if (!name || !identifier) {
            alert('Please select a profile or enter custom name and identifier');
            return;
        }

        fetch('/admin/api/required-profiles/add', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                manifest: manifest,
                os: os,
                profile_name: name,
                profile_identifier: identifier,
                match_pattern: pattern
            })
        })
        .then(r => r.json())
        .then(d => {
            if (d.success) {
                location.reload();
            } else {
                alert('Error: ' + d.error);
            }
        })
        .catch(e => alert('Error: ' + e));
    }

    function removeProfile(id) {
        if (!confirm('Remove this profile requirement?')) return;

        fetch('/admin/api/required-profiles/remove', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({id: id})
        })
        .then(r => r.json())
        .then(d => {
            if (d.success) {
                const row = document.querySelector('tr[data-id="' + id + '"]');
                if (row) row.remove();
                allRows = Array.from(document.querySelectorAll('#profilesTable tbody tr:not(.no-data)'));
                filterProfiles();
            } else {
                alert('Error: ' + d.error);
            }
        })
        .catch(e => alert('Error: ' + e));
    }
    </script>
</body>
</html>
'''
