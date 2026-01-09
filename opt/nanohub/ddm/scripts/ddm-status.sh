#!/bin/bash
# DDM Status Script
# Shows DDM status for a device or all declarations/sets

# Load environment
source /opt/nanohub/environment.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DDM_DIR="$(dirname "$SCRIPT_DIR")"
DDM_API="${NANOHUB_URL}/api/v1/ddm"
AUTH="nanohub:${NANOHUB_API_KEY}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

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

    # Get declaration status (deduplicated - KMFDDM bug causes duplicates via set_declarations join)
    echo "Declaration status:"
    response=$(curl -s -u "${AUTH}" "$DDM_API/declaration-status/${udid}" 2>&1)
    if [ -n "$response" ] && [ "$response" != "null" ] && [ "$response" != "[]" ]; then
        # Deduplicate by identifier
        echo "$response" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for key, items in data.items():
    seen = {}
    for item in items:
        ident = item.get('identifier', '')
        if ident not in seen:
            seen[ident] = item
    data[key] = list(seen.values())
print(json.dumps(data, indent=4))
" 2>/dev/null || echo "  $response"
    else
        echo "  No declaration status available"
    fi
    echo ""

    # Get status errors
    echo "Status errors:"
    response=$(curl -s -u "${AUTH}" "$DDM_API/status-errors/${udid}" 2>&1)
    if [ -n "$response" ] && [ "$response" != "null" ] && [ "$response" != "[]" ] && [ "$response" != "{}" ]; then
        echo -e "${RED}"
        echo "$response" | python3 -m json.tool 2>/dev/null || echo "  $response"
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
