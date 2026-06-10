#!/bin/bash
#
# Import devices.json to device_inventory SQL table
#
# Usage: ./import_json_to_sql_v2.sh
#

# Source environment variables
source /opt/nanohub/environment.sh

JSON_FILE="/home/microm/nanohub/data/devices.json"

echo "============================================================"
echo "  NANOHUB - Import devices.json to MySQL"
echo "============================================================"
echo "JSON file: $JSON_FILE"
echo "Database: $DB_NAME"
echo ""

# Check if JSON file exists
if [[ ! -f "$JSON_FILE" ]]; then
    echo "❌ Error: JSON file not found: $JSON_FILE"
    exit 1
fi

# Check if jq is installed
if ! command -v jq &> /dev/null; then
    echo "❌ Error: jq is required but not installed"
    exit 1
fi

echo "[1/4] Reading JSON file..."
DEVICE_COUNT=$(jq '. | length' "$JSON_FILE")
echo "✓ Found $DEVICE_COUNT devices in JSON"

echo ""
echo "[2/4] Connecting to MySQL..."
mysql -h "$DB_HOST" -u "$DB_USER" -p"$DB_PASSWORD" "$DB_NAME" -e "SELECT 1" > /dev/null 2>&1
if [[ $? -ne 0 ]]; then
    echo "❌ Error: Cannot connect to MySQL"
    exit 1
fi
echo "✓ Connected to MySQL"

echo ""
echo "[3/4] Importing devices..."
SUCCESS_COUNT=0
ERROR_COUNT=0

# Process each device
jq -c '.[]' "$JSON_FILE" | while read -r device; do
    UUID=$(echo "$device" | jq -r '.uuid')
    SERIAL=$(echo "$device" | jq -r '.serial')
    OS=$(echo "$device" | jq -r '.os')
    HOSTNAME=$(echo "$device" | jq -r '.hostname')
    MANIFEST=$(echo "$device" | jq -r '.manifest')
    ACCOUNT=$(echo "$device" | jq -r '.account')
    DEP=$(echo "$device" | jq -r '.dep')

    # Validate required fields
    if [[ -z "$UUID" || -z "$SERIAL" || -z "$OS" || -z "$HOSTNAME" ]]; then
        echo "  ⚠ Skipping device: missing required fields"
        ((ERROR_COUNT++))
        continue
    fi

    # Escape single quotes for SQL
    HOSTNAME="${HOSTNAME//\'/\'\'}"

    # Insert or update device
    SQL="INSERT INTO device_inventory (uuid, serial, os, hostname, manifest, account, dep)
         VALUES ('$UUID', '$SERIAL', '$OS', '$HOSTNAME', '$MANIFEST', '$ACCOUNT', '$DEP')
         ON DUPLICATE KEY UPDATE
             serial = VALUES(serial),
             os = VALUES(os),
             hostname = VALUES(hostname),
             manifest = VALUES(manifest),
             account = VALUES(account),
             dep = VALUES(dep),
             updated_at = CURRENT_TIMESTAMP;"

    mysql -h "$DB_HOST" -u "$DB_USER" -p"$DB_PASSWORD" "$DB_NAME" -e "$SQL" 2>/dev/null

    if [[ $? -eq 0 ]]; then
        echo "  ✓ Imported: $HOSTNAME ($UUID)"
        ((SUCCESS_COUNT++))
    else
        echo "  ❌ Error importing: $HOSTNAME ($UUID)"
        ((ERROR_COUNT++))
    fi
done

echo ""
echo "[4/4] Verifying import..."
TOTAL_IN_DB=$(mysql -h "$DB_HOST" -u "$DB_USER" -p"$DB_PASSWORD" "$DB_NAME" -sN -e "SELECT COUNT(*) FROM device_inventory" 2>/dev/null)
echo "✓ Total devices in database: $TOTAL_IN_DB"

echo ""
echo "============================================================"
echo "  IMPORT SUMMARY"
echo "============================================================"
echo "Total devices in JSON:    $DEVICE_COUNT"
echo "Total in database:        $TOTAL_IN_DB"
echo "============================================================"

if [[ "$TOTAL_IN_DB" -eq "$DEVICE_COUNT" ]]; then
    echo "✓ Import completed successfully!"
    exit 0
else
    echo "⚠ Warning: Device counts don't match!"
    exit 1
fi
