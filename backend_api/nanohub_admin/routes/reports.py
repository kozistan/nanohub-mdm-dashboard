"""
NanoHUB Admin - Reports Routes
==============================
Reports page and individual report routes for device statistics,
compliance reports, and activity tracking.
"""

import json
import logging
import os
from datetime import datetime

from flask import Blueprint, render_template_string, session, request, jsonify

from config import Config
from nanohub_admin.utils import login_required_admin


def load_expected_app_versions():
    """Load expected app versions from VPP JSON files."""
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
    return expected_versions


def get_outdated_apps(apps_data, os_type, expected_versions):
    """Check installed apps against expected versions and return outdated list."""
    outdated_apps = []
    if not apps_data or os_type not in expected_versions:
        return outdated_apps

    try:
        installed_apps = json.loads(apps_data) if isinstance(apps_data, str) else apps_data
        if not isinstance(installed_apps, list):
            return outdated_apps

        expected = expected_versions[os_type]
        for app in installed_apps:
            bundle_id = app.get('identifier', app.get('bundleId', ''))
            if bundle_id in expected:
                installed_ver = app.get('version', app.get('ShortVersion', ''))
                expected_ver = expected[bundle_id]['version']
                app_name = expected[bundle_id]['name']
                if installed_ver and expected_ver and installed_ver != expected_ver:
                    if expected_ver > installed_ver:
                        outdated_apps.append(f"{app_name}: {installed_ver} → {expected_ver}")
    except Exception:
        pass
    return outdated_apps


def get_enrollment_type(dep_value, security_data):
    """Determine enrollment type from DEP and security_data.

    Enrollment types:
    - IsUserEnrollment=True → BYOD (personal device with managed Apple ID)
    - EnrolledViaDEP=True + UserApprovedEnrollment=True → DEP (User Approved)
    - EnrolledViaDEP=True + UserApprovedEnrollment=False → DEP (Not Approved)
    - EnrolledViaDEP=False + UserApprovedEnrollment=True → Manual (User Approved)
    - EnrolledViaDEP=False + UserApprovedEnrollment=False → Manual (Not Approved)
    """
    is_dep = False
    is_user_enrollment = False
    is_user_approved = False

    # Check DEP status
    if dep_value in ['1', 'enabled', True, 'Yes']:
        is_dep = True
    elif isinstance(security_data, dict):
        dep_sec = security_data.get('enrolled_via_dep', security_data.get('EnrolledViaDEP', False))
        is_dep = dep_sec is True or str(dep_sec).lower() in ('true', 'yes', '1')

    # Check BYOD user enrollment
    if isinstance(security_data, dict):
        user_enroll = security_data.get('is_user_enrollment', security_data.get('IsUserEnrollment', False))
        is_user_enrollment = user_enroll is True or str(user_enroll).lower() in ('true', 'yes', '1')

    # Check user approved enrollment
    if isinstance(security_data, dict):
        user_approved = security_data.get('user_approved_enrollment', security_data.get('UserApprovedEnrollment', False))
        is_user_approved = user_approved is True or str(user_approved).lower() in ('true', 'yes', '1')

    # BYOD takes priority (personal device)
    if is_user_enrollment:
        return 'BYOD'

    # DEP enrollment
    if is_dep:
        return 'DEP (User Approved)' if is_user_approved else 'DEP (Not Approved)'

    # Manual enrollment
    return 'Manual (User Approved)' if is_user_approved else 'Manual (Not Approved)'
from db_utils import db, required_profiles, ddm_compliance, command_history, devices
from cache_utils import device_cache

logger = logging.getLogger('nanohub_admin')

# Create a blueprint for reports routes
reports_bp = Blueprint('admin_reports', __name__)


# Import shared functions from core module (they stay in core to avoid circular imports)
def _get_shared_functions():
    """Lazy import to avoid circular imports"""
    from nanohub_admin.core import fetch_apple_latest_os, get_manifests_list, is_device_outdated
    return fetch_apple_latest_os, get_manifests_list, is_device_outdated


# =============================================================================
# REPORTS
# =============================================================================

@reports_bp.route('/reports')
@login_required_admin
def admin_reports():
    """Reports page with device table, filters and sortable columns"""
    user = session.get('user', {})
    manifest_filter = user.get('manifest_filter')  # e.g. 'site-%' for site-admin

    # Get shared functions
    fetch_apple_latest_os, get_manifests_list, is_device_outdated = _get_shared_functions()
    apple_latest = fetch_apple_latest_os()  # Still needed for latest_versions display

    # Get all devices with details
    devices = []
    stats = {
        'total': 0, 'macos': 0, 'ios': 0,
        'dep_yes': 0, 'dep_no': 0,
        'supervised_yes': 0, 'supervised_no': 0,
        'encrypted_yes': 0, 'encrypted_no': 0,
        'outdated_yes': 0, 'outdated_no': 0,
        'profiles_ok': 0, 'profiles_missing': 0,
        'ddm_ok': 0, 'ddm_missing': 0
    }

    # Build WHERE clause for manifest filter
    where_clause = ""
    query_params = []
    if manifest_filter:
        where_clause = "WHERE di.manifest LIKE %s"
        query_params.append(manifest_filter)

    # Load expected app versions for outdated detection
    expected_app_versions = load_expected_app_versions()

    try:
        rows = db.query_all(f"""
            SELECT
                di.uuid, di.hostname, di.serial, di.os, di.manifest, di.account, di.dep,
                dd.hardware_data, dd.security_data, dd.profiles_data, dd.ddm_data, dd.apps_data,
                e.max_last_seen,
                CASE
                    WHEN e.max_last_seen IS NULL THEN 'offline'
                    WHEN TIMESTAMPDIFF(MINUTE, e.max_last_seen, NOW()) <= 15 THEN 'online'
                    WHEN TIMESTAMPDIFF(MINUTE, e.max_last_seen, NOW()) <= 60 THEN 'active'
                    ELSE 'offline'
                END as status
            FROM device_inventory di
            LEFT JOIN device_details dd ON di.uuid = dd.uuid
            LEFT JOIN (
                SELECT device_id, MAX(last_seen_at) as max_last_seen
                FROM enrollments
                GROUP BY device_id
            ) e ON di.uuid = e.device_id
            {where_clause}
            ORDER BY di.hostname
        """, query_params if query_params else None)

        for row in rows or []:
            device_uuid = row.get('uuid', '')
            os_type = (row.get('os') or '').lower()
            manifest = row.get('manifest', '') or ''

            # Try to get processed data from cache (using reports-specific cache key)
            cache_key = f"reports:{device_uuid}"
            cached = device_cache.get(cache_key)

            if cached:
                # Use cached processed data
                os_ver = cached.get('os_version', '-')
                model = cached.get('model', '-')
                product_name = cached.get('product_name', '-')
                is_supervised = cached.get('is_supervised', False)
                is_encrypted = cached.get('is_encrypted', False)
                is_dep = cached.get('is_dep', False)
                profile_check = cached.get('profile_check', {'required': 0, 'installed': 0, 'missing': 0, 'complete': True, 'missing_list': []})
                ddm_check = cached.get('ddm_check', {'required': 0, 'valid': 0, 'complete': True, 'set_name': None, 'missing_list': []})
            else:
                # Parse JSON and process data
                hw = row.get('hardware_data')
                if hw and isinstance(hw, str):
                    try: hw = json.loads(hw)
                    except: hw = {}
                elif not hw:
                    hw = {}

                sec = row.get('security_data')
                if sec and isinstance(sec, str):
                    try: sec = json.loads(sec)
                    except: sec = {}
                elif not sec:
                    sec = {}

                profiles = row.get('profiles_data')
                if profiles and isinstance(profiles, str):
                    try: profiles = json.loads(profiles)
                    except: profiles = []
                if not profiles:
                    profiles = []

                ddm_data = row.get('ddm_data')
                # Handle various formats: string, bytes, already-parsed list/dict
                if ddm_data:
                    if isinstance(ddm_data, bytes):
                        ddm_data = ddm_data.decode('utf-8')
                    if isinstance(ddm_data, str):
                        try:
                            ddm_data = json.loads(ddm_data)
                        except:
                            ddm_data = []
                    elif not isinstance(ddm_data, list):
                        ddm_data = []
                else:
                    ddm_data = []

                os_ver = hw.get('os_version', hw.get('OSVersion', '')) if hw else ''
                model = hw.get('model_name', hw.get('ModelName', '')) if hw else ''
                product_name = hw.get('product_name', hw.get('ProductName', '')) if hw else ''

                # Supervised
                is_supervised = False
                if hw:
                    sup = hw.get('is_supervised', hw.get('IsSupervised', False))
                    is_supervised = sup is True or sup == 'true'

                # Encrypted (FileVault for macOS)
                is_encrypted = False
                if sec:
                    fv = sec.get('filevault_enabled', sec.get('FDE_Enabled', False))
                    is_encrypted = fv is True or fv == 'true'

                # DEP enrolled (check di.dep column first, fallback to security_data)
                is_dep = False
                dep_val = str(row.get('dep', '')).lower()
                if dep_val in ('enabled', '1', 'yes', 'true'):
                    is_dep = True
                elif sec:
                    # Fallback to security_data.enrolled_via_dep
                    dep_sec = sec.get('enrolled_via_dep', sec.get('IsDeviceEnrollmentProgram', sec.get('DEPEnrolled')))
                    is_dep = dep_sec is True or str(dep_sec).lower() in ('true', 'yes', '1')

                # Profile compliance check
                profile_check = required_profiles.check_device_profiles(manifest, os_type, profiles)

                # DDM compliance check
                ddm_check = ddm_compliance.check_device_ddm(manifest, os_type, ddm_data)

                # Store in cache for next request
                device_cache.set(cache_key, {
                    'os_version': os_ver,
                    'model': model,
                    'product_name': product_name,
                    'is_supervised': is_supervised,
                    'is_encrypted': is_encrypted,
                    'is_dep': is_dep,
                    'profile_check': profile_check,
                    'ddm_check': ddm_check
                })

            # Outdated OS check - compare against max supported version for this specific model
            is_outdated = is_device_outdated(os_ver, product_name)

            # Outdated apps check
            outdated_apps = get_outdated_apps(row.get('apps_data'), os_type, expected_app_versions)

            # Parse security_data for enrollment type (need to parse again if was cached)
            sec_data = row.get('security_data')
            if sec_data and isinstance(sec_data, str):
                try:
                    sec_data = json.loads(sec_data)
                except:
                    sec_data = {}
            elif not sec_data:
                sec_data = {}

            # Enrollment type (DEP Device/User, Manual Device/User)
            enrollment_type = get_enrollment_type(row.get('dep'), sec_data)

            # Last check-in
            last_seen = row.get('max_last_seen')
            last_seen_str = last_seen.strftime('%Y-%m-%d %H:%M') if last_seen else '-'

            # Status from SQL (uses MySQL NOW() for accurate time comparison)
            status = row.get('status', 'offline')

            device = {
                'uuid': device_uuid,
                'hostname': row.get('hostname', ''),
                'serial': row.get('serial', ''),
                'os': os_type,
                'os_version': os_ver or '-',
                'model': model or '-',
                'product_name': product_name or '-',
                'manifest': manifest or '-',
                'account': row.get('account', '') or '-',
                'dep': 'Yes' if is_dep else 'No',
                'enrollment_type': enrollment_type,
                'supervised': 'Yes' if is_supervised else 'No',
                'encrypted': 'Yes' if is_encrypted else 'No',
                'outdated': 'Yes' if is_outdated else 'No',
                'outdated_apps': outdated_apps,
                'profiles_required': profile_check['required'],
                'profiles_installed': profile_check['installed'],
                'profiles_missing': profile_check['missing'],
                'profiles_complete': profile_check['complete'],
                'profiles_missing_list': profile_check['missing_list'],
                'ddm_required': ddm_check['required'],
                'ddm_valid': ddm_check['valid'],
                'ddm_complete': ddm_check['complete'],
                'ddm_set_name': ddm_check['set_name'],
                'ddm_missing_list': ddm_check['missing_list'],
                'last_seen': last_seen_str,
                'status': status
            }
            devices.append(device)

            # Update stats
            stats['total'] += 1
            if os_type == 'macos':
                stats['macos'] += 1
            elif os_type == 'ios':
                stats['ios'] += 1
            # DEP
            if is_dep:
                stats['dep_yes'] += 1
            else:
                stats['dep_no'] += 1
            # Supervised
            if is_supervised:
                stats['supervised_yes'] += 1
            else:
                stats['supervised_no'] += 1
            # Encrypted
            if is_encrypted:
                stats['encrypted_yes'] += 1
            else:
                stats['encrypted_no'] += 1
            # Outdated
            if is_outdated:
                stats['outdated_yes'] += 1
            else:
                stats['outdated_no'] += 1
            # Profiles
            if profile_check['complete']:
                stats['profiles_ok'] += 1
            elif profile_check['required'] > 0:
                stats['profiles_missing'] += 1
            # DDM
            if ddm_check['complete']:
                stats['ddm_ok'] += 1
            elif ddm_check['required'] > 0:
                stats['ddm_missing'] += 1

    except Exception as e:
        logger.error(f"Reports error: {e}")

    # Get manifests for filter from DB
    manifests = get_manifests_list(manifest_filter)

    # Latest versions info for display
    latest_info = {k: v.get('version', '?') for k, v in apple_latest.items()}

    # Return HTML with empty data - data will be loaded via AJAX
    return render_template_string(ADMIN_REPORTS_TEMPLATE,
        user=user,
        devices=[],  # Empty - loaded via AJAX
        stats={'total': 0, 'macos': 0, 'ios': 0, 'dep_yes': 0, 'dep_no': 0,
               'supervised_yes': 0, 'supervised_no': 0, 'encrypted_yes': 0, 'encrypted_no': 0,
               'outdated_yes': 0, 'outdated_no': 0, 'profiles_ok': 0, 'profiles_missing': 0,
               'ddm_ok': 0, 'ddm_missing': 0},
        manifests=manifests,
        latest_versions=latest_info,
        async_load=True  # Flag for template to show loading state
    )


@reports_bp.route('/api/reports/data')
@login_required_admin
def api_reports_data():
    """API endpoint for reports data - returns JSON for async loading"""
    user = session.get('user', {})
    manifest_filter = user.get('manifest_filter')

    # Get shared functions
    fetch_apple_latest_os, get_manifests_list, is_device_outdated = _get_shared_functions()
    apple_latest = fetch_apple_latest_os()  # Still needed for latest_versions display

    # Get all devices with details
    devices_list = []
    stats = {
        'total': 0, 'macos': 0, 'ios': 0,
        'dep_yes': 0, 'dep_no': 0,
        'supervised_yes': 0, 'supervised_no': 0,
        'encrypted_yes': 0, 'encrypted_no': 0,
        'outdated_yes': 0, 'outdated_no': 0,
        'profiles_ok': 0, 'profiles_missing': 0,
        'ddm_ok': 0, 'ddm_missing': 0
    }

    # Build WHERE clause for manifest filter
    where_clause = ""
    query_params = []
    if manifest_filter:
        where_clause = "WHERE di.manifest LIKE %s"
        query_params.append(manifest_filter)

    # Load expected app versions for outdated detection
    expected_app_versions = load_expected_app_versions()

    try:
        rows = db.query_all(f"""
            SELECT
                di.uuid, di.hostname, di.serial, di.os, di.manifest, di.account, di.dep,
                dd.hardware_data, dd.security_data, dd.profiles_data, dd.ddm_data, dd.apps_data,
                e.max_last_seen,
                CASE
                    WHEN e.max_last_seen IS NULL THEN 'offline'
                    WHEN TIMESTAMPDIFF(MINUTE, e.max_last_seen, NOW()) <= 15 THEN 'online'
                    WHEN TIMESTAMPDIFF(MINUTE, e.max_last_seen, NOW()) <= 60 THEN 'active'
                    ELSE 'offline'
                END as status
            FROM device_inventory di
            LEFT JOIN device_details dd ON di.uuid = dd.uuid
            LEFT JOIN (
                SELECT device_id, MAX(last_seen_at) as max_last_seen
                FROM enrollments
                GROUP BY device_id
            ) e ON di.uuid = e.device_id
            {where_clause}
            ORDER BY di.hostname
        """, query_params if query_params else None)

        for row in rows or []:
            device_uuid = row.get('uuid', '')
            os_type = (row.get('os') or '').lower()
            manifest = row.get('manifest', '') or ''

            # Try to get processed data from cache
            cache_key = f"reports:{device_uuid}"
            cached = device_cache.get(cache_key)

            if cached:
                os_ver = cached.get('os_version', '-')
                model = cached.get('model', '-')
                product_name = cached.get('product_name', '-')
                is_supervised = cached.get('is_supervised', False)
                is_encrypted = cached.get('is_encrypted', False)
                is_dep = cached.get('is_dep', False)
                profile_check = cached.get('profile_check', {'required': 0, 'installed': 0, 'missing': 0, 'complete': True, 'missing_list': []})
                ddm_check = cached.get('ddm_check', {'required': 0, 'valid': 0, 'complete': True, 'set_name': None, 'missing_list': []})
            else:
                # Parse JSON and process data
                hw = row.get('hardware_data')
                if hw and isinstance(hw, str):
                    try: hw = json.loads(hw)
                    except: hw = {}
                elif not hw:
                    hw = {}

                sec = row.get('security_data')
                if sec and isinstance(sec, str):
                    try: sec = json.loads(sec)
                    except: sec = {}
                elif not sec:
                    sec = {}

                profiles = row.get('profiles_data')
                if profiles and isinstance(profiles, str):
                    try: profiles = json.loads(profiles)
                    except: profiles = []
                if not profiles:
                    profiles = []

                ddm_data = row.get('ddm_data')
                if ddm_data:
                    if isinstance(ddm_data, bytes):
                        ddm_data = ddm_data.decode('utf-8')
                    if isinstance(ddm_data, str):
                        try: ddm_data = json.loads(ddm_data)
                        except: ddm_data = []
                    elif not isinstance(ddm_data, list):
                        ddm_data = []
                else:
                    ddm_data = []

                os_ver = hw.get('os_version', hw.get('OSVersion', '')) if hw else ''
                model = hw.get('model_name', hw.get('ModelName', '')) if hw else ''
                product_name = hw.get('product_name', hw.get('ProductName', '')) if hw else ''

                is_supervised = False
                if hw:
                    sup = hw.get('is_supervised', hw.get('IsSupervised', False))
                    is_supervised = sup is True or sup == 'true'

                is_encrypted = False
                if sec:
                    fv = sec.get('filevault_enabled', sec.get('FDE_Enabled', False))
                    is_encrypted = fv is True or fv == 'true'

                is_dep = False
                dep_val = str(row.get('dep', '')).lower()
                if dep_val in ('enabled', '1', 'yes', 'true'):
                    is_dep = True
                elif sec:
                    dep_sec = sec.get('enrolled_via_dep', sec.get('IsDeviceEnrolledVia', sec.get('DEPEnrolled')))
                    is_dep = dep_sec is True or str(dep_sec).lower() in ('true', 'yes', '1')

                profile_check = required_profiles.check_device_profiles(manifest, os_type, profiles)
                ddm_check = ddm_compliance.check_device_ddm(manifest, os_type, ddm_data)

                # Store in cache
                device_cache.set(cache_key, {
                    'os_version': os_ver,
                    'model': model,
                    'product_name': product_name,
                    'is_supervised': is_supervised,
                    'is_encrypted': is_encrypted,
                    'is_dep': is_dep,
                    'profile_check': profile_check,
                    'ddm_check': ddm_check
                })

            # Outdated check - compare against max supported version for this specific model
            is_outdated = is_device_outdated(os_ver, product_name)

            # Outdated apps check
            outdated_apps = get_outdated_apps(row.get('apps_data'), os_type, expected_app_versions)

            # Parse security_data for enrollment type
            sec_data = row.get('security_data')
            if sec_data and isinstance(sec_data, str):
                try:
                    sec_data = json.loads(sec_data)
                except:
                    sec_data = {}
            elif not sec_data:
                sec_data = {}

            # Enrollment type
            enrollment_type = get_enrollment_type(row.get('dep'), sec_data)

            last_seen = row.get('max_last_seen')
            last_seen_str = last_seen.strftime('%Y-%m-%d %H:%M') if last_seen else '-'
            status = row.get('status', 'offline')

            device = {
                'uuid': device_uuid,
                'hostname': row.get('hostname', ''),
                'serial': row.get('serial', ''),
                'os': os_type,
                'os_version': os_ver or '-',
                'model': model or '-',
                'product_name': product_name or '-',
                'manifest': manifest or '-',
                'account': row.get('account', '') or '-',
                'dep': 'Yes' if is_dep else 'No',
                'enrollment_type': enrollment_type,
                'supervised': 'Yes' if is_supervised else 'No',
                'encrypted': 'Yes' if is_encrypted else 'No',
                'outdated': 'Yes' if is_outdated else 'No',
                'outdated_apps': outdated_apps,
                'profiles_required': profile_check['required'],
                'profiles_installed': profile_check['installed'],
                'profiles_missing': profile_check['missing'],
                'profiles_complete': profile_check['complete'],
                'profiles_missing_list': profile_check['missing_list'],
                'ddm_required': ddm_check['required'],
                'ddm_valid': ddm_check['valid'],
                'ddm_complete': ddm_check['complete'],
                'ddm_set_name': ddm_check['set_name'],
                'ddm_missing_list': ddm_check['missing_list'],
                'last_seen': last_seen_str,
                'status': status
            }
            devices_list.append(device)

            # Update stats
            stats['total'] += 1
            if os_type == 'macos':
                stats['macos'] += 1
            elif os_type == 'ios':
                stats['ios'] += 1
            if is_dep:
                stats['dep_yes'] += 1
            else:
                stats['dep_no'] += 1
            if is_supervised:
                stats['supervised_yes'] += 1
            else:
                stats['supervised_no'] += 1
            if is_encrypted:
                stats['encrypted_yes'] += 1
            else:
                stats['encrypted_no'] += 1
            if is_outdated:
                stats['outdated_yes'] += 1
            else:
                stats['outdated_no'] += 1
            if profile_check['complete']:
                stats['profiles_ok'] += 1
            elif profile_check['required'] > 0:
                stats['profiles_missing'] += 1
            if ddm_check['complete']:
                stats['ddm_ok'] += 1
            elif ddm_check['required'] > 0:
                stats['ddm_missing'] += 1

    except Exception as e:
        logger.error(f"API Reports error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

    latest_info = {k: v.get('version', '?') for k, v in apple_latest.items()}

    return jsonify({
        'success': True,
        'devices': devices_list,
        'stats': stats,
        'latest_versions': latest_info
    })


ADMIN_REPORTS_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Reports - NanoHUB Admin</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="/static/dashboard.css">
    <link rel="stylesheet" href="/static/css/qbone.css">
    <link rel="stylesheet" href="/static/css/admin.css">
    <link rel="shortcut icon" href="/static/favicon.ico">
    <style>
    /* Tooltip for missing profiles/DDM - uses position:fixed to escape overflow containers */
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
    .profiles-tooltip, .ddm-tooltip { cursor: help; }
    .custom-tooltip div { padding: 1px 0; }
    </style>
</head>
<body class="page-with-table">
    <div id="wrap">
        <div style="display: flex; justify-content: center;">
            <img id="logo" src="{{ current_logo }}" alt="Logo" style="max-height:60px;max-width:200px;"/>
        </div>
        <h1>Reports</h1>

        <div class="panel">
            <div class="admin-header">
                <h2>Device Reports</h2>
                <div class="nav-tabs">
                    <a href="/admin" class="btn">Commands</a>
                    <a href="/admin/devices" class="btn">Devices</a>
                    <a href="/admin/profiles" class="btn">Profiles</a>
                    <a href="/admin/ddm" class="btn">DDM</a>
                    <a href="/admin/vpp" class="btn">VPP</a>
                    <a href="/admin/reports" class="btn active">Reports</a>
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

            <!-- Stats Bar (clickable filters) -->
            <div class="stats-bar">
                <div class="stat-item" data-filter="all" onclick="filterByStat('all')">
                    <div class="stat-value">{{ stats.total }}</div>
                    <div class="stat-label">Total</div>
                </div>
                <div class="stat-item" data-filter="macos" onclick="filterByStat('macos')">
                    <div class="stat-value">{{ stats.macos }}</div>
                    <div class="stat-label">macOS</div>
                </div>
                <div class="stat-item" data-filter="ios" onclick="filterByStat('ios')">
                    <div class="stat-value">{{ stats.ios }}</div>
                    <div class="stat-label">iOS</div>
                </div>
                <div class="stat-item stat-toggle" data-filter="dep" data-yes="{{ stats.dep_yes }}" data-no="{{ stats.dep_no }}" onclick="toggleStat(this, 'dep')">
                    <div class="stat-value">{{ stats.dep_yes }}</div>
                    <div class="stat-label">DEP</div>
                </div>
                <div class="stat-item stat-toggle" data-filter="supervised" data-yes="{{ stats.supervised_yes }}" data-no="{{ stats.supervised_no }}" onclick="toggleStat(this, 'supervised')">
                    <div class="stat-value">{{ stats.supervised_yes }}</div>
                    <div class="stat-label">Supervised</div>
                </div>
                <div class="stat-item stat-toggle" data-filter="encrypted" data-yes="{{ stats.encrypted_yes }}" data-no="{{ stats.encrypted_no }}" onclick="toggleStat(this, 'encrypted')">
                    <div class="stat-value">{{ stats.encrypted_yes }}</div>
                    <div class="stat-label">Encrypted</div>
                </div>
                <div class="stat-item stat-toggle" data-filter="outdated" data-yes="{{ stats.outdated_yes }}" data-no="{{ stats.outdated_no }}" onclick="toggleStat(this, 'outdated')">
                    <div class="stat-value">{{ stats.outdated_yes }}</div>
                    <div class="stat-label">Outdated</div>
                </div>
                <div class="stat-item stat-toggle" data-filter="profiles" data-yes="{{ stats.profiles_ok }}" data-no="{{ stats.profiles_missing }}" onclick="toggleStat(this, 'profiles')">
                    <div class="stat-value">{{ stats.profiles_ok }}</div>
                    <div class="stat-label">Profiles</div>
                </div>
                <div class="stat-item stat-toggle" data-filter="ddm" data-yes="{{ stats.ddm_ok }}" data-no="{{ stats.ddm_missing }}" onclick="toggleStat(this, 'ddm')">
                    <div class="stat-value">{{ stats.ddm_ok }}</div>
                    <div class="stat-label">DDM</div>
                </div>
            </div>

            <!-- Latest versions info -->
            <div class="latest-info">
                Latest versions:
                <span>iOS {{ latest_versions.ios }}</span>
                <span>iPadOS {{ latest_versions.ipados }}</span>
                <span>macOS {{ latest_versions.macos }}</span>
            </div>

            <!-- Filters -->
            <div class="filter-form">
                <div class="filter-group">
                    <label>Manifest</label>
                    <select id="filterManifest" onchange="applyFilters()">
                        <option value="">All</option>
                        {% for m in manifests %}<option value="{{ m }}">{{ m }}</option>{% endfor %}
                    </select>
                </div>
                <div class="filter-group">
                    <label>Search</label>
                    <input type="text" id="filterSearch" placeholder="Hostname, serial..." onkeyup="applyFilters()">
                </div>
                <!-- Hidden selects for JS compatibility (stat buttons set these values) -->
                <select id="filterOS" style="display:none;"><option value="">All</option><option value="macos">macOS</option><option value="ios">iOS</option></select>
                <select id="filterSupervised" style="display:none;"><option value="">All</option><option value="Yes">Yes</option><option value="No">No</option></select>
                <select id="filterEncrypted" style="display:none;"><option value="">All</option><option value="Yes">Yes</option><option value="No">No</option></select>
                <select id="filterOutdated" style="display:none;"><option value="">All</option><option value="Yes">Yes</option><option value="No">No</option></select>
                <select id="filterDep" style="display:none;"><option value="">All</option><option value="Yes">Yes</option><option value="No">No</option></select>
                <select id="filterProfiles" style="display:none;"><option value="">All</option><option value="complete">Complete</option><option value="incomplete">Incomplete</option></select>
                <select id="filterDDM" style="display:none;"><option value="">All</option><option value="complete">Complete</option><option value="incomplete">Incomplete</option></select>
                <div class="filter-buttons" style="margin-left:auto;">
                    <button class="btn" onclick="selectAllFiltered()">Select All</button>
                    <button class="btn" onclick="deselectAll()">Deselect</button>
                    <span class="selected-count" id="selectedCount">0 selected</span>
                    <button class="btn btn-warning" onclick="refreshDeviceData()">Refresh Data</button>
                    <button class="export-btn" onclick="exportCSV()">Export CSV</button>
                    <button class="export-btn" onclick="exportSelectedCSV()">Export Selected</button>
                </div>
            </div>

            <!-- Device Table -->
            <div class="table-wrapper">
                <table class="device-table" id="deviceTable">
                    <thead>
                        <tr>
                            <th style="width:30px;"><input type="checkbox" id="selectAllCheckbox" onchange="toggleSelectAll()"></th>
                            <th class="sortable" data-col="hostname" onclick="sortTable('hostname')">Hostname <span class="sort-arrow"></span></th>
                            <th class="sortable" data-col="serial" onclick="sortTable('serial')">Serial <span class="sort-arrow"></span></th>
                            <th class="sortable" data-col="os" onclick="sortTable('os')">OS <span class="sort-arrow"></span></th>
                            <th class="sortable" data-col="os_version" onclick="sortTable('os_version')">Version <span class="sort-arrow"></span></th>
                            <th class="sortable" data-col="model" onclick="sortTable('model')">Model <span class="sort-arrow"></span></th>
                            <th class="sortable" data-col="product_name" onclick="sortTable('product_name')">Product <span class="sort-arrow"></span></th>
                            <th class="sortable" data-col="manifest" onclick="sortTable('manifest')">Manifest <span class="sort-arrow"></span></th>
                            <th class="sortable" data-col="dep" onclick="sortTable('dep')">DEP <span class="sort-arrow"></span></th>
                            <th class="sortable" data-col="supervised" onclick="sortTable('supervised')">Supervised <span class="sort-arrow"></span></th>
                            <th class="sortable" data-col="encrypted" onclick="sortTable('encrypted')">Encrypted <span class="sort-arrow"></span></th>
                            <th class="sortable" data-col="outdated" onclick="sortTable('outdated')">Outdated <span class="sort-arrow"></span></th>
                            <th class="sortable" data-col="profiles" onclick="sortTable('profiles')">Profiles <span class="sort-arrow"></span></th>
                            <th class="sortable" data-col="ddm" onclick="sortTable('ddm')">DDM <span class="sort-arrow"></span></th>
                            <th class="sortable" data-col="last_seen" onclick="sortTable('last_seen')">Last Check-in <span class="sort-arrow"></span></th>
                            <th class="sortable" data-col="status" onclick="sortTable('status')" style="text-align:center;">Status <span class="sort-arrow"></span></th>
                        </tr>
                    </thead>
                    <tbody id="deviceTableBody"></tbody>
                </table>
            </div>

            <!-- Pagination -->
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
    const perPage = 50;
    let isLoading = false;

    document.addEventListener('DOMContentLoaded', function() {
        // Load data asynchronously
        loadReportsData();
    });

    function showLoading() {
        isLoading = true;
        const tbody = document.getElementById('deviceTableBody');
        tbody.innerHTML = '<tr><td colspan="15" style="text-align:center;padding:40px;color:#B0B0B0;"><div style="font-size:1.2em;">Loading devices...</div><div style="margin-top:10px;font-size:0.9em;">Please wait</div></td></tr>';
        document.getElementById('pagination').innerHTML = '';
        document.getElementById('page-info').innerHTML = '';
    }

    function hideLoading() {
        isLoading = false;
    }

    function updateStatsDisplay(stats) {
        // Update all stat values in the stats bar
        const statMappings = {
            'all': stats.total,
            'macos': stats.macos,
            'ios': stats.ios
        };

        // Update simple stats
        document.querySelectorAll('.stat-item').forEach(el => {
            const filter = el.dataset.filter;
            if (filter === 'all') {
                el.querySelector('.stat-value').textContent = stats.total;
            } else if (filter === 'macos') {
                el.querySelector('.stat-value').textContent = stats.macos;
            } else if (filter === 'ios') {
                el.querySelector('.stat-value').textContent = stats.ios;
            }
        });

        // Update toggle stats (yes/no values)
        document.querySelectorAll('.stat-toggle').forEach(el => {
            const filter = el.dataset.filter;
            let yesVal = 0, noVal = 0;

            if (filter === 'dep') { yesVal = stats.dep_yes; noVal = stats.dep_no; }
            else if (filter === 'supervised') { yesVal = stats.supervised_yes; noVal = stats.supervised_no; }
            else if (filter === 'encrypted') { yesVal = stats.encrypted_yes; noVal = stats.encrypted_no; }
            else if (filter === 'outdated') { yesVal = stats.outdated_yes; noVal = stats.outdated_no; }
            else if (filter === 'profiles') { yesVal = stats.profiles_ok; noVal = stats.profiles_missing; }
            else if (filter === 'ddm') { yesVal = stats.ddm_ok; noVal = stats.ddm_missing; }

            el.dataset.yes = yesVal;
            el.dataset.no = noVal;
            el.querySelector('.stat-value').textContent = yesVal;
        });
    }

    function loadReportsData() {
        showLoading();

        fetch('/admin/api/reports/data')
            .then(response => {
                if (!response.ok) {
                    throw new Error('Network response was not ok');
                }
                return response.json();
            })
            .then(data => {
                hideLoading();

                if (!data.success) {
                    throw new Error(data.error || 'Failed to load data');
                }

                // Update global data
                allDevices = data.devices || [];
                filteredDevices = [...allDevices];

                // Update stats display
                if (data.stats) {
                    updateStatsDisplay(data.stats);
                }

                // Apply filters and render
                applyFilters();
            })
            .catch(error => {
                hideLoading();
                console.error('Error loading reports data:', error);
                const tbody = document.getElementById('deviceTableBody');
                tbody.innerHTML = '<tr><td colspan="15" style="text-align:center;padding:40px;color:#e92128;"><div style="font-size:1.1em;">Error loading data</div><div style="margin-top:10px;font-size:0.9em;">' + error.message + '</div><div style="margin-top:15px;"><button class="btn" onclick="loadReportsData()">Retry</button></div></td></tr>';
            });
    }

    function applyFilters() {
        const os = document.getElementById('filterOS').value.toLowerCase();
        const manifest = document.getElementById('filterManifest').value;
        const supervised = document.getElementById('filterSupervised').value;
        const encrypted = document.getElementById('filterEncrypted').value;
        const outdated = document.getElementById('filterOutdated').value;
        const dep = document.getElementById('filterDep').value;
        const profiles = document.getElementById('filterProfiles').value;
        const ddm = document.getElementById('filterDDM').value;
        const search = document.getElementById('filterSearch').value.toLowerCase();

        filteredDevices = allDevices.filter(d => {
            if (os && d.os !== os) return false;
            if (manifest && d.manifest !== manifest) return false;
            if (supervised && d.supervised !== supervised) return false;
            if (encrypted && d.encrypted !== encrypted) return false;
            if (outdated && d.outdated !== outdated) return false;
            if (dep && d.dep !== dep) return false;
            if (profiles === 'complete' && !d.profiles_complete) return false;
            if (profiles === 'incomplete' && d.profiles_complete) return false;
            if (ddm === 'complete' && !d.ddm_complete) return false;
            if (ddm === 'incomplete' && (d.ddm_complete || d.ddm_required === 0)) return false;
            if (search && !d.hostname.toLowerCase().includes(search) && !d.serial.toLowerCase().includes(search)) return false;
            return true;
        });

        // Sort filtered devices
        sortDevices();
        currentPage = 1;
        renderTable();
        renderPagination();
        updateSelectedCount();
    }

    function sortDevices() {
        filteredDevices.sort((a, b) => {
            let va = a[currentSort.col] || '';
            let vb = b[currentSort.col] || '';

            // Handle profiles sorting (by installed/required ratio)
            if (currentSort.col === 'profiles') {
                va = a.profiles_required > 0 ? a.profiles_installed / a.profiles_required : 1;
                vb = b.profiles_required > 0 ? b.profiles_installed / b.profiles_required : 1;
                return currentSort.dir === 'asc' ? va - vb : vb - va;
            }

            // Handle DDM sorting (by valid/required ratio)
            if (currentSort.col === 'ddm') {
                va = a.ddm_required > 0 ? a.ddm_valid / a.ddm_required : 1;
                vb = b.ddm_required > 0 ? b.ddm_valid / b.ddm_required : 1;
                return currentSort.dir === 'asc' ? va - vb : vb - va;
            }

            // Handle version sorting
            if (currentSort.col === 'os_version' && va !== '-' && vb !== '-') {
                const pa = va.split('.').map(Number);
                const pb = vb.split('.').map(Number);
                for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
                    const na = pa[i] || 0;
                    const nb = pb[i] || 0;
                    if (na !== nb) return currentSort.dir === 'asc' ? na - nb : nb - na;
                }
                return 0;
            }

            // String comparison
            if (typeof va === 'string') va = va.toLowerCase();
            if (typeof vb === 'string') vb = vb.toLowerCase();

            if (va < vb) return currentSort.dir === 'asc' ? -1 : 1;
            if (va > vb) return currentSort.dir === 'asc' ? 1 : -1;
            return 0;
        });
    }

    function renderProfilesCell(d) {
        if (d.profiles_required === 0) {
            return '<span class="badge" style="background:#3A3A3A;color:#B0B0B0;">N/A</span>';
        }
        const badgeClass = d.profiles_complete ? 'badge-yes' : 'badge-no';
        const text = d.profiles_installed + '/' + d.profiles_required;

        if (d.profiles_complete) {
            return '<span class="badge ' + badgeClass + '">' + text + '</span>';
        }

        // Store missing profiles in data attribute for tooltip
        let missingNames = [];
        if (d.profiles_missing_list && d.profiles_missing_list.length > 0) {
            d.profiles_missing_list.forEach(p => {
                const name = p.name || p.identifier || String(p);
                missingNames.push(name);
            });
        }
        const dataAttr = missingNames.join('; ').replace(/"/g, '&quot;');
        return '<span class="badge ' + badgeClass + ' profiles-tooltip" data-profiles="' + dataAttr + '">' + text + '</span>';
    }

    function renderDDMCell(d) {
        if (d.ddm_required === 0) {
            return '<span class="badge" style="background:#3A3A3A;color:#B0B0B0;">N/A</span>';
        }
        const badgeClass = d.ddm_complete ? 'badge-yes' : 'badge-no';
        const text = d.ddm_valid + '/' + d.ddm_required;

        if (d.ddm_complete) {
            return '<span class="badge ' + badgeClass + '">' + text + '</span>';
        }

        // Store missing declarations in data attribute for tooltip
        let missingNames = [];
        if (d.ddm_missing_list && d.ddm_missing_list.length > 0) {
            d.ddm_missing_list.forEach(decl => {
                const name = decl.identifier || String(decl);
                missingNames.push(name);
            });
        }
        const dataAttr = missingNames.join('; ').replace(/"/g, '&quot;');
        return '<span class="badge ' + badgeClass + ' ddm-tooltip" data-ddm="' + dataAttr + '">' + text + '</span>';
    }

    // Global tooltip element (shared for all tooltips)
    let globalTooltip = null;

    function createGlobalTooltip() {
        if (!globalTooltip) {
            globalTooltip = document.createElement('div');
            globalTooltip.className = 'custom-tooltip';
            document.body.appendChild(globalTooltip);
        }
    }

    function showTooltip(el, content, headerText) {
        createGlobalTooltip();
        globalTooltip.innerHTML = '';

        // Add header
        const header = document.createElement('div');
        header.style.color = '#e92128';
        header.innerHTML = '<strong>' + headerText + '</strong>';
        globalTooltip.appendChild(header);

        // Add each item
        content.split('; ').forEach(item => {
            if (item.trim()) {
                const line = document.createElement('div');
                line.textContent = '• ' + item;
                globalTooltip.appendChild(line);
            }
        });

        // Position tooltip - show briefly to measure, then position
        const rect = el.getBoundingClientRect();
        globalTooltip.style.visibility = 'hidden';
        globalTooltip.style.display = 'block';
        const tooltipHeight = globalTooltip.offsetHeight;

        // Show above if enough space, otherwise below
        let top = rect.top - tooltipHeight - 5;
        if (top < 10) {
            top = rect.bottom + 5;
        }

        globalTooltip.style.left = rect.left + 'px';
        globalTooltip.style.top = top + 'px';
        globalTooltip.style.visibility = 'visible';
    }

    function hideTooltip() {
        if (globalTooltip) {
            globalTooltip.style.display = 'none';
        }
    }

    // Initialize tooltip hover events for profiles
    function initProfileTooltips() {
        document.querySelectorAll('.profiles-tooltip').forEach(el => {
            if (el.dataset.tooltipInit) return;
            el.dataset.tooltipInit = 'true';

            const profiles = el.dataset.profiles;
            if (profiles && profiles.trim()) {
                el.addEventListener('mouseenter', () => showTooltip(el, profiles, 'Missing:'));
                el.addEventListener('mouseleave', hideTooltip);
            }
        });
    }

    // Initialize tooltip hover events for DDM
    function initDDMTooltips() {
        document.querySelectorAll('.ddm-tooltip').forEach(el => {
            if (el.dataset.tooltipInit) return;
            el.dataset.tooltipInit = 'true';

            const ddmList = el.dataset.ddm;
            if (ddmList && ddmList.trim()) {
                el.addEventListener('mouseenter', () => showTooltip(el, ddmList, 'Missing/Invalid:'));
                el.addEventListener('mouseleave', hideTooltip);
            }
        });
    }

    function renderTable() {
        const tbody = document.getElementById('deviceTableBody');
        tbody.innerHTML = '';

        const start = (currentPage - 1) * perPage;
        const end = Math.min(start + perPage, filteredDevices.length);
        const pageDevices = filteredDevices.slice(start, end);

        pageDevices.forEach(d => {
            const isSelected = selectedUuids.has(d.uuid);
            const row = document.createElement('tr');
            row.dataset.uuid = d.uuid;
            if (isSelected) row.classList.add('selected');
            row.innerHTML = `
                <td><input type="checkbox" class="device-checkbox" data-uuid="${d.uuid}" ${isSelected ? 'checked' : ''} onchange="toggleDevice('${d.uuid}')"></td>
                <td><a href="/admin/device/${d.uuid}" class="device-link"><strong>${d.hostname}</strong></a></td>
                <td>${d.serial}</td>
                <td><span class="os-badge ${d.os.toLowerCase()}">${d.os}</span></td>
                <td>${d.os_version}</td>
                <td>${d.model}</td>
                <td>${d.product_name}</td>
                <td>${d.manifest}</td>
                <td><span class="badge badge-${d.dep === 'Yes' ? 'yes' : 'no'}">${d.dep}</span></td>
                <td><span class="badge badge-${d.supervised === 'Yes' ? 'yes' : 'no'}">${d.supervised}</span></td>
                <td><span class="badge badge-${d.encrypted === 'Yes' ? 'yes' : 'no'}">${d.encrypted}</span></td>
                <td><span class="badge badge-${d.outdated === 'Yes' ? 'no' : 'yes'}">${d.outdated}</span></td>
                <td>${renderProfilesCell(d)}</td>
                <td>${renderDDMCell(d)}</td>
                <td>${d.last_seen}</td>
                <td style="text-align:center;"><span class="status-dot ${d.status}" title="${d.status}"></span></td>
            `;
            tbody.appendChild(row);
        });

        // Update visible count
        const visibleEl = document.getElementById('visibleCount');
        if (visibleEl) visibleEl.textContent = filteredDevices.length;

        // Update header sort indicators
        document.querySelectorAll('.device-table th').forEach(th => {
            th.classList.remove('sorted-asc', 'sorted-desc');
            if (th.dataset.col === currentSort.col) {
                th.classList.add(currentSort.dir === 'asc' ? 'sorted-asc' : 'sorted-desc');
            }
        });

        // Update select all checkbox state
        updateSelectAllCheckbox();

        // Initialize tooltips for missing profiles and DDM
        initProfileTooltips();
        initDDMTooltips();
    }

    function renderPagination() {
        const totalPages = Math.ceil(filteredDevices.length / perPage) || 1;
        const pagination = document.getElementById('pagination');
        const pageInfo = document.getElementById('page-info');

        if (totalPages <= 1) {
            pagination.innerHTML = '';
            pageInfo.innerHTML = filteredDevices.length > 0 ? `Showing ${filteredDevices.length} devices` : '';
            return;
        }

        const start = (currentPage - 1) * perPage + 1;
        const end = Math.min(currentPage * perPage, filteredDevices.length);
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
        const totalPages = Math.ceil(filteredDevices.length / perPage) || 1;
        if (page < 1 || page > totalPages) return;
        currentPage = page;
        renderTable();
        renderPagination();
    }

    function sortTable(col) {
        if (currentSort.col === col) {
            currentSort.dir = currentSort.dir === 'asc' ? 'desc' : 'asc';
        } else {
            currentSort.col = col;
            currentSort.dir = 'asc';
        }
        sortDevices();
        renderTable();
    }

    function filterByStat(stat) {
        resetFilters(false);
        resetToggleStates();

        if (stat === 'macos' || stat === 'ios') {
            document.getElementById('filterOS').value = stat;
        }

        applyFilters();

        // Highlight active stat
        document.querySelectorAll('.stat-item').forEach(el => el.classList.remove('active'));
        const statEl = document.querySelector(`.stat-item[data-filter="${stat}"]`);
        if (statEl) statEl.classList.add('active');
    }

    function toggleStat(el, stat) {
        const currentState = el.dataset.state || 'none';
        let newState, filterValue, displayValue;

        // Toggle: none -> yes -> no (click Total to reset back to none)
        if (currentState === 'none' || currentState === 'no') {
            newState = 'yes';
            filterValue = 'Yes';
            displayValue = el.dataset.yes;
        } else {
            newState = 'no';
            filterValue = 'No';
            displayValue = el.dataset.no;
        }

        // Clear other toggle states
        document.querySelectorAll('.stat-toggle').forEach(t => {
            if (t !== el) {
                t.dataset.state = 'none';
                t.querySelector('.stat-value').textContent = t.dataset.yes;
                t.querySelector('.stat-value').style.color = '';
            }
        });
        document.querySelectorAll('.stat-item').forEach(s => s.classList.remove('active'));

        // Update this element
        el.dataset.state = newState;
        el.querySelector('.stat-value').textContent = displayValue;

        // Apply color directly via style
        const valueEl = el.querySelector('.stat-value');
        if (newState === 'yes') {
            // Outdated: yes=red (bad), others: yes=green (good)
            valueEl.style.color = (stat === 'outdated') ? '#e92128' : '#5FC812';
        } else if (newState === 'no') {
            // Outdated: no=green (good), others: no=red (bad)
            valueEl.style.color = (stat === 'outdated') ? '#5FC812' : '#e92128';
        } else {
            valueEl.style.color = '';
        }

        // Reset filters (without applying yet)
        resetFilters(false);

        // Set new filter value
        if (filterValue) {
            if (stat === 'dep') document.getElementById('filterDep').value = filterValue;
            else if (stat === 'supervised') document.getElementById('filterSupervised').value = filterValue;
            else if (stat === 'encrypted') document.getElementById('filterEncrypted').value = filterValue;
            else if (stat === 'outdated') document.getElementById('filterOutdated').value = filterValue;
            else if (stat === 'profiles') document.getElementById('filterProfiles').value = (filterValue === 'Yes' ? 'complete' : 'incomplete');
            else if (stat === 'ddm') document.getElementById('filterDDM').value = (filterValue === 'Yes' ? 'complete' : 'incomplete');
        }

        // Now apply
        applyFilters();
    }

    function resetToggleStates() {
        document.querySelectorAll('.stat-toggle').forEach(el => {
            el.dataset.state = 'none';
            el.querySelector('.stat-value').textContent = el.dataset.yes;
            el.querySelector('.stat-value').style.color = '';
        });
    }

    function clearStatHighlight() {
        document.querySelectorAll('.stat-item').forEach(el => el.classList.remove('active'));
        resetToggleStates();
    }

    function resetFilters(andApply = true) {
        document.getElementById('filterOS').value = '';
        document.getElementById('filterManifest').value = '';
        document.getElementById('filterSupervised').value = '';
        document.getElementById('filterEncrypted').value = '';
        document.getElementById('filterOutdated').value = '';
        document.getElementById('filterDep').value = '';
        document.getElementById('filterProfiles').value = '';
        document.getElementById('filterDDM').value = '';
        document.getElementById('filterSearch').value = '';
        if (andApply) applyFilters();
    }

    // Selection functions
    function toggleDevice(uuid) {
        if (selectedUuids.has(uuid)) {
            selectedUuids.delete(uuid);
        } else {
            selectedUuids.add(uuid);
        }
        updateSelectedCount();
        updateSelectAllCheckbox();

        // Update row highlight
        const row = document.querySelector(`tr[data-uuid="${uuid}"]`);
        if (row) {
            row.classList.toggle('selected', selectedUuids.has(uuid));
        }
    }

    function toggleSelectAll() {
        const checkbox = document.getElementById('selectAllCheckbox');
        const start = (currentPage - 1) * perPage;
        const end = Math.min(start + perPage, filteredDevices.length);
        const pageDevices = filteredDevices.slice(start, end);

        if (checkbox.checked) {
            pageDevices.forEach(d => selectedUuids.add(d.uuid));
        } else {
            pageDevices.forEach(d => selectedUuids.delete(d.uuid));
        }
        renderTable();
        updateSelectedCount();
    }

    function selectAllPage() {
        const start = (currentPage - 1) * perPage;
        const end = Math.min(start + perPage, filteredDevices.length);
        const pageDevices = filteredDevices.slice(start, end);
        pageDevices.forEach(d => selectedUuids.add(d.uuid));
        renderTable();
        updateSelectedCount();
    }

    function selectAllFiltered() {
        filteredDevices.forEach(d => selectedUuids.add(d.uuid));
        renderTable();
        updateSelectedCount();
    }

    function deselectAll() {
        selectedUuids.clear();
        renderTable();
        updateSelectedCount();
    }

    function updateSelectedCount() {
        document.getElementById('selectedCount').textContent = selectedUuids.size + ' selected';
    }

    function updateSelectAllCheckbox() {
        const start = (currentPage - 1) * perPage;
        const end = Math.min(start + perPage, filteredDevices.length);
        const pageDevices = filteredDevices.slice(start, end);

        const allPageSelected = pageDevices.length > 0 && pageDevices.every(d => selectedUuids.has(d.uuid));
        document.getElementById('selectAllCheckbox').checked = allPageSelected;
    }

    function getMissingProfileNames(list) {
        if (!list || !list.length) return '';
        return list.map(p => p.name || p.identifier || String(p)).join('; ');
    }

    function getMissingDdmNames(list) {
        if (!list || !list.length) return '';
        return list.map(d => d.identifier || String(d)).join('; ');
    }

    function getOutdatedApps(list) {
        if (!list || !list.length) return '';
        return list.join('; ');
    }

    function exportCSV() {
        const headers = ['Hostname', 'Serial', 'OS', 'Version', 'Model', 'Product Name', 'Manifest', 'Enrollment Type', 'Supervised', 'Encrypted', 'Outdated OS', 'Outdated Apps', 'Profiles Status', 'Missing Profiles', 'DDM Status', 'Missing DDM', 'Last Check-in', 'Status'];
        const rows = filteredDevices.map(d => [
            d.hostname,
            d.serial,
            d.os,
            d.os_version,
            d.model,
            d.product_name,
            d.manifest,
            d.enrollment_type || d.dep,
            d.supervised,
            d.encrypted,
            d.outdated,
            getOutdatedApps(d.outdated_apps),
            d.profiles_installed + '/' + d.profiles_required,
            getMissingProfileNames(d.profiles_missing_list),
            d.ddm_valid + '/' + d.ddm_required,
            getMissingDdmNames(d.ddm_missing_list),
            d.last_seen,
            d.status
        ]);

        let csv = headers.join(',') + '\\n';
        rows.forEach(r => {
            csv += r.map(v => '"' + String(v || '').replace(/"/g, '""') + '"').join(',') + '\\n';
        });

        downloadCSV(csv, 'device_report');
    }

    function exportSelectedCSV() {
        if (selectedUuids.size === 0) {
            alert('No devices selected');
            return;
        }

        const headers = ['Hostname', 'Serial', 'OS', 'Version', 'Model', 'Product Name', 'Manifest', 'Enrollment Type', 'Supervised', 'Encrypted', 'Outdated OS', 'Outdated Apps', 'Profiles Status', 'Missing Profiles', 'DDM Status', 'Missing DDM', 'Last Check-in', 'Status'];
        const selected = allDevices.filter(d => selectedUuids.has(d.uuid));
        const rows = selected.map(d => [
            d.hostname,
            d.serial,
            d.os,
            d.os_version,
            d.model,
            d.product_name,
            d.manifest,
            d.enrollment_type || d.dep,
            d.supervised,
            d.encrypted,
            d.outdated,
            getOutdatedApps(d.outdated_apps),
            d.profiles_installed + '/' + d.profiles_required,
            getMissingProfileNames(d.profiles_missing_list),
            d.ddm_valid + '/' + d.ddm_required,
            getMissingDdmNames(d.ddm_missing_list),
            d.last_seen,
            d.status
        ]);

        let csv = headers.join(',') + '\\n';
        rows.forEach(r => {
            csv += r.map(v => '"' + String(v || '').replace(/"/g, '""') + '"').join(',') + '\\n';
        });

        downloadCSV(csv, 'device_report_selected');
    }

    function downloadCSV(csv, prefix) {
        const blob = new Blob([csv], {type: 'text/csv'});
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = prefix + '_' + new Date().toISOString().slice(0,10) + '.csv';
        a.click();
        URL.revokeObjectURL(url);
    }

    function refreshDeviceData() {
        if (selectedUuids.size === 0) return;

        const devices = Array.from(selectedUuids);
        const btn = event.target;
        btn.disabled = true;
        btn.textContent = 'Refreshing...';

        fetch('/admin/api/vpp-updates/refresh', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ devices: devices })
        })
        .then(r => r.json())
        .then(data => {
            btn.disabled = false;
            btn.textContent = data.success ? 'Done!' : 'Error';
            setTimeout(() => btn.textContent = 'Refresh Data', 2000);
        })
        .catch(err => {
            btn.disabled = false;
            btn.textContent = 'Error';
            setTimeout(() => btn.textContent = 'Refresh Data', 2000);
        });
    }
    </script>
</body>
</html>
'''




def generate_report_template(title, columns, data, user, csv_filename=None, filters=None):
    """Generate a standard report page with table, sorting, filtering and CSV export"""
    filters = filters or {}

    # Build filter display
    filter_html = ''
    if filters:
        filter_tags = ' '.join([f'<span class="filter-tag">{k}: {v}</span>' for k, v in filters.items()])
        filter_html = f'<div class="active-filters">Active filters: {filter_tags}</div>'

    # Build table headers
    headers_html = ''.join([
        f'<th onclick="sortTable({i})" style="cursor:pointer">{col["label"]} <span class="sort-icon">&#8597;</span></th>'
        for i, col in enumerate(columns)
    ])

    # Build table rows
    rows_html = ''
    for row in data:
        cells = ''.join([f'<td>{row.get(col["key"], "")}</td>' for col in columns])
        rows_html += f'<tr>{cells}</tr>'

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - NanoHUB Reports</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="/static/dashboard.css">
    <link rel="stylesheet" href="/static/css/qbone.css">
    <link rel="stylesheet" href="/static/css/admin.css">
    <link rel="shortcut icon" href="/static/favicon.ico">
    <style>
        /* Reports page-specific styles */
        .report-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            flex-wrap: wrap;
            gap: 15px;
        }}
        .report-controls {{
            display: flex;
            gap: 10px;
            align-items: center;
        }}
        .search-box {{
            padding: 4px 8px;
            border: 1px solid #3A3A3A;
            border-radius: 5px;
            width: 250px;
            background: #2A2A2A;
            color: #FFFFFF;
            font-size: 0.75em;
        }}
        .btn-export {{
            background: #5FC812;
            color: #0D0D0D;
            border: none;
            padding: 4px 10px;
            border-radius: 5px;
            cursor: pointer;
            font-size: 0.85em;
        }}
        .btn-export:hover {{ background: #A5F36C; }}
        .btn-back {{
            background: #2A2A2A;
            color: #FFFFFF;
            border: 1px solid #3A3A3A;
            padding: 4px 10px;
            border-radius: 5px;
            cursor: pointer;
            text-decoration: none;
            font-size: 0.85em;
        }}
        .btn-back:hover {{ background: #3A3A3A; border-color: #5FC812; }}
        .active-filters {{
            background: #1E1E1E;
            border: 1px solid #3A3A3A;
            padding: 8px 12px;
            border-radius: 5px;
            margin-bottom: 15px;
            color: #B0B0B0;
        }}
        .filter-tag {{
            background: #5FC812;
            color: #0D0D0D;
            padding: 2px 8px;
            border-radius: 15px;
            margin-left: 8px;
            font-size: 0.8em;
        }}
        .report-table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 15px;
            font-size: 0.75em;
            background-color: #1E1E1E;
        }}
        .report-table th {{
            background: #2A2A2A;
            padding: 3px 7px;
            text-align: left;
            border-bottom: 1px solid #3A3A3A;
            font-weight: 500;
            color: #FFFFFF;
            white-space: nowrap;
        }}
        .report-table td {{
            padding: 3px 7px;
            border-bottom: 1px solid #2A2A2A;
            color: #B0B0B0;
        }}
        .report-table tr:hover {{ background: #2A2A2A; }}
        .report-table tr.hidden {{ display: none; }}
        .sort-icon {{ color: #B0B0B0; font-size: 0.8em; }}
        .pagination {{
            display: flex;
            justify-content: center;
            align-items: center;
            gap: 5px;
            margin-top: 20px;
        }}
        .pagination button {{
            padding: 4px 10px;
            border: 1px solid #3A3A3A;
            background: #2A2A2A;
            color: #B0B0B0;
            cursor: pointer;
            border-radius: 4px;
            font-size: 0.85em;
        }}
        .pagination button:hover {{ background: #3A3A3A; border-color: #5FC812; color: #FFFFFF; }}
        .pagination button:disabled {{ opacity: 0.5; cursor: not-allowed; }}
        .pagination .page-info {{ margin: 0 15px; color: #B0B0B0; font-size: 0.85em; }}
        .row-count {{ color: #B0B0B0; font-size: 0.85em; }}
        /* Toggle stat styles */
        .stat-toggle {{ cursor: pointer; }}
        /* Tooltip styles - position:fixed handled by JS */
        .profiles-tooltip, .ddm-tooltip {{ cursor: help; }}
        .custom-tooltip {{
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
        }}
        .custom-tooltip div {{ padding: 1px 0; }}
    </style>
</head>
<body class="page-with-table">
    <div id="wrap">
        <div style="display: flex; justify-content: center; align-items: center;">
            <img id="logo" src="{{ current_logo }}" alt="Logo" style="max-height:60px;max-width:200px;"/>
        </div>
        <h1>{title}</h1>

        <div class="panel">
            <div class="admin-header">
                <h2>Reports</h2>
                <div class="nav-tabs" style="margin:0;">
                    <a href="/admin" class="btn">Commands</a>
                    <a href="/admin/devices" class="btn">Devices</a>
                    <a href="/admin/profiles" class="btn">Profiles</a>
                    <a href="/admin/ddm" class="btn">DDM</a>
                    <a href="/admin/vpp" class="btn">VPP</a>
                    <a href="/admin/reports" class="btn active">Reports</a>
                    <a href="/admin/history" class="btn">History</a>
                </div>
                <div>
                    <span style="color:#B0B0B0;">{{{{ user.get('display_name', user.get('username', '')) }}}}</span>
                    <span class="role-badge">{{{{ user.get('role', '') }}}}</span>
                    {{%% if user.get('role') == 'admin' %%}}<a href="/admin/settings" class="btn" style="margin-left:10px;">Settings</a>{{%% endif %%}}
                    <a href="/" class="btn" style="margin-left:10px;">Dashboard</a>
                </div>
            </div>

            {filter_html}

            <div class="report-header">
                <div class="report-controls">
                    <a href="/admin/reports" class="btn-back">&larr; Back to Reports</a>
                    <input type="text" class="search-box" id="searchBox" placeholder="Search..." onkeyup="filterTable()">
                    <span class="row-count" id="rowCount">{len(data)} rows</span>
                </div>
                <button class="btn-export" onclick="exportCSV()">Export CSV</button>
            </div>

            <div class="table-wrapper">
                <table class="report-table" id="reportTable">
                    <thead>
                        <tr>{headers_html}</tr>
                    </thead>
                    <tbody>
                        {rows_html}
                    </tbody>
                </table>
            </div>

            <div class="pagination" id="pagination"></div>
        </div>
    </div>

    <script>
    const ROWS_PER_PAGE = 50;
    let currentPage = 1;
    let sortCol = -1;
    let sortAsc = true;
    const allRows = Array.from(document.querySelectorAll('#reportTable tbody tr'));

    function getVisibleRows() {{
        return allRows.filter(row => !row.dataset.filtered);
    }}

    function filterTable() {{
        const search = document.getElementById('searchBox').value.toLowerCase();

        allRows.forEach(row => {{
            const text = row.textContent.toLowerCase();
            row.dataset.filtered = !text.includes(search);
        }});

        currentPage = 1;
        showPage(1);
        document.getElementById('rowCount').textContent = getVisibleRows().length + ' rows';
    }}

    function sortTable(colIndex) {{
        if (sortCol === colIndex) {{
            sortAsc = !sortAsc;
        }} else {{
            sortCol = colIndex;
            sortAsc = true;
        }}

        allRows.sort((a, b) => {{
            const aVal = a.cells[colIndex].textContent.trim();
            const bVal = b.cells[colIndex].textContent.trim();

            const aNum = parseFloat(aVal);
            const bNum = parseFloat(bVal);

            if (!isNaN(aNum) && !isNaN(bNum)) {{
                return sortAsc ? aNum - bNum : bNum - aNum;
            }}
            return sortAsc ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
        }});

        const tbody = document.querySelector('#reportTable tbody');
        allRows.forEach(row => tbody.appendChild(row));

        showPage(currentPage);
    }}

    function updatePagination() {{
        const visibleRows = getVisibleRows();
        const totalPages = Math.ceil(visibleRows.length / ROWS_PER_PAGE) || 1;
        const pagination = document.getElementById('pagination');

        let html = '<button onclick="showPage(1)" ' + (currentPage === 1 ? 'disabled' : '') + '>&laquo;</button>';
        html += '<button onclick="showPage(' + (currentPage - 1) + ')" ' + (currentPage === 1 ? 'disabled' : '') + '>&lsaquo;</button>';

        html += '<button onclick="showPage(' + (currentPage + 1) + ')" ' + (currentPage === totalPages ? 'disabled' : '') + '>&rsaquo;</button>';
        html += '<button onclick="showPage(' + totalPages + ')" ' + (currentPage === totalPages ? 'disabled' : '') + '>&raquo;</button>';
        html += '<span class="page-info">Page ' + currentPage + ' of ' + totalPages + '</span>';

        pagination.innerHTML = html;
    }}

    function showPage(page) {{
        const visibleRows = getVisibleRows();
        const totalPages = Math.ceil(visibleRows.length / ROWS_PER_PAGE) || 1;

        currentPage = Math.max(1, Math.min(page, totalPages));

        const start = (currentPage - 1) * ROWS_PER_PAGE;
        const end = start + ROWS_PER_PAGE;

        allRows.forEach(row => row.classList.add('hidden'));
        visibleRows.slice(start, end).forEach(row => row.classList.remove('hidden'));

        updatePagination();
    }}

    function exportCSV() {{
        const visibleRows = getVisibleRows();
        const headers = Array.from(document.querySelectorAll('#reportTable thead th')).map(th => th.textContent.trim());

        let csv = [headers.map(h => '"' + h.replace(/"/g, '""') + '"').join(',')];

        visibleRows.forEach(row => {{
            const cells = Array.from(row.cells).map(cell => '"' + cell.textContent.replace(/"/g, '""') + '"');
            csv.push(cells.join(','));
        }});

        const blob = new Blob([csv.join('\\n')], {{ type: 'text/csv' }});
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = '{csv_filename or "report"}.csv';
        a.click();
        window.URL.revokeObjectURL(url);
    }}

    // Initialize
    showPage(1);
    </script>
</body>
</html>'''

    return render_template_string(html, user=user)


# -----------------------------------------------------------------------------
# DEVICE INVENTORY REPORTS
# -----------------------------------------------------------------------------

@reports_bp.route('/reports/devices/all')
@login_required_admin
def report_devices_all():
    """All devices report"""
    user = session.get('user', {})
    manifest_filter = user.get('manifest_filter')

    os_filter = request.args.get('os', '')
    manifest_param = request.args.get('manifest', '')
    if manifest_param:
        manifest_filter = manifest_param

    active_filters = {}
    if os_filter:
        active_filters['OS'] = os_filter.upper()
    if manifest_filter:
        active_filters['Manifest'] = manifest_filter

    data = []
    try:
        device_list = devices.get_all(manifest_filter)
        for d in device_list:
            if os_filter and d.get('os', '').lower() != os_filter.lower():
                continue

            last_seen = d.get('last_seen')
            if last_seen:
                last_seen = last_seen.strftime('%Y-%m-%d %H:%M') if hasattr(last_seen, 'strftime') else str(last_seen)
            data.append({
                'hostname': d.get('hostname', ''),
                'serial': d.get('serial', ''),
                'os': d.get('os', '').upper(),
                'manifest': d.get('manifest', ''),
                'account': d.get('account', ''),
                'status': d.get('status', ''),
                'last_seen': last_seen or 'Never'
            })
    except Exception as e:
        logger.error(f"Report devices/all error: {e}")

    columns = [
        {'key': 'hostname', 'label': 'Hostname'},
        {'key': 'serial', 'label': 'Serial'},
        {'key': 'os', 'label': 'OS'},
        {'key': 'manifest', 'label': 'Manifest'},
        {'key': 'account', 'label': 'Account'},
        {'key': 'status', 'label': 'Status'},
        {'key': 'last_seen', 'label': 'Last Seen'}
    ]

    return generate_report_template('All Devices', columns, data, user, 'all_devices', active_filters)


@reports_bp.route('/reports/devices/by-os')
@login_required_admin
def report_devices_by_os():
    """Devices grouped by OS version"""
    user = session.get('user', {})

    os_filter = request.args.get('os', '')
    active_filters = {}
    if os_filter:
        active_filters['OS'] = os_filter.upper()

    data = []
    try:
        where_clause = ""
        params = []
        if os_filter:
            where_clause = "WHERE di.os = %s"
            params = [os_filter.lower()]

        rows = db.query_all(f"""
            SELECT di.hostname, di.serial, di.os, dd.hardware_data
            FROM device_inventory di
            LEFT JOIN device_details dd ON di.uuid = dd.uuid
            {where_clause}
            ORDER BY di.os, di.hostname
        """, params if params else None)

        for row in rows:
            os_version = 'Unknown'
            product_name = ''

            if row.get('hardware_data'):
                hw = row['hardware_data']
                if isinstance(hw, str):
                    try:
                        hw = json.loads(hw)
                    except:
                        hw = {}

                os_version = hw.get('OSVersion', hw.get('os_version', 'Unknown'))
                product_name = hw.get('ProductName', hw.get('product_name', ''))

            data.append({
                'hostname': row.get('hostname', ''),
                'serial': row.get('serial', ''),
                'os_type': row.get('os', '').upper(),
                'os_version': os_version,
                'model': product_name
            })

    except Exception as e:
        logger.error(f"Report devices/by-os error: {e}")

    columns = [
        {'key': 'hostname', 'label': 'Hostname'},
        {'key': 'serial', 'label': 'Serial'},
        {'key': 'os_type', 'label': 'OS Type'},
        {'key': 'os_version', 'label': 'OS Version'},
        {'key': 'model', 'label': 'Model'}
    ]

    return generate_report_template('Devices by OS Version', columns, data, user, 'devices_by_os', active_filters)


@reports_bp.route('/reports/devices/by-model')
@login_required_admin
def report_devices_by_model():
    """Devices grouped by model"""
    user = session.get('user', {})

    os_filter = request.args.get('os', '')
    active_filters = {}
    if os_filter:
        active_filters['OS'] = os_filter.upper()

    data = []
    try:
        where_clause = ""
        params = []
        if os_filter:
            where_clause = "WHERE di.os = %s"
            params = [os_filter.lower()]

        rows = db.query_all(f"""
            SELECT di.hostname, di.serial, di.os, dd.hardware_data
            FROM device_inventory di
            LEFT JOIN device_details dd ON di.uuid = dd.uuid
            {where_clause}
            ORDER BY di.hostname
        """, params if params else None)

        for row in rows:
            product_name = 'Unknown'
            model_number = ''

            if row.get('hardware_data'):
                hw = row['hardware_data']
                if isinstance(hw, str):
                    try:
                        hw = json.loads(hw)
                    except:
                        hw = {}

                product_name = hw.get('ProductName', hw.get('product_name', 'Unknown'))
                model_number = hw.get('ModelNumber', hw.get('model_number', ''))

            data.append({
                'hostname': row.get('hostname', ''),
                'serial': row.get('serial', ''),
                'os': row.get('os', '').upper(),
                'model': product_name,
                'model_number': model_number
            })

    except Exception as e:
        logger.error(f"Report devices/by-model error: {e}")

    columns = [
        {'key': 'hostname', 'label': 'Hostname'},
        {'key': 'serial', 'label': 'Serial'},
        {'key': 'os', 'label': 'OS'},
        {'key': 'model', 'label': 'Model Name'},
        {'key': 'model_number', 'label': 'Model Number'}
    ]

    return generate_report_template('Devices by Model', columns, data, user, 'devices_by_model', active_filters)


@reports_bp.route('/reports/devices/storage')
@login_required_admin
def report_devices_storage():
    """Storage capacity report"""
    user = session.get('user', {})

    os_filter = request.args.get('os', '')
    active_filters = {}
    if os_filter:
        active_filters['OS'] = os_filter.upper()

    data = []
    try:
        where_clause = ""
        params = []
        if os_filter:
            where_clause = "WHERE di.os = %s"
            params = [os_filter.lower()]

        rows = db.query_all(f"""
            SELECT di.uuid, di.hostname, di.serial, di.os, dd.hardware_data
            FROM device_inventory di
            LEFT JOIN device_details dd ON di.uuid = dd.uuid
            {where_clause}
            ORDER BY di.hostname
        """, params if params else None)

        for row in rows:
            total_storage = 'Unknown'
            available_storage = 'Unknown'
            percent_used = ''

            if row.get('hardware_data'):
                hw = row['hardware_data']
                if isinstance(hw, str):
                    try:
                        hw = json.loads(hw)
                    except:
                        hw = {}

                capacity = hw.get('DeviceCapacity', hw.get('device_capacity'))
                available = hw.get('AvailableDeviceCapacity', hw.get('available_device_capacity'))

                if capacity is not None:
                    # Handle string values like "128.0 GB"
                    if isinstance(capacity, str):
                        capacity = float(capacity.replace(' GB', '').replace(',', '.'))
                    total_storage = f"{float(capacity):.1f} GB"
                    if available is not None:
                        if isinstance(available, str):
                            available = float(available.replace(' GB', '').replace(',', '.'))
                        available_storage = f"{float(available):.1f} GB"
                        used = float(capacity) - float(available)
                        percent_used = f"{(used / float(capacity) * 100):.0f}%"

            data.append({
                'hostname': row.get('hostname', ''),
                'serial': row.get('serial', ''),
                'os': row.get('os', '').upper(),
                'total': total_storage,
                'available': available_storage,
                'used_percent': percent_used
            })

    except Exception as e:
        logger.error(f"Report devices/storage error: {e}")

    columns = [
        {'key': 'hostname', 'label': 'Hostname'},
        {'key': 'serial', 'label': 'Serial'},
        {'key': 'os', 'label': 'OS'},
        {'key': 'total', 'label': 'Total Storage'},
        {'key': 'available', 'label': 'Available'},
        {'key': 'used_percent', 'label': '% Used'}
    ]

    return generate_report_template('Storage Capacity Report', columns, data, user, 'storage_report', active_filters)


# -----------------------------------------------------------------------------
# COMPLIANCE & SECURITY REPORTS
# -----------------------------------------------------------------------------

@reports_bp.route('/reports/compliance/encryption')
@login_required_admin
def report_compliance_encryption():
    """FileVault / Encryption status report"""
    user = session.get('user', {})

    os_filter = request.args.get('os', '')
    status_filter = request.args.get('filter', '')
    active_filters = {}
    if os_filter:
        active_filters['OS'] = os_filter.upper()
    if status_filter:
        active_filters['Status'] = status_filter.capitalize()

    data = []
    try:
        where_clause = ""
        params = []
        if os_filter:
            where_clause = "WHERE di.os = %s"
            params = [os_filter.lower()]

        rows = db.query_all(f"""
            SELECT di.uuid, di.hostname, di.serial, di.os, dd.security_data
            FROM device_inventory di
            LEFT JOIN device_details dd ON di.uuid = dd.uuid
            {where_clause}
            ORDER BY di.hostname
        """, params if params else None)

        for row in rows:
            encryption_status = 'Unknown'
            filevault_prk = 'N/A'

            if row.get('security_data'):
                sec = row['security_data']
                if isinstance(sec, str):
                    try:
                        sec = json.loads(sec)
                    except:
                        sec = {}

                fv_enabled = sec.get('filevault_enabled', sec.get('FDE_Enabled', sec.get('IsEncrypted', False)))
                if fv_enabled is True or fv_enabled == 'true' or fv_enabled == 'Yes':
                    encryption_status = 'Enabled'
                elif fv_enabled is False or fv_enabled == 'false' or fv_enabled == 'No':
                    encryption_status = 'Disabled'
                elif fv_enabled:
                    encryption_status = str(fv_enabled)

                if sec.get('filevault_has_prk', sec.get('FDE_HasPersonalRecoveryKey', False)):
                    filevault_prk = 'Yes'
                elif encryption_status == 'Enabled':
                    filevault_prk = 'No'

            if status_filter:
                if status_filter.lower() == 'enabled' and encryption_status != 'Enabled':
                    continue
                elif status_filter.lower() == 'disabled' and encryption_status != 'Disabled':
                    continue

            data.append({
                'hostname': row.get('hostname', ''),
                'serial': row.get('serial', ''),
                'os': row.get('os', '').upper(),
                'encryption': encryption_status,
                'prk': filevault_prk
            })

    except Exception as e:
        logger.error(f"Report compliance/encryption error: {e}")

    columns = [
        {'key': 'hostname', 'label': 'Hostname'},
        {'key': 'serial', 'label': 'Serial'},
        {'key': 'os', 'label': 'OS'},
        {'key': 'encryption', 'label': 'Encryption Status'},
        {'key': 'prk', 'label': 'Recovery Key'}
    ]

    return generate_report_template('FileVault / Encryption Status', columns, data, user, 'encryption_status', active_filters)


@reports_bp.route('/reports/compliance/passcode')
@login_required_admin
def report_compliance_passcode():
    """Passcode compliance report"""
    user = session.get('user', {})

    os_filter = request.args.get('os', '')
    status_filter = request.args.get('filter', '')
    active_filters = {}
    if os_filter:
        active_filters['OS'] = os_filter.upper()
    if status_filter:
        active_filters['Status'] = status_filter.capitalize()

    data = []
    try:
        where_clause = ""
        params = []
        if os_filter:
            where_clause = "WHERE di.os = %s"
            params = [os_filter.lower()]

        rows = db.query_all(f"""
            SELECT di.uuid, di.hostname, di.serial, di.os, dd.security_data
            FROM device_inventory di
            LEFT JOIN device_details dd ON di.uuid = dd.uuid
            {where_clause}
            ORDER BY di.hostname
        """, params if params else None)

        for row in rows:
            passcode_present = 'Unknown'
            passcode_compliant = 'Unknown'

            if row.get('security_data'):
                sec = row['security_data']
                if isinstance(sec, str):
                    try:
                        sec = json.loads(sec)
                    except:
                        sec = {}

                has_passcode = sec.get('PasscodePresent', sec.get('HasPasscode'))
                if has_passcode is True or has_passcode == 'true':
                    passcode_present = 'Yes'
                elif has_passcode is False or has_passcode == 'false':
                    passcode_present = 'No'

                is_compliant = sec.get('PasscodeCompliant', sec.get('IsPasscodeCompliant'))
                if is_compliant is True or is_compliant == 'true':
                    passcode_compliant = 'Yes'
                elif is_compliant is False or is_compliant == 'false':
                    passcode_compliant = 'No'

            if status_filter:
                if status_filter.lower() == 'compliant' and passcode_compliant != 'Yes':
                    continue
                elif status_filter.lower() == 'non-compliant' and passcode_compliant == 'Yes':
                    continue

            data.append({
                'hostname': row.get('hostname', ''),
                'serial': row.get('serial', ''),
                'os': row.get('os', '').upper(),
                'passcode': passcode_present,
                'compliant': passcode_compliant
            })

    except Exception as e:
        logger.error(f"Report compliance/passcode error: {e}")

    columns = [
        {'key': 'hostname', 'label': 'Hostname'},
        {'key': 'serial', 'label': 'Serial'},
        {'key': 'os', 'label': 'OS'},
        {'key': 'passcode', 'label': 'Passcode Set'},
        {'key': 'compliant', 'label': 'Compliant'}
    ]

    return generate_report_template('Passcode Compliance', columns, data, user, 'passcode_compliance', active_filters)


@reports_bp.route('/reports/compliance/os-update')
@login_required_admin
def report_compliance_os_update():
    """OS Version status report - shows which devices need updates"""
    user = session.get('user', {})

    os_filter = request.args.get('os', '')
    status_filter = request.args.get('filter', '')
    active_filters = {}
    if os_filter:
        active_filters['OS'] = os_filter.upper()
    if status_filter:
        active_filters['Status'] = status_filter.capitalize()

    data = []
    try:
        where_clause = ""
        params = []
        if os_filter:
            where_clause = "WHERE di.os = %s"
            params = [os_filter.lower()]

        # First get ALL rows to find max versions
        all_rows = db.query_all("""
            SELECT di.uuid, di.hostname, di.serial, di.os, dd.hardware_data
            FROM device_inventory di
            LEFT JOIN device_details dd ON di.uuid = dd.uuid
            ORDER BY di.os, di.hostname
        """)

        # Find max version per OS type from DB
        max_versions = {'macos': [], 'ios': [], 'ipados': []}
        for row in all_rows or []:
            if row.get('hardware_data'):
                hw = row['hardware_data']
                if isinstance(hw, str):
                    try: hw = json.loads(hw)
                    except: hw = {}
                os_ver = hw.get('os_version', hw.get('OSVersion', ''))
                os_type = (row.get('os') or '').lower()
                if os_ver and os_type in max_versions:
                    try:
                        ver_tuple = tuple(int(x) for x in str(os_ver).split('.')[:3])
                        max_versions[os_type].append(ver_tuple)
                    except:
                        pass

        latest_versions = {}
        for os_type, versions in max_versions.items():
            if versions:
                latest_versions[os_type] = max(versions)

        # Now process rows (with optional filter)
        rows = all_rows
        if os_filter:
            rows = [r for r in all_rows if (r.get('os') or '').lower() == os_filter.lower()]

        for row in rows:
            os_version = 'Unknown'
            build_version = ''
            needs_update = 'Unknown'

            if row.get('hardware_data'):
                hw = row['hardware_data']
                if isinstance(hw, str):
                    try: hw = json.loads(hw)
                    except: hw = {}

                os_version = hw.get('os_version', hw.get('OSVersion', 'Unknown'))
                build_version = hw.get('build_version', hw.get('BuildVersion', ''))

                os_type = (row.get('os') or '').lower()
                if os_version != 'Unknown' and os_type in latest_versions:
                    try:
                        current = tuple(int(x) for x in str(os_version).split('.')[:3])
                        if current < latest_versions[os_type]:
                            needs_update = 'Yes'
                        else:
                            needs_update = 'No'
                    except:
                        needs_update = 'Unknown'

            if status_filter:
                if status_filter.lower() == 'outdated' and needs_update != 'Yes':
                    continue
                elif status_filter.lower() == 'current' and needs_update != 'No':
                    continue

            data.append({
                'hostname': row.get('hostname', ''),
                'serial': row.get('serial', ''),
                'os': row.get('os', '').upper(),
                'os_version': os_version,
                'build': build_version,
                'needs_update': needs_update
            })

    except Exception as e:
        logger.error(f"Report compliance/os-update error: {e}")

    columns = [
        {'key': 'hostname', 'label': 'Hostname'},
        {'key': 'serial', 'label': 'Serial'},
        {'key': 'os', 'label': 'OS Type'},
        {'key': 'os_version', 'label': 'OS Version'},
        {'key': 'build', 'label': 'Build'},
        {'key': 'needs_update', 'label': 'Needs Update'}
    ]

    return generate_report_template('OS Update Status', columns, data, user, 'os_update_status', active_filters)


@reports_bp.route('/reports/compliance/supervised')
@login_required_admin
def report_compliance_supervised():
    """Supervised status report"""
    user = session.get('user', {})

    os_filter = request.args.get('os', '')
    active_filters = {}
    if os_filter:
        active_filters['OS'] = os_filter.upper()

    data = []
    try:
        where_clause = ""
        params = []
        if os_filter:
            where_clause = "WHERE di.os = %s"
            params = [os_filter.lower()]

        rows = db.query_all(f"""
            SELECT di.uuid, di.hostname, di.serial, di.os, dd.hardware_data, dd.security_data
            FROM device_inventory di
            LEFT JOIN device_details dd ON di.uuid = dd.uuid
            {where_clause}
            ORDER BY di.hostname
        """, params if params else None)

        for row in rows:
            supervised = 'Unknown'
            dep_enrolled = 'Unknown'

            if row.get('hardware_data'):
                hw = row['hardware_data']
                if isinstance(hw, str):
                    try:
                        hw = json.loads(hw)
                    except:
                        hw = {}

                is_supervised = hw.get('is_supervised', hw.get('IsSupervised', False))
                if is_supervised is True or is_supervised == 'true':
                    supervised = 'Yes'
                elif is_supervised is False or is_supervised == 'false':
                    supervised = 'No'

            if row.get('security_data'):
                sec = row['security_data']
                if isinstance(sec, str):
                    try:
                        sec = json.loads(sec)
                    except:
                        sec = {}

                is_dep = sec.get('enrolled_via_dep', sec.get('IsDeviceEnrollmentProgram', sec.get('DEPEnrolled')))
                if is_dep is True or is_dep == 'true':
                    dep_enrolled = 'Yes'
                elif is_dep is False or is_dep == 'false':
                    dep_enrolled = 'No'

            data.append({
                'hostname': row.get('hostname', ''),
                'serial': row.get('serial', ''),
                'os': row.get('os', '').upper(),
                'supervised': supervised,
                'dep': dep_enrolled
            })

    except Exception as e:
        logger.error(f"Report compliance/supervised error: {e}")

    columns = [
        {'key': 'hostname', 'label': 'Hostname'},
        {'key': 'serial', 'label': 'Serial'},
        {'key': 'os', 'label': 'OS'},
        {'key': 'supervised', 'label': 'Supervised'},
        {'key': 'dep', 'label': 'DEP Enrolled'}
    ]

    return generate_report_template('Supervised Status', columns, data, user, 'supervised_status', active_filters)


# -----------------------------------------------------------------------------
# APPLICATION REPORTS
# -----------------------------------------------------------------------------

@reports_bp.route('/reports/apps/vpp-coverage')
@login_required_admin
def report_apps_vpp_coverage():
    """VPP License coverage report"""
    user = session.get('user', {})
    active_filters = {}

    data = []
    try:
        rows = db.query_all("""
            SELECT app_name, adam_id, pricing_param, total_licenses, used_licenses,
                CASE WHEN total_licenses > 0
                    THEN ROUND((used_licenses / total_licenses) * 100, 1)
                    ELSE 0
                END as usage_percent
            FROM vpp_licenses
            ORDER BY app_name
        """)

        for row in rows:
            available = row.get('total_licenses', 0) - row.get('used_licenses', 0)
            data.append({
                'app_name': row.get('app_name', ''),
                'adam_id': row.get('adam_id', ''),
                'total': row.get('total_licenses', 0),
                'used': row.get('used_licenses', 0),
                'available': available,
                'usage': f"{row.get('usage_percent', 0)}%"
            })

    except Exception as e:
        logger.error(f"Report apps/vpp-coverage error: {e}")

    columns = [
        {'key': 'app_name', 'label': 'Application'},
        {'key': 'adam_id', 'label': 'Adam ID'},
        {'key': 'total', 'label': 'Total Licenses'},
        {'key': 'used', 'label': 'Used'},
        {'key': 'available', 'label': 'Available'},
        {'key': 'usage', 'label': 'Usage %'}
    ]

    return generate_report_template('VPP License Coverage', columns, data, user, 'vpp_coverage', active_filters)


@reports_bp.route('/reports/apps/installed')
@login_required_admin
def report_apps_installed():
    """Installed applications report"""
    user = session.get('user', {})

    os_filter = request.args.get('os', '')
    active_filters = {}
    if os_filter:
        active_filters['OS'] = os_filter.upper()

    data = []
    try:
        where_clause = "WHERE dd.apps_data IS NOT NULL"
        params = []
        if os_filter:
            where_clause += " AND di.os = %s"
            params = [os_filter.lower()]

        rows = db.query_all(f"""
            SELECT di.hostname, di.serial, di.os, dd.apps_data
            FROM device_inventory di
            LEFT JOIN device_details dd ON di.uuid = dd.uuid
            {where_clause}
            ORDER BY di.hostname
        """, params if params else None)

        for row in rows:
            apps_data = row.get('apps_data')
            if apps_data:
                if isinstance(apps_data, str):
                    try:
                        apps_data = json.loads(apps_data)
                    except:
                        apps_data = []

                if isinstance(apps_data, list):
                    app_count = len(apps_data)
                    top_apps = ', '.join([a.get('Name', a.get('name', ''))[:20] for a in apps_data[:3]])
                    if app_count > 3:
                        top_apps += f' (+{app_count - 3} more)'
                else:
                    app_count = 0
                    top_apps = ''

                data.append({
                    'hostname': row.get('hostname', ''),
                    'serial': row.get('serial', ''),
                    'os': row.get('os', '').upper(),
                    'app_count': app_count,
                    'apps': top_apps
                })

    except Exception as e:
        logger.error(f"Report apps/installed error: {e}")

    columns = [
        {'key': 'hostname', 'label': 'Hostname'},
        {'key': 'serial', 'label': 'Serial'},
        {'key': 'os', 'label': 'OS'},
        {'key': 'app_count', 'label': 'App Count'},
        {'key': 'apps', 'label': 'Applications'}
    ]

    return generate_report_template('Installed Applications', columns, data, user, 'installed_apps', active_filters)


# -----------------------------------------------------------------------------
# ACTIVITY REPORTS
# -----------------------------------------------------------------------------

@reports_bp.route('/reports/activity/check-in')
@login_required_admin
def report_activity_checkin():
    """Last check-in report - shows devices by last communication time"""
    user = session.get('user', {})

    os_filter = request.args.get('os', '')
    days_filter = request.args.get('days', '')
    active_filters = {}
    if os_filter:
        active_filters['OS'] = os_filter.upper()
    if days_filter:
        active_filters['Period'] = f'Last {days_filter} days'

    data = []
    try:
        where_clauses = []
        params = []
        if os_filter:
            where_clauses.append("di.os = %s")
            params.append(os_filter.lower())

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        rows = db.query_all(f"""
            SELECT di.uuid, di.hostname, di.serial, di.os,
                e.max_last_seen,
                CASE
                    WHEN e.max_last_seen IS NULL THEN 'Never'
                    WHEN TIMESTAMPDIFF(MINUTE, e.max_last_seen, NOW()) <= 15 THEN 'Online'
                    WHEN TIMESTAMPDIFF(MINUTE, e.max_last_seen, NOW()) <= 60 THEN 'Active'
                    WHEN TIMESTAMPDIFF(HOUR, e.max_last_seen, NOW()) <= 24 THEN 'Today'
                    WHEN TIMESTAMPDIFF(DAY, e.max_last_seen, NOW()) <= 7 THEN 'This Week'
                    WHEN TIMESTAMPDIFF(DAY, e.max_last_seen, NOW()) <= 30 THEN 'This Month'
                    ELSE 'Stale'
                END as status,
                TIMESTAMPDIFF(HOUR, e.max_last_seen, NOW()) as hours_ago
            FROM device_inventory di
            LEFT JOIN (
                SELECT device_id, MAX(last_seen_at) as max_last_seen
                FROM enrollments
                GROUP BY device_id
            ) e ON di.uuid = e.device_id
            {where_sql}
            ORDER BY e.max_last_seen DESC
        """, params if params else None)

        for row in rows:
            last_seen = row.get('max_last_seen')
            if last_seen:
                last_seen_str = last_seen.strftime('%Y-%m-%d %H:%M') if hasattr(last_seen, 'strftime') else str(last_seen)
            else:
                last_seen_str = 'Never'

            hours = row.get('hours_ago')
            if hours is not None:
                if hours < 1:
                    time_ago = 'Just now'
                elif hours < 24:
                    time_ago = f'{hours}h ago'
                else:
                    days_ago = hours // 24
                    time_ago = f'{days_ago}d ago'
            else:
                time_ago = 'Never'

            if days_filter:
                try:
                    max_days = int(days_filter)
                    if hours is not None and hours > max_days * 24:
                        continue
                except ValueError:
                    pass

            data.append({
                'hostname': row.get('hostname', ''),
                'serial': row.get('serial', ''),
                'os': row.get('os', '').upper(),
                'last_seen': last_seen_str,
                'time_ago': time_ago,
                'status': row.get('status', 'Unknown')
            })

    except Exception as e:
        logger.error(f"Report activity/check-in error: {e}")

    columns = [
        {'key': 'hostname', 'label': 'Hostname'},
        {'key': 'serial', 'label': 'Serial'},
        {'key': 'os', 'label': 'OS'},
        {'key': 'last_seen', 'label': 'Last Check-in'},
        {'key': 'time_ago', 'label': 'Time Ago'},
        {'key': 'status', 'label': 'Status'}
    ]

    return generate_report_template('Last Check-in Report', columns, data, user, 'last_checkin', active_filters)


@reports_bp.route('/reports/activity/failed-commands')
@login_required_admin
def report_activity_failed_commands():
    """Failed commands report - shows commands that failed"""
    user = session.get('user', {})

    days_filter = request.args.get('days', '30')
    active_filters = {}
    if days_filter:
        active_filters['Period'] = f'Last {days_filter} days'

    data = []
    try:
        try:
            days_val = int(days_filter) if days_filter else 30
        except ValueError:
            days_val = 30

        rows = db.query_all(f"""
            SELECT ch.timestamp, ch.command, ch.device_hostname, ch.device_serial,
                ch.status, ch.user, ch.result
            FROM command_history ch
            WHERE ch.status = 'error'
              AND ch.timestamp >= DATE_SUB(NOW(), INTERVAL {days_val} DAY)
            ORDER BY ch.timestamp DESC
            LIMIT 200
        """)

        for row in rows:
            timestamp = row.get('timestamp')
            if timestamp:
                ts_str = timestamp.strftime('%Y-%m-%d %H:%M') if hasattr(timestamp, 'strftime') else str(timestamp)
            else:
                ts_str = ''

            result = row.get('result', '') or ''
            if len(result) > 80:
                result = result[:77] + '...'

            data.append({
                'timestamp': ts_str,
                'command': row.get('command', ''),
                'hostname': row.get('device_hostname', ''),
                'serial': row.get('device_serial', ''),
                'user': row.get('user', ''),
                'error': result
            })

    except Exception as e:
        logger.error(f"Report activity/failed-commands error: {e}")

    columns = [
        {'key': 'timestamp', 'label': 'Time'},
        {'key': 'command', 'label': 'Command'},
        {'key': 'hostname', 'label': 'Hostname'},
        {'key': 'serial', 'label': 'Serial'},
        {'key': 'user', 'label': 'User'},
        {'key': 'error', 'label': 'Error'}
    ]

    title = f'Failed Commands (Last {days_val} Days)' if days_val != 30 else 'Failed Commands (Last 30 Days)'
    return generate_report_template(title, columns, data, user, 'failed_commands', active_filters)
