"""
NanoHUB Web Configuration Loader
================================
Loads configuration from /opt/nanohub/web_environment.sh
Provides helper functions for generating UI options dynamically.
"""

import os
import re

# Configuration file path
WEB_ENV_PATH = '/opt/nanohub/web_environment.sh'

# Cache for loaded configuration
_config_cache = None
_config_mtime = 0


def _parse_env_file(filepath):
    """Parse shell environment file and extract variables."""
    config = {}

    if not os.path.exists(filepath):
        print(f"[WARNING] Config file not found: {filepath}")
        return config

    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            # Skip empty lines and comments
            if not line or line.startswith('#'):
                continue
            # Match VAR="value" or VAR='value' or VAR=value
            match = re.match(r'^([A-Z_][A-Z0-9_]*)=(.*)$', line)
            if match:
                key = match.group(1)
                value = match.group(2)
                # Remove quotes
                if (value.startswith('"') and value.endswith('"')) or \
                   (value.startswith("'") and value.endswith("'")):
                    value = value[1:-1]
                config[key] = value

    return config


def load_config(force_reload=False):
    """Load configuration from web_environment.sh with caching."""
    global _config_cache, _config_mtime

    # Check if file has been modified
    try:
        current_mtime = os.path.getmtime(WEB_ENV_PATH)
    except OSError:
        current_mtime = 0

    if force_reload or _config_cache is None or current_mtime > _config_mtime:
        _config_cache = _parse_env_file(WEB_ENV_PATH)
        _config_mtime = current_mtime

    return _config_cache


def get_value(key, default=''):
    """Get single configuration value."""
    config = load_config()
    return config.get(key, default)


def parse_options(value_string, include_empty=False, empty_label='-- Select --'):
    """
    Parse 'value:label,value:label' format into options list.

    Args:
        value_string: String in format "value1:label1,value2:label2"
        include_empty: If True, add empty option at start
        empty_label: Label for empty option

    Returns:
        List of {'value': str, 'label': str} dicts
    """
    options = []

    if include_empty:
        options.append({'value': '', 'label': empty_label})

    if not value_string:
        return options

    for item in value_string.split(','):
        if ':' in item:
            value, label = item.split(':', 1)
            options.append({'value': value.strip(), 'label': label.strip()})
        else:
            # If no label provided, use value as label
            options.append({'value': item.strip(), 'label': item.strip()})

    return options


def get_options(key, include_empty=False, empty_label='-- Select --'):
    """
    Get options list for a configuration key.

    Args:
        key: Configuration key (e.g., 'MANIFESTS', 'BRANCHES')
        include_empty: If True, add empty option at start
        empty_label: Label for empty option

    Returns:
        List of {'value': str, 'label': str} dicts
    """
    config = load_config()
    value_string = config.get(key, '')
    return parse_options(value_string, include_empty, empty_label)


def get_manifest_options(include_empty=False, empty_label='-- All Manifests --'):
    """Get manifest options from database manifests table."""
    options = []

    if include_empty:
        options.append({'value': '', 'label': empty_label})

    try:
        from db_utils import db
        rows = db.query_all("SELECT name FROM manifests ORDER BY name")
        for row in rows:
            if row['name']:
                options.append({'value': row['name'], 'label': row['name']})
    except Exception as e:
        # Fallback to config file if DB not available
        config = load_config()
        value_string = config.get('MANIFESTS', '')
        fallback_options = parse_options(value_string, False, '')
        options.extend(fallback_options)

    return options


def get_branch_options(include_empty=False, empty_label='-- Select --'):
    """Get branch options for select fields."""
    return get_options('BRANCHES', include_empty, empty_label)


def get_platform_options(include_empty=False, empty_label='-- Select --'):
    """Get platform/OS options for select fields."""
    return get_options('PLATFORMS', include_empty, empty_label)


def get_account_options(include_empty=False, empty_label='-- All Accounts --'):
    """Get account status options for select fields."""
    return get_options('ACCOUNT_STATUSES', include_empty, empty_label)


def get_dep_options(include_empty=False, empty_label='-- Default --'):
    """Get DEP options for select fields."""
    return get_options('DEP_VALUES', include_empty, empty_label)


def get_os_update_action_options(include_empty=False, empty_label='-- Select --'):
    """Get OS update action options for select fields."""
    return get_options('OS_UPDATE_ACTIONS', include_empty, empty_label)


def get_priority_options(include_empty=False, empty_label='-- Default --'):
    """Get priority options for select fields."""
    return get_options('PRIORITIES', include_empty, empty_label)


def get_yes_no_options(include_empty=False, empty_label='-- Select --'):
    """Get yes/no options for select fields."""
    return get_options('YES_NO_OPTIONS', include_empty, empty_label)


def get_munki_profile(manifest_type):
    """
    Get Munki profile filename for given manifest type.

    Args:
        manifest_type: One of 'default', 'tech', 'bel-default', 'bel-tech'

    Returns:
        Profile filename or None
    """
    config = load_config()

    mapping = {
        'default': config.get('MUNKI_PROFILE_DEFAULT'),
        'tech': config.get('MUNKI_PROFILE_TECH'),
        'bel-default': config.get('MUNKI_PROFILE_BEL_DEFAULT'),
        'bel-tech': config.get('MUNKI_PROFILE_BEL_TECH'),
    }

    return mapping.get(manifest_type)


def get_profile_list(key):
    """
    Get list of profiles from comma-separated config value.

    Args:
        key: Configuration key (e.g., 'MACOS_BASE_PROFILES')

    Returns:
        List of profile filenames
    """
    config = load_config()
    value = config.get(key, '')
    if not value:
        return []
    return [p.strip() for p in value.split(',') if p.strip()]


def get_app_manifest(key):
    """Get application manifest URL."""
    return get_value(key, '')


def get_path(key):
    """Get path from configuration."""
    return get_value(key, '')


# Pre-built option getters for common use cases
def get_munki_type_options():
    """Get Munki type options (same as manifests but for Munki profile selection)."""
    return get_manifest_options(include_empty=False)


def get_os_filter_options():
    """Get OS filter options with auto option."""
    options = [{'value': '', 'label': '-- Auto (based on options) --'}]
    for opt in get_platform_options():
        options.append({'value': opt['value'], 'label': f"{opt['label']} Only"})
    return options


# Reload config on import to ensure fresh data
load_config(force_reload=True)


# For debugging
if __name__ == '__main__':
    print("=== Web Configuration ===")
    config = load_config()
    for key, value in sorted(config.items()):
        print(f"{key}: {value[:50]}..." if len(value) > 50 else f"{key}: {value}")

    print("\n=== Manifest Options ===")
    for opt in get_manifest_options():
        print(f"  {opt['value']}: {opt['label']}")

    print("\n=== Munki Profiles ===")
    for mtype in ['default', 'tech', 'bel-default', 'bel-tech']:
        print(f"  {mtype}: {get_munki_profile(mtype)}")
