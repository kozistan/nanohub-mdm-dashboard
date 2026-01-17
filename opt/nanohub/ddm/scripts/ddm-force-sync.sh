#!/bin/bash
#===============================================================================
# DDM Force Sync Script
# Sends push notification to force device to sync DDM declarations
#===============================================================================
#
# DESCRIPTION:
#   Sends an APNs push notification to a device to trigger DDM synchronization.
#   The device will connect to the MDM server and sync its declarations on
#   the next wake/unlock event after receiving the push.
#
# USAGE:
#   ./ddm-force-sync.sh <device_udid>
#
# ARGUMENTS:
#   device_udid   Device UDID (UUID format)
#
# OPTIONS:
#   -h, --help    Show this help message
#
# EXAMPLES:
#   ./ddm-force-sync.sh 3A5A07A2-7062-581F-B109-40269AA794FD
#
# HOW IT WORKS:
#   1. Script sends push notification via NanoMDM API
#   2. APNs delivers notification to device
#   3. Device wakes (if sleeping) and contacts MDM server
#   4. Device requests current declaration manifest from KMFDDM
#   5. Device applies/removes declarations based on manifest
#   6. Device reports back status to KMFDDM
#
# WHEN TO USE:
#   - After assigning/removing DDM sets (automatic push is sent)
#   - When device seems out of sync
#   - To verify device is responding to MDM
#   - After making changes to declarations
#
# NOTES:
#   - Push is delivered via APNs, device must have internet connectivity
#   - Device will sync on next wake/unlock, not immediately
#   - If device is offline, push will be delivered when it comes online
#
# SEE ALSO:
#   ddm-assign-device.sh  - Assign/remove sets (sends push automatically)
#   ddm-status.sh         - View device DDM status after sync
#
#===============================================================================

# Show help
if [[ "$1" == "-h" ]] || [[ "$1" == "--help" ]]; then
    sed -n '2,47p' "$0" | sed 's/^#//' | sed 's/^=/=/g'
    exit 0
fi

# Load environment
source /opt/nanohub/environment.sh

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

if [ $# -ne 1 ]; then
    echo "Usage: $0 <device_udid>"
    echo ""
    echo "Sends push notification to device to force DDM sync."
    exit 1
fi

DEVICE_UDID="$1"

echo "=== DDM Force Sync ==="
echo "Device UDID: $DEVICE_UDID"
echo ""

echo -n "Sending push notification... "

response=$(curl -s -w "\n%{http_code}" -X PUT \
    -u "${AUTH}" \
    "$NANOMDM_API/push/${DEVICE_UDID}" 2>&1)

http_code=$(echo "$response" | tail -n1)
body=$(echo "$response" | sed '$d')

if [ "$http_code" = "200" ] || [ "$http_code" = "201" ]; then
    echo -e "${GREEN}OK${NC}"
    echo ""
    echo "Push sent to device $DEVICE_UDID"
    echo "Device will sync DDM declarations on next wake/unlock."

    # Parse push result if available
    if echo "$body" | grep -q "push_result"; then
        push_id=$(echo "$body" | grep -o '"push_result":"[^"]*"' | cut -d'"' -f4)
        echo "Push ID: $push_id"
    fi
    exit 0
else
    echo -e "${RED}FAILED (HTTP $http_code)${NC}"
    [ -n "$body" ] && echo "Response: $body"
    exit 1
fi
