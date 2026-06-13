#!/bin/bash
#
# NanoHUB Device Inventory SQL Query Helper (HOME VERSION)
#
# Description:
# Helper script for querying device_inventory table
# Replaces jq-based queries on devices.json file
#
# Usage:
#   source /home/microm/nanohub/environment.sh
#   db_device_query.sh <query_type> [params...]
#
# Examples:
#   db_device_query.sh get_all
#   db_device_query.sh get_by_os ios
#   db_device_query.sh get_by_hostname sloto01
#   db_device_query.sh get_by_serial FVFKQ0LW1WG7
#   db_device_query.sh get_by_uuid "1FABE57D-AD95-597F-8E02-E8251E4A1933"
#   db_device_query.sh get_by_manifest tech
#   db_device_query.sh get_uuids_by_os macos
#   db_device_query.sh search hostname sloto
#   db_device_query.sh count_by_os ios
#

# Source environment variables (prefer /opt, fallback to legacy /home)
if [ -f /opt/nanohub/environment.sh ]; then
    source /opt/nanohub/environment.sh
elif [ -f /home/microm/nanohub/environment.sh ]; then
    source /home/microm/nanohub/environment.sh
else
    echo "Error: environment.sh not found!"
    exit 1
fi

# MySQL command wrapper
function mysql_query() {
    mysql -h "$DB_HOST" -u "$DB_USER" -p"$DB_PASSWORD" "$DB_NAME" -sN -e "$1" 2>/dev/null
}

# MySQL command for formatted output (with headers)
function mysql_query_formatted() {
    mysql -h "$DB_HOST" -u "$DB_USER" -p"$DB_PASSWORD" "$DB_NAME" -e "$1" 2>/dev/null
}

# Query type
QUERY_TYPE="$1"
shift

case "$QUERY_TYPE" in
    get_all)
        # Get all devices in JSON format
        mysql_query "SELECT JSON_OBJECT('uuid', uuid, 'serial', serial, 'os', os, 'hostname', hostname, 'manifest', manifest, 'account', account, 'dep', dep) FROM device_inventory ORDER BY hostname"
        ;;

    get_by_os)
        OS="$1"
        mysql_query "SELECT JSON_OBJECT('uuid', uuid, 'serial', serial, 'os', os, 'hostname', hostname, 'manifest', manifest, 'account', account, 'dep', dep) FROM device_inventory WHERE os='$OS' ORDER BY hostname"
        ;;

    get_by_hostname)
        HOSTNAME="$1"
        mysql_query "SELECT JSON_OBJECT('uuid', uuid, 'serial', serial, 'os', os, 'hostname', hostname, 'manifest', manifest, 'account', account, 'dep', dep) FROM device_inventory WHERE hostname='$HOSTNAME' LIMIT 1"
        ;;

    get_by_serial)
        SERIAL="$1"
        mysql_query "SELECT JSON_OBJECT('uuid', uuid, 'serial', serial, 'os', os, 'hostname', hostname, 'manifest', manifest, 'account', account, 'dep', dep) FROM device_inventory WHERE serial='$SERIAL' LIMIT 1"
        ;;

    get_by_uuid)
        UUID="$1"
        mysql_query "SELECT JSON_OBJECT('uuid', uuid, 'serial', serial, 'os', os, 'hostname', hostname, 'manifest', manifest, 'account', account, 'dep', dep) FROM device_inventory WHERE uuid='$UUID' LIMIT 1"
        ;;

    get_by_manifest)
        MANIFEST="$1"
        mysql_query "SELECT JSON_OBJECT('uuid', uuid, 'serial', serial, 'os', os, 'hostname', hostname, 'manifest', manifest, 'account', account, 'dep', dep) FROM device_inventory WHERE manifest='$MANIFEST' ORDER BY hostname"
        ;;

    get_uuids_by_os)
        # Get only UUIDs for specific OS (used by bulk scripts)
        OS="$1"
        mysql_query "SELECT uuid FROM device_inventory WHERE os='$OS' ORDER BY hostname"
        ;;

    get_uuids_by_manifest)
        # Get UUIDs filtered by manifest
        MANIFEST="$1"
        mysql_query "SELECT uuid FROM device_inventory WHERE manifest='$MANIFEST' ORDER BY hostname"
        ;;

    get_uuids_by_os_and_manifest)
        # Get UUIDs filtered by OS and manifest
        OS="$1"
        MANIFEST="$2"
        mysql_query "SELECT uuid FROM device_inventory WHERE os='$OS' AND manifest='$MANIFEST' ORDER BY hostname"
        ;;

    search)
        # Search in specific field (contains match)
        FIELD="$1"
        VALUE="$2"
        mysql_query "SELECT JSON_OBJECT('uuid', uuid, 'serial', serial, 'os', os, 'hostname', hostname, 'manifest', manifest, 'account', account, 'dep', dep) FROM device_inventory WHERE $FIELD LIKE '%$VALUE%' ORDER BY hostname"
        ;;

    count_all)
        mysql_query "SELECT COUNT(*) FROM device_inventory"
        ;;

    count_by_os)
        OS="$1"
        mysql_query "SELECT COUNT(*) FROM device_inventory WHERE os='$OS'"
        ;;

    list_manifests)
        mysql_query "SELECT DISTINCT manifest FROM device_inventory ORDER BY manifest"
        ;;

    list_os)
        mysql_query "SELECT DISTINCT os FROM device_inventory ORDER BY os"
        ;;

    table_info)
        mysql_query_formatted "DESCRIBE device_inventory"
        ;;

    *)
        echo "Usage: $0 <query_type> [params...]"
        echo ""
        echo "Query types:"
        echo "  get_all                              - Get all devices (JSON)"
        echo "  get_by_os <os>                       - Get devices by OS"
        echo "  get_by_hostname <hostname>           - Get device by hostname"
        echo "  get_by_serial <serial>               - Get device by serial"
        echo "  get_by_uuid <uuid>                   - Get device by UUID"
        echo "  get_by_manifest <manifest>           - Get devices by manifest"
        echo "  get_uuids_by_os <os>                 - Get UUIDs only for OS"
        echo "  get_uuids_by_manifest <manifest>     - Get UUIDs by manifest"
        echo "  get_uuids_by_os_and_manifest <os> <manifest> - Get UUIDs by OS and manifest"
        echo "  search <field> <value>               - Search in field (LIKE)"
        echo "  count_all                            - Count all devices"
        echo "  count_by_os <os>                     - Count devices by OS"
        echo "  list_manifests                       - List all manifest types"
        echo "  list_os                              - List all OS types"
        echo "  table_info                           - Show table structure"
        echo ""
        exit 1
        ;;
esac
