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
        'description': 'Automated installation workflow for new devices (Site A/B branches)',
        'script': '_internal_bulk_install',
        'parameters': [
            {'name': 'branch', 'label': 'Branch', 'type': 'select', 'required': True,
             'options': '_DYNAMIC_BRANCHES'},
            {'name': 'platform', 'label': 'Platform', 'type': 'select', 'required': True,
             'options': '_DYNAMIC_PLATFORMS'},
            {'name': 'udid', 'label': 'Device', 'type': 'device', 'required': True},
            {'name': 'munki_type', 'label': 'Munki Profile Type (macOS only)', 'type': 'select', 'required': False,
             'options': '_DYNAMIC_MANIFESTS'},
            {'name': 'hostname', 'label': 'Hostname (for Directory Services)', 'type': 'string', 'required': False,
             'placeholder': 'e.g. device08'},
            {'name': 'install_directory_services', 'label': 'Join Active Directory', 'type': 'select', 'required': False,
             'options': [
                 {'value': 'no', 'label': 'No - Skip AD join'},
                 {'value': 'yes', 'label': 'Yes - Join AD (requires hostname)'},
             ]},
            {'name': 'install_filevault', 'label': 'Install FileVault Profile', 'type': 'select', 'required': False,
             'options': [
                 {'value': 'no', 'label': 'No - Skip FileVault'},
                 {'value': 'yes', 'label': 'Yes - Client is logged in'},
             ]},
            {'name': 'install_wireguard', 'label': 'Install WireGuard Profile', 'type': 'select', 'required': False,
             'options': [
                 {'value': 'no', 'label': 'No - Skip WireGuard'},
                 {'value': 'yes', 'label': 'Yes - Search by username'},
             ]},
            {'name': 'wireguard_username', 'label': 'WireGuard Username (for profile search)', 'type': 'string', 'required': False,
             'placeholder': 'e.g. j.smith or smith'},
        ],
        'dangerous': False,
        'min_role': 'operator',
        'bulk_supported': False,
        'info_text': 'This will install all required profiles and applications for a new device. For macOS: profiles (Root, Energy Saver, Munki, SSO, Restrictions, Account, Firewall) + applications (MDM Agent, Munki). Optional: Directory Services, FileVault, WireGuard. For iOS: Root, Account, Restrictions, Whitelist profiles.',
    },

    # =========================================================================
    # PROFILES
    # =========================================================================
    'install_profile': {
        'name': 'Install Profile',
        'category': 'profiles',
        'description': 'Install mobileconfig profile to device',
        'script': 'install_profile',
        'parameters': [
            {'name': 'udid', 'label': 'Device', 'type': 'device', 'required': True},
            {'name': 'profile', 'label': 'Profile', 'type': 'profile', 'required': True},
        ],
        'dangerous': False,
        'min_role': 'operator',
        'bulk_supported': True,
    },
    'remove_profile': {
        'name': 'Remove Profile',
        'category': 'profiles',
        'description': 'Remove installed profile from device',
        'script': 'remove_profile',
        'parameters': [
            {'name': 'udid', 'label': 'Device', 'type': 'device', 'required': True},
            {'name': 'identifier', 'label': 'Profile Identifier', 'type': 'string', 'required': True,
             'placeholder': 'com.example.profile'},
        ],
        'dangerous': False,
        'min_role': 'operator',
        'bulk_supported': True,
    },
    'profile_list': {
        'name': 'List Profiles',
        'category': 'profiles',
        'description': 'List all installed profiles on device',
        'script': 'profile_list',
        'parameters': [
            {'name': 'udid', 'label': 'Device', 'type': 'device', 'required': True},
        ],
        'dangerous': False,
        'min_role': 'report',
        'bulk_supported': False,
    },
    'bulk_install_profile': {
        'name': 'Bulk Install Profile',
        'category': 'profiles',
        'description': 'Install profile to multiple devices',
        'script': 'bulk_install_profile',
        'parameters': [
            {'name': 'devices', 'label': 'Devices', 'type': 'devices', 'required': True},
            {'name': 'profile', 'label': 'Profile', 'type': 'profile', 'required': True},
        ],
        'dangerous': False,
        'min_role': 'operator',
        'bulk_supported': False,
    },
    'bulk_remove_profile': {
        'name': 'Bulk Remove Profile',
        'category': 'profiles',
        'description': 'Remove profile from multiple devices',
        'script': 'bulk_remove_profile',
        'parameters': [
            {'name': 'devices', 'label': 'Devices', 'type': 'devices', 'required': True},
            {'name': 'identifier', 'label': 'Profile Identifier', 'type': 'string', 'required': True},
        ],
        'dangerous': False,
        'min_role': 'operator',
        'bulk_supported': False,
    },
    'sign_profile': {
        'name': 'Sign Profile',
        'category': 'profiles',
        'description': 'Sign a mobileconfig profile',
        'script': 'sign_profile',
        'parameters': [
            {'name': 'profile', 'label': 'Profile Path', 'type': 'string', 'required': True},
        ],
        'dangerous': False,
        'min_role': 'admin',
        'bulk_supported': False,
    },

    # =========================================================================
    # DDM (Declarative Device Management)
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
    'ddm_assign_device': {
        'name': 'Assign DDM Set',
        'category': 'ddm',
        'description': 'Assign a DDM set to a device',
        'script': 'ddm-assign-device.sh',
        'script_dir': '/opt/nanohub/ddm/scripts',
        'parameters': [
            {'name': 'udid', 'label': 'Device', 'type': 'device', 'required': True},
            {'name': 'set_name', 'label': 'DDM Set', 'type': 'select', 'required': True,
             'options': [
                 {'value': 'macos-site-a-default', 'label': 'macOS Site A Default'},
                 {'value': 'macos-site-a-tech', 'label': 'macOS Site A Tech'},
                 {'value': 'macos-site-b-default', 'label': 'macOS Site B Default'},
                 {'value': 'macos-site-b-tech', 'label': 'macOS Site B Tech'},
                 {'value': 'ios-site-a', 'label': 'iOS Site A'},
                 {'value': 'ios-site-b', 'label': 'iOS Site B'},
             ]},
        ],
        'dangerous': False,
        'min_role': 'operator',
        'bulk_supported': False,
        'info_text': 'Assign a DDM configuration set to a device. The device will receive declarations on next check-in.',
    },
    'ddm_bulk_assign': {
        'name': 'Bulk Assign DDM Set',
        'category': 'ddm',
        'description': 'Assign a DDM set to multiple devices',
        'script': 'ddm-bulk-assign.sh',
        'script_dir': '/opt/nanohub/ddm/scripts',
        'parameters': [
            {'name': 'devices', 'label': 'Devices', 'type': 'devices', 'required': True},
            {'name': 'set_name', 'label': 'DDM Set', 'type': 'select', 'required': True,
             'options': [
                 {'value': 'macos-site-a-default', 'label': 'macOS Site A Default'},
                 {'value': 'macos-site-a-tech', 'label': 'macOS Site A Tech'},
                 {'value': 'macos-site-b-default', 'label': 'macOS Site B Default'},
                 {'value': 'macos-site-b-tech', 'label': 'macOS Site B Tech'},
                 {'value': 'ios-site-a', 'label': 'iOS Site A'},
                 {'value': 'ios-site-b', 'label': 'iOS Site B'},
             ]},
        ],
        'dangerous': False,
        'min_role': 'operator',
        'bulk_supported': False,
        'info_text': 'Assign a DDM configuration set to multiple devices at once.',
    },
    'ddm_upload_declarations': {
        'name': 'Upload Declarations',
        'category': 'ddm',
        'description': 'Upload all DDM declarations to server',
        'script': 'ddm-upload-declarations.sh',
        'script_dir': '/opt/nanohub/ddm/scripts',
        'parameters': [],
        'dangerous': True,
        'danger_level': 'medium',
        'min_role': 'admin',
        'bulk_supported': False,
        'info_text': 'Upload all declaration JSON files from /opt/nanohub/ddm/declarations/ to DDM server.',
    },
    'ddm_create_sets': {
        'name': 'Create Sets',
        'category': 'ddm',
        'description': 'Create all DDM sets on server',
        'script': 'ddm-create-sets.sh',
        'script_dir': '/opt/nanohub/ddm/scripts',
        'parameters': [],
        'dangerous': True,
        'danger_level': 'medium',
        'min_role': 'admin',
        'bulk_supported': False,
        'info_text': 'Create all DDM sets from /opt/nanohub/ddm/sets/ and bind declarations to them.',
    },

    # =========================================================================
    # APPLICATIONS
    # =========================================================================
    'install_application': {
        'name': 'Install Application',
        'category': 'apps',
        'description': 'Install application on device',
        'script': 'install_application',
        'parameters': [
            {'name': 'udid', 'label': 'Device', 'type': 'device', 'required': True},
            {'name': 'manifest_url', 'label': 'Manifest URL', 'type': 'string', 'required': True,
             'placeholder': 'https://example.com/app.plist'},
        ],
        'dangerous': False,
        'min_role': 'operator',
        'bulk_supported': True,
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
    'bulk_install_application': {
        'name': 'Bulk Install App',
        'category': 'apps',
        'description': 'Install application on multiple devices',
        'script': 'bulk_install_application',
        'parameters': [
            {'name': 'devices', 'label': 'Devices', 'type': 'devices', 'required': True},
            {'name': 'manifest_url', 'label': 'Manifest URL', 'type': 'string', 'required': True},
        ],
        'dangerous': False,
        'min_role': 'operator',
        'bulk_supported': False,
    },

    # =========================================================================
    # DEVICE CONTROL
    # =========================================================================
    'lock_device': {
        'name': 'Lock Device',
        'category': 'device_control',
        'description': 'Lock device immediately',
        'script': 'lock_device',
        'parameters': [
            {'name': 'udid', 'label': 'Device', 'type': 'device', 'required': True},
            {'name': 'pin', 'label': 'PIN Code', 'type': 'string', 'required': False,
             'placeholder': '123456'},
            {'name': 'message', 'label': 'Lock Message', 'type': 'string', 'required': False,
             'placeholder': 'Device locked by administrator'},
        ],
        'dangerous': True,
        'danger_level': 'medium',
        'min_role': 'operator',
        'bulk_supported': False,
    },
    'unlock_device': {
        'name': 'Unlock Device (Clear Passcode)',
        'category': 'device_control',
        'description': 'Clear passcode using ClearPasscode MDM command with UnlockToken (supervised iOS devices)',
        'script': 'unlock_device',
        'parameters': [
            {'name': 'udid', 'label': 'Device', 'type': 'device', 'required': True},
        ],
        'dangerous': True,
        'danger_level': 'medium',
        'min_role': 'operator',
        'bulk_supported': False,
        'info_text': 'Sends ClearPasscode command with UnlockToken from database. Device must be supervised with UnlockToken escrow enabled.',
    },
    'restart_device': {
        'name': 'Restart Device',
        'category': 'device_control',
        'description': 'Restart device remotely',
        'script': 'restart_device',
        'parameters': [
            {'name': 'udid', 'label': 'Device', 'type': 'device', 'required': True},
        ],
        'dangerous': True,
        'danger_level': 'low',
        'min_role': 'operator',
        'bulk_supported': False,
    },
    'erase_device': {
        'name': 'Erase Device',
        'category': 'device_control',
        'description': 'Factory reset device - ALL DATA WILL BE PERMANENTLY LOST',
        'script': 'erase_device',
        'parameters': [
            {'name': 'udid', 'label': 'Device', 'type': 'device', 'required': True},
            {'name': 'pin', 'label': 'PIN Code', 'type': 'string', 'required': False,
             'placeholder': '123456'},
        ],
        'dangerous': True,
        'danger_level': 'critical',
        'confirm_text': 'ERASE',
        'min_role': 'admin',
        'bulk_supported': False,
    },

    # =========================================================================
    # OS UPDATES
    # =========================================================================
    'schedule_os_update': {
        'name': 'Schedule OS Update',
        'category': 'os_updates',
        'description': 'Schedule OS update on device',
        'script': 'schedule_os_update',
        'parameters': [
            {'name': 'udid', 'label': 'Device', 'type': 'device', 'required': True},
            {'name': 'action', 'label': 'Install Action', 'type': 'select', 'required': True,
             'options': [
                 {'value': 'Default', 'label': 'Default'},
                 {'value': 'DownloadOnly', 'label': 'Download Only'},
                 {'value': 'InstallASAP', 'label': 'Install ASAP'},
                 {'value': 'NotifyOnly', 'label': 'Notify Only'},
                 {'value': 'InstallLater', 'label': 'Install Later'},
                 {'value': 'InstallForceRestart', 'label': 'Install & Force Restart'},
             ]},
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
        'bulk_supported': True,
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
    'bulk_schedule_os_update': {
        'name': 'Bulk OS Update',
        'category': 'os_updates',
        'description': 'Schedule OS update on multiple devices (platform-specific options)',
        'script': 'bulk_schedule_os_update',
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
            {'name': 'devices', 'label': 'Select Devices (empty = all matching filters)', 'type': 'devices', 'required': False},
            {'name': 'manifest', 'label': 'Filter by Manifest', 'type': 'select', 'required': False,
             'options': '_DYNAMIC_MANIFESTS_ALL'},
            {'name': 'account_filter', 'label': 'Filter by Account', 'type': 'select', 'required': False,
             'options': '_DYNAMIC_ACCOUNTS_ALL'},
            {'name': 'os_filter', 'label': 'Filter by OS', 'type': 'select', 'required': False,
             'options': '_DYNAMIC_OS_FILTER'},
            {'name': 'ios_key', 'label': 'iOS Product Key', 'type': 'string', 'required': False,
             'placeholder': 'e.g. iOS17.1'},
            {'name': 'ios_version', 'label': 'iOS Version', 'type': 'string', 'required': False,
             'placeholder': 'e.g. 17.1'},
            {'name': 'ios_deferrals', 'label': 'iOS Max Deferrals', 'type': 'string', 'required': False,
             'placeholder': 'e.g. 3'},
            {'name': 'ios_priority', 'label': 'iOS Priority', 'type': 'select', 'required': False,
             'options': [
                 {'value': '', 'label': '-- Default --'},
                 {'value': 'Low', 'label': 'Low'},
                 {'value': 'High', 'label': 'High'},
             ]},
            {'name': 'macos_key', 'label': 'macOS Product Key', 'type': 'string', 'required': False,
             'placeholder': 'e.g. macOS14.1'},
            {'name': 'macos_version', 'label': 'macOS Version', 'type': 'string', 'required': False,
             'placeholder': 'e.g. 14.1'},
            {'name': 'macos_deferrals', 'label': 'macOS Max Deferrals', 'type': 'string', 'required': False,
             'placeholder': 'e.g. 3'},
            {'name': 'macos_priority', 'label': 'macOS Priority', 'type': 'select', 'required': False,
             'options': [
                 {'value': '', 'label': '-- Default --'},
                 {'value': 'Low', 'label': 'Low'},
                 {'value': 'High', 'label': 'High'},
             ]},
            {'name': 'dry_run', 'label': 'Dry Run (preview only)', 'type': 'checkbox', 'required': False},
        ],
        'dangerous': True,
        'danger_level': 'medium',
        'min_role': 'operator',
        'bulk_supported': False,
    },

    # =========================================================================
    # REMOTE DESKTOP
    # =========================================================================
    'enable_rd': {
        'name': 'Enable Remote Desktop',
        'category': 'remote_desktop',
        'description': 'Enable remote desktop access on device',
        'script': 'enable_rd',
        'parameters': [
            {'name': 'udid', 'label': 'Device', 'type': 'device', 'required': True},
        ],
        'dangerous': True,
        'danger_level': 'medium',
        'min_role': 'operator',
        'bulk_supported': False,
    },
    'disable_rd': {
        'name': 'Disable Remote Desktop',
        'category': 'remote_desktop',
        'description': 'Disable remote desktop access on device',
        'script': 'disable_rd',
        'parameters': [
            {'name': 'udid', 'label': 'Device', 'type': 'device', 'required': True},
        ],
        'dangerous': False,
        'min_role': 'operator',
        'bulk_supported': False,
    },
    'bulk_remote_desktop': {
        'name': 'Bulk Remote Desktop',
        'category': 'remote_desktop',
        'description': 'Enable or disable Remote Desktop on selected macOS devices',
        'script': '_internal_bulk_remote_desktop',
        'parameters': [
            {'name': 'action', 'label': 'Action', 'type': 'select', 'required': True,
             'options': [
                 {'value': 'enable', 'label': 'Enable Remote Desktop'},
                 {'value': 'disable', 'label': 'Disable Remote Desktop'},
             ]},
            {'name': 'devices', 'label': 'Select Devices (empty = all macOS matching filter)', 'type': 'devices', 'required': False,
             'filter_os': 'macos'},
            {'name': 'manifest', 'label': 'Filter by Manifest', 'type': 'select', 'required': False,
             'options': '_DYNAMIC_MANIFESTS_ALL'},
        ],
        'dangerous': True,
        'danger_level': 'medium',
        'min_role': 'operator',
        'bulk_supported': False,
        'info_text': 'Select specific devices or leave empty to target ALL macOS devices matching the manifest filter. Commands are executed in parallel for fast execution.',
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
    'device_information': {
        'name': 'Device Information',
        'category': 'diagnostics',
        'description': 'Get detailed device information',
        'script': 'device_information',
        'parameters': [
            {'name': 'udid', 'label': 'Device', 'type': 'device', 'required': True},
        ],
        'dangerous': False,
        'min_role': 'report',
        'bulk_supported': False,
    },
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
    'system_report': {
        'name': 'System Report',
        'category': 'diagnostics',
        'description': 'Get system report from device',
        'script': 'system_report',
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

    # =========================================================================
    # VPP APPS
    # =========================================================================
    'install_vpp_app': {
        'name': 'Install VPP App',
        'category': 'vpp',
        'description': 'Install VPP application on device',
        'script': 'install_vpp_app',
        'parameters': [
            {'name': 'udid', 'label': 'Device', 'type': 'device', 'required': True},
            {'name': 'adam_id', 'label': 'Adam ID', 'type': 'string', 'required': True,
             'placeholder': 'App Store Adam ID'},
        ],
        'dangerous': False,
        'min_role': 'operator',
        'bulk_supported': True,
    },
    'remove_vpp_app': {
        'name': 'Remove VPP App',
        'category': 'vpp',
        'description': 'Remove VPP application from device',
        'script': 'remove_vpp_app',
        'parameters': [
            {'name': 'udid', 'label': 'Device', 'type': 'device', 'required': True},
            {'name': 'adam_id', 'label': 'Adam ID', 'type': 'string', 'required': True},
        ],
        'dangerous': False,
        'min_role': 'operator',
        'bulk_supported': True,
    },
    'get_vpp_application_version': {
        'name': 'Get VPP App Version',
        'category': 'vpp',
        'description': 'Get VPP application version info',
        'script': 'get_vpp_application_version',
        'parameters': [
            {'name': 'adam_id', 'label': 'Adam ID', 'type': 'string', 'required': True},
        ],
        'dangerous': False,
        'min_role': 'report',
        'bulk_supported': False,
    },
    'bulk_install_ios_vpp_apps': {
        'name': 'Bulk Install iOS VPP Apps',
        'category': 'vpp',
        'description': 'Install VPP apps on multiple iOS devices',
        'script': 'bulk_install_ios_vpp_apps',
        'parameters': [
            {'name': 'devices', 'label': 'Devices', 'type': 'devices', 'required': True},
            {'name': 'adam_id', 'label': 'Adam ID', 'type': 'string', 'required': True},
        ],
        'dangerous': False,
        'min_role': 'operator',
        'bulk_supported': False,
    },
    'bulk_install_macos_vpp_apps': {
        'name': 'Bulk Install macOS VPP Apps',
        'category': 'vpp',
        'description': 'Install VPP apps on multiple macOS devices',
        'script': 'bulk_install_macos_vpp_apps',
        'parameters': [
            {'name': 'devices', 'label': 'Devices', 'type': 'devices', 'required': True},
            {'name': 'adam_id', 'label': 'Adam ID', 'type': 'string', 'required': True},
        ],
        'dangerous': False,
        'min_role': 'operator',
        'bulk_supported': False,
    },
    'bulk_remove_ios_vpp_apps': {
        'name': 'Bulk Remove iOS VPP Apps',
        'category': 'vpp',
        'description': 'Remove VPP apps from multiple iOS devices',
        'script': 'bulk_remove_ios_vpp_apps',
        'parameters': [
            {'name': 'devices', 'label': 'Devices', 'type': 'devices', 'required': True},
            {'name': 'adam_id', 'label': 'Adam ID', 'type': 'string', 'required': True},
        ],
        'dangerous': False,
        'min_role': 'operator',
        'bulk_supported': False,
    },
    'bulk_remove_macos_vpp_apps': {
        'name': 'Bulk Remove macOS VPP Apps',
        'category': 'vpp',
        'description': 'Remove VPP apps from multiple macOS devices',
        'script': 'bulk_remove_macos_vpp_apps',
        'parameters': [
            {'name': 'devices', 'label': 'Devices', 'type': 'devices', 'required': True},
            {'name': 'adam_id', 'label': 'Adam ID', 'type': 'string', 'required': True},
        ],
        'dangerous': False,
        'min_role': 'operator',
        'bulk_supported': False,
    },
    'update_vpp_from_list': {
        'name': 'Update VPP From List',
        'category': 'vpp',
        'description': 'Update VPP apps from predefined list',
        'script': 'update_vpp_from_list',
        'parameters': [],
        'dangerous': False,
        'min_role': 'admin',
        'bulk_supported': False,
    },

    # =========================================================================
    # OTHER
    # =========================================================================
    'gen_wireguard_mobileconfig': {
        'name': 'Generate WireGuard Config',
        'category': 'other',
        'description': 'Generate WireGuard VPN mobileconfig profile',
        'script': 'gen_wireguard_mobileconfig',
        'parameters': [
            {'name': 'name', 'label': 'Config Name', 'type': 'string', 'required': True,
             'placeholder': 'vpn-user1'},
        ],
        'dangerous': False,
        'min_role': 'admin',
        'bulk_supported': False,
    },
    'clear_queue': {
        'name': 'Clear Command Queue',
        'category': 'other',
        'description': 'Clear pending commands from device queue',
        'script': 'clear_queue',
        'parameters': [
            {'name': 'udid', 'label': 'Device', 'type': 'device', 'required': True},
        ],
        'dangerous': True,
        'danger_level': 'low',
        'min_role': 'admin',
        'bulk_supported': False,
    },
    'send_command': {
        'name': 'Send HTTP Command',
        'category': 'other',
        'description': 'Send HTTP command to NanoHUB agent on device (test, hostname, shell, user management)',
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

    # =========================================================================
    # DATABASE TOOLS
    # =========================================================================
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
                'type': 'wireguard'
            })

    return sorted(profiles, key=lambda x: x['name'])


def check_role_permission(user_role, required_role):
    """Check if user role meets minimum requirement"""
    # restricted-admin has same permission level as admin, just filtered by manifest
    role_hierarchy = {'admin': 3, 'restricted-admin': 3, 'operator': 2, 'report': 1}
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
