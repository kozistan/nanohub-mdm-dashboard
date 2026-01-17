#!/bin/bash
#===============================================================================
# DDM Bulk Assign/Remove Script
# Assigns or removes a DDM set to/from multiple devices
#===============================================================================
#
# DESCRIPTION:
#   Manages DDM set assignments for multiple devices at once. Accepts a
#   comma-separated list of device UDIDs and performs the assign/remove
#   action on each device. Sends push notification after each operation.
#
# USAGE:
#   ./ddm-bulk-assign.sh <action> <device_udids> <set_name>
#
# ARGUMENTS:
#   action        Action to perform: 'assign' or 'remove'
#   device_udids  Comma-separated list of device UDIDs (no spaces)
#   set_name      DDM set name (must exist in /opt/nanohub/ddm/sets/)
#
# OPTIONS:
#   -h, --help    Show this help message
#
# EXAMPLES:
#   # Assign set to multiple devices
#   ./ddm-bulk-assign.sh assign "UDID1,UDID2,UDID3" sloto-macos-karlin-default
#
#   # Remove set from multiple devices
#   ./ddm-bulk-assign.sh remove "UDID1,UDID2,UDID3" sloto-macos-karlin-default
#
#   # Real example with UDIDs
#   ./ddm-bulk-assign.sh assign "3A5A07A2-7062-581F-B109-40269AA794FD,B2C3D4E5-6789-ABCD-EF01-234567890ABC" sloto-macos-karlin-default
#
# IMPORTANT NOTES:
#   - DDM sets are ADDITIVE. Assigning a new set does NOT remove old sets.
#   - When removing the LAST set from a device, status data is auto-cleared.
#   - Each device receives a push notification after its operation completes.
#
# OUTPUT:
#   Shows progress for each device and final summary of success/failed counts.
#
# SEE ALSO:
#   ddm-assign-device.sh  - Assign/remove for single device
#   ddm-status.sh         - View device DDM status
#   ddm-force-sync.sh     - Force device to sync
#
#===============================================================================

# Show help
if [[ "$1" == "-h" ]] || [[ "$1" == "--help" ]]; then
    sed -n '2,46p' "$0" | sed 's/^#//' | sed 's/^=/=/g'
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
    echo "Usage: $0 <action> <device_udids> <set_name>"
    echo ""
    echo "Arguments:"
    echo "  action       - 'assign' or 'remove'"
    echo "  device_udids - Comma-separated list of device UDIDs"
    echo "  set_name     - DDM set name (e.g., sloto-macos-karlin-default)"
    exit 1
}

if [ $# -ne 3 ]; then
    usage
fi

ACTION="$1"
DEVICES="$2"
SET_NAME="$3"

# Validate action
if [ "$ACTION" != "assign" ] && [ "$ACTION" != "remove" ]; then
    echo -e "${RED}Error: Invalid action '$ACTION'. Use 'assign' or 'remove'.${NC}"
    exit 1
fi

# Validate set exists (for assign)
SET_FILE="$(dirname "$SCRIPT_DIR")/sets/${SET_NAME}.txt"
if [ "$ACTION" = "assign" ] && [ ! -f "$SET_FILE" ]; then
    echo -e "${RED}Error: Set '$SET_NAME' not found${NC}"
    exit 1
fi

echo "=== DDM Bulk ${ACTION^} ==="
echo "Set: $SET_NAME"
echo "Action: $ACTION"
echo ""

SUCCESS=0
FAILED=0

IFS=',' read -ra DEVICE_ARRAY <<< "$DEVICES"

for UDID in "${DEVICE_ARRAY[@]}"; do
    UDID=$(echo "$UDID" | xargs)  # Trim whitespace

    if [ -z "$UDID" ]; then
        continue
    fi

    if [ "$ACTION" = "assign" ]; then
        echo -n "Assigning $UDID... "
        HTTP_METHOD="PUT"
    else
        echo -n "Removing $UDID... "
        HTTP_METHOD="DELETE"
    fi

    # KMFDDM API: PUT/DELETE /enrollment-sets/{enrollment-id}?set={set-name}
    response=$(curl -s -w "\n%{http_code}" -X "$HTTP_METHOD" \
        -u "${AUTH}" \
        "$DDM_API/enrollment-sets/${UDID}?set=${SET_NAME}" 2>&1)

    http_code=$(echo "$response" | tail -n1)

    if [ "$http_code" = "200" ] || [ "$http_code" = "201" ] || [ "$http_code" = "204" ] || [ "$http_code" = "304" ]; then
        echo -e "${GREEN}OK${NC}"
        ((SUCCESS++))

        # For remove: clear status if no remaining sets
        if [ "$ACTION" = "remove" ]; then
            remaining=$(curl -s -u "${AUTH}" "$DDM_API/enrollment-sets/${UDID}" 2>/dev/null)
            if [ "$remaining" = "null" ] || [ "$remaining" = "[]" ] || [ -z "$remaining" ]; then
                docker exec -i mysql-nanohub mysql -u nanohub -p"${DB_PASSWORD}" nanohub \
                    -e "DELETE FROM status_declarations WHERE enrollment_id = '${UDID}';" 2>/dev/null
                docker exec -i mysql-nanohub mysql -u nanohub -p"${DB_PASSWORD}" nanohub \
                    -e "DELETE FROM status_errors WHERE enrollment_id = '${UDID}';" 2>/dev/null
            fi
        fi

        # Send push notification
        curl -s -X PUT \
            -u "${AUTH}" \
            "$NANOMDM_API/push/${UDID}" > /dev/null 2>&1
    else
        echo -e "${RED}FAILED (HTTP $http_code)${NC}"
        ((FAILED++))
    fi
done

echo ""
echo "=== Summary ==="
if [ "$ACTION" = "assign" ]; then
    echo -e "Assigned: ${GREEN}$SUCCESS${NC}"
else
    echo -e "Removed: ${GREEN}$SUCCESS${NC}"
fi
echo -e "Failed: ${RED}$FAILED${NC}"

[ $FAILED -gt 0 ] && exit 1
exit 0
