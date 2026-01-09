#!/bin/bash
# DDM Assign Device Script
# Assigns a DDM set to a device by UDID

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
    echo "Usage: $0 <device_udid> <set_name>"
    echo ""
    echo "Arguments:"
    echo "  device_udid  - Device UDID to assign"
    echo "  set_name     - DDM set name (e.g., macos-default)"
    echo ""
    echo "Available sets:"
    for set_file in "$(dirname "$SCRIPT_DIR")/sets"/*.txt; do
        [ -f "$set_file" ] && echo "  - $(basename "$set_file" .txt)"
    done
    exit 1
}

if [ $# -ne 2 ]; then
    usage
fi

DEVICE_UDID="$1"
SET_NAME="$2"

# Validate set exists
SET_FILE="$(dirname "$SCRIPT_DIR")/sets/${SET_NAME}.txt"
if [ ! -f "$SET_FILE" ]; then
    echo -e "${RED}Error: Set '$SET_NAME' not found${NC}"
    echo "Available sets:"
    for set_file in "$(dirname "$SCRIPT_DIR")/sets"/*.txt; do
        [ -f "$set_file" ] && echo "  - $(basename "$set_file" .txt)"
    done
    exit 1
fi

echo "=== DDM Device Assignment ==="
echo "Device UDID: $DEVICE_UDID"
echo "Set: $SET_NAME"
echo ""

echo -n "Assigning device to set... "

# KMFDDM API: PUT /enrollment-sets/{enrollment-id}?set={set-name}
response=$(curl -s -w "\n%{http_code}" -X PUT \
    -u "${AUTH}" \
    "$DDM_API/enrollment-sets/${DEVICE_UDID}?set=${SET_NAME}" 2>&1)

http_code=$(echo "$response" | tail -n1)
body=$(echo "$response" | sed '$d')

if [ "$http_code" = "200" ] || [ "$http_code" = "201" ] || [ "$http_code" = "204" ] || [ "$http_code" = "304" ]; then
    echo -e "${GREEN}OK${NC}"
    echo ""
    echo "Device $DEVICE_UDID assigned to set $SET_NAME"
    echo -n "Triggering DDM sync... "

    # Send push notification to device
    curl -s -X PUT \
        -u "${AUTH}" \
        "$NANOMDM_API/push/${DEVICE_UDID}" > /dev/null 2>&1

    echo -e "${GREEN}Done${NC}"
    echo "Device will receive DDM declarations on next check-in."
    exit 0
else
    echo -e "${RED}FAILED (HTTP $http_code)${NC}"
    [ -n "$body" ] && echo "Response: $body"
    exit 1
fi
