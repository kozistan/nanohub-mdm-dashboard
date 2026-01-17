#!/bin/bash
#===============================================================================
# DDM Create Sets Script
# Creates DDM sets by adding declarations to them
#===============================================================================
#
# DESCRIPTION:
#   Reads set definition files (.txt) from the sets directory and creates
#   corresponding sets in KMFDDM by associating declarations with set names.
#   Each .txt file defines one set, with one declaration identifier per line.
#
# USAGE:
#   ./ddm-create-sets.sh [options]
#
# OPTIONS:
#   -h, --help     Show this help message
#
# EXAMPLES:
#   ./ddm-create-sets.sh                      # Create all sets
#
# SET FILE FORMAT:
#   Each .txt file in /opt/nanohub/ddm/sets/ defines a set.
#   File name (without .txt) becomes the set name.
#   Contents: one declaration identifier per line.
#   Lines starting with # are comments.
#
#   Example: sloto-macos-karlin-default.txt
#     # Default set for Karlin macOS devices
#     com.sloto.ddm.activation.macos-karlin
#     com.sloto.ddm.softwareupdate.macos
#     com.sloto.ddm.passcode
#
# WORKFLOW:
#   1. First run ddm-upload-declarations.sh to upload declarations
#   2. Then run this script to create sets from declarations
#   3. Then run ddm-assign-device.sh to assign sets to devices
#
# SEE ALSO:
#   ddm-upload-declarations.sh  - Upload declarations first
#   ddm-status.sh               - View created sets
#   ddm-assign-device.sh        - Assign sets to devices
#
#===============================================================================

# Show help
if [[ "$1" == "-h" ]] || [[ "$1" == "--help" ]]; then
    sed -n '2,43p' "$0" | sed 's/^#//' | sed 's/^=/=/g'
    exit 0
fi

# Load environment
source /opt/nanohub/environment.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DDM_DIR="$(dirname "$SCRIPT_DIR")"
SETS_DIR="$DDM_DIR/sets"
DDM_API="${NANOHUB_URL}/api/v1/ddm"
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

echo "=== DDM Set Creation ==="
echo "Sets directory: $SETS_DIR"
echo ""

if [ ! -d "$SETS_DIR" ]; then
    echo -e "${RED}Error: Sets directory not found${NC}"
    exit 1
fi

SUCCESS=0
FAILED=0

for set_file in "$SETS_DIR"/*.txt; do
    if [ -f "$set_file" ]; then
        set_name=$(basename "$set_file" .txt)

        echo "Processing set: $set_name"

        # Add declarations to the set
        # KMFDDM API: PUT /set-declarations/{set-name}?declaration={decl-id}
        while IFS= read -r line; do
            # Skip comments and empty lines
            [[ "$line" =~ ^#.*$ ]] && continue
            [[ -z "$line" ]] && continue

            decl_id=$(echo "$line" | xargs)  # Trim whitespace

            echo -n "  Adding $decl_id... "
            response=$(curl -s -w "\n%{http_code}" -X PUT \
                -u "${AUTH}" \
                "$DDM_API/set-declarations/${set_name}?declaration=${decl_id}" 2>&1)

            http_code=$(echo "$response" | tail -n1)

            if [ "$http_code" = "200" ] || [ "$http_code" = "201" ] || [ "$http_code" = "204" ] || [ "$http_code" = "304" ]; then
                echo -e "${GREEN}OK${NC}"
            else
                echo -e "${RED}FAILED (HTTP $http_code)${NC}"
            fi
        done < "$set_file"

        ((SUCCESS++))
        echo ""
    fi
done

echo "=== Summary ==="
echo -e "Sets processed: ${GREEN}$SUCCESS${NC}"

exit 0
