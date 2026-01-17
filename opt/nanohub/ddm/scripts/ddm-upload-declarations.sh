#!/bin/bash
#===============================================================================
# DDM Upload Declarations Script
# Uploads all declaration JSON files to KMFDDM server
#===============================================================================
#
# DESCRIPTION:
#   Scans the declarations directory and uploads all JSON files to the
#   KMFDDM server. Each JSON file should contain a valid Apple DDM declaration
#   with an 'Identifier' field.
#
# USAGE:
#   ./ddm-upload-declarations.sh [options]
#
# OPTIONS:
#   -h, --help     Show this help message
#
# EXAMPLES:
#   ./ddm-upload-declarations.sh              # Upload all declarations
#
# DIRECTORY STRUCTURE:
#   /opt/nanohub/ddm/declarations/            # Declaration JSON files
#     ├── activation.macos-karlin.json
#     ├── softwareupdate.macos.json
#     └── ...
#
# WORKFLOW:
#   1. First run this script to upload declarations to KMFDDM
#   2. Then run ddm-create-sets.sh to create sets from declarations
#   3. Then run ddm-assign-device.sh to assign sets to devices
#
# SEE ALSO:
#   ddm-create-sets.sh    - Create sets from uploaded declarations
#   ddm-status.sh         - View uploaded declarations and sets
#   ddm-assign-device.sh  - Assign sets to devices
#
#===============================================================================

# Show help
if [[ "$1" == "-h" ]] || [[ "$1" == "--help" ]]; then
    sed -n '2,37p' "$0" | sed 's/^#//' | sed 's/^=/=/g'
    exit 0
fi

# Load environment
source /opt/nanohub/environment.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DDM_DIR="$(dirname "$SCRIPT_DIR")"
DECLARATIONS_DIR="$DDM_DIR/declarations"
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

echo "=== DDM Declaration Upload ==="
echo "Declarations directory: $DECLARATIONS_DIR"
echo ""

if [ ! -d "$DECLARATIONS_DIR" ]; then
    echo -e "${RED}Error: Declarations directory not found${NC}"
    exit 1
fi

SUCCESS=0
FAILED=0

for json_file in "$DECLARATIONS_DIR"/*.json; do
    if [ -f "$json_file" ]; then
        identifier=$(jq -r '.Identifier' "$json_file" 2>/dev/null)
        if [ -z "$identifier" ] || [ "$identifier" = "null" ]; then
            identifier=$(basename "$json_file" .json)
        fi

        echo -n "Uploading $identifier... "

        response=$(curl -s -w "\n%{http_code}" -X PUT \
            -u "${AUTH}" \
            -d @"$json_file" \
            "$DDM_API/declarations" 2>&1)

        http_code=$(echo "$response" | tail -n1)
        body=$(echo "$response" | sed '$d')

        if [ "$http_code" = "200" ] || [ "$http_code" = "201" ] || [ "$http_code" = "204" ] || [ "$http_code" = "304" ] || [ -z "$http_code" ]; then
            echo -e "${GREEN}OK${NC}"
            ((SUCCESS++))
        else
            echo -e "${RED}FAILED (HTTP $http_code)${NC}"
            [ -n "$body" ] && echo "  Response: $body"
            ((FAILED++))
        fi
    fi
done

echo ""
echo "=== Summary ==="
echo -e "Uploaded: ${GREEN}$SUCCESS${NC}"
echo -e "Failed: ${RED}$FAILED${NC}"

[ $FAILED -gt 0 ] && exit 1
exit 0
