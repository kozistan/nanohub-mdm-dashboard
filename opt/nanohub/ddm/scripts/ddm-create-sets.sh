#!/bin/bash
# DDM Create Sets Script
# Creates DDM sets by adding declarations to them

# Load environment
source /opt/nanohub/environment.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DDM_DIR="$(dirname "$SCRIPT_DIR")"
SETS_DIR="$DDM_DIR/sets"
DDM_API="${NANOHUB_URL}/api/v1/ddm"
AUTH="nanohub:${NANOHUB_API_KEY}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

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
