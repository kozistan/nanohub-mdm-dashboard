"""
NanoHUB Admin - DDM Routes
==========================
Declarative Device Management page with database storage.
"""

import logging
import json
import os
import urllib.request
import urllib.error
import base64
from datetime import datetime

from flask import Blueprint, render_template_string, session, request, jsonify

from config import Config
from db_utils import db, app_settings
from nanohub_admin.utils import login_required_admin

logger = logging.getLogger('nanohub_admin')

# Create a blueprint for DDM routes
ddm_bp = Blueprint('admin_ddm', __name__)


def get_api_credentials():
    """Load NanoHUB API credentials from environment.sh"""
    nanohub_url = 'http://localhost:9004'
    api_key = ''
    env_file = '/opt/nanohub/environment.sh'
    if os.path.exists(env_file):
        with open(env_file, 'r') as f:
            for line in f:
                if line.startswith('export NANOHUB_URL='):
                    nanohub_url = line.split('=', 1)[1].strip().strip('"\'')
                elif line.startswith('export NANOHUB_API_KEY='):
                    api_key = line.split('=', 1)[1].strip().strip('"\'')
    return nanohub_url, api_key


def upload_declaration_to_kmfddm(identifier: str, decl_type: str, payload: dict) -> tuple:
    """
    Upload declaration to KMFDDM server.
    Returns (success: bool, error: str or None)
    """
    try:
        nanohub_url, api_key = get_api_credentials()
        if not api_key:
            return False, 'API key not configured'

        # Build full declaration payload for KMFDDM
        full_payload = {
            'Type': decl_type,
            'Identifier': identifier,
            'Payload': payload
        }

        auth_string = base64.b64encode(f"nanohub:{api_key}".encode()).decode()
        req = urllib.request.Request(
            f"{nanohub_url}/api/v1/ddm/declarations",
            data=json.dumps(full_payload).encode(),
            headers={
                'Authorization': f'Basic {auth_string}',
                'Content-Type': 'application/json'
            },
            method='PUT'
        )

        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()

        return True, None
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else str(e)
        logger.error(f"Failed to upload declaration to KMFDDM: {e} - {error_body}")
        return False, f'KMFDDM error: {error_body}'
    except Exception as e:
        logger.error(f"Failed to upload declaration to KMFDDM: {e}")
        return False, str(e)


def delete_declaration_from_kmfddm(identifier: str) -> tuple:
    """
    Delete declaration from KMFDDM server.
    Returns (success: bool, error: str or None)
    """
    try:
        nanohub_url, api_key = get_api_credentials()
        if not api_key:
            return False, 'API key not configured'

        auth_string = base64.b64encode(f"nanohub:{api_key}".encode()).decode()
        req = urllib.request.Request(
            f"{nanohub_url}/api/v1/ddm/declarations/{identifier}",
            headers={
                'Authorization': f'Basic {auth_string}'
            },
            method='DELETE'
        )

        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()

        return True, None
    except urllib.error.HTTPError as e:
        # 404 is OK - declaration might not exist on server
        if e.code == 404:
            return True, None
        error_body = e.read().decode() if e.fp else str(e)
        logger.error(f"Failed to delete declaration from KMFDDM: {e} - {error_body}")
        return False, f'KMFDDM error: {error_body}'
    except Exception as e:
        logger.error(f"Failed to delete declaration from KMFDDM: {e}")
        return False, str(e)


def upload_set_to_kmfddm(set_name: str, declaration_identifiers: list) -> tuple:
    """
    Upload set to KMFDDM server by adding declarations one by one.
    Uses: PUT /set-declarations/{set_name}?declaration={decl_id}
    Returns (success: bool, error: str or None)
    """
    try:
        nanohub_url, api_key = get_api_credentials()
        if not api_key:
            return False, 'API key not configured'

        auth_string = base64.b64encode(f"nanohub:{api_key}".encode()).decode()
        errors = []

        for decl_id in declaration_identifiers:
            try:
                req = urllib.request.Request(
                    f"{nanohub_url}/api/v1/ddm/set-declarations/{set_name}?declaration={decl_id}",
                    headers={'Authorization': f'Basic {auth_string}'},
                    method='PUT'
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    resp.read()
            except urllib.error.HTTPError as e:
                error_body = e.read().decode() if e.fp else str(e)
                errors.append(f"{decl_id}: {error_body}")
            except Exception as e:
                errors.append(f"{decl_id}: {str(e)}")

        if errors:
            return False, '; '.join(errors)
        return True, None
    except Exception as e:
        logger.error(f"Failed to upload set to KMFDDM: {e}")
        return False, str(e)


def delete_set_declarations_from_kmfddm(set_name: str, declaration_identifiers: list) -> tuple:
    """
    Remove declarations from set on KMFDDM server.
    Uses: DELETE /set-declarations/{set_name}?declaration={decl_id}
    Returns (success: bool, error: str or None)
    """
    try:
        nanohub_url, api_key = get_api_credentials()
        if not api_key:
            return False, 'API key not configured'

        auth_string = base64.b64encode(f"nanohub:{api_key}".encode()).decode()

        for decl_id in declaration_identifiers:
            try:
                req = urllib.request.Request(
                    f"{nanohub_url}/api/v1/ddm/set-declarations/{set_name}?declaration={decl_id}",
                    headers={'Authorization': f'Basic {auth_string}'},
                    method='DELETE'
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    resp.read()
            except urllib.error.HTTPError as e:
                # 404 is OK - declaration might not exist in set
                if e.code != 404:
                    logger.warning(f"Failed to remove {decl_id} from set {set_name}: {e}")
            except Exception as e:
                logger.warning(f"Failed to remove {decl_id} from set {set_name}: {e}")

        return True, None
    except Exception as e:
        logger.error(f"Failed to delete set declarations from KMFDDM: {e}")
        return False, str(e)


def get_set_declarations_from_kmfddm(set_name: str) -> list:
    """
    Get declarations in a set from KMFDDM server.
    Returns list of declaration identifiers.
    """
    try:
        nanohub_url, api_key = get_api_credentials()
        if not api_key:
            return []

        auth_string = base64.b64encode(f"nanohub:{api_key}".encode()).decode()
        req = urllib.request.Request(
            f"{nanohub_url}/api/v1/ddm/set-declarations/{set_name}",
            headers={'Authorization': f'Basic {auth_string}'}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return data if isinstance(data, list) else []
    except:
        return []


# =============================================================================
# ADMIN DDM TEMPLATE
# =============================================================================

ADMIN_DDM_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>DDM - NanoHUB Admin</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="/static/dashboard.css">
    <link rel="stylesheet" href="/static/css/qbone.css">
    <link rel="stylesheet" href="/static/css/admin.css">
    <link rel="shortcut icon" href="/static/favicon.ico">
    <style>
    /* DDM-specific styles - modal styles inherited from admin.css */
    .checkbox-list { max-height:200px; overflow-y:auto; border:1px solid #3A3A3A; border-radius:4px; padding:10px; background:#2A2A2A; margin-bottom:10px; }
    .checkbox-list label { display:flex; align-items:center; gap:8px; padding:5px 0; cursor:pointer; color:#FFFFFF; font-size:0.9em; }
    .checkbox-list input[type="checkbox"] { width:auto; margin:0; }
    .status-badge { padding:2px 8px; border-radius:10px; font-size:0.8em; }
    .status-uploaded { background:rgba(95,200,18,0.15); color:#5FC812; border:1px solid #5FC812; }
    .status-pending { background:rgba(245,166,35,0.15); color:#F5A623; border:1px solid #F5A623; }
    .modal-box textarea { min-height:200px; font-family:monospace; }
    </style>
</head>
<body class="page-with-table">
    <div id="wrap">
        <div style="display: flex; justify-content: center; align-items: center;">
            <img id="logo" src="{{ current_logo }}" alt="Logo" style="max-height:60px;max-width:200px;"/>
        </div>
        <h1>Declarative Device Management</h1>

        <div class="panel">
            <div class="admin-header">
                <h2>DDM</h2>
                <div class="nav-tabs" style="margin:0;">
                    <a href="/admin" class="btn">Commands</a>
                    <a href="/admin/devices" class="btn">Devices</a>
                    <a href="/admin/profiles" class="btn">Profiles</a>
                    <a href="/admin/ddm" class="btn active">DDM</a>
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

            <div class="sub-tabs">
                <a href="#" onclick="showSubTab('declarations')" class="active" id="subtab-declarations">Declarations</a>
                <a href="#" onclick="showSubTab('sets')" id="subtab-sets">Sets</a>
                <a href="#" onclick="showSubTab('required')" id="subtab-required">Required Sets</a>
            </div>

            <!-- Declarations Tab -->
            <div id="tab-declarations" class="sub-tab-content">
                <div class="filter-form">
                    <div class="filter-group">
                        <label>Type</label>
                        <select id="filterType" onchange="filterDeclarations()">
                            <option value="">All Types</option>
                        </select>
                    </div>
                    <div class="filter-group">
                        <label>Search</label>
                        <input type="text" id="filterSearch" placeholder="Identifier..." onkeyup="filterDeclarations()">
                    </div>
                    <div class="filter-buttons" style="margin-left:auto;">
                        <button class="btn" onclick="showAddDeclarationModal()">+ Add Declaration</button>
                        <button class="btn" onclick="showImportDeclarationsModal()">Import from Files</button>
                        <button class="btn" onclick="loadDeclarations()">Refresh</button>
                        <span class="selected-count" id="declarationsCount">-</span>
                    </div>
                </div>

                <table class="device-table" id="declarationsTable">
                    <thead>
                        <tr>
                            <th>Identifier</th>
                            <th>Type</th>
                            <th>Updated</th>
                            <th style="text-align:right;">Actions</th>
                        </tr>
                    </thead>
                    <tbody id="declarations-tbody">
                        <tr><td colspan="4" style="text-align:center;color:#B0B0B0;">Loading...</td></tr>
                    </tbody>
                </table>
            </div>

            <!-- Sets Tab -->
            <div id="tab-sets" class="sub-tab-content" style="display:none;">
                <div class="filter-form">
                    <div class="filter-group">
                        <label>Search</label>
                        <input type="text" id="filterSetsSearch" placeholder="Set name..." onkeyup="filterSets()">
                    </div>
                    <div class="filter-buttons" style="margin-left:auto;">
                        <button class="btn" onclick="showAddSetModal()">+ Create Set</button>
                        <button class="btn" onclick="loadSets()">Refresh</button>
                        <span class="selected-count" id="setsCount">-</span>
                    </div>
                </div>

                <table class="device-table" id="setsTable">
                    <thead>
                        <tr>
                            <th>Set Name</th>
                            <th>Declarations</th>
                            <th>Updated</th>
                            <th style="text-align:right;">Actions</th>
                        </tr>
                    </thead>
                    <tbody id="sets-tbody">
                        <tr><td colspan="4" style="text-align:center;color:#B0B0B0;">Loading...</td></tr>
                    </tbody>
                </table>
            </div>

            <!-- Required Sets Tab -->
            <div id="tab-required" class="sub-tab-content" style="display:none;">
                <div class="filter-form">
                    <div class="filter-group">
                        <label>Manifest</label>
                        <select id="filterManifest" onchange="loadRequiredSets()">
                            <option value="">All manifests</option>
                            {% for m in manifests %}
                            <option value="{{ m }}">{{ m }}</option>
                            {% endfor %}
                        </select>
                    </div>
                    <div class="filter-group">
                        <label>OS</label>
                        <select id="filterOS" onchange="loadRequiredSets()">
                            <option value="">All</option>
                            <option value="macos">macOS</option>
                            <option value="ios">iOS</option>
                        </select>
                    </div>
                    <div class="filter-buttons" style="margin-left:auto;">
                        <button class="btn" onclick="showAddRequiredSetModal()">+ Assign Set</button>
                        <button class="btn" onclick="loadRequiredSets()">Refresh</button>
                    </div>
                </div>

                <table class="device-table" id="requiredTable">
                    <thead>
                        <tr>
                            <th>Manifest</th>
                            <th>OS</th>
                            <th>Set Name</th>
                            <th>Declarations</th>
                            <th style="text-align:right;">Actions</th>
                        </tr>
                    </thead>
                    <tbody id="required-tbody">
                        <tr><td colspan="5" style="text-align:center;color:#B0B0B0;">Loading...</td></tr>
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <!-- Add Declaration Modal -->
    <div id="addDeclarationModal" class="modal-overlay">
        <div class="modal-box">
            <h3>Add Declaration</h3>
            <div class="modal-body">
                <label>Identifier</label>
                <input type="text" id="declIdentifier" placeholder="e.g. com.example.wifi-config">
                <label>Type</label>
                <input type="text" id="declType" placeholder="e.g. com.apple.configuration.wifi">
                <label>Payload (JSON)</label>
                <textarea id="declPayload" placeholder='{"Type": "...", "Identifier": "...", "Payload": {...}}'></textarea>
            </div>
            <div class="modal-footer">
                <button class="btn" onclick="closeModal('addDeclarationModal')">Cancel</button>
                <button class="btn btn-primary" onclick="saveDeclaration()">Save</button>
            </div>
        </div>
    </div>

    <!-- Import Declarations Modal -->
    <div id="importDeclarationsModal" class="modal-overlay">
        <div class="modal-box">
            <h3>Import Declarations from Files</h3>
            <div class="modal-body">
                <p class="text-muted" style="font-size:0.85em;margin-bottom:15px;">Import JSON declarations from /opt/nanohub/ddm/declarations/</p>
                <div id="importFilesList" class="checkbox-list">Loading files...</div>
            </div>
            <div class="modal-footer">
                <button class="btn" onclick="closeModal('importDeclarationsModal')">Cancel</button>
                <button class="btn btn-primary" onclick="importSelectedDeclarations()">Import Selected</button>
            </div>
        </div>
    </div>

    <!-- Add/Edit Set Modal -->
    <div id="addSetModal" class="modal-overlay">
        <div class="modal-box">
            <h3 id="setModalTitle">Create Set</h3>
            <div class="modal-body">
                <input type="hidden" id="editSetId">
                <label>Set Name</label>
                <input type="text" id="setName" placeholder="e.g. default-config">
                <label>Description</label>
                <input type="text" id="setDescription" placeholder="Optional description">
                <label>Select Declarations</label>
                <div id="setDeclarationsList" class="checkbox-list">Loading...</div>
            </div>
            <div class="modal-footer">
                <button class="btn" onclick="closeModal('addSetModal')">Cancel</button>
                <button class="btn btn-primary" onclick="saveSet()">Save</button>
            </div>
        </div>
    </div>

    <!-- Add Required Set Modal -->
    <div id="addRequiredSetModal" class="modal-overlay">
        <div class="modal-box">
            <h3>Assign DDM Set to Manifest</h3>
            <div class="modal-body">
                <label>Manifest</label>
                <select id="reqManifest">
                    {% for m in manifests %}
                    <option value="{{ m }}">{{ m }}</option>
                    {% endfor %}
                </select>
                <label>OS</label>
                <select id="reqOS">
                    <option value="macos">macOS</option>
                    <option value="ios">iOS</option>
                </select>
                <label>DDM Set</label>
                <select id="reqSet">
                    <option value="">Select set...</option>
                </select>
            </div>
            <div class="modal-footer">
                <button class="btn" onclick="closeModal('addRequiredSetModal')">Cancel</button>
                <button class="btn btn-primary" onclick="saveRequiredSet()">Assign</button>
            </div>
        </div>
    </div>

    <script>
    let allDeclarations = [];
    let filteredDeclarations = [];
    let allSets = [];
    let filteredSets = [];

    function showSubTab(tabName) {
        event.preventDefault();
        document.querySelectorAll('.sub-tab-content').forEach(el => el.style.display = 'none');
        document.querySelectorAll('.sub-tabs a').forEach(el => el.classList.remove('active'));
        document.getElementById('tab-' + tabName).style.display = 'block';
        document.getElementById('subtab-' + tabName).classList.add('active');
    }

    function closeModal(id) {
        document.getElementById(id).style.display = 'none';
    }

    // === DECLARATIONS ===
    function loadDeclarations() {
        fetch('/admin/api/ddm/declarations')
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    allDeclarations = data.declarations || [];
                    const types = [...new Set(allDeclarations.map(d => d.type))].sort();
                    const typeSelect = document.getElementById('filterType');
                    typeSelect.innerHTML = '<option value="">All Types</option>';
                    types.forEach(t => typeSelect.innerHTML += '<option value="' + t + '">' + t + '</option>');
                    filterDeclarations();
                } else {
                    document.getElementById('declarations-tbody').innerHTML = '<tr><td colspan="4" style="color:#D91F25;">Error: ' + data.error + '</td></tr>';
                }
            });
    }

    function filterDeclarations() {
        const typeFilter = document.getElementById('filterType').value;
        const searchFilter = document.getElementById('filterSearch').value.toLowerCase();
        filteredDeclarations = allDeclarations.filter(d => {
            if (typeFilter && d.type !== typeFilter) return false;
            if (searchFilter && !d.identifier.toLowerCase().includes(searchFilter)) return false;
            return true;
        });
        renderDeclarations();
        document.getElementById('declarationsCount').textContent = filteredDeclarations.length + ' declarations';
    }

    function renderDeclarations() {
        const tbody = document.getElementById('declarations-tbody');
        if (filteredDeclarations.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:#B0B0B0;">No declarations found</td></tr>';
            return;
        }
        let html = '';
        filteredDeclarations.forEach(d => {
            html += '<tr>';
            html += '<td><span style="font-family:monospace;">' + d.identifier + '</span></td>';
            html += '<td>' + d.type + '</td>';
            html += '<td style="font-size:0.85em;color:#B0B0B0;">' + (d.updated_at || '-') + '</td>';
            html += '<td style="text-align:right;">';
            html += '<button class="btn btn-small" onclick="viewDeclaration(' + d.id + ')">View</button> ';
            html += '<button class="btn btn-small btn-danger" onclick="removeDeclaration(' + d.id + ')">Remove</button>';
            html += '</td></tr>';
        });
        tbody.innerHTML = html;
    }

    function showAddDeclarationModal() {
        document.getElementById('declIdentifier').value = '';
        document.getElementById('declType').value = '';
        document.getElementById('declPayload').value = '';
        document.getElementById('addDeclarationModal').style.display = 'flex';
    }

    function saveDeclaration() {
        const identifier = document.getElementById('declIdentifier').value.trim();
        const type = document.getElementById('declType').value.trim();
        const payloadStr = document.getElementById('declPayload').value.trim();

        if (!identifier || !type || !payloadStr) {
            alert('All fields are required');
            return;
        }

        let payload;
        try {
            payload = JSON.parse(payloadStr);
        } catch(e) {
            alert('Invalid JSON payload: ' + e.message);
            return;
        }

        fetch('/admin/api/ddm/declarations', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({identifier, type, payload})
        })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                closeModal('addDeclarationModal');
                loadDeclarations();
            } else {
                alert('Error: ' + data.error);
            }
        });
    }

    function removeDeclaration(id) {
        if (!confirm('Remove this declaration from database? (JSON file on disk will not be deleted)')) return;
        fetch('/admin/api/ddm/declarations/' + id, {method: 'DELETE'})
            .then(r => r.json())
            .then(data => {
                if (data.success) loadDeclarations();
                else alert('Error: ' + data.error);
            });
    }

    function viewDeclaration(id) {
        const decl = allDeclarations.find(d => d.id === id);
        if (decl) {
            document.getElementById('declIdentifier').value = decl.identifier;
            document.getElementById('declType').value = decl.type;
            document.getElementById('declPayload').value = JSON.stringify(decl.payload, null, 2);
            document.getElementById('addDeclarationModal').style.display = 'flex';
        }
    }

    function showImportDeclarationsModal() {
        document.getElementById('importDeclarationsModal').style.display = 'flex';
        fetch('/admin/api/ddm/declarations/files')
            .then(r => r.json())
            .then(data => {
                if (data.success && data.files.length > 0) {
                    let html = '';
                    data.files.forEach(f => {
                        html += '<label><input type="checkbox" value="' + f.filename + '"> ' + f.filename + ' <span style="color:#B0B0B0;">(' + f.type + ')</span></label>';
                    });
                    document.getElementById('importFilesList').innerHTML = html;
                } else {
                    document.getElementById('importFilesList').innerHTML = '<p style="color:#B0B0B0;">No JSON files found in /opt/nanohub/ddm/declarations/</p>';
                }
            });
    }

    function importSelectedDeclarations() {
        const checkboxes = document.querySelectorAll('#importFilesList input[type="checkbox"]:checked');
        const files = Array.from(checkboxes).map(cb => cb.value);
        if (files.length === 0) {
            alert('Select at least one file');
            return;
        }
        fetch('/admin/api/ddm/declarations/import', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({files})
        })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                alert('Imported ' + data.imported + ' declarations');
                closeModal('importDeclarationsModal');
                loadDeclarations();
            } else {
                alert('Error: ' + data.error);
            }
        });
    }

    // === SETS ===
    function loadSets() {
        fetch('/admin/api/ddm/sets')
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    allSets = data.sets || [];
                    filterSets();
                } else {
                    document.getElementById('sets-tbody').innerHTML = '<tr><td colspan="4" style="color:#D91F25;">Error: ' + data.error + '</td></tr>';
                }
            });
    }

    function filterSets() {
        const searchFilter = document.getElementById('filterSetsSearch').value.toLowerCase();
        filteredSets = allSets.filter(s => !searchFilter || s.name.toLowerCase().includes(searchFilter));
        renderSets();
        document.getElementById('setsCount').textContent = filteredSets.length + ' sets';
    }

    function renderSets() {
        const tbody = document.getElementById('sets-tbody');
        if (filteredSets.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:#B0B0B0;">No sets found</td></tr>';
            return;
        }
        let html = '';
        filteredSets.forEach(s => {
            html += '<tr>';
            html += '<td><strong>' + s.name + '</strong></td>';
            html += '<td>' + s.declaration_count + ' declarations</td>';
            html += '<td style="font-size:0.85em;color:#B0B0B0;">' + (s.updated_at || '-') + '</td>';
            html += '<td style="text-align:right;">';
            html += '<button class="btn btn-small" onclick="editSet(' + s.id + ')">Edit</button> ';
            html += '<button class="btn btn-small btn-danger" onclick="removeSet(' + s.id + ')">Remove</button>';
            html += '</td></tr>';
        });
        tbody.innerHTML = html;
    }

    function showAddSetModal() {
        document.getElementById('setModalTitle').textContent = 'Create Set';
        document.getElementById('editSetId').value = '';
        document.getElementById('setName').value = '';
        document.getElementById('setDescription').value = '';
        loadDeclarationsForSet([]);
        document.getElementById('addSetModal').style.display = 'flex';
    }

    function loadDeclarationsForSet(selectedIds) {
        fetch('/admin/api/ddm/declarations')
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    let html = '';
                    data.declarations.forEach(d => {
                        const checked = selectedIds.includes(d.id) ? 'checked' : '';
                        html += '<label><input type="checkbox" value="' + d.id + '" ' + checked + '> ' + d.identifier + '</label>';
                    });
                    document.getElementById('setDeclarationsList').innerHTML = html || '<p style="color:#B0B0B0;">No declarations available</p>';
                }
            });
    }

    function editSet(id) {
        const set = allSets.find(s => s.id === id);
        if (set) {
            document.getElementById('setModalTitle').textContent = 'Edit Set';
            document.getElementById('editSetId').value = id;
            document.getElementById('setName').value = set.name;
            document.getElementById('setDescription').value = set.description || '';
            loadDeclarationsForSet(set.declaration_ids || []);
            document.getElementById('addSetModal').style.display = 'flex';
        }
    }

    function saveSet() {
        const id = document.getElementById('editSetId').value;
        const name = document.getElementById('setName').value.trim();
        const description = document.getElementById('setDescription').value.trim();
        const checkboxes = document.querySelectorAll('#setDeclarationsList input[type="checkbox"]:checked');
        const declarationIds = Array.from(checkboxes).map(cb => parseInt(cb.value));

        if (!name) {
            alert('Set name is required');
            return;
        }

        const method = id ? 'PUT' : 'POST';
        const url = id ? '/admin/api/ddm/sets/' + id : '/admin/api/ddm/sets';

        fetch(url, {
            method: method,
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name, description, declaration_ids: declarationIds})
        })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                closeModal('addSetModal');
                loadSets();
            } else {
                alert('Error: ' + data.error);
            }
        });
    }

    function removeSet(id) {
        if (!confirm('Remove this set from database?')) return;
        fetch('/admin/api/ddm/sets/' + id, {method: 'DELETE'})
            .then(r => r.json())
            .then(data => {
                if (data.success) loadSets();
                else alert('Error: ' + data.error);
            });
    }

    // === REQUIRED SETS ===
    function loadRequiredSets() {
        const manifest = document.getElementById('filterManifest').value;
        const os = document.getElementById('filterOS').value;
        let url = '/admin/api/ddm/required?';
        const params = [];
        if (manifest) params.push('manifest=' + encodeURIComponent(manifest));
        if (os) params.push('os=' + encodeURIComponent(os));
        url += params.join('&');

        fetch(url)
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    renderRequiredSets(data.required || []);
                } else {
                    document.getElementById('required-tbody').innerHTML = '<tr><td colspan="5" style="color:#D91F25;">Error: ' + data.error + '</td></tr>';
                }
            });
    }

    function renderRequiredSets(required) {
        const tbody = document.getElementById('required-tbody');
        if (required.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:#B0B0B0;">No required sets configured</td></tr>';
            return;
        }
        let html = '';
        required.forEach(r => {
            const osBadge = '<span class="os-badge ' + r.os + '">' + (r.os === 'macos' ? 'macOS' : 'iOS') + '</span>';
            html += '<tr>';
            html += '<td>' + r.manifest + '</td>';
            html += '<td>' + osBadge + '</td>';
            html += '<td><strong>' + r.set_name + '</strong></td>';
            html += '<td>' + r.declaration_count + ' declarations</td>';
            html += '<td style="text-align:right;">';
            html += '<button class="btn btn-small btn-danger" onclick="deleteRequiredSet(' + r.id + ')">Remove</button>';
            html += '</td></tr>';
        });
        tbody.innerHTML = html;
    }

    function showAddRequiredSetModal() {
        // Load sets for dropdown
        fetch('/admin/api/ddm/sets')
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    const select = document.getElementById('reqSet');
                    select.innerHTML = '<option value="">Select set...</option>';
                    data.sets.forEach(s => {
                        select.innerHTML += '<option value="' + s.id + '">' + s.name + ' (' + s.declaration_count + ' decl)</option>';
                    });
                }
            });
        document.getElementById('addRequiredSetModal').style.display = 'flex';
    }

    function saveRequiredSet() {
        const manifest = document.getElementById('reqManifest').value;
        const os = document.getElementById('reqOS').value;
        const setId = document.getElementById('reqSet').value;

        if (!manifest || !os || !setId) {
            alert('Select manifest, OS and set');
            return;
        }

        fetch('/admin/api/ddm/required', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({manifest, os, set_id: parseInt(setId)})
        })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                closeModal('addRequiredSetModal');
                loadRequiredSets();
            } else {
                alert('Error: ' + data.error);
            }
        });
    }

    function deleteRequiredSet(id) {
        if (!confirm('Remove this required set?')) return;
        fetch('/admin/api/ddm/required/' + id, {method: 'DELETE'})
            .then(r => r.json())
            .then(data => {
                if (data.success) loadRequiredSets();
                else alert('Error: ' + data.error);
            });
    }

    // Initial load
    document.addEventListener('DOMContentLoaded', function() {
        loadDeclarations();
        loadSets();
        loadRequiredSets();
    });
    </script>
</body>
</html>
'''


# =============================================================================
# ROUTES
# =============================================================================

@ddm_bp.route('/ddm')
@login_required_admin
def admin_ddm():
    """DDM (Declarative Device Management) page"""
    user = session.get('user', {})
    current_logo = app_settings.get('header_logo', '/static/logos/slotegrator_green.png')

    # Get manifests for dropdown
    manifests = []
    try:
        rows = db.query_all("SELECT name FROM manifests ORDER BY name")
        manifests = [r['name'] for r in rows or []]
    except:
        pass

    return render_template_string(ADMIN_DDM_TEMPLATE, user=user, current_logo=current_logo, manifests=manifests)


# === DECLARATIONS API ===

@ddm_bp.route('/api/ddm/declarations')
@login_required_admin
def api_ddm_declarations():
    """Get all DDM declarations from database"""
    try:
        rows = db.query_all("""
            SELECT id, identifier, type, payload, server_token, uploaded_at, updated_at
            FROM ddm_declarations
            ORDER BY identifier
        """)

        declarations = []
        for row in rows or []:
            payload = row.get('payload', {})
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except:
                    payload = {}

            declarations.append({
                'id': row['id'],
                'identifier': row['identifier'],
                'type': row['type'],
                'payload': payload,
                'server_token': row.get('server_token'),
                'uploaded_at': row['uploaded_at'].strftime('%Y-%m-%d %H:%M') if row.get('uploaded_at') else None,
                'updated_at': row['updated_at'].strftime('%Y-%m-%d %H:%M') if row.get('updated_at') else '-'
            })

        return jsonify({'success': True, 'declarations': declarations})
    except Exception as e:
        logger.error(f"Failed to get DDM declarations: {e}")
        return jsonify({'success': False, 'error': str(e)})


@ddm_bp.route('/api/ddm/declarations', methods=['POST'])
@login_required_admin
def api_ddm_declarations_create():
    """Create a new DDM declaration and upload to KMFDDM"""
    try:
        data = request.get_json()
        identifier = data.get('identifier', '').strip()
        decl_type = data.get('type', '').strip()
        payload = data.get('payload', {})

        if not identifier or not decl_type:
            return jsonify({'success': False, 'error': 'Identifier and type are required'})

        payload_dict = payload if isinstance(payload, dict) else json.loads(payload)
        payload_str = json.dumps(payload_dict) if isinstance(payload, dict) else payload

        # Save to local DB
        db.execute("""
            INSERT INTO ddm_declarations (identifier, type, payload)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE type = VALUES(type), payload = VALUES(payload), updated_at = NOW()
        """, (identifier, decl_type, payload_str))

        # Auto-upload to KMFDDM server
        success, error = upload_declaration_to_kmfddm(identifier, decl_type, payload_dict)
        if not success:
            logger.warning(f"Declaration saved to DB but KMFDDM upload failed: {error}")
            return jsonify({'success': True, 'warning': f'Saved locally but KMFDDM upload failed: {error}'})

        # Mark as uploaded
        db.execute("UPDATE ddm_declarations SET uploaded_at = NOW() WHERE identifier = %s", (identifier,))

        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Failed to create DDM declaration: {e}")
        return jsonify({'success': False, 'error': str(e)})


@ddm_bp.route('/api/ddm/declarations/<int:decl_id>', methods=['DELETE'])
@login_required_admin
def api_ddm_declarations_delete(decl_id):
    """Remove DDM declaration from DB and KMFDDM server"""
    try:
        # Get identifier before deleting
        row = db.query_one("SELECT identifier FROM ddm_declarations WHERE id = %s", (decl_id,))
        if not row:
            return jsonify({'success': False, 'error': 'Declaration not found'})

        identifier = row['identifier']

        # Delete from KMFDDM server
        success, error = delete_declaration_from_kmfddm(identifier)
        if not success:
            logger.warning(f"Failed to delete from KMFDDM: {error}")

        # Delete from local DB
        db.execute("DELETE FROM ddm_declarations WHERE id = %s", (decl_id,))

        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Failed to delete DDM declaration: {e}")
        return jsonify({'success': False, 'error': str(e)})


@ddm_bp.route('/api/ddm/declarations/<int:decl_id>/upload', methods=['POST'])
@login_required_admin
def api_ddm_declarations_upload(decl_id):
    """Upload declaration to NanoHUB server"""
    try:
        row = db.query_one("SELECT identifier, type, payload FROM ddm_declarations WHERE id = %s", (decl_id,))
        if not row:
            return jsonify({'success': False, 'error': 'Declaration not found'})

        payload = row['payload']
        if isinstance(payload, str):
            payload = json.loads(payload)

        nanohub_url, api_key = get_api_credentials()
        if not api_key:
            return jsonify({'success': False, 'error': 'API key not configured'})

        auth_string = base64.b64encode(f"nanohub:{api_key}".encode()).decode()
        req = urllib.request.Request(
            f"{nanohub_url}/api/v1/ddm/declarations",
            data=json.dumps(payload).encode(),
            headers={
                'Authorization': f'Basic {auth_string}',
                'Content-Type': 'application/json'
            },
            method='PUT'
        )

        with urllib.request.urlopen(req, timeout=30) as resp:
            result = resp.read().decode()

        # Mark as uploaded
        db.execute("UPDATE ddm_declarations SET uploaded_at = NOW() WHERE id = %s", (decl_id,))

        return jsonify({'success': True})
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else str(e)
        logger.error(f"Failed to upload declaration: {e} - {error_body}")
        return jsonify({'success': False, 'error': f'Server error: {error_body}'})
    except Exception as e:
        logger.error(f"Failed to upload DDM declaration: {e}")
        return jsonify({'success': False, 'error': str(e)})


@ddm_bp.route('/api/ddm/declarations/files')
@login_required_admin
def api_ddm_declarations_files():
    """List JSON files in DDM declarations directory"""
    try:
        ddm_dir = '/opt/nanohub/ddm/declarations'
        files = []
        if os.path.isdir(ddm_dir):
            for filename in os.listdir(ddm_dir):
                if filename.endswith('.json'):
                    filepath = os.path.join(ddm_dir, filename)
                    try:
                        with open(filepath, 'r') as f:
                            data = json.load(f)
                        files.append({
                            'filename': filename,
                            'type': data.get('Type', data.get('type', '-'))
                        })
                    except:
                        files.append({'filename': filename, 'type': 'Error reading'})

        return jsonify({'success': True, 'files': files})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@ddm_bp.route('/api/ddm/declarations/import', methods=['POST'])
@login_required_admin
def api_ddm_declarations_import():
    """Import declarations from JSON files and upload to KMFDDM"""
    try:
        data = request.get_json()
        files = data.get('files', [])
        ddm_dir = '/opt/nanohub/ddm/declarations'

        imported = 0
        upload_errors = []
        for filename in files:
            filepath = os.path.join(ddm_dir, filename)
            if os.path.exists(filepath):
                with open(filepath, 'r') as f:
                    payload = json.load(f)

                identifier = payload.get('Identifier', payload.get('identifier', filename[:-5]))
                decl_type = payload.get('Type', payload.get('type', '-'))
                inner_payload = payload.get('Payload', payload)

                # Save to local DB
                db.execute("""
                    INSERT INTO ddm_declarations (identifier, type, payload)
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE type = VALUES(type), payload = VALUES(payload), updated_at = NOW()
                """, (identifier, decl_type, json.dumps(inner_payload)))

                # Auto-upload to KMFDDM server
                success, error = upload_declaration_to_kmfddm(identifier, decl_type, inner_payload)
                if success:
                    db.execute("UPDATE ddm_declarations SET uploaded_at = NOW() WHERE identifier = %s", (identifier,))
                else:
                    upload_errors.append(f"{identifier}: {error}")

                imported += 1

        result = {'success': True, 'imported': imported}
        if upload_errors:
            result['warnings'] = upload_errors
        return jsonify(result)
    except Exception as e:
        logger.error(f"Failed to import declarations: {e}")
        return jsonify({'success': False, 'error': str(e)})


# === SETS API ===

@ddm_bp.route('/api/ddm/sets')
@login_required_admin
def api_ddm_sets():
    """Get all DDM sets from database"""
    try:
        rows = db.query_all("""
            SELECT s.id, s.name, s.description, s.updated_at,
                   GROUP_CONCAT(sd.declaration_id) as declaration_ids
            FROM ddm_sets s
            LEFT JOIN ddm_set_declarations sd ON s.id = sd.set_id
            GROUP BY s.id
            ORDER BY s.name
        """)

        # Check which sets are on server
        nanohub_url, api_key = get_api_credentials()
        server_sets = set()
        if api_key:
            try:
                auth_string = base64.b64encode(f"nanohub:{api_key}".encode()).decode()
                req = urllib.request.Request(
                    f"{nanohub_url}/api/v1/ddm/sets",
                    headers={'Authorization': f'Basic {auth_string}'}
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    server_data = json.loads(resp.read().decode())
                    if isinstance(server_data, list):
                        for s in server_data:
                            if isinstance(s, str):
                                server_sets.add(s)
                            elif isinstance(s, dict):
                                server_sets.add(s.get('Name', s.get('name', '')))
            except:
                pass

        sets = []
        for row in rows or []:
            decl_ids_str = row.get('declaration_ids') or ''
            decl_ids = [int(x) for x in decl_ids_str.split(',') if x]

            sets.append({
                'id': row['id'],
                'name': row['name'],
                'description': row.get('description'),
                'declaration_count': len(decl_ids),
                'declaration_ids': decl_ids,
                'on_server': row['name'] in server_sets,
                'updated_at': row['updated_at'].strftime('%Y-%m-%d %H:%M') if row.get('updated_at') else '-'
            })

        return jsonify({'success': True, 'sets': sets})
    except Exception as e:
        logger.error(f"Failed to get DDM sets: {e}")
        return jsonify({'success': False, 'error': str(e)})


@ddm_bp.route('/api/ddm/sets', methods=['POST'])
@login_required_admin
def api_ddm_sets_create():
    """Create a new DDM set and upload to KMFDDM"""
    try:
        data = request.get_json()
        name = data.get('name', '').strip()
        description = data.get('description', '').strip()
        declaration_ids = data.get('declaration_ids', [])

        if not name:
            return jsonify({'success': False, 'error': 'Set name is required'})

        db.execute("INSERT INTO ddm_sets (name, description) VALUES (%s, %s)", (name, description or None))

        # Get the new set ID and add declarations
        row = db.query_one("SELECT id FROM ddm_sets WHERE name = %s", (name,))
        declaration_identifiers = []
        if row and declaration_ids:
            for decl_id in declaration_ids:
                db.execute("INSERT IGNORE INTO ddm_set_declarations (set_id, declaration_id) VALUES (%s, %s)", (row['id'], decl_id))
            # Get declaration identifiers for KMFDDM upload
            decl_rows = db.query_all(
                "SELECT identifier FROM ddm_declarations WHERE id IN (%s)" % ','.join(['%s'] * len(declaration_ids)),
                tuple(declaration_ids)
            )
            declaration_identifiers = [r['identifier'] for r in decl_rows or []]

        # Auto-upload to KMFDDM server
        if declaration_identifiers:
            success, error = upload_set_to_kmfddm(name, declaration_identifiers)
            if not success:
                logger.warning(f"Set saved to DB but KMFDDM upload failed: {error}")
                return jsonify({'success': True, 'warning': f'Saved locally but KMFDDM upload failed: {error}'})

        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Failed to create DDM set: {e}")
        return jsonify({'success': False, 'error': str(e)})


@ddm_bp.route('/api/ddm/sets/<int:set_id>', methods=['PUT'])
@login_required_admin
def api_ddm_sets_update(set_id):
    """Update a DDM set and sync to KMFDDM"""
    try:
        data = request.get_json()
        name = data.get('name', '').strip()
        description = data.get('description', '').strip()
        declaration_ids = data.get('declaration_ids', [])

        if not name:
            return jsonify({'success': False, 'error': 'Set name is required'})

        # Get old set name for KMFDDM sync
        old_row = db.query_one("SELECT name FROM ddm_sets WHERE id = %s", (set_id,))
        old_name = old_row['name'] if old_row else name

        # Get old declarations from KMFDDM
        old_decls_on_server = get_set_declarations_from_kmfddm(old_name)

        # Update DB
        db.execute("UPDATE ddm_sets SET name = %s, description = %s WHERE id = %s", (name, description or None, set_id))
        db.execute("DELETE FROM ddm_set_declarations WHERE set_id = %s", (set_id,))
        for decl_id in declaration_ids:
            db.execute("INSERT INTO ddm_set_declarations (set_id, declaration_id) VALUES (%s, %s)", (set_id, decl_id))

        # Get new declaration identifiers
        new_declaration_identifiers = []
        if declaration_ids:
            decl_rows = db.query_all(
                "SELECT identifier FROM ddm_declarations WHERE id IN (%s)" % ','.join(['%s'] * len(declaration_ids)),
                tuple(declaration_ids)
            )
            new_declaration_identifiers = [r['identifier'] for r in decl_rows or []]

        # Sync with KMFDDM - remove old declarations, add new ones
        # If name changed, we need to remove from old set and add to new set
        if old_name != name and old_decls_on_server:
            delete_set_declarations_from_kmfddm(old_name, old_decls_on_server)

        # Remove declarations that are no longer in the set
        decls_to_remove = [d for d in old_decls_on_server if d not in new_declaration_identifiers]
        if decls_to_remove:
            delete_set_declarations_from_kmfddm(name if old_name == name else old_name, decls_to_remove)

        # Add new declarations
        if new_declaration_identifiers:
            success, error = upload_set_to_kmfddm(name, new_declaration_identifiers)
            if not success:
                logger.warning(f"Set updated in DB but KMFDDM sync failed: {error}")
                return jsonify({'success': True, 'warning': f'Saved locally but KMFDDM sync failed: {error}'})

        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Failed to update DDM set: {e}")
        return jsonify({'success': False, 'error': str(e)})


@ddm_bp.route('/api/ddm/sets/<int:set_id>', methods=['DELETE'])
@login_required_admin
def api_ddm_sets_delete(set_id):
    """Delete a DDM set from DB and KMFDDM"""
    try:
        # Get set name and declarations before deleting
        row = db.query_one("SELECT name FROM ddm_sets WHERE id = %s", (set_id,))
        if not row:
            return jsonify({'success': False, 'error': 'Set not found'})

        set_name = row['name']

        # Get declarations from KMFDDM and remove them from the set
        decls_on_server = get_set_declarations_from_kmfddm(set_name)
        if decls_on_server:
            success, error = delete_set_declarations_from_kmfddm(set_name, decls_on_server)
            if not success:
                logger.warning(f"Failed to remove declarations from KMFDDM set {set_name}: {error}")

        # Delete from local DB
        db.execute("DELETE FROM ddm_sets WHERE id = %s", (set_id,))

        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Failed to delete DDM set: {e}")
        return jsonify({'success': False, 'error': str(e)})


@ddm_bp.route('/api/ddm/sets/<int:set_id>/upload', methods=['POST'])
@login_required_admin
def api_ddm_sets_upload(set_id):
    """Manually upload set to KMFDDM server"""
    try:
        row = db.query_one("SELECT name FROM ddm_sets WHERE id = %s", (set_id,))
        if not row:
            return jsonify({'success': False, 'error': 'Set not found'})

        set_name = row['name']

        # Get declaration identifiers
        decl_rows = db.query_all("""
            SELECT d.identifier FROM ddm_declarations d
            JOIN ddm_set_declarations sd ON d.id = sd.declaration_id
            WHERE sd.set_id = %s
        """, (set_id,))

        declaration_identifiers = [r['identifier'] for r in decl_rows or []]

        if not declaration_identifiers:
            return jsonify({'success': False, 'error': 'Set has no declarations'})

        # Upload using correct endpoint
        success, error = upload_set_to_kmfddm(set_name, declaration_identifiers)
        if not success:
            return jsonify({'success': False, 'error': error})

        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Failed to upload DDM set: {e}")
        return jsonify({'success': False, 'error': str(e)})


# === REQUIRED SETS API ===

@ddm_bp.route('/api/ddm/required')
@login_required_admin
def api_ddm_required():
    """Get required DDM sets for manifests"""
    try:
        manifest = request.args.get('manifest')
        os_filter = request.args.get('os')

        conditions = []
        params = []

        if manifest:
            conditions.append("r.manifest = %s")
            params.append(manifest)
        if os_filter:
            conditions.append("r.os = %s")
            params.append(os_filter)

        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

        rows = db.query_all(f"""
            SELECT r.id, r.manifest, r.os, s.id as set_id, s.name as set_name,
                   (SELECT COUNT(*) FROM ddm_set_declarations WHERE set_id = s.id) as declaration_count
            FROM ddm_required_sets r
            JOIN ddm_sets s ON r.set_id = s.id
            {where_clause}
            ORDER BY r.manifest, r.os, s.name
        """, tuple(params) if params else None)

        required = [{
            'id': r['id'],
            'manifest': r['manifest'],
            'os': r['os'],
            'set_id': r['set_id'],
            'set_name': r['set_name'],
            'declaration_count': r['declaration_count']
        } for r in rows or []]

        return jsonify({'success': True, 'required': required})
    except Exception as e:
        logger.error(f"Failed to get required DDM sets: {e}")
        return jsonify({'success': False, 'error': str(e)})


@ddm_bp.route('/api/ddm/required', methods=['POST'])
@login_required_admin
def api_ddm_required_create():
    """Assign a DDM set as required for a manifest"""
    try:
        data = request.get_json()
        manifest = data.get('manifest', '').strip()
        os_type = data.get('os', '').strip()
        set_id = data.get('set_id')

        if not manifest or not os_type or not set_id:
            return jsonify({'success': False, 'error': 'Manifest, os and set_id are required'})

        if os_type not in ('ios', 'macos'):
            return jsonify({'success': False, 'error': 'OS must be ios or macos'})

        db.execute("""
            INSERT IGNORE INTO ddm_required_sets (manifest, os, set_id)
            VALUES (%s, %s, %s)
        """, (manifest, os_type, set_id))

        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Failed to create required DDM set: {e}")
        return jsonify({'success': False, 'error': str(e)})


@ddm_bp.route('/api/ddm/required/<int:req_id>', methods=['DELETE'])
@login_required_admin
def api_ddm_required_delete(req_id):
    """Remove a required DDM set"""
    try:
        db.execute("DELETE FROM ddm_required_sets WHERE id = %s", (req_id,))
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Failed to delete required DDM set: {e}")
        return jsonify({'success': False, 'error': str(e)})


# === DEVICE STATUS API ===

@ddm_bp.route('/api/ddm/device-status/<device_uuid>')
@login_required_admin
def api_ddm_device_status(device_uuid):
    """Get DDM status for a specific device"""
    try:
        # Verify device exists
        device = db.query_one("""
            SELECT uuid, hostname, serial FROM device_inventory WHERE uuid = %s
        """, (device_uuid,))

        if not device:
            return jsonify({'success': False, 'error': 'Device not found'})

        nanohub_url, api_key = get_api_credentials()

        assigned_sets = []
        declarations = []
        errors = []

        # 1. Get assigned sets via API
        if api_key:
            try:
                auth_string = base64.b64encode(f"nanohub:{api_key}".encode()).decode()
                req = urllib.request.Request(
                    f"{nanohub_url}/api/v1/ddm/enrollment-sets/{device_uuid}",
                    headers={'Authorization': f'Basic {auth_string}'}
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode())
                    if data and isinstance(data, list):
                        assigned_sets = data
            except urllib.error.HTTPError as e:
                if e.code != 404:
                    logger.warning(f"Failed to get enrollment sets for {device_uuid}: {e}")
            except Exception as e:
                logger.warning(f"Failed to get enrollment sets for {device_uuid}: {e}")

        # 2. Get declaration status from status_declarations table
        try:
            status_rows = db.query_all("""
                SELECT declaration_identifier, active, valid, server_token, updated_at
                FROM status_declarations
                WHERE enrollment_id = %s
                ORDER BY declaration_identifier
            """, (device_uuid,))

            for row in status_rows or []:
                is_active = row.get('active') == 1 or row.get('active') == True
                is_valid = row.get('valid') == 1 or row.get('valid') == True or row.get('valid') == 'valid'
                declarations.append({
                    'identifier': row.get('declaration_identifier', ''),
                    'active': is_active,
                    'valid': is_valid,
                    'server_token': row.get('server_token', ''),
                    'updated_at': row['updated_at'].strftime('%Y-%m-%d %H:%M') if row.get('updated_at') else '-',
                    'error': None
                })
        except Exception as e:
            logger.warning(f"Failed to get status_declarations for {device_uuid}: {e}")

        # 3. Get errors from status_errors table
        try:
            error_rows = db.query_all("""
                SELECT declaration_identifier, reasons, updated_at
                FROM status_errors
                WHERE enrollment_id = %s
            """, (device_uuid,))

            error_map = {}
            for row in error_rows or []:
                decl_id = row.get('declaration_identifier', '')
                reasons = row.get('reasons', '')
                if isinstance(reasons, str):
                    try:
                        reasons = json.loads(reasons)
                    except:
                        pass
                error_map[decl_id] = reasons
                errors.append({
                    'identifier': decl_id,
                    'reasons': reasons,
                    'updated_at': row['updated_at'].strftime('%Y-%m-%d %H:%M') if row.get('updated_at') else '-'
                })

            # Mark declarations with errors
            for d in declarations:
                if d['identifier'] in error_map:
                    d['error'] = error_map[d['identifier']]
        except Exception as e:
            logger.warning(f"Failed to get status_errors for {device_uuid}: {e}")

        # Cache DDM data in device_details table
        if declarations:
            try:
                db.execute("""
                    INSERT INTO device_details (uuid, ddm_data, ddm_updated_at)
                    VALUES (%s, %s, NOW())
                    ON DUPLICATE KEY UPDATE ddm_data = VALUES(ddm_data), ddm_updated_at = NOW()
                """, (device_uuid, json.dumps(declarations)))
            except Exception as e:
                logger.warning(f"Failed to cache DDM data for {device_uuid}: {e}")

        return jsonify({
            'success': True,
            'device_uuid': device_uuid,
            'hostname': device.get('hostname'),
            'ddm_set': ', '.join(assigned_sets) if assigned_sets else None,
            'assigned_sets': assigned_sets,
            'declarations': declarations,
            'declaration_count': len(declarations),
            'errors': errors
        })
    except Exception as e:
        logger.error(f"Failed to get DDM device status: {e}")
        return jsonify({'success': False, 'error': str(e)})
