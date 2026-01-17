#!/bin/bash
#===============================================================================
# DDM Assign/Remove Device Script
# Assigns or removes a DDM set to/from a device by UDID
#===============================================================================
#
# DESCRIPTION:
#   Manages DDM set assignments for individual devices. Can assign a new set
#   to a device or remove an existing set assignment. After successful
#   operation, sends push notification to trigger device sync.
#
# USAGE:
#   ./ddm-assign-device.sh <action> <device_udid> <set_name>
#
# ARGUMENTS:
#   action        Action to perform: 'assign' or 'remove'
#   device_udid   Device UDID (UUID format)
#   set_name      DDM set name (must exist in /opt/nanohub/ddm/sets/)
#
# OPTIONS:
#   -h, --help    Show this help message
#
# EXAMPLES:
#   # Assign a set to device
#   ./ddm-assign-device.sh assign 3A5A07A2-7062-581F-B109-40269AA794FD sloto-macos-karlin-default
#
#   # Remove a set from device
#   ./ddm-assign-device.sh remove 3A5A07A2-7062-581F-B109-40269AA794FD sloto-macos-karlin-default
#
# IMPORTANT NOTES:
#   - DDM sets are ADDITIVE. Assigning a new set does NOT remove old sets.
#     To replace a set, you must explicitly remove the old one first.
#
#   - When removing the LAST set from a device, this script automatically
#     clears the device's status_declarations and status_errors from MySQL.
#     This is because KMFDDM doesn't clean up status data automatically.
#
#   - After assign/remove, a push notification is sent to the device.
#     Device will sync DDM on next wake/unlock.
#
# DATABASE CLEANUP (on remove):
#   When a device has no remaining sets after removal, these tables are cleared:
#   - status_declarations: Device-reported declaration status
#   - status_errors: Device-reported declaration errors
#
# SEE ALSO:
#   ddm-bulk-assign.sh    - Assign/remove sets for multiple devices
#   ddm-status.sh         - View device DDM status
#   ddm-force-sync.sh     - Force device to sync
#   ddm-create-sets.sh    - Create new sets
#
#===============================================================================

# Show help
if [[ "$1" == "-h" ]] || [[ "$1" == "--help" ]]; then
    sed -n '2,52p' "$0" | sed 's/^#//' | sed 's/^=/=/g'
    exit 0
fi

# Load environment
source /opt/nanohub/environment.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DDM_API="${NANOHUB_URL}/api/v1/ddm"
NANOMDM_API="${NANOHUB_URL}/api/v1/nanomdm"
AUTH="nanohub:${NANOHUB_API_KEY}"

# Colors - only if running in terminal
if [ -t 1 ]; then
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'
else
    RED=''
    GREEN=''
    YELLOW=''
    CYAN=''
    NC=''
fi

usage() {
    echo "Usage: $0 <action> <device_udid> <set_name>"
    echo ""
    echo "Arguments:"
    echo "  action       - 'assign' or 'remove'"
    echo "  device_udid  - Device UDID"
    echo "  set_name     - DDM set name (e.g., sloto-macos-karlin-default)"
    echo ""
    echo "Available sets:"
    for set_file in "$(dirname "$SCRIPT_DIR")/sets"/*.txt; do
        [ -f "$set_file" ] && echo "  - $(basename "$set_file" .txt)"
    done
    exit 1
}

if [ $# -ne 3 ]; then
    usage
fi

ACTION="$1"
DEVICE_UDID="$2"
SET_NAME="$3"

# Validate action
if [ "$ACTION" != "assign" ] && [ "$ACTION" != "remove" ]; then
    echo -e "${RED}Error: Invalid action '$ACTION'. Use 'assign' or 'remove'.${NC}"
    exit 1
fi

# Validate set exists (for assign) or is known (for remove)
SET_FILE="$(dirname "$SCRIPT_DIR")/sets/${SET_NAME}.txt"
if [ "$ACTION" = "assign" ] && [ ! -f "$SET_FILE" ]; then
    echo -e "${RED}Error: Set '$SET_NAME' not found${NC}"
    echo "Available sets:"
    for set_file in "$(dirname "$SCRIPT_DIR")/sets"/*.txt; do
        [ -f "$set_file" ] && echo "  - $(basename "$set_file" .txt)"
    done
    exit 1
fi

echo "=== DDM Device ${ACTION^} ==="
echo "Device UDID: $DEVICE_UDID"
echo "Set: $SET_NAME"
echo "Action: $ACTION"
echo ""

if [ "$ACTION" = "assign" ]; then
    echo -n "Assigning device to set... "
    # KMFDDM API: PUT /enrollment-sets/{enrollment-id}?set={set-name}
    response=$(curl -s -w "\n%{http_code}" -X PUT \
        -u "${AUTH}" \
        "$DDM_API/enrollment-sets/${DEVICE_UDID}?set=${SET_NAME}" 2>&1)
else
    echo -n "Removing device from set... "
    # KMFDDM API: DELETE /enrollment-sets/{enrollment-id}?set={set-name}
    response=$(curl -s -w "\n%{http_code}" -X DELETE \
        -u "${AUTH}" \
        "$DDM_API/enrollment-sets/${DEVICE_UDID}?set=${SET_NAME}" 2>&1)
fi

http_code=$(echo "$response" | tail -n1)
body=$(echo "$response" | sed '$d')

if [ "$http_code" = "200" ] || [ "$http_code" = "201" ] || [ "$http_code" = "204" ] || [ "$http_code" = "304" ]; then
    echo -e "${GREEN}OK${NC}"
    echo ""
    if [ "$ACTION" = "assign" ]; then
        echo "Device $DEVICE_UDID assigned to set $SET_NAME"
    else
        echo "Device $DEVICE_UDID removed from set $SET_NAME"

        # Check if device has any remaining sets
        remaining=$(curl -s -u "${AUTH}" "$DDM_API/enrollment-sets/${DEVICE_UDID}" 2>/dev/null)
        if [ "$remaining" = "null" ] || [ "$remaining" = "[]" ] || [ -z "$remaining" ]; then
            echo -n "Clearing DDM status from database... "
            # Clear status_declarations for this device (no sets = no declarations)
            docker exec -i mysql-nanohub mysql -u nanohub -p"${DB_PASSWORD}" nanohub \
                -e "DELETE FROM status_declarations WHERE enrollment_id = '${DEVICE_UDID}';" 2>/dev/null
            # Clear status_errors too
            docker exec -i mysql-nanohub mysql -u nanohub -p"${DB_PASSWORD}" nanohub \
                -e "DELETE FROM status_errors WHERE enrollment_id = '${DEVICE_UDID}';" 2>/dev/null
            echo -e "${GREEN}OK${NC}"
        fi
    fi
    echo -n "Triggering DDM sync... "

    # Send push notification to device
    curl -s -X PUT \
        -u "${AUTH}" \
        "$NANOMDM_API/push/${DEVICE_UDID}" > /dev/null 2>&1

    echo -e "${GREEN}Done${NC}"
    echo "Device will receive DDM update on next check-in."
    exit 0
else
    echo -e "${RED}FAILED (HTTP $http_code)${NC}"
    [ -n "$body" ] && echo "Response: $body"
    exit 1
fi
