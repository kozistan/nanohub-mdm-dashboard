#!/bin/bash
# DDM Bulk Assign Script
# Assigns a DDM set to multiple devices (comma-separated UDIDs)

# Load environment
source /opt/nanohub/environment.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DDM_API="${NANOHUB_URL}/api/v1/ddm"
NANOMDM_API="${NANOHUB_URL}/api/v1/nanomdm"
AUTH="nanohub:${NANOHUB_API_KEY}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

usage() {
    echo "Usage: $0 <device_udids> <set_name>"
    echo ""
    echo "Arguments:"
    echo "  device_udids - Comma-separated list of device UDIDs"
    echo "  set_name     - DDM set name (e.g., macos-default)"
    exit 1
}

if [ $# -ne 2 ]; then
    usage
fi

DEVICES="$1"
SET_NAME="$2"

# Validate set exists
SET_FILE="$(dirname "$SCRIPT_DIR")/sets/${SET_NAME}.txt"
if [ ! -f "$SET_FILE" ]; then
    echo -e "${RED}Error: Set '$SET_NAME' not found${NC}"
    exit 1
fi

echo "=== DDM Bulk Assignment ==="
echo "Set: $SET_NAME"
echo ""

SUCCESS=0
FAILED=0

IFS=',' read -ra DEVICE_ARRAY <<< "$DEVICES"

for UDID in "${DEVICE_ARRAY[@]}"; do
    UDID=$(echo "$UDID" | xargs)  # Trim whitespace

    if [ -z "$UDID" ]; then
        continue
    fi

    echo -n "Assigning $UDID... "

    # KMFDDM API: PUT /enrollment-sets/{enrollment-id}?set={set-name}
    response=$(curl -s -w "\n%{http_code}" -X PUT \
        -u "${AUTH}" \
        "$DDM_API/enrollment-sets/${UDID}?set=${SET_NAME}" 2>&1)

    http_code=$(echo "$response" | tail -n1)

    if [ "$http_code" = "200" ] || [ "$http_code" = "201" ] || [ "$http_code" = "204" ] || [ "$http_code" = "304" ]; then
        echo -e "${GREEN}OK${NC}"
        ((SUCCESS++))

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
echo -e "Assigned: ${GREEN}$SUCCESS${NC}"
echo -e "Failed: ${RED}$FAILED${NC}"

[ $FAILED -gt 0 ] && exit 1
exit 0
