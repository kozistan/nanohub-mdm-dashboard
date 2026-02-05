"""
NanoHUB Admin - Settings Routes
===============================
Admin settings page routes for system configuration, user roles,
branding, backups, and more.
"""

import os
import json
import logging
import platform
import shutil
import subprocess
from datetime import datetime

from flask import Blueprint, render_template_string, session, request, jsonify, send_file, Response
from werkzeug.utils import secure_filename

from config import Config
from db_utils import db, app_settings
from nanohub_admin.utils import login_required_admin

logger = logging.getLogger('nanohub_admin')

# Create a blueprint for settings routes
# This will be registered with the main admin_bp
settings_bp = Blueprint('admin_settings', __name__)


# =============================================================================
# SETTINGS PAGE TEMPLATE
# =============================================================================

ADMIN_SETTINGS_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Settings - NanoHUB Admin</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="/static/dashboard.css">
    <link rel="stylesheet" href="/static/css/qbone.css">
    <link rel="stylesheet" href="/static/css/admin.css">
    <link rel="shortcut icon" href="/static/favicon.ico">
    <style>
    /* Settings page-specific styles - Dark Theme */
    .settings-tabs { display: flex; gap: 5px; margin-bottom: 20px; border-bottom: 2px solid #3A3A3A; padding-bottom: 10px; flex-wrap: wrap; }
    .settings-tabs a { padding: 8px 16px; text-decoration: none; color: #B0B0B0; border-radius: 5px 5px 0 0; background: #2A2A2A; border: 1px solid #3A3A3A; }
    .settings-tabs a.active { background: #5FC812; color: #0D0D0D; border-color: #5FC812; }
    .settings-tabs a:hover:not(.active) { background: #3A3A3A; color: #FFFFFF; }
    .settings-section { display: none; }
    .settings-section.active { display: block; }
    .settings-card { background: #1E1E1E; border: 1px solid #3A3A3A; border-radius: 8px; padding: 15px; margin-bottom: 15px; }
    .settings-card h4 { margin: 0 0 10px 0; color: #FFFFFF; font-size: 0.95em; }
    .settings-row { display: flex; align-items: center; gap: 15px; margin-bottom: 10px; }
    .settings-row label { min-width: 150px; font-weight: 500; font-size: 0.85em; color: #B0B0B0; }
    .settings-row input, .settings-row select { flex: 1; max-width: 300px; padding: 6px 10px; border: 1px solid #3A3A3A; border-radius: 4px; font-size: 0.85em; background: #2A2A2A; color: #FFFFFF; }
    .settings-row .hint { font-size: 0.8em; color: #B0B0B0; margin-left: 10px; }
    .info-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; }
    .info-item { background: #2A2A2A; border: 1px solid #3A3A3A; border-radius: 6px; padding: 12px; }
    .info-item .label { font-size: 0.8em; color: #B0B0B0; margin-bottom: 4px; }
    .info-item .value { font-size: 0.95em; font-weight: 500; color: #FFFFFF; }
    .info-item .value.ok { color: #5FC812; }
    .info-item .value.warning { color: #F5A623; }
    .info-item .value.error { color: #D91F25; }
    .user-role-row { display: flex; align-items: center; gap: 10px; padding: 8px; background: #2A2A2A; border: 1px solid #3A3A3A; border-radius: 4px; margin-bottom: 5px; }
    .user-role-row .username { font-weight: 500; min-width: 150px; color: #FFFFFF; }
    .user-role-row .role { background: rgba(95,200,18,0.15); color: #5FC812; border: 1px solid #5FC812; padding: 2px 8px; border-radius: 10px; font-size: 0.8em; }
    .user-role-row .filter { font-size: 0.8em; color: #B0B0B0; }
    .user-role-row .actions { margin-left: auto; }
    .manifests-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
    .logo-option { display: inline-block; margin: 10px; padding: 10px; border: 2px solid #3A3A3A; border-radius: 8px; cursor: pointer; text-align: center; position: relative; background: #2A2A2A; }
    .logo-option.selected { border-color: #5FC812; background: rgba(95,200,18,0.15); }
    .logo-option img { max-height: 50px; max-width: 150px; }
    .logo-option .name { font-size: 0.8em; color: #B0B0B0; margin-top: 5px; }
    .logo-option .delete-btn { position: absolute; top: -8px; right: -8px; width: 20px; height: 20px; background: #D91F25; color: white; border: none; border-radius: 50%; cursor: pointer; font-size: 12px; line-height: 20px; padding: 0; display: none; }
    .logo-option:hover .delete-btn { display: block; }
    .backup-btn { padding: 10px 20px; margin: 5px; }
    </style>
</head>
<body class="page-with-table">
    <div id="wrap">
        <div style="display: flex; justify-content: center;">
            <img id="logo" src="{{ current_logo }}" alt="Logo" style="max-height:60px;max-width:200px;"/>
        </div>
        <h1>Admin Settings</h1>

        <div class="panel">
            <div class="admin-header">
                <h2>Settings</h2>
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
                    <span style="color:#B0B0B0;font-size:0.85em;">{{ user.display_name or user.username }}</span>
                    <span class="role-badge">{{ user.role }}</span>
                    <a href="/admin/settings" class="btn active" style="margin-left:10px;">Settings</a>
                    <a href="/admin/help" class="btn" style="margin-left:10px;">Help</a>
                    <a href="/" class="btn" style="margin-left:10px;">Dashboard</a>
                </div>
            </div>

            <div class="settings-tabs">
                <a href="#" onclick="showTab('system')" class="active" data-tab="system">System Info</a>
                <a href="#" onclick="showTab('users')" data-tab="users">Users</a>
                <a href="#" onclick="showTab('branding')" data-tab="branding">Logo/Branding</a>
                <a href="#" onclick="showTab('manifests')" data-tab="manifests">Manifests</a>
                <a href="#" onclick="showTab('session')" data-tab="session">Session</a>
                <a href="#" onclick="showTab('audit')" data-tab="audit">Audit Log</a>
                <a href="#" onclick="showTab('backup')" data-tab="backup">Backup/Export</a>
            </div>

            <!-- System Info Tab -->
            <div id="tab-system" class="settings-section active">
                <h3>System Information</h3>
                <div class="info-grid">
                    <div class="info-item">
                        <div class="label">NanoHUB Version</div>
                        <div class="value">{{ system_info.version }}</div>
                    </div>
                    <div class="info-item">
                        <div class="label">Python Version</div>
                        <div class="value">{{ system_info.python_version }}</div>
                    </div>
                    <div class="info-item">
                        <div class="label">Database Status</div>
                        <div class="value {{ 'ok' if system_info.db_status == 'Connected' else 'error' }}">{{ system_info.db_status }}</div>
                    </div>
                    <div class="info-item">
                        <div class="label">Server Uptime</div>
                        <div class="value">{{ system_info.uptime }}</div>
                    </div>
                    <div class="info-item">
                        <div class="label">Disk Usage</div>
                        <div class="value {{ 'warning' if system_info.disk_percent > 80 else 'ok' }}">{{ system_info.disk_usage }}</div>
                    </div>
                    <div class="info-item">
                        <div class="label">Last Backup</div>
                        <div class="value">{{ system_info.last_backup or 'Never' }}</div>
                    </div>
                </div>
                <div class="settings-card" style="margin-top:20px;">
                    <h4>Services Status</h4>
                    <div class="info-grid">
                        {% for service in system_info.services %}
                        <div class="info-item">
                            <div class="label">{{ service.name }}</div>
                            <div class="value {{ 'ok' if service.status in ['running', 'active'] else 'error' }}">{{ service.status }}</div>
                        </div>
                        {% endfor %}
                    </div>
                </div>
            </div>

            <!-- Users Tab (LDAP Role Overrides + Local Users) -->
            <div id="tab-users" class="settings-section">
                <h3>Local Users</h3>
                <p style="font-size:0.85em;color:#6b7280;margin-bottom:15px;">Manage local user accounts for authentication when LDAP/SSO is unavailable.</p>

                <div class="settings-card">
                    <h4 id="localUserFormTitle">Add Local User</h4>
                    <input type="hidden" id="localEditMode" value="create">
                    <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end;">
                        <div>
                            <label style="display:block;font-size:0.8em;margin-bottom:3px;">Username</label>
                            <input type="text" id="localUsername" placeholder="username" style="width:150px;">
                        </div>
                        <div>
                            <label style="display:block;font-size:0.8em;margin-bottom:3px;">Display Name</label>
                            <input type="text" id="localDisplayName" placeholder="Full Name" style="width:150px;">
                        </div>
                        <div id="localPasswordGroup">
                            <label style="display:block;font-size:0.8em;margin-bottom:3px;">Password</label>
                            <input type="password" id="localPassword" placeholder="min 6 chars" style="width:130px;">
                        </div>
                        <div>
                            <label style="display:block;font-size:0.8em;margin-bottom:3px;">Role</label>
                            <select id="localRole" style="width:120px;">
                                <option value="admin">admin</option>
                                <option value="bel-admin">bel-admin</option>
                                <option value="operator" selected>operator</option>
                                <option value="report">report</option>
                            </select>
                        </div>
                        <div>
                            <label style="display:block;font-size:0.8em;margin-bottom:3px;">Manifest Filter</label>
                            <input type="text" id="localFilter" placeholder="e.g. bel-%" style="width:120px;">
                        </div>
                        <div>
                            <label style="display:block;font-size:0.8em;margin-bottom:3px;">Notes</label>
                            <input type="text" id="localNotes" placeholder="Optional" style="width:130px;">
                        </div>
                        <div style="display:flex;align-items:center;gap:5px;">
                            <input type="checkbox" id="localForceChange" checked>
                            <label for="localForceChange" style="font-size:0.8em;white-space:nowrap;">Force PW change</label>
                        </div>
                        <button class="btn btn-primary" onclick="saveLocalUser()">Save</button>
                        <button class="btn" onclick="resetLocalForm()" style="display:none;" id="localCancelBtn">Cancel</button>
                    </div>
                </div>

                <div class="settings-card">
                    <h4>Current Local Users</h4>
                    <div id="localUsersList">
                        {% for lu in local_users_list %}
                        <div class="user-role-row" data-username="{{ lu.username }}">
                            <span class="username">{{ lu.username }}</span>
                            <span class="role">{{ lu.role }}</span>
                            <span class="filter">{{ lu.manifest_filter or 'No filter' }}</span>
                            <span style="font-size:0.8em;color:#B0B0B0;">{{ lu.display_name or '' }}</span>
                            {% if lu.must_change_password %}
                            <span style="font-size:0.75em;color:#F5A623;border:1px solid #F5A623;padding:1px 6px;border-radius:8px;">PW change required</span>
                            {% endif %}
                            <span style="font-size:0.75em;color:#6b7280;">Last login: {{ lu.last_login.strftime('%Y-%m-%d %H:%M') if lu.last_login else 'Never' }}</span>
                            <div class="actions">
                                <button class="btn btn-small" onclick="editLocalUser('{{ lu.username }}', '{{ lu.display_name or '' }}', '{{ lu.role }}', '{{ lu.manifest_filter or '' }}', '{{ lu.notes or '' }}')">Edit</button>
                                <button class="btn btn-small" onclick="resetLocalPassword('{{ lu.username }}')">Reset PW</button>
                                {% if lu.username != 'admin' %}
                                <button class="btn btn-small btn-danger" onclick="deleteLocalUser('{{ lu.username }}')">Delete</button>
                                {% endif %}
                            </div>
                        </div>
                        {% endfor %}
                        {% if not local_users_list %}
                        <p style="color:#6b7280;font-size:0.85em;">No local users found.</p>
                        {% endif %}
                    </div>
                </div>

                <h3 style="margin-top:30px;">Users Role Overrides</h3>
                <p style="font-size:0.85em;color:#6b7280;margin-bottom:15px;">Override roles for LDAP and Google SSO users. The override takes precedence over the role derived from AD group membership or SSO default.</p>

                <div class="settings-card">
                    <h4>Add/Edit User Role</h4>
                    <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end;">
                        <div>
                            <label style="display:block;font-size:0.8em;margin-bottom:3px;">Username</label>
                            <input type="text" id="roleUsername" placeholder="username" style="width:150px;">
                        </div>
                        <div>
                            <label style="display:block;font-size:0.8em;margin-bottom:3px;">Role</label>
                            <select id="roleRole" style="width:120px;">
                                <option value="admin">admin</option>
                                <option value="bel-admin">bel-admin</option>
                                <option value="operator">operator</option>
                                <option value="report">report</option>
                            </select>
                        </div>
                        <div>
                            <label style="display:block;font-size:0.8em;margin-bottom:3px;">Manifest Filter</label>
                            <input type="text" id="roleFilter" placeholder="e.g. bel-%" style="width:120px;">
                        </div>
                        <div>
                            <label style="display:block;font-size:0.8em;margin-bottom:3px;">Notes</label>
                            <input type="text" id="roleNotes" placeholder="Optional notes" style="width:150px;">
                        </div>
                        <button class="btn btn-primary" onclick="saveUserRole()">Save Role</button>
                    </div>
                </div>

                <div class="settings-card">
                    <h4>Current Role Overrides</h4>
                    <div id="userRolesList">
                        {% for u in user_roles %}
                        <div class="user-role-row" data-username="{{ u.username }}">
                            <span class="username">{{ u.username }}</span>
                            <span class="role">{{ u.role }}</span>
                            <span class="filter">{{ u.manifest_filter or 'No filter' }}</span>
                            <span style="font-size:0.8em;color:#6b7280;">{{ u.notes or '' }}</span>
                            <div class="actions">
                                <button class="btn btn-small" onclick="editUserRole('{{ u.username }}', '{{ u.role }}', '{{ u.manifest_filter or '' }}', '{{ u.notes or '' }}')">Edit</button>
                                <button class="btn btn-small btn-danger" onclick="removeUserRole('{{ u.username }}')">Remove</button>
                            </div>
                        </div>
                        {% endfor %}
                        {% if not user_roles %}
                        <p style="color:#6b7280;font-size:0.85em;">No role overrides configured. All users use LDAP-derived roles.</p>
                        {% endif %}
                    </div>
                </div>
            </div>

            <!-- Logo/Branding Tab -->
            <div id="tab-branding" class="settings-section">
                <h3>Logo & Branding</h3>
                <div class="settings-card">
                    <h4>Header Logo</h4>
                    <p style="font-size:0.85em;color:#6b7280;margin-bottom:15px;">Select the logo displayed in the page header.</p>
                    <div id="logoOptions">
                        {% for logo in available_logos %}
                        <div class="logo-option {{ 'selected' if logo.path == current_logo else '' }}" onclick="selectLogo('{{ logo.path }}')">
                            {% if not logo.is_default %}
                            <button class="delete-btn" onclick="event.stopPropagation(); deleteLogo('{{ logo.path }}', '{{ logo.name }}')" title="Delete">&times;</button>
                            {% endif %}
                            <img src="{{ logo.path }}" alt="{{ logo.name }}">
                            <div class="name">{{ logo.name }}</div>
                        </div>
                        {% endfor %}
                    </div>
                    <div style="margin-top:15px;">
                        <label style="font-size:0.85em;font-weight:500;">Or upload new logo:</label>
                        <input type="file" id="logoUpload" accept="image/*" style="margin-left:10px;">
                        <button class="btn" onclick="uploadLogo()">Upload</button>
                    </div>
                </div>
            </div>

            <!-- Manifests Tab -->
            <div id="tab-manifests" class="settings-section">
                <div class="manifests-header">
                    <div>
                        <h3 style="margin:0;">Manifests Management</h3>
                        <p style="font-size:0.85em;color:#6b7280;margin:5px 0 0 0;">Device groups for organizing and applying configurations</p>
                    </div>
                    <button class="btn btn-primary" onclick="showAddManifestModal()">+ Add Manifest</button>
                </div>

                <table class="device-table" style="margin-top:15px;">
                    <thead>
                        <tr>
                            <th style="width:50%;">Name</th>
                            <th style="width:25%;text-align:center;">Devices</th>
                            <th style="width:25%;text-align:right;">Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% if manifests %}
                            {% for m in manifests %}
                            <tr>
                                <td><strong>{{ m.name }}</strong></td>
                                <td style="text-align:center;">{{ m.device_count }}</td>
                                <td style="text-align:right;">
                                    <button class="btn btn-small" onclick="editManifest('{{ m.name }}')" title="Rename">Rename</button>
                                    <button class="btn btn-small btn-danger" onclick="removeManifest('{{ m.name }}')" title="Delete">Remove</button>
                                </td>
                            </tr>
                            {% endfor %}
                        {% else %}
                            <tr>
                                <td colspan="3" style="text-align:center;color:#6b7280;padding:30px;">No manifests found. Click "Add Manifest" to create one.</td>
                            </tr>
                        {% endif %}
                    </tbody>
                </table>
            </div>

            <!-- Add Manifest Modal -->
            <div id="addManifestModal" class="modal-overlay">
                <div class="modal-box">
                    <h3>Add Manifest</h3>
                    <div class="modal-body">
                        <label>Manifest Name</label>
                        <input type="text" id="newManifestName" placeholder="e.g. production, testing, bel-devices">
                        <small>Name used to group devices for configuration</small>
                    </div>
                    <div class="modal-footer">
                        <button class="btn" onclick="closeAddManifestModal()">Cancel</button>
                        <button class="btn btn-primary" onclick="addManifest()">Add</button>
                    </div>
                </div>
            </div>

            <!-- Edit Manifest Modal -->
            <div id="editManifestModal" class="modal-overlay">
                <div class="modal-box">
                    <h3>Rename Manifest</h3>
                    <div class="modal-body">
                        <input type="hidden" id="editManifestOldName">
                        <label>New Name</label>
                        <input type="text" id="editManifestNewName">
                    </div>
                    <div class="modal-footer">
                        <button class="btn" onclick="closeEditManifestModal()">Cancel</button>
                        <button class="btn btn-primary" onclick="saveManifestRename()">Save</button>
                    </div>
                </div>
            </div>

            <!-- Session Settings Tab -->
            <div id="tab-session" class="settings-section">
                <h3>Session Settings</h3>
                <div class="settings-card">
                    <h4>Session Configuration</h4>
                    <div class="settings-row">
                        <label>Session Timeout</label>
                        <select id="sessionTimeout">
                            <option value="1800" {{ 'selected' if settings.session_timeout == 1800 else '' }}>30 minutes</option>
                            <option value="3600" {{ 'selected' if settings.session_timeout == 3600 else '' }}>1 hour</option>
                            <option value="7200" {{ 'selected' if settings.session_timeout == 7200 else '' }}>2 hours</option>
                            <option value="14400" {{ 'selected' if settings.session_timeout == 14400 else '' }}>4 hours</option>
                            <option value="28800" {{ 'selected' if settings.session_timeout == 28800 else '' }}>8 hours</option>
                            <option value="86400" {{ 'selected' if settings.session_timeout == 86400 else '' }}>24 hours</option>
                        </select>
                        <span class="hint">Time before inactive users are logged out</span>
                    </div>
                    <div class="settings-row">
                        <label>Max Concurrent Sessions</label>
                        <select id="maxSessions">
                            <option value="1" {{ 'selected' if settings.max_sessions == 1 else '' }}>1</option>
                            <option value="3" {{ 'selected' if settings.max_sessions == 3 else '' }}>3</option>
                            <option value="5" {{ 'selected' if settings.max_sessions == 5 else '' }}>5</option>
                            <option value="0" {{ 'selected' if settings.max_sessions == 0 else '' }}>Unlimited</option>
                        </select>
                        <span class="hint">Per user limit (0 = unlimited)</span>
                    </div>
                    <button class="btn btn-primary" style="margin-top:10px;" onclick="saveSessionSettings()">Save Session Settings</button>
                </div>
            </div>

            <!-- Audit Log Tab -->
            <div id="tab-audit" class="settings-section">
                <h3>Audit Log Settings</h3>
                <div class="settings-card">
                    <h4>Log Retention</h4>
                    <div class="settings-row">
                        <label>History Retention</label>
                        <select id="historyRetention">
                            <option value="30" {{ 'selected' if settings.history_retention == 30 else '' }}>30 days</option>
                            <option value="60" {{ 'selected' if settings.history_retention == 60 else '' }}>60 days</option>
                            <option value="90" {{ 'selected' if settings.history_retention == 90 else '' }}>90 days</option>
                            <option value="180" {{ 'selected' if settings.history_retention == 180 else '' }}>180 days</option>
                            <option value="365" {{ 'selected' if settings.history_retention == 365 else '' }}>1 year</option>
                        </select>
                        <span class="hint">How long to keep command history</span>
                    </div>
                    <div class="settings-row">
                        <label>Current Log Entries</label>
                        <span style="font-weight:500;">{{ settings.history_count }} entries</span>
                    </div>
                    <button class="btn btn-primary" style="margin-top:10px;" onclick="saveAuditSettings()">Save Audit Settings</button>
                    <button class="btn btn-warning" style="margin-top:10px;margin-left:10px;" onclick="cleanupOldLogs()">Cleanup Old Logs Now</button>
                </div>
            </div>

            <!-- Backup/Export Tab -->
            <div id="tab-backup" class="settings-section">
                <div class="manifests-header">
                    <div>
                        <h3 style="margin:0;">Backup & Export</h3>
                        <p style="font-size:0.85em;color:#6b7280;margin:5px 0 0 0;">Database backups stored on the server</p>
                    </div>
                    <button class="btn btn-purple" onclick="createBackup()">+ Create Backup</button>
                </div>

                <table class="device-table" style="margin-top:15px;">
                    <thead>
                        <tr>
                            <th style="width:45%;">Filename</th>
                            <th style="width:15%;text-align:center;">Size</th>
                            <th style="width:20%;text-align:center;">Date</th>
                            <th style="width:20%;text-align:right;">Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% if backups %}
                            {% for b in backups %}
                            <tr>
                                <td><strong>{{ b.filename }}</strong></td>
                                <td style="text-align:center;">{{ b.size }}</td>
                                <td style="text-align:center;">{{ b.date }}</td>
                                <td style="text-align:right;">
                                    <button class="btn btn-small" onclick="downloadBackup('{{ b.filename }}')">Download</button>
                                    <button class="btn btn-small btn-danger" onclick="deleteBackup('{{ b.filename }}')">Remove</button>
                                </td>
                            </tr>
                            {% endfor %}
                        {% else %}
                            <tr>
                                <td colspan="4" style="text-align:center;color:#6b7280;padding:30px;">No backups found. Click "Create Backup" to create one.</td>
                            </tr>
                        {% endif %}
                    </tbody>
                </table>

                <div class="settings-card" style="margin-top:20px;">
                    <h4>Export Configuration</h4>
                    <p style="font-size:0.85em;color:#6b7280;margin-bottom:15px;">Export settings and configuration as JSON.</p>
                    <button class="btn backup-btn" onclick="exportConfig()">Export Config</button>
                    <button class="btn backup-btn" onclick="exportUserRoles()">Export User Roles</button>
                    <button class="btn backup-btn" onclick="exportProfiles()">Export Profiles</button>
                </div>
            </div>
        </div>
    </div>

    <script>
    function showTab(tabId) {
        event.preventDefault();
        document.querySelectorAll('.settings-section').forEach(s => s.classList.remove('active'));
        document.querySelectorAll('.settings-tabs a').forEach(a => a.classList.remove('active'));
        document.getElementById('tab-' + tabId).classList.add('active');
        document.querySelector('.settings-tabs a[data-tab="' + tabId + '"]').classList.add('active');
        location.hash = tabId;
    }

    // Restore active tab from URL hash on page load
    (function() {
        var hash = location.hash.replace('#', '');
        if (hash && document.getElementById('tab-' + hash)) {
            document.querySelectorAll('.settings-section').forEach(s => s.classList.remove('active'));
            document.querySelectorAll('.settings-tabs a').forEach(a => a.classList.remove('active'));
            document.getElementById('tab-' + hash).classList.add('active');
            document.querySelector('.settings-tabs a[data-tab="' + hash + '"]').classList.add('active');
        }
    })();

    function saveUserRole() {
        const username = document.getElementById('roleUsername').value.trim().toLowerCase();
        const role = document.getElementById('roleRole').value;
        const filter = document.getElementById('roleFilter').value.trim();
        const notes = document.getElementById('roleNotes').value.trim();

        if (!username) { alert('Please enter a username'); return; }

        fetch('/admin/api/settings/user-role', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({username, role, filter, notes})
        })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                alert('User role saved');
                location.reload();
            } else {
                alert('Error: ' + data.error);
            }
        });
    }

    function editUserRole(username, role, filter, notes) {
        document.getElementById('roleUsername').value = username;
        document.getElementById('roleRole').value = role;
        document.getElementById('roleFilter').value = filter;
        document.getElementById('roleNotes').value = notes;
        showTab('users');
    }

    function removeUserRole(username) {
        if (!confirm('Remove role override for ' + username + '?')) return;
        fetch('/admin/api/settings/user-role/' + username, {method: 'DELETE'})
        .then(r => r.json())
        .then(data => {
            if (data.success) location.reload();
            else alert('Error: ' + data.error);
        });
    }

    function selectLogo(path) {
        document.querySelectorAll('.logo-option').forEach(o => o.classList.remove('selected'));
        event.currentTarget.classList.add('selected');
        fetch('/admin/api/settings/logo', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({logo: path})
        })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                document.getElementById('logo').src = path;
            } else {
                alert('Error: ' + data.error);
            }
        });
    }

    function deleteLogo(path, name) {
        if (!confirm('Delete logo "' + name + '"?')) return;
        fetch('/admin/api/settings/logo/delete', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({logo: path})
        })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                location.reload();
            } else {
                alert('Error: ' + data.error);
            }
        });
    }

    function uploadLogo() {
        const file = document.getElementById('logoUpload').files[0];
        if (!file) { alert('Please select a file'); return; }
        const formData = new FormData();
        formData.append('logo', file);
        fetch('/admin/api/settings/logo/upload', {method: 'POST', body: formData})
        .then(r => r.json())
        .then(data => {
            if (data.success) location.reload();
            else alert('Error: ' + data.error);
        });
    }

    function showAddManifestModal() {
        document.getElementById('newManifestName').value = '';
        document.getElementById('addManifestModal').style.display = 'flex';
        document.getElementById('newManifestName').focus();
    }

    function closeAddManifestModal() {
        document.getElementById('addManifestModal').style.display = 'none';
    }

    function addManifest() {
        const name = document.getElementById('newManifestName').value.trim();
        if (!name) { alert('Please enter a manifest name'); return; }
        fetch('/admin/api/settings/manifest', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name})
        })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                closeAddManifestModal();
                location.reload();
            } else {
                alert('Error: ' + data.error);
            }
        });
    }

    function removeManifest(name) {
        if (!confirm('Remove manifest "' + name + '"? This will not delete devices.')) return;
        fetch('/admin/api/settings/manifest/' + encodeURIComponent(name), {method: 'DELETE'})
        .then(r => r.json())
        .then(data => {
            if (data.success) location.reload();
            else alert('Error: ' + data.error);
        });
    }

    function editManifest(name) {
        document.getElementById('editManifestOldName').value = name;
        document.getElementById('editManifestNewName').value = name;
        document.getElementById('editManifestModal').style.display = 'flex';
        document.getElementById('editManifestNewName').focus();
        document.getElementById('editManifestNewName').select();
    }

    function closeEditManifestModal() {
        document.getElementById('editManifestModal').style.display = 'none';
    }

    function saveManifestRename() {
        const oldName = document.getElementById('editManifestOldName').value;
        const newName = document.getElementById('editManifestNewName').value.trim();
        if (!newName) {
            alert('Please enter a new name');
            return;
        }
        if (oldName === newName) {
            closeEditManifestModal();
            return;
        }
        fetch('/admin/api/settings/manifest/rename', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({oldName, newName})
        })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                closeEditManifestModal();
                location.reload();
            } else {
                alert('Error: ' + data.error);
            }
        });
    }

    function saveSessionSettings() {
        const timeout = document.getElementById('sessionTimeout').value;
        const maxSessions = document.getElementById('maxSessions').value;
        fetch('/admin/api/settings/session', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({timeout, maxSessions})
        })
        .then(r => r.json())
        .then(data => {
            if (data.success) alert('Session settings saved');
            else alert('Error: ' + data.error);
        });
    }

    function saveAuditSettings() {
        const retention = document.getElementById('historyRetention').value;
        fetch('/admin/api/settings/audit', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({retention})
        })
        .then(r => r.json())
        .then(data => {
            if (data.success) alert('Audit settings saved');
            else alert('Error: ' + data.error);
        });
    }

    function cleanupOldLogs() {
        if (!confirm('This will delete logs older than the retention period. Continue?')) return;
        fetch('/admin/api/settings/audit/cleanup', {method: 'POST'})
        .then(r => r.json())
        .then(data => {
            if (data.success) alert('Cleaned up ' + data.deleted + ' old entries');
            else alert('Error: ' + data.error);
        });
    }

    function createBackup() {
        fetch('/admin/api/settings/backup', {method: 'POST'})
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                alert('Backup created: ' + data.filename);
                location.reload();
            } else {
                alert('Error: ' + data.error);
            }
        });
    }

    function downloadBackup(filename) {
        window.location.href = '/admin/api/settings/backup/download/' + filename;
    }

    function deleteBackup(filename) {
        if (!confirm('Delete backup "' + filename + '"? This cannot be undone.')) return;
        fetch('/admin/api/settings/backup/delete/' + encodeURIComponent(filename), {method: 'DELETE'})
        .then(r => r.json())
        .then(data => {
            if (data.success) location.reload();
            else alert('Error: ' + data.error);
        });
    }

    function exportConfig() {
        window.location.href = '/admin/api/settings/export/config';
    }

    function exportUserRoles() {
        window.location.href = '/admin/api/settings/export/user-roles';
    }

    function exportProfiles() {
        window.location.href = '/admin/api/settings/export/profiles';
    }

    // Local Users functions
    function resetLocalForm() {
        document.getElementById('localEditMode').value = 'create';
        document.getElementById('localUsername').value = '';
        document.getElementById('localUsername').readOnly = false;
        document.getElementById('localDisplayName').value = '';
        document.getElementById('localPassword').value = '';
        document.getElementById('localPasswordGroup').style.display = '';
        document.getElementById('localRole').value = 'operator';
        document.getElementById('localFilter').value = '';
        document.getElementById('localNotes').value = '';
        document.getElementById('localForceChange').checked = true;
        document.getElementById('localUserFormTitle').textContent = 'Add Local User';
        document.getElementById('localCancelBtn').style.display = 'none';
    }

    function saveLocalUser() {
        const mode = document.getElementById('localEditMode').value;
        const username = document.getElementById('localUsername').value.trim().toLowerCase();
        const displayName = document.getElementById('localDisplayName').value.trim();
        const password = document.getElementById('localPassword').value;
        const role = document.getElementById('localRole').value;
        const filter = document.getElementById('localFilter').value.trim();
        const notes = document.getElementById('localNotes').value.trim();
        const forceChange = document.getElementById('localForceChange').checked;

        if (!username) { alert('Please enter a username'); return; }
        if (mode === 'create' && password.length < 6) { alert('Password must be at least 6 characters'); return; }

        const body = {username, display_name: displayName, role, filter, notes, force_change: forceChange, mode};
        if (mode === 'create') body.password = password;

        fetch('/admin/api/settings/local-user', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(body)
        })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                alert(mode === 'create' ? 'Local user created' : 'Local user updated');
                location.reload();
            } else {
                alert('Error: ' + data.error);
            }
        });
    }

    function editLocalUser(username, displayName, role, filter, notes) {
        document.getElementById('localEditMode').value = 'edit';
        document.getElementById('localUsername').value = username;
        document.getElementById('localUsername').readOnly = true;
        document.getElementById('localDisplayName').value = displayName;
        document.getElementById('localPassword').value = '';
        document.getElementById('localPasswordGroup').style.display = 'none';
        document.getElementById('localRole').value = role;
        document.getElementById('localFilter').value = filter;
        document.getElementById('localNotes').value = notes;
        document.getElementById('localUserFormTitle').textContent = 'Edit Local User: ' + username;
        document.getElementById('localCancelBtn').style.display = '';
        showTab('users');
    }

    function resetLocalPassword(username) {
        const newPw = prompt('Enter new password for ' + username + ' (min 6 chars):');
        if (!newPw) return;
        if (newPw.length < 6) { alert('Password must be at least 6 characters'); return; }

        fetch('/admin/api/settings/local-user/reset-password', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({username, new_password: newPw})
        })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                alert('Password reset. User will be forced to change it on next login.');
                location.reload();
            } else {
                alert('Error: ' + data.error);
            }
        });
    }

    function deleteLocalUser(username) {
        if (!confirm('Delete local user "' + username + '"? This cannot be undone.')) return;
        fetch('/admin/api/settings/local-user/' + encodeURIComponent(username), {method: 'DELETE'})
        .then(r => r.json())
        .then(data => {
            if (data.success) location.reload();
            else alert('Error: ' + data.error);
        });
    }
    </script>
</body>
</html>
'''


# =============================================================================
# SETTINGS ROUTES
# =============================================================================

@settings_bp.route('/settings')
@login_required_admin
def admin_settings():
    """Admin settings page"""
    user = session.get('user', {})

    # Only admins can access settings
    if user.get('role') not in ['admin']:
        return render_template_string('<h1>Access Denied</h1><p>Only admins can access settings.</p><a href="/admin">Back</a>'), 403

    # Get NanoHUB version from Docker image
    nanohub_version = 'Unknown'
    try:
        result = subprocess.run(['/usr/bin/docker', 'inspect', '--format', '{{.Config.Image}}', 'nanohub'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            image = result.stdout.strip()
            nanohub_version = image.split('/')[-1] if '/' in image else image
    except Exception as e:
        nanohub_version = f'Error: {str(e)[:20]}'

    # Get server uptime
    server_uptime = 'Unknown'
    try:
        result = subprocess.run(['/usr/bin/uptime', '-p'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            server_uptime = result.stdout.strip()
    except Exception:
        pass

    # Get system info
    system_info = {
        'version': nanohub_version,
        'python_version': platform.python_version(),
        'db_status': 'Connected',
        'uptime': server_uptime,
        'disk_usage': 'Unknown',
        'disk_percent': 0,
        'last_backup': None,
        'services': []
    }

    try:
        # Database check
        db.query_one("SELECT 1")
        system_info['db_status'] = 'Connected'
    except Exception as e:
        system_info['db_status'] = f'Error: {str(e)[:30]}'

    # Disk usage
    try:
        disk = shutil.disk_usage('/')
        used_gb = disk.used / (1024**3)
        total_gb = disk.total / (1024**3)
        percent = (disk.used / disk.total) * 100
        system_info['disk_usage'] = f'{used_gb:.1f} / {total_gb:.1f} GB ({percent:.0f}%)'
        system_info['disk_percent'] = percent
    except Exception:
        pass

    # Services status (systemd services)
    services_to_check = ['nanohub', 'nanohub-webhook', 'nanohub-web', 'nanodep', 'scep', 'nginx']
    for svc in services_to_check:
        try:
            result = subprocess.run(['/usr/bin/systemctl', 'is-active', f'{svc}.service'], capture_output=True, text=True, timeout=5)
            status = result.stdout.strip() if result.returncode == 0 else 'inactive'
            system_info['services'].append({'name': svc, 'status': status})
        except Exception as e:
            system_info['services'].append({'name': svc, 'status': f'error'})

    # Check MySQL Docker container
    try:
        result = subprocess.run(['/usr/bin/docker', 'inspect', '-f', '{{.State.Status}}', 'mysql-nanohub'], capture_output=True, text=True, timeout=5)
        mysql_status = result.stdout.strip() if result.returncode == 0 else 'not found'
        system_info['services'].append({'name': 'mysql (docker)', 'status': mysql_status})
    except Exception:
        system_info['services'].append({'name': 'mysql (docker)', 'status': 'error'})

    # Get user roles
    user_roles_list = []
    try:
        from db_utils import user_roles as user_roles_db
        user_roles_list = user_roles_db.get_all_users(include_inactive=False)
    except Exception as e:
        logger.error(f"Failed to get user roles: {e}")

    # Get local users
    local_users_list = []
    try:
        from db_utils import local_users as local_users_db
        local_users_list = local_users_db.get_all_users(include_inactive=True)
    except Exception as e:
        logger.error(f"Failed to get local users: {e}")

    # Get available logos from logos directory
    available_logos = []
    logo_dir = Config.LOGO_DIR
    if os.path.exists(logo_dir):
        for f in os.listdir(logo_dir):
            if f.lower().endswith(('.svg', '.png', '.jpg', '.jpeg', '.webp')):
                available_logos.append({'path': f'/static/logos/{f}', 'name': f, 'is_default': False})

    # Load current logo from settings
    current_logo = app_settings.get('header_logo', '/static/logos/slotegrator_green.png')

    # Get manifests with device counts (from manifests table + device_inventory)
    manifests = []
    try:
        rows = db.query_all("""
            SELECT m.name, m.description, m.created_at, m.created_by,
                   COALESCE(d.device_count, 0) as device_count
            FROM manifests m
            LEFT JOIN (
                SELECT manifest, COUNT(*) as device_count
                FROM device_inventory
                WHERE manifest IS NOT NULL AND manifest != ''
                GROUP BY manifest
            ) d ON m.name = d.manifest
            ORDER BY m.name
        """)
        manifests = [{'name': r['name'], 'device_count': r['device_count'],
                      'description': r.get('description', ''),
                      'created_by': r.get('created_by', '')} for r in rows]
    except Exception as e:
        logger.error(f"Failed to get manifests: {e}")

    # Settings with defaults, then load from database
    settings = {
        'session_timeout': 3600,
        'max_sessions': 0,
        'history_retention': 90,
        'history_count': 0
    }

    # Load saved settings from database
    try:
        saved_timeout = app_settings.get('session_timeout')
        if saved_timeout:
            settings['session_timeout'] = int(saved_timeout)

        saved_max_sessions = app_settings.get('max_sessions')
        if saved_max_sessions:
            settings['max_sessions'] = int(saved_max_sessions)

        saved_retention = app_settings.get('audit_retention_days')
        if saved_retention:
            settings['history_retention'] = int(saved_retention)
    except Exception as e:
        logger.error(f"Failed to load settings: {e}")

    try:
        result = db.query_one("SELECT COUNT(*) as cnt FROM command_history")
        settings['history_count'] = result['cnt'] if result else 0
    except Exception:
        pass

    # Get backups
    backups = []
    backup_dir = Config.BACKUP_DIR
    if os.path.exists(backup_dir):
        for f in sorted(os.listdir(backup_dir), reverse=True)[:10]:
            if f.endswith('.sql') or f.endswith('.gz'):
                fpath = os.path.join(backup_dir, f)
                stat = os.stat(fpath)
                size_mb = stat.st_size / (1024*1024)
                mtime = datetime.fromtimestamp(stat.st_mtime)
                backups.append({
                    'filename': f,
                    'size': f'{size_mb:.1f} MB',
                    'date': mtime.strftime('%Y-%m-%d %H:%M')
                })

    # Set last backup date from most recent backup
    if backups:
        system_info['last_backup'] = backups[0]['date']

    return render_template_string(
        ADMIN_SETTINGS_TEMPLATE,
        user=user,
        system_info=system_info,
        user_roles=user_roles_list,
        local_users_list=local_users_list,
        available_logos=available_logos,
        current_logo=current_logo,
        manifests=manifests,
        settings=settings,
        backups=backups
    )


@settings_bp.route('/api/settings/logo/current', methods=['GET'])
def api_settings_logo_current():
    """Get current logo path (no auth required for dashboard)"""
    try:
        logo = app_settings.get('header_logo', '/static/logos/slotegrator_green.png')
        return jsonify({'logo': logo})
    except Exception:
        return jsonify({'logo': '/static/logos/slotegrator_green.png'})


@settings_bp.route('/api/settings/logo', methods=['POST'])
@login_required_admin
def api_settings_logo():
    """Save selected logo"""
    user = session.get('user', {})
    if user.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Admin only'})

    data = request.get_json()
    logo_path = data.get('logo', '').strip()

    if not logo_path:
        return jsonify({'success': False, 'error': 'Logo path required'})

    try:
        app_settings.set('header_logo', logo_path, user.get('username', 'admin'))
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Failed to save logo setting: {e}")
        return jsonify({'success': False, 'error': str(e)})


@settings_bp.route('/api/settings/logo/upload', methods=['POST'])
@login_required_admin
def api_settings_logo_upload():
    """Upload a new logo file"""
    user = session.get('user', {})
    if user.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Admin only'})

    if 'logo' not in request.files:
        return jsonify({'success': False, 'error': 'No file uploaded'})

    file = request.files['logo']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No file selected'})

    # Check file extension
    allowed_extensions = {'png', 'jpg', 'jpeg', 'svg', 'gif'}
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in allowed_extensions:
        return jsonify({'success': False, 'error': f'Invalid file type. Allowed: {", ".join(allowed_extensions)}'})

    try:
        # Ensure logos directory exists
        logo_dir = Config.LOGO_DIR
        os.makedirs(logo_dir, exist_ok=True)

        # Save file with secure filename
        filename = secure_filename(file.filename)
        filepath = os.path.join(logo_dir, filename)
        file.save(filepath)

        # Set as current logo
        logo_path = f'/static/logos/{filename}'
        app_settings.set('header_logo', logo_path, user.get('username', 'admin'))

        return jsonify({'success': True, 'path': logo_path})
    except Exception as e:
        logger.error(f"Failed to upload logo: {e}")
        return jsonify({'success': False, 'error': str(e)})


@settings_bp.route('/api/settings/logo/delete', methods=['POST'])
@login_required_admin
def api_settings_logo_delete():
    """Delete a logo file"""
    user = session.get('user', {})
    if user.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Admin only'})

    data = request.get_json()
    logo_path = data.get('logo', '').strip()

    if not logo_path:
        return jsonify({'success': False, 'error': 'Logo path required'})

    # Don't allow deleting default logos
    if 'nanohub_logo' in logo_path or logo_path == '/static/logos/slotegrator_green.png':
        return jsonify({'success': False, 'error': 'Cannot delete default logo'})

    try:
        # Convert URL path to file path
        if logo_path.startswith('/static/logos/'):
            filename = logo_path.replace('/static/logos/', '')
            filepath = os.path.join(Config.LOGO_DIR, filename)

            if os.path.exists(filepath):
                os.remove(filepath)

                # If this was the current logo, switch to default
                current = app_settings.get('header_logo', '/static/logos/slotegrator_green.png')
                if current == logo_path:
                    app_settings.set('header_logo', '/static/logos/slotegrator_green.png', user.get('username', 'admin'))

                return jsonify({'success': True})
            else:
                return jsonify({'success': False, 'error': 'File not found'})
        else:
            return jsonify({'success': False, 'error': 'Invalid logo path'})
    except Exception as e:
        logger.error(f"Failed to delete logo: {e}")
        return jsonify({'success': False, 'error': str(e)})


@settings_bp.route('/api/settings/user-role', methods=['POST'])
@login_required_admin
def api_settings_user_role():
    """Save user role override"""
    user = session.get('user', {})
    if user.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Admin only'})

    data = request.get_json()
    username = data.get('username', '').strip().lower()
    role = data.get('role', '').strip().lower()
    manifest_filter = data.get('filter', '').strip() or None
    notes = data.get('notes', '').strip() or None

    if not username or not role:
        return jsonify({'success': False, 'error': 'Username and role required'})

    try:
        from db_utils import user_roles as user_roles_db
        success = user_roles_db.set_user_role(
            username=username,
            role=role,
            manifest_filter=manifest_filter,
            created_by=user.get('username', 'admin'),
            notes=notes
        )
        return jsonify({'success': success})
    except Exception as e:
        logger.error(f"Failed to set user role: {e}")
        return jsonify({'success': False, 'error': str(e)})


@settings_bp.route('/api/settings/user-role/<username>', methods=['DELETE'])
@login_required_admin
def api_settings_delete_user_role(username):
    """Permanently delete user role override"""
    user = session.get('user', {})
    if user.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Admin only'})

    try:
        from db_utils import user_roles as user_roles_db
        success = user_roles_db.delete_user_role(username)
        return jsonify({'success': success})
    except Exception as e:
        logger.error(f"Failed to delete user role: {e}")
        return jsonify({'success': False, 'error': str(e)})


@settings_bp.route('/api/settings/manifest', methods=['POST'])
@login_required_admin
def api_settings_add_manifest():
    """Add a new manifest"""
    user = session.get('user', {})
    if user.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Admin only'})

    data = request.get_json() or {}
    name = data.get('name', '').strip()
    description = data.get('description', '').strip()

    if not name:
        return jsonify({'success': False, 'error': 'Manifest name required'})

    try:
        # Check if already exists
        existing = db.query_one("SELECT id FROM manifests WHERE name = %s", (name,))
        if existing:
            return jsonify({'success': False, 'error': f'Manifest "{name}" already exists'})

        # Insert new manifest
        db.execute(
            "INSERT INTO manifests (name, description, created_by) VALUES (%s, %s, %s)",
            (name, description or None, user.get('username'))
        )
        return jsonify({'success': True, 'message': f'Manifest "{name}" created'})
    except Exception as e:
        logger.error(f"Failed to add manifest: {e}")
        return jsonify({'success': False, 'error': str(e)})


@settings_bp.route('/api/settings/manifest/rename', methods=['POST'])
@login_required_admin
def api_settings_rename_manifest():
    """Rename a manifest"""
    user = session.get('user', {})
    if user.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Admin only'})

    data = request.get_json() or {}
    old_name = data.get('oldName', '').strip()
    new_name = data.get('newName', '').strip()

    if not old_name or not new_name:
        return jsonify({'success': False, 'error': 'Both old and new names are required'})

    if old_name == new_name:
        return jsonify({'success': True})

    try:
        # Check if new name already exists in manifests table
        existing = db.query_one("SELECT id FROM manifests WHERE name = %s", (new_name,))
        if existing:
            return jsonify({'success': False, 'error': f'Manifest "{new_name}" already exists'})

        # Rename in manifests table
        db.execute("UPDATE manifests SET name = %s WHERE name = %s", (new_name, old_name))
        # Rename manifest for all devices
        db.execute("UPDATE device_inventory SET manifest = %s WHERE manifest = %s", (new_name, old_name))
        # Rename manifest in required_profiles
        db.execute("UPDATE required_profiles SET manifest = %s WHERE manifest = %s", (new_name, old_name))
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Failed to rename manifest: {e}")
        return jsonify({'success': False, 'error': str(e)})


@settings_bp.route('/api/settings/manifest/<name>', methods=['DELETE'])
@login_required_admin
def api_settings_delete_manifest(name):
    """Remove manifest (delete from table and unassign devices)"""
    user = session.get('user', {})
    if user.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Admin only'})

    try:
        # Delete from manifests table
        db.execute("DELETE FROM manifests WHERE name = %s", (name,))
        # Set manifest to NULL for devices with this manifest
        db.execute("UPDATE device_inventory SET manifest = NULL WHERE manifest = %s", (name,))
        # Delete required profiles for this manifest
        db.execute("DELETE FROM required_profiles WHERE manifest = %s", (name,))
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Failed to remove manifest: {e}")
        return jsonify({'success': False, 'error': str(e)})


@settings_bp.route('/api/settings/session', methods=['POST'])
@login_required_admin
def api_settings_session():
    """Save session settings"""
    user = session.get('user', {})
    if user.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Admin only'})

    data = request.get_json()
    timeout = data.get('timeout')
    max_sessions = data.get('maxSessions')
    username = user.get('username', 'admin')

    try:
        app_settings.set('session_timeout', str(timeout), username)
        app_settings.set('max_sessions', str(max_sessions), username)
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Failed to save session settings: {e}")
        return jsonify({'success': False, 'error': str(e)})


@settings_bp.route('/api/settings/audit', methods=['POST'])
@login_required_admin
def api_settings_audit():
    """Save audit log retention settings"""
    user = session.get('user', {})
    if user.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Admin only'})

    data = request.get_json()
    retention = data.get('retention')
    username = user.get('username', 'admin')

    try:
        app_settings.set('audit_retention_days', str(retention), username)
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Failed to save audit settings: {e}")
        return jsonify({'success': False, 'error': str(e)})


@settings_bp.route('/api/settings/audit/cleanup', methods=['POST'])
@login_required_admin
def api_settings_audit_cleanup():
    """Cleanup old audit logs"""
    user = session.get('user', {})
    if user.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Admin only'})

    # Get retention days from settings, default to 90
    retention_value = app_settings.get('audit_retention_days', str(Config.DEFAULT_HISTORY_RETENTION_DAYS))
    retention_days = int(retention_value) if retention_value else 90

    try:
        result = db.execute(
            "DELETE FROM command_history WHERE timestamp < DATE_SUB(NOW(), INTERVAL %s DAY)",
            (retention_days,)
        )
        deleted = result.rowcount if hasattr(result, 'rowcount') else 0
        return jsonify({'success': True, 'deleted': deleted, 'retention_days': retention_days})
    except Exception as e:
        logger.error(f"Failed to cleanup audit logs: {e}")
        return jsonify({'success': False, 'error': str(e)})


@settings_bp.route('/api/settings/backup', methods=['POST'])
@login_required_admin
def api_settings_create_backup():
    """Create database backup"""
    user = session.get('user', {})
    if user.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Admin only'})

    backup_dir = Config.BACKUP_DIR
    os.makedirs(backup_dir, exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'nanohub_backup_{timestamp}.sql.gz'
    filepath = os.path.join(backup_dir, filename)

    try:
        # Run mysqldump with absolute paths and credentials from config
        cmd = f'/usr/bin/mysqldump -h {Config.DB_HOST} -u {Config.DB_USER} -p{Config.DB_PASSWORD} {Config.DB_NAME} | /usr/bin/gzip > {filepath}'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if result.returncode == 0:
            return jsonify({'success': True, 'filename': filename})
        else:
            return jsonify({'success': False, 'error': result.stderr})
    except Exception as e:
        logger.error(f"Backup failed: {e}")
        return jsonify({'success': False, 'error': str(e)})


@settings_bp.route('/api/settings/backup/download/<filename>')
@login_required_admin
def api_settings_download_backup(filename):
    """Download a backup file"""
    user = session.get('user', {})
    if user.get('role') != 'admin':
        return "Access denied", 403

    # Sanitize filename
    if '..' in filename or '/' in filename:
        return "Invalid filename", 400

    backup_dir = Config.BACKUP_DIR
    filepath = os.path.join(backup_dir, filename)

    if not os.path.exists(filepath):
        return "File not found", 404

    return send_file(filepath, as_attachment=True)


@settings_bp.route('/api/settings/backup/delete/<filename>', methods=['DELETE'])
@login_required_admin
def api_settings_delete_backup(filename):
    """Delete a backup file"""
    user = session.get('user', {})
    if user.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Admin only'})

    # Sanitize filename
    if '..' in filename or '/' in filename:
        return jsonify({'success': False, 'error': 'Invalid filename'})

    backup_dir = Config.BACKUP_DIR
    filepath = os.path.join(backup_dir, filename)

    if not os.path.exists(filepath):
        return jsonify({'success': False, 'error': 'File not found'})

    try:
        os.remove(filepath)
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Failed to delete backup: {e}")
        return jsonify({'success': False, 'error': str(e)})


@settings_bp.route('/api/settings/export/user-roles')
@login_required_admin
def api_settings_export_user_roles():
    """Export user roles as JSON"""
    user = session.get('user', {})
    if user.get('role') != 'admin':
        return "Access denied", 403

    try:
        from db_utils import user_roles as user_roles_db
        roles = user_roles_db.get_all_users(include_inactive=True)
        data = json.dumps(roles, indent=2, default=str)
        return Response(data, mimetype='application/json',
                       headers={'Content-Disposition': 'attachment;filename=user_roles.json'})
    except Exception as e:
        return f"Error: {e}", 500


@settings_bp.route('/api/settings/export/profiles')
@login_required_admin
def api_settings_export_profiles():
    """Export list of profile files as JSON"""
    user = session.get('user', {})
    if user.get('role') != 'admin':
        return "Access denied", 403

    try:
        import glob
        from config import Config
        profiles_dir = Config.PROFILES_DIR

        profiles = []
        for pattern in ['*.mobileconfig', '*.signed.mobileconfig']:
            for filepath in glob.glob(os.path.join(profiles_dir, '**', pattern), recursive=True):
                stat = os.stat(filepath)
                profiles.append({
                    'filename': os.path.basename(filepath),
                    'path': filepath.replace(profiles_dir, ''),
                    'size': stat.st_size,
                    'modified': stat.st_mtime
                })

        data = json.dumps(profiles, indent=2, default=str)
        return Response(data, mimetype='application/json',
                       headers={'Content-Disposition': 'attachment;filename=profiles_list.json'})
    except Exception as e:
        return f"Error: {e}", 500


# =============================================================================
# LOCAL USER MANAGEMENT API
# =============================================================================

@settings_bp.route('/api/settings/local-user', methods=['POST'])
@login_required_admin
def api_settings_local_user():
    """Create or update a local user"""
    user = session.get('user', {})
    if user.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Admin only'})

    data = request.get_json() or {}
    mode = data.get('mode', 'create')
    username = data.get('username', '').strip().lower()
    display_name = data.get('display_name', '').strip() or None
    role = data.get('role', 'operator').strip()
    manifest_filter = data.get('filter', '').strip() or None
    notes = data.get('notes', '').strip() or None
    force_change = data.get('force_change', True)

    if not username:
        return jsonify({'success': False, 'error': 'Username required'})

    valid_roles = ['admin', 'bel-admin', 'operator', 'report']
    if role not in valid_roles:
        return jsonify({'success': False, 'error': f'Invalid role. Must be one of: {", ".join(valid_roles)}'})

    try:
        from db_utils import local_users as local_users_db

        if mode == 'create':
            password = data.get('password', '')
            if len(password) < 6:
                return jsonify({'success': False, 'error': 'Password must be at least 6 characters'})

            # Check if user already exists
            existing = local_users_db.get_user(username)
            if existing:
                return jsonify({'success': False, 'error': f'User "{username}" already exists'})

            success = local_users_db.create_user(
                username=username,
                password=password,
                role=role,
                display_name=display_name,
                manifest_filter=manifest_filter,
                must_change_password=force_change,
                created_by=user.get('username', 'admin'),
                notes=notes
            )
        else:
            # Edit mode - update fields only (not password)
            success = local_users_db.update_user(
                username=username,
                role=role,
                display_name=display_name,
                manifest_filter=manifest_filter,
                notes=notes
            )

        return jsonify({'success': success, 'error': None if success else 'Operation failed'})
    except Exception as e:
        logger.error(f"Failed to save local user: {e}")
        return jsonify({'success': False, 'error': str(e)})


@settings_bp.route('/api/settings/local-user/reset-password', methods=['POST'])
@login_required_admin
def api_settings_local_user_reset_password():
    """Admin password reset for a local user"""
    user = session.get('user', {})
    if user.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Admin only'})

    data = request.get_json() or {}
    username = data.get('username', '').strip().lower()
    new_password = data.get('new_password', '')

    if not username:
        return jsonify({'success': False, 'error': 'Username required'})
    if len(new_password) < 6:
        return jsonify({'success': False, 'error': 'Password must be at least 6 characters'})

    try:
        from db_utils import local_users as local_users_db
        success = local_users_db.reset_password(username, new_password, force_change=True)
        return jsonify({'success': success, 'error': None if success else 'Reset failed'})
    except Exception as e:
        logger.error(f"Failed to reset password: {e}")
        return jsonify({'success': False, 'error': str(e)})


@settings_bp.route('/api/settings/local-user/<username>', methods=['DELETE'])
@login_required_admin
def api_settings_delete_local_user(username):
    """Delete a local user"""
    user = session.get('user', {})
    if user.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Admin only'})

    username = username.strip().lower()
    if username == 'admin':
        return jsonify({'success': False, 'error': 'Cannot delete the default admin user'})

    try:
        from db_utils import local_users as local_users_db
        success = local_users_db.delete_user(username)
        return jsonify({'success': success, 'error': None if success else 'Delete failed'})
    except Exception as e:
        logger.error(f"Failed to delete local user: {e}")
        return jsonify({'success': False, 'error': str(e)})
