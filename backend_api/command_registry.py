"""
NanoHUB Command Registry
Metadata for all MDM commands available in admin panel
Configuration loaded from /opt/nanohub/web_environment.sh
"""

# Import configuration loader
from web_config import (
    get_branch_options, get_platform_options, get_manifest_options,
    get_account_options, get_dep_options, get_os_update_action_options,
    get_priority_options, get_yes_no_options, get_os_filter_options,
    get_path
)

# Command categories
CATEGORIES = {
    'setup': {'name': 'Device Setup', 'icon': 'zap', 'order': 1},
    'profiles': {'name': 'Profiles', 'icon': 'file-text', 'order': 2},
    'ddm': {'name': 'DDM', 'icon': 'layers', 'order': 3},
    'apps': {'name': 'Applications', 'icon': 'package', 'order': 4},
    'device_control': {'name': 'Device Control', 'icon': 'smartphone', 'order': 5},
    'os_updates': {'name': 'OS Updates', 'icon': 'download', 'order': 6},
    'remote_desktop': {'name': 'Remote Desktop', 'icon': 'monitor', 'order': 7},
    'security': {'name': 'Security', 'icon': 'shield', 'order': 8},
    'diagnostics': {'name': 'Diagnostics', 'icon': 'activity', 'order': 9},
    'vpp': {'name': 'VPP Apps', 'icon': 'shopping-bag', 'order': 10},
    'other': {'name': 'Other', 'icon': 'settings', 'order': 11},
}

# Profile directories (loaded from config)
PROFILE_DIRS = {
    'standard': get_path('PROFILES_DIR') or '/opt/nanohub/profiles/',
    'wireguard': get_path('WIREGUARD_DIR') or '/opt/nanohub/profiles/wireguard_configs/',
}

# Commands directory (loaded from config)
COMMANDS_DIR = get_path('COMMANDS_DIR') or '/opt/nanohub/tools/api/commands'

# All available commands with metadata
COMMANDS = {
    # =========================================================================
    # DEVICE SETUP
    # =========================================================================
    'bulk_new_device_installation': {
        'name': 'New Device Installation',
        'category': 'setup',
        'description': 'Automated installation workflow - profiles and apps from DB based on manifest',
        'script': '_internal_bulk_install',
        'parameters': [
            {'name': 'manifest', 'label': 'Manifest', 'type': 'select', 'required': True,
             'options': '_DYNAMIC_MANIFESTS'},
            {'name': 'udid', 'label': 'Device', 'type': 'device', 'required': True},
            # Wildcard profile options
            {'name': 'account_type', 'label': 'Account Profile', 'type': 'select', 'required': False,
             'options': [
                 {'value': 'disabled', 'label': 'Account Disabled (default)'},
                 {'value': 'enabled', 'label': 'Account Enabled'},
                 {'value': 'skip', 'label': 'Skip - Do not install'},
             ]},
            {'name': 'restrictions_type', 'label': 'Restrictions Profile (macOS)', 'type': 'select', 'required': False,
             'options': [
                 {'value': 'standard', 'label': 'Standard (default)'},
                 {'value': 'icloud', 'label': 'iCloudSync'},
                 {'value': 'levelc', 'label': 'LevelC'},
                 {'value': 'skip', 'label': 'Skip - Do not install'},
             ]},
            # Optional profiles
            {'name': 'applications', 'label': 'Applications to Install', 'type': 'select_multiple', 'required': False,
             'options': '_DYNAMIC_APPLICATIONS'},
            {'name': 'install_wifi', 'label': 'Install WiFi Profile', 'type': 'select', 'required': False,
             'options': [
                 {'value': 'no', 'label': 'No - Skip WiFi'},
                 {'value': 'yes', 'label': 'Yes - Install WiFi'},
             ]},
            {'name': 'install_filevault', 'label': 'Install FileVault (macOS)', 'type': 'select', 'required': False,
             'options': [
                 {'value': 'no', 'label': 'No - Skip FileVault'},
                 {'value': 'yes', 'label': 'Yes - Client must be logged in'},
             ]},
            {'name': 'install_directory_services', 'label': 'Join Active Directory (macOS)', 'type': 'select', 'required': False,
             'options': [
                 {'value': 'no', 'label': 'No - Skip AD join'},
                 {'value': 'yes', 'label': 'Yes - Join AD (requires hostname)'},
             ]},
            {'name': 'hostname', 'label': 'Hostname (for AD)', 'type': 'string', 'required': False,
             'placeholder': 'e.g. device08'},
            {'name': 'install_wireguard', 'label': 'Install WireGuard Profile', 'type': 'select', 'required': False,
             'options': [
                 {'value': 'no', 'label': 'No - Skip WireGuard'},
                 {'value': 'yes', 'label': 'Yes - Search by username'},
             ]},
            {'name': 'wireguard_username', 'label': 'WireGuard Username', 'type': 'string', 'required': False,
             'placeholder': 'e.g. j.smith or smith'},
        ],
        'dangerous': False,
        'min_role': 'operator',
        'bulk_supported': False,
        'info_text': 'Installs all required profiles and applications for new device based on selected manifest. Profiles and apps are loaded from database (required_profiles, required_applications tables). Optional: WiFi, FileVault, Directory Services, WireGuard.',
    },

    # =========================================================================
    # PROFILES (Consolidated)
    # =========================================================================
    'manage_profiles': {
        'name': 'Manage Profiles',
        'category': 'profiles',
        'description': 'Install, remove or list profiles on one or more devices',
        'script': '_internal_manage_profiles',
        'parameters': [
            {'name': 'action', 'label': 'Action', 'type': 'select', 'required': True,
             'options': [
                 {'value': 'install', 'label': 'Install Profile'},
                 {'value': 'remove', 'label': 'Remove Profile'},
                 {'value': 'list', 'label': 'List Installed Profiles'},
             ]},
            {'name': 'devices', 'label': 'Devices', 'type': 'devices', 'required': True},
            {'name': 'profile', 'label': 'Profile (for Install)', 'type': 'profile', 'required': False,
             'help': 'Required for Install action'},
            {'name': 'identifier', 'label': 'Profile Identifier (for Remove)', 'type': 'string', 'required': False,
             'placeholder': 'com.example.profile',
             'help': 'Required for Remove action'},
        ],
        'dangerous': False,
        'min_role': 'operator',
        'bulk_supported': False,
        'info_text': 'Manage profiles on selected devices. Select one or multiple devices. For Install: select a profile. For Remove: enter profile identifier.',
    },

    # =========================================================================
    # DDM (Declarative Device Management) - Consolidated
    # =========================================================================
    'ddm_status': {
        'name': 'DDM Status',
        'category': 'ddm',
        'description': 'Show DDM declarations, sets, or device enrollment status',
        'script': 'ddm-status.sh',
        'script_dir': '/opt/nanohub/ddm/scripts',
        'parameters': [
            {'name': 'view', 'label': 'View', 'type': 'select', 'required': True, 'default': 'all',
             'options': [
                 {'value': 'all', 'label': 'Full Overview (Declarations + Sets)'},
                 {'value': 'declarations', 'label': 'Declarations Only'},
                 {'value': 'sets', 'label': 'Sets Only'},
                 {'value': 'device', 'label': 'Device Status'},
             ]},
            {'name': 'udid', 'label': 'Device', 'type': 'device', 'required': False,
             'help': 'Select device when using "Device Status" view'},
        ],
        'dangerous': False,
        'min_role': 'report',
        'bulk_supported': False,
        'info_text': 'View DDM configuration: declarations (policies), sets (device groups), or specific device enrollment.',
    },
    'manage_ddm_sets': {
        'name': 'Manage DDM Sets',
        'category': 'ddm',
        'description': 'Assign or remove DDM sets on one or more devices',
        'script': '_internal_manage_ddm_sets',
        'parameters': [
            {'name': 'action', 'label': 'Action', 'type': 'select', 'required': True, 'default': 'assign',
             'options': [
                 {'value': 'assign', 'label': 'Assign Set'},
                 {'value': 'remove', 'label': 'Remove Set'},
             ]},
            {'name': 'devices', 'label': 'Devices', 'type': 'devices', 'required': True},
            {'name': 'set_name', 'label': 'DDM Set', 'type': 'select', 'required': True,
             'options': [
                 {'value': 'sloto-macos-karlin-default', 'label': 'macOS Karlin Default'},
                 {'value': 'sloto-macos-karlin-tech', 'label': 'macOS Karlin Tech'},
                 {'value': 'sloto-macos-bel-default', 'label': 'macOS Belehradska Default'},
                 {'value': 'sloto-macos-bel-tech', 'label': 'macOS Belehradska Tech'},
                 {'value': 'sloto-ios-karlin', 'label': 'iOS Karlin'},
                 {'value': 'sloto-ios-bel', 'label': 'iOS Belehradska'},
             ]},
        ],
        'dangerous': False,
        'min_role': 'operator',
        'bulk_supported': False,
        'info_text': 'Assign or remove DDM configuration sets. Select one or multiple devices. DDM sets are additive - to replace a set, remove the old one first.',
    },
    'ddm_force_sync': {
        'name': 'DDM Force Sync',
        'category': 'ddm',
        'description': 'Send push to force device DDM sync',
        'script': 'ddm-force-sync.sh',
        'script_dir': '/opt/nanohub/ddm/scripts',
        'parameters': [
            {'name': 'udid', 'label': 'Device', 'type': 'device', 'required': True},
        ],
        'dangerous': False,
        'min_role': 'operator',
        'bulk_supported': False,
        'info_text': 'Send push notification to device to force DDM declarations sync.',
    },

    # =========================================================================
    # APPLICATIONS (Consolidated)
    # =========================================================================
    'install_application': {
        'name': 'Install Application',
        'category': 'apps',
        'description': 'Install application on one or more devices',
        'script': '_internal_install_application',
        'parameters': [
            {'name': 'devices', 'label': 'Devices', 'type': 'devices', 'required': True},
            {'name': 'manifest_url', 'label': 'Manifest URL', 'type': 'string', 'required': True,
             'placeholder': 'https://example.com/app.plist'},
        ],
        'dangerous': False,
        'min_role': 'operator',
        'bulk_supported': False,
        'info_text': 'Install application via manifest URL. Select one or multiple devices.',
    },
    'installed_application_list': {
        'name': 'List Installed Apps',
        'category': 'apps',
        'description': 'List all installed applications on device',
        'script': 'installed_application_list',
        'parameters': [
            {'name': 'udid', 'label': 'Device', 'type': 'device', 'required': True},
        ],
        'dangerous': False,
        'min_role': 'report',
        'bulk_supported': False,
    },

    # =========================================================================
    # DEVICE CONTROL (Consolidated)
    # =========================================================================
    'device_action': {
        'name': 'Device Action',
        'category': 'device_control',
        'description': 'Perform actions on device: Lock, Unlock, Restart, Erase, Clear Passcode',
        'script': '_internal_device_action',
        'parameters': [
            {'name': 'action', 'label': 'Action', 'type': 'select', 'required': True,
             'options': [
                 {'value': 'lock', 'label': 'Lock Device'},
                 {'value': 'unlock', 'label': 'Unlock Device (Clear Passcode)'},
                 {'value': 'restart', 'label': 'Restart Device'},
                 {'value': 'erase', 'label': 'Erase Device (Factory Reset)'},
                 {'value': 'clear_passcode', 'label': 'Clear Passcode'},
             ]},
            {'name': 'udid', 'label': 'Device', 'type': 'device', 'required': True},
            {'name': 'pin', 'label': 'PIN Code (for Lock/Erase)', 'type': 'string', 'required': False,
             'placeholder': '123456'},
            {'name': 'message', 'label': 'Lock Message', 'type': 'string', 'required': False,
             'placeholder': 'Device locked by administrator'},
            {'name': 'confirm_erase', 'label': 'Type ERASE to confirm (required for Erase action)', 'type': 'string', 'required': False,
             'placeholder': 'Type ERASE to confirm'},
        ],
        'dangerous': True,
        'danger_level': 'high',
        'min_role': 'operator',
        'bulk_supported': False,
        'info_text': 'Perform device control actions. Erase requires admin role, typing "ERASE" to confirm, and will PERMANENTLY delete all data.',
    },

    'update_inventory': {
        'name': 'Update Inventory',
        'category': 'device_control',
        'description': 'Update device inventory (hardware, security, profiles, apps) and cache in database',
        'script': '_internal_update_inventory',
        'parameters': [
            {'name': 'os_filter', 'label': 'OS Filter', 'type': 'select', 'required': False,
             'options': [
                 {'value': '', 'label': '-- All --'},
                 {'value': 'macOS', 'label': 'macOS only'},
                 {'value': 'iOS', 'label': 'iOS only'},
             ]},
            {'name': 'manifest', 'label': 'Manifest', 'type': 'select', 'required': False,
             'options': '_DYNAMIC_MANIFESTS_ALL'},
            {'name': 'last_updated', 'label': 'Last Updated', 'type': 'select', 'required': False,
             'options': [
                 {'value': '', 'label': '-- All --'},
                 {'value': '24h', 'label': 'Not updated in 24h'},
                 {'value': '7d', 'label': 'Not updated in 7 days'},
                 {'value': 'never', 'label': 'Never updated'},
             ]},
            {'name': 'devices', 'label': 'Devices (optional - leave empty to use filters)', 'type': 'devices', 'required': False},
        ],
        'dangerous': False,
        'min_role': 'operator',
        'bulk_supported': True,
        'info_text': 'Query devices for inventory data and cache in database. Select specific devices OR use filters to update all matching devices.',
    },

    # =========================================================================
    # OS UPDATES (Consolidated)
    # =========================================================================
    'schedule_os_update': {
        'name': 'Schedule OS Update',
        'category': 'os_updates',
        'description': 'Schedule OS update on one or more devices',
        'script': '_internal_schedule_os_update',
        'parameters': [
            {'name': 'action', 'label': 'Install Action', 'type': 'select', 'required': True,
             'options': [
                 {'value': 'Default', 'label': 'Default'},
                 {'value': 'DownloadOnly', 'label': 'Download Only'},
                 {'value': 'InstallASAP', 'label': 'Install ASAP'},
                 {'value': 'NotifyOnly', 'label': 'Notify Only'},
                 {'value': 'InstallLater', 'label': 'Install Later'},
                 {'value': 'InstallForceRestart', 'label': 'Install & Force Restart'},
             ]},
            {'name': 'devices', 'label': 'Devices', 'type': 'devices', 'required': True},
            {'name': 'key', 'label': 'Product Key', 'type': 'string', 'required': False,
             'placeholder': 'Specific update product key'},
            {'name': 'version', 'label': 'Version', 'type': 'string', 'required': False,
             'placeholder': 'e.g. 17.1'},
            {'name': 'deferrals', 'label': 'Max Deferrals', 'type': 'string', 'required': False,
             'placeholder': 'Max user deferrals (e.g. 3)'},
            {'name': 'priority', 'label': 'Priority', 'type': 'select', 'required': False,
             'options': [
                 {'value': '', 'label': '-- Default --'},
                 {'value': 'Low', 'label': 'Low'},
                 {'value': 'High', 'label': 'High'},
             ]},
        ],
        'dangerous': True,
        'danger_level': 'medium',
        'min_role': 'operator',
        'bulk_supported': False,
        'info_text': 'Schedule OS update on selected devices. Select one or multiple devices.',
    },
    'available_os_updates': {
        'name': 'Available OS Updates',
        'category': 'os_updates',
        'description': 'Get list of available OS updates for device',
        'script': 'available_os_updates',
        'parameters': [
            {'name': 'udid', 'label': 'Device', 'type': 'device', 'required': True},
        ],
        'dangerous': False,
        'min_role': 'report',
        'bulk_supported': False,
    },
    'os_update_status': {
        'name': 'OS Update Status',
        'category': 'os_updates',
        'description': 'Get OS update status for device',
        'script': 'os_update_status',
        'parameters': [
            {'name': 'udid', 'label': 'Device', 'type': 'device', 'required': True},
        ],
        'dangerous': False,
        'min_role': 'report',
        'bulk_supported': False,
    },

    # =========================================================================
    # REMOTE DESKTOP (Consolidated)
    # =========================================================================
    'manage_remote_desktop': {
        'name': 'Manage Remote Desktop',
        'category': 'remote_desktop',
        'description': 'Enable or disable Remote Desktop on one or more macOS devices',
        'script': '_internal_manage_remote_desktop',
        'parameters': [
            {'name': 'action', 'label': 'Action', 'type': 'select', 'required': True,
             'options': [
                 {'value': 'enable', 'label': 'Enable Remote Desktop'},
                 {'value': 'disable', 'label': 'Disable Remote Desktop'},
             ]},
            {'name': 'devices', 'label': 'Devices', 'type': 'devices', 'required': True,
             'filter_os': 'macos'},
        ],
        'dangerous': True,
        'danger_level': 'medium',
        'min_role': 'operator',
        'bulk_supported': False,
        'info_text': 'Enable or disable Remote Desktop (ARD) on selected macOS devices. Select one or multiple devices.',
    },

    # =========================================================================
    # SECURITY
    # =========================================================================
    'lost_mode': {
        'name': 'Lost Mode',
        'category': 'security',
        'description': 'Enable lost mode on device',
        'script': 'lost_mode',
        'parameters': [
            {'name': 'udid', 'label': 'Device', 'type': 'device', 'required': True},
            {'name': 'message', 'label': 'Message', 'type': 'string', 'required': False,
             'placeholder': 'This device has been lost. Please contact...'},
            {'name': 'phone', 'label': 'Phone Number', 'type': 'string', 'required': False,
             'placeholder': '+420...'},
        ],
        'dangerous': True,
        'danger_level': 'medium',
        'min_role': 'operator',
        'bulk_supported': False,
    },
    'security_info': {
        'name': 'Security Info',
        'category': 'security',
        'description': 'Get security information from device',
        'script': 'security_info',
        'parameters': [
            {'name': 'udid', 'label': 'Device', 'type': 'device', 'required': True},
        ],
        'dangerous': False,
        'min_role': 'report',
        'bulk_supported': False,
    },

    # =========================================================================
    # DIAGNOSTICS
    # =========================================================================
    'device_lookup': {
        'name': 'Device Lookup',
        'category': 'diagnostics',
        'description': 'Lookup device by serial or UDID',
        'script': 'device_lookup',
        'parameters': [
            {'name': 'query', 'label': 'Serial or UDID', 'type': 'string', 'required': True,
             'placeholder': 'Serial number or UDID'},
        ],
        'dangerous': False,
        'min_role': 'report',
        'bulk_supported': False,
    },
    'mdm_analyzer': {
        'name': 'MDM Analyzer',
        'category': 'diagnostics',
        'description': 'Analyze MDM status and configuration',
        'script': 'mdm_analyzer',
        'parameters': [
            {'name': 'udid', 'label': 'Device', 'type': 'device', 'required': True},
        ],
        'dangerous': False,
        'min_role': 'report',
        'bulk_supported': False,
    },
    'system_report_full': {
        'name': 'Full System Report',
        'category': 'diagnostics',
        'description': 'Get comprehensive system report from device',
        'script': 'system_report_full',
        'parameters': [
            {'name': 'udid', 'label': 'Device', 'type': 'device', 'required': True},
        ],
        'dangerous': False,
        'min_role': 'report',
        'bulk_supported': False,
    },
    'db_device_query': {
        'name': 'Database Device Query',
        'category': 'diagnostics',
        'description': 'Query device inventory database',
        'script': 'db_device_query.sh',
        'script_dir': '/opt/nanohub/tools',
        'parameters': [
            {'name': 'query_type', 'label': 'Query Type', 'type': 'select', 'required': True,
             'options': [
                 {'value': 'get_all', 'label': 'Get All Devices'},
                 {'value': 'get_by_os', 'label': 'Get by OS'},
                 {'value': 'get_by_hostname', 'label': 'Get by Hostname'},
                 {'value': 'get_by_serial', 'label': 'Get by Serial'},
                 {'value': 'get_by_uuid', 'label': 'Get by UUID'},
                 {'value': 'get_by_manifest', 'label': 'Get by Manifest'},
                 {'value': 'count_all', 'label': 'Count All'},
                 {'value': 'count_by_os', 'label': 'Count by OS'},
                 {'value': 'list_manifests', 'label': 'List Manifests'},
                 {'value': 'list_os', 'label': 'List OS Types'},
             ]},
            {'name': 'param1', 'label': 'Parameter', 'type': 'string', 'required': False,
             'placeholder': 'e.g. ios, macos, hostname, serial...'},
        ],
        'dangerous': False,
        'min_role': 'report',
        'bulk_supported': False,
    },

    # =========================================================================
    # VPP APPS (Consolidated)
    # =========================================================================
    'manage_vpp_app': {
        'name': 'Manage VPP App',
        'category': 'vpp',
        'description': 'Install or remove VPP application on one or more devices',
        'script': '_internal_manage_vpp_app',
        'parameters': [
            {'name': 'platform', 'label': 'Platform', 'type': 'select', 'required': True,
             'options': [
                 {'value': 'ios', 'label': 'iOS'},
                 {'value': 'macos', 'label': 'macOS'},
             ]},
            {'name': 'action', 'label': 'Action', 'type': 'select', 'required': True,
             'options': [
                 {'value': 'install', 'label': 'Install'},
                 {'value': 'remove', 'label': 'Remove'},
             ]},
            {'name': 'devices', 'label': 'Devices', 'type': 'devices', 'required': True},
            {'name': 'adam_id', 'label': 'Adam ID', 'type': 'string', 'required': True,
             'placeholder': 'App Store Adam ID'},
        ],
        'dangerous': False,
        'min_role': 'operator',
        'bulk_supported': False,
        'info_text': 'Install or remove VPP application. Select platform (iOS/macOS), action (Install/Remove), and one or multiple devices.',
    },

    # =========================================================================
    # OTHER
    # =========================================================================
    'device_manager': {
        'name': 'Device Manager',
        'category': 'setup',
        'description': 'Add, update or delete devices in inventory',
        'script': '_internal',
        'has_device_autofill': True,
        'parameters': [
            {'name': 'command', 'label': 'Action', 'type': 'select', 'required': True,
             'options': [
                 {'value': 'add', 'label': 'ADD - New device'},
                 {'value': 'update', 'label': 'UPDATE - Edit existing device'},
                 {'value': 'delete', 'label': 'DELETE - Remove device'},
             ]},
            {'name': 'device_select', 'label': 'Select Device (for update/delete)', 'type': 'device_autofill', 'required': False},
            {'name': 'uuid', 'label': 'UUID', 'type': 'string', 'required': False,
             'placeholder': 'e.g. 1FABE57D-AD95-597F-8E02-E8251E4A1933'},
            {'name': 'serial', 'label': 'Serial Number', 'type': 'string', 'required': False,
             'placeholder': 'e.g. FVFKQ0LW1WG7'},
            {'name': 'hostname', 'label': 'Hostname', 'type': 'string', 'required': False,
             'placeholder': 'e.g. office-mac01'},
            {'name': 'os', 'label': 'OS', 'type': 'select', 'required': False,
             'options': '_DYNAMIC_PLATFORMS_SELECT'},
            {'name': 'manifest', 'label': 'Manifest', 'type': 'select', 'required': False,
             'options': '_DYNAMIC_MANIFESTS_DEFAULT'},
            {'name': 'account', 'label': 'Account', 'type': 'select', 'required': False,
             'options': '_DYNAMIC_ACCOUNTS_DEFAULT'},
            {'name': 'dep', 'label': 'DEP', 'type': 'select', 'required': False,
             'options': '_DYNAMIC_DEP_DEFAULT'},
        ],
        'dangerous': False,
        'min_role': 'operator',
        'bulk_supported': False,
    },
    'manage_applications': {
        'name': 'Manage Applications',
        'category': 'apps',
        'description': 'Add, edit or remove applications for device installation',
        'script': '_internal_manage_applications',
        'parameters': [
            {'name': 'action', 'label': 'Action', 'type': 'select', 'required': True,
             'options': [
                 {'value': 'list', 'label': 'LIST - Show all applications'},
                 {'value': 'add', 'label': 'ADD - New application'},
                 {'value': 'edit', 'label': 'EDIT - Modify existing'},
                 {'value': 'remove', 'label': 'REMOVE - Delete application'},
             ]},
            {'name': 'manifest', 'label': 'Manifest', 'type': 'select', 'required': False,
             'options': '_DYNAMIC_MANIFESTS'},
            {'name': 'app_id', 'label': 'Application (for edit/remove)', 'type': 'select', 'required': False,
             'options': '_DYNAMIC_APPLICATIONS_LIST'},
            {'name': 'os', 'label': 'OS', 'type': 'select', 'required': False,
             'options': [
                 {'value': 'macos', 'label': 'macOS'},
                 {'value': 'ios', 'label': 'iOS'},
             ]},
            {'name': 'app_name', 'label': 'Application Name', 'type': 'string', 'required': False,
             'placeholder': 'e.g. MDM Agent'},
            {'name': 'manifest_url', 'label': 'Manifest URL (plist)', 'type': 'string', 'required': False,
             'placeholder': 'e.g. https://repo.example.com/munki/app.plist'},
            {'name': 'install_order', 'label': 'Install Order', 'type': 'string', 'required': False,
             'placeholder': 'e.g. 1, 2, 3...'},
        ],
        'dangerous': False,
        'min_role': 'admin',
        'bulk_supported': False,
        'info_text': 'Manage applications in the required_applications table. LIST shows all apps grouped by manifest. ADD/EDIT/REMOVE modify the database.',
    },
    'manage_command_queue': {
        'name': 'Command Queue',
        'category': 'other',
        'description': 'Show or clear pending commands in device queue',
        'script': '_internal_manage_command_queue',
        'parameters': [
            {'name': 'action', 'label': 'Action', 'type': 'select', 'required': True,
             'options': [
                 {'value': 'show', 'label': 'Show Queue'},
                 {'value': 'clear', 'label': 'Clear Queue'},
             ]},
            {'name': 'udid', 'label': 'Device', 'type': 'device', 'required': True},
        ],
        'dangerous': True,
        'danger_level': 'low',
        'min_role': 'admin',
        'bulk_supported': False,
        'info_text': 'View or clear pending MDM commands in the device queue.',
    },
    'send_command': {
        'name': 'Send Command',
        'category': 'other',
        'description': 'Send command to NanoHUB agent on device (test, hostname, shell, user management)',
        'script': 'send_command',
        'script_dir': '/opt/nanohub/tools/api/commands',
        'parameters': [
            {'name': 'udid', 'label': 'Device', 'type': 'device', 'required': True},
            {'name': 'command_type', 'label': 'Command Type', 'type': 'select', 'required': True,
             'options': [
                 {'value': 'test', 'label': 'Test - Test connectivity'},
                 {'value': 'hostname', 'label': 'Hostname - Change computer name'},
                 {'value': 'shell', 'label': 'Shell - Execute shell command'},
                 {'value': 'createuser', 'label': 'Create User'},
                 {'value': 'disableuser', 'label': 'Disable User'},
                 {'value': 'enableuser', 'label': 'Enable User'},
                 {'value': 'removeuser', 'label': 'Remove User'},
                 {'value': 'setpassword', 'label': 'Set Password'},
             ]},
            {'name': 'value', 'label': 'Value', 'type': 'string', 'required': True,
             'placeholder': 'Command value (e.g. new-hostname, username, shell command)'},
            {'name': 'parameter', 'label': 'Parameter', 'type': 'string', 'required': False,
             'placeholder': 'Optional: admin|password or standard|password for createuser'},
        ],
        'dangerous': True,
        'danger_level': 'high',
        'min_role': 'admin',
        'bulk_supported': False,
    },
}


def get_commands_by_category():
    """Return commands grouped by category"""
    result = {}
    for cat_id, cat_info in CATEGORIES.items():
        result[cat_id] = {
            'info': cat_info,
            'commands': {}
        }

    for cmd_id, cmd_info in COMMANDS.items():
        cat = cmd_info.get('category', 'other')
        if cat in result:
            result[cat]['commands'][cmd_id] = cmd_info

    return result


def get_command(cmd_id):
    """Get command by ID"""
    return COMMANDS.get(cmd_id)


def _extract_profile_identifier(filepath):
    """Extract PayloadIdentifier from a mobileconfig file"""
    import re
    try:
        # Read file as binary and decode, ignoring errors (handles signed profiles)
        with open(filepath, 'rb') as f:
            content = f.read().decode('utf-8', errors='ignore')

        # Find PayloadIdentifier using regex
        match = re.search(r'<key>PayloadIdentifier</key>\s*<string>([^<]+)</string>', content)
        if match:
            return match.group(1).strip()
    except Exception:
        pass
    return ''


def get_available_profiles():
    """Get list of available signed profiles only"""
    import os
    import glob

    profiles = []

    # Standard profiles - only signed ones (*.signed.mobileconfig)
    if os.path.exists(PROFILE_DIRS['standard']):
        for f in glob.glob(os.path.join(PROFILE_DIRS['standard'], '*.signed.mobileconfig')):
            profiles.append({
                'path': f,
                'name': os.path.basename(f),
                'identifier': _extract_profile_identifier(f),
                'type': 'standard'
            })

    # WireGuard profiles - recursive search for signed profiles
    if os.path.exists(PROFILE_DIRS['wireguard']):
        for f in glob.glob(os.path.join(PROFILE_DIRS['wireguard'], '**/*.signed.mobileconfig'), recursive=True):
            # Extract relative path for better identification
            rel_path = os.path.relpath(f, PROFILE_DIRS['wireguard'])
            profiles.append({
                'path': f,
                'name': os.path.basename(f),
                'rel_path': rel_path,
                'identifier': _extract_profile_identifier(f),
                'type': 'wireguard'
            })

    return sorted(profiles, key=lambda x: x['name'])


def check_role_permission(user_role, required_role):
    """Check if user role meets minimum requirement"""
    # bel-admin has same permission level as admin, just filtered by manifest
    role_hierarchy = {'admin': 3, 'bel-admin': 3, 'operator': 2, 'report': 1}
    return role_hierarchy.get(user_role, 0) >= role_hierarchy.get(required_role, 0)


# =============================================================================
# DYNAMIC OPTIONS RESOLUTION
# =============================================================================

def _get_dynamic_options():
    """Build dynamic options mapping from web_environment.sh config."""
    return {
        # Basic options without empty selection
        '_DYNAMIC_BRANCHES': get_branch_options(include_empty=False),
        '_DYNAMIC_PLATFORMS': get_platform_options(include_empty=False),
        '_DYNAMIC_MANIFESTS': get_manifest_options(include_empty=False),

        # Options with "All" selection for filters
        '_DYNAMIC_MANIFESTS_ALL': get_manifest_options(include_empty=True, empty_label='-- All Manifests --'),
        '_DYNAMIC_ACCOUNTS_ALL': get_account_options(include_empty=True, empty_label='-- All Accounts --'),

        # Options with "Select" selection
        '_DYNAMIC_PLATFORMS_SELECT': get_platform_options(include_empty=True, empty_label='-- Select --'),

        # Options with "Default" selection
        '_DYNAMIC_MANIFESTS_DEFAULT': get_manifest_options(include_empty=True, empty_label='-- Default --'),
        '_DYNAMIC_ACCOUNTS_DEFAULT': get_account_options(include_empty=True, empty_label='-- Default --'),
        '_DYNAMIC_DEP_DEFAULT': get_dep_options(include_empty=True, empty_label='-- Default --'),

        # OS filter with auto option
        '_DYNAMIC_OS_FILTER': get_os_filter_options(),

        # Applications for New Device Installation (populated at render time)
        '_DYNAMIC_APPLICATIONS': [],

        # Applications list for Manage Applications (populated at render time)
        '_DYNAMIC_APPLICATIONS_LIST': [],
    }


def _resolve_dynamic_options(commands):
    """Replace dynamic option placeholders with actual options."""
    dynamic_opts = _get_dynamic_options()

    for cmd_id, cmd in commands.items():
        if 'parameters' not in cmd:
            continue

        for param in cmd['parameters']:
            if 'options' in param and isinstance(param['options'], str):
                placeholder = param['options']
                if placeholder in dynamic_opts:
                    param['options'] = dynamic_opts[placeholder]
                else:
                    print(f"[WARNING] Unknown dynamic option placeholder: {placeholder}")

    return commands


def reload_commands():
    """Reload commands with fresh configuration (call after config change)."""
    global COMMANDS
    from web_config import load_config
    load_config(force_reload=True)
    _resolve_dynamic_options(COMMANDS)


# Initialize dynamic options on module load
_resolve_dynamic_options(COMMANDS)
