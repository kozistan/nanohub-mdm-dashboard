"""
NanoHUB Command Registry
Metadata for all MDM commands available in admin panel
"""

import os

# Command categories
CATEGORIES = {
    'setup': {'name': 'Device Setup', 'icon': 'zap', 'order': 1},
    'profiles': {'name': 'Profiles', 'icon': 'file-text', 'order': 2},
    'apps': {'name': 'Applications', 'icon': 'package', 'order': 3},
    'device_control': {'name': 'Device Control', 'icon': 'smartphone', 'order': 4},
    'os_updates': {'name': 'OS Updates', 'icon': 'download', 'order': 5},
    'remote_desktop': {'name': 'Remote Desktop', 'icon': 'monitor', 'order': 6},
    'security': {'name': 'Security', 'icon': 'shield', 'order': 7},
    'diagnostics': {'name': 'Diagnostics', 'icon': 'activity', 'order': 8},
    'vpp': {'name': 'VPP Apps', 'icon': 'shopping-bag', 'order': 9},
    'other': {'name': 'Other', 'icon': 'settings', 'order': 10},
}

# Profile directories - configure for your environment
PROFILE_DIRS = {
    'standard': os.getenv('PROFILES_DIR', '/opt/nanohub/profiles/'),
    'wireguard': os.getenv('WIREGUARD_PROFILES_DIR', '/opt/nanohub/profiles/wireguard_configs/'),
}

# Commands directory
COMMANDS_DIR = os.getenv('COMMANDS_DIR', '/opt/nanohub/tools/api/commands')

# All available commands with metadata
COMMANDS = {
    # =========================================================================
    # DEVICE SETUP
    # =========================================================================
    'bulk_new_device_installation': {
        'name': 'New Device Installation',
        'category': 'setup',
        'description': 'Automated installation workflow for new devices',
        'script': '_internal_bulk_install',
        'parameters': [
            {'name': 'branch', 'label': 'Branch', 'type': 'select', 'required': True,
             'options': [
                 {'value': 'main', 'label': 'Main Office'},
                 {'value': 'branch', 'label': 'Branch Office'},
             ]},
            {'name': 'platform', 'label': 'Platform', 'type': 'select', 'required': True,
             'options': [
                 {'value': 'macos', 'label': 'macOS'},
                 {'value': 'ios', 'label': 'iOS'},
             ]},
            {'name': 'udid', 'label': 'Device', 'type': 'device', 'required': True},
            {'name': 'munki_type', 'label': 'Munki Profile Type (macOS only)', 'type': 'select', 'required': False,
             'options': [
                 {'value': 'default', 'label': 'Default'},
                 {'value': 'tech', 'label': 'Tech'},
                 {'value': 'branch-default', 'label': 'Branch Default'},
                 {'value': 'branch-tech', 'label': 'Branch Tech'},
             ]},
            {'name': 'hostname', 'label': 'Hostname (optional, for Directory Services)', 'type': 'string', 'required': False,
             'placeholder': 'e.g. mac-001'},
            {'name': 'install_filevault', 'label': 'Install FileVault Profile', 'type': 'select', 'required': False,
             'options': [
                 {'value': 'no', 'label': 'No - Skip FileVault'},
                 {'value': 'yes', 'label': 'Yes - Client is logged in'},
             ]},
            {'name': 'install_wireguard', 'label': 'Install WireGuard Profile', 'type': 'select', 'required': False,
             'options': [
                 {'value': 'no', 'label': 'No - Skip WireGuard'},
                 {'value': 'yes', 'label': 'Yes - Search by hostname'},
             ]},
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
             'placeholder': 'https://repo.example.com/app.plist'},
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
        'name': 'Unlock Device',
        'category': 'device_control',
        'description': 'Clear passcode and unlock device',
        'script': 'unlock_device',
        'parameters': [
            {'name': 'udid', 'label': 'Device', 'type': 'device', 'required': True},
        ],
        'dangerous': True,
        'danger_level': 'medium',
        'min_role': 'operator',
        'bulk_supported': False,
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
        'description': 'Schedule OS update on multiple devices',
        'script': 'bulk_schedule_os_update',
        'parameters': [
            {'name': 'devices', 'label': 'Devices', 'type': 'devices', 'required': True},
            {'name': 'action', 'label': 'Install Action', 'type': 'select', 'required': True,
             'options': [
                 {'value': 'Default', 'label': 'Default'},
                 {'value': 'DownloadOnly', 'label': 'Download Only'},
                 {'value': 'InstallASAP', 'label': 'Install ASAP'},
                 {'value': 'NotifyOnly', 'label': 'Notify Only'},
                 {'value': 'InstallLater', 'label': 'Install Later'},
                 {'value': 'InstallForceRestart', 'label': 'Install & Force Restart'},
             ]},
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
             'placeholder': '+1...'},
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
        'category': 'diagnostics',
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
             'placeholder': 'e.g. mac-001'},
            {'name': 'os', 'label': 'OS', 'type': 'select', 'required': False,
             'options': [
                 {'value': '', 'label': '-- Select --'},
                 {'value': 'macos', 'label': 'macOS'},
                 {'value': 'ios', 'label': 'iOS'},
             ]},
            {'name': 'manifest', 'label': 'Manifest', 'type': 'select', 'required': False,
             'options': [
                 {'value': '', 'label': '-- Default --'},
                 {'value': 'default', 'label': 'Default'},
                 {'value': 'tech', 'label': 'Tech'},
                 {'value': 'branch-default', 'label': 'Branch Default'},
                 {'value': 'branch-tech', 'label': 'Branch Tech'},
             ]},
            {'name': 'account', 'label': 'Account', 'type': 'select', 'required': False,
             'options': [
                 {'value': '', 'label': '-- Default --'},
                 {'value': 'disabled', 'label': 'Disabled'},
                 {'value': 'enabled', 'label': 'Enabled'},
             ]},
            {'name': 'dep', 'label': 'DEP', 'type': 'select', 'required': False,
             'options': [
                 {'value': '', 'label': '-- Default --'},
                 {'value': '1', 'label': 'Enabled'},
                 {'value': '0', 'label': 'Disabled'},
             ]},
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
    # bel-admin has same permission level as admin, just filtered by manifest
    role_hierarchy = {'admin': 3, 'bel-admin': 3, 'operator': 2, 'report': 1}
    return role_hierarchy.get(user_role, 0) >= role_hierarchy.get(required_role, 0)
