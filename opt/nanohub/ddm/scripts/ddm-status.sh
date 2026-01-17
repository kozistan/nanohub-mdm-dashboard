#!/bin/bash
#===============================================================================
# DDM Status Script
# Shows DDM status for a device or all declarations/sets
#===============================================================================
#
# DESCRIPTION:
#   Displays DDM information from the KMFDDM server. Can show:
#   - All uploaded declarations
#   - All created sets
#   - Device-specific declaration status and errors
#
# USAGE:
#   ./ddm-status.sh [command] [options]
#
# COMMANDS:
#   declarations      List all uploaded declarations (local + server)
#   sets              List all created sets (local + server)
#   device <udid>     Show DDM status for specific device
#   all               Show all declarations and sets (default)
#
# OPTIONS:
#   -h, --help        Show this help message
#
# EXAMPLES:
#   ./ddm-status.sh                           # Show all declarations and sets
#   ./ddm-status.sh declarations              # List only declarations
#   ./ddm-status.sh sets                      # List only sets
#   ./ddm-status.sh device 3A5A07A2-7062-581F-B109-40269AA794FD
#
# DEVICE STATUS OUTPUT:
#   - Assigned sets: Which DDM sets are assigned to the device
#   - Declaration status: Status reported by device for each declaration
#     - active: Whether declaration is active on device
#     - valid: Whether declaration passed validation
#     - server-token: Hash to detect changes
#   - Status errors: Any errors reported by device
#
# NOTES:
#   Declaration status comes from what the DEVICE reported, not what
#   is currently assigned. If you remove a set, old status may remain
#   until device syncs again or status is manually cleared.
#
# SEE ALSO:
#   ddm-assign-device.sh  - Assign/remove sets from devices
#   ddm-force-sync.sh     - Force device to sync DDM
#
#===============================================================================

# Show help
if [[ "$1" == "-h" ]] || [[ "$1" == "--help" ]]; then
    sed -n '2,48p' "$0" | sed 's/^#//' | sed 's/^=/=/g'
    exit 0
fi

# Load environment
source /opt/nanohub/environment.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DDM_DIR="$(dirname "$SCRIPT_DIR")"
DDM_API="${NANOHUB_URL}/api/v1/ddm"
AUTH="nanohub:${NANOHUB_API_KEY}"

# Colors - only if running in terminal
if [ -t 1 ]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    CYAN='\033[0;36m'
    NC='\033[0m'
else
    RED=''
    GREEN=''
    YELLOW=''
    CYAN=''
    NC=''
fi

usage() {
    echo "Usage: $0 [command]"
    echo ""
    echo "Commands:"
    echo "  declarations  - List all uploaded declarations"
    echo "  sets          - List all created sets"
    echo "  device <udid> - Show DDM status for specific device"
    echo "  all           - Show all DDM information"
    echo ""
    exit 1
}

show_declarations() {
    echo -e "${CYAN}=== DDM Declarations ===${NC}"

    # Show local declarations
    echo "Local declarations in $DDM_DIR/declarations/:"
    for json_file in "$DDM_DIR/declarations"/*.json; do
        if [ -f "$json_file" ]; then
            identifier=$(basename "$json_file" .json)
            echo "  - $identifier"
        fi
    done
    echo ""

    # Query server for uploaded declarations
    echo "Server declarations:"
    response=$(curl -s -u "${AUTH}" "$DDM_API/declarations" 2>&1)
    if [ -n "$response" ] && [ "$response" != "null" ]; then
        echo "$response" | python3 -m json.tool 2>/dev/null || echo "  $response"
    else
        echo "  No declarations on server"
    fi
}

show_sets() {
    echo -e "${CYAN}=== DDM Sets ===${NC}"

    # Show local sets
    echo "Local sets in $DDM_DIR/sets/:"
    for set_file in "$DDM_DIR/sets"/*.txt; do
        if [ -f "$set_file" ]; then
            set_name=$(basename "$set_file" .txt)
            count=$(grep -v '^#' "$set_file" | grep -v '^$' | wc -l)
            echo "  - $set_name ($count declarations)"
        fi
    done
    echo ""

    # Query server for created sets
    echo "Server sets:"
    response=$(curl -s -u "${AUTH}" "$DDM_API/sets" 2>&1)
    if [ -n "$response" ] && [ "$response" != "null" ]; then
        echo "$response" | python3 -m json.tool 2>/dev/null || echo "  $response"
    else
        echo "  No sets on server"
    fi
}

show_device() {
    local udid="$1"
    echo -e "${CYAN}=== DDM Status for Device ===${NC}"
    echo "UDID: $udid"
    echo ""

    # Get enrollment sets
    echo "Assigned sets:"
    response=$(curl -s -u "${AUTH}" "$DDM_API/enrollment-sets/${udid}" 2>&1)
    if [ -n "$response" ] && [ "$response" != "null" ] && [ "$response" != "[]" ]; then
        echo "$response" | python3 -m json.tool 2>/dev/null || echo "  $response"
    else
        echo "  No DDM sets assigned to this device"
    fi
    echo ""

    # Get declaration status directly from MySQL (KMFDDM API doesn't return correct timestamps)
    echo "Declaration status:"
    db_result=$(docker exec -i mysql-nanohub mysql -u nanohub -p"${DB_PASSWORD}" nanohub -N -e "
        SELECT declaration_identifier, active, valid, server_token, updated_at
        FROM status_declarations
        WHERE enrollment_id = '${udid}'
        ORDER BY declaration_identifier;
    " 2>/dev/null)

    if [ -n "$db_result" ]; then
        echo "$db_result" | python3 -c "
import sys
entries = []
for line in sys.stdin:
    parts = line.strip().split('\t')
    if len(parts) >= 5:
        entries.append({
            'identifier': parts[0],
            'active': parts[1] == '1',
            'valid': parts[2],
            'server-token': parts[3],
            'last_update': parts[4]
        })
import json
print(json.dumps({'${udid}': entries}, indent=4))
" 2>/dev/null || echo "  Error parsing status"
    else
        echo "  No declaration status available"
    fi
    echo ""

    # Get status errors directly from MySQL
    echo "Status errors:"
    error_result=$(docker exec -i mysql-nanohub mysql -u nanohub -p"${DB_PASSWORD}" nanohub -N -e "
        SELECT declaration_identifier, reasons, updated_at
        FROM status_errors
        WHERE enrollment_id = '${udid}';
    " 2>/dev/null)

    if [ -n "$error_result" ]; then
        echo -e "${RED}"
        echo "$error_result" | python3 -c "
import sys, json
errors = []
for line in sys.stdin:
    parts = line.strip().split('\t')
    if len(parts) >= 3:
        reasons = parts[1]
        try:
            reasons = json.loads(reasons)
        except:
            pass
        errors.append({
            'identifier': parts[0],
            'reasons': reasons,
            'timestamp': parts[2]
        })
print(json.dumps(errors, indent=4))
" 2>/dev/null || echo "  $error_result"
        echo -e "${NC}"
    else
        echo -e "  ${GREEN}No errors${NC}"
    fi
}

case "${1:-all}" in
    declarations)
        show_declarations
        ;;
    sets)
        show_sets
        ;;
    device)
        if [ -z "$2" ]; then
            echo -e "${RED}Error: Device UDID required${NC}"
            usage
        fi
        show_device "$2"
        ;;
    all)
        show_declarations
        echo ""
        show_sets
        ;;
    *)
        usage
        ;;
esac
