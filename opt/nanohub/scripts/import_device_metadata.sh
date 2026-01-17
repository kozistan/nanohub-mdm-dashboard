#!/bin/bash

# Source environment variables
source /opt/nanohub/environment.sh

DB="${DB_NAME:-nanohub}"
USER="${DB_USER:-nanohub}"
PASS="${DB_PASSWORD}"
JSON_PATH="/home/microm/nanohub/data/devices.json"

echo "[INFO] Importing devices from $JSON_PATH into database $DB..."

cat "$JSON_PATH" | jq -c '.[]' | while read -r device; do
    UDID=$(echo "$device" | jq -r '.udid')
    SERIAL=$(echo "$device" | jq -r '.serial_number')
    WORKFLOW=$(echo "$device" | jq -r '.workflow_name')

    PLACEHOLDER_AUTH='<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd"><plist version="1.0"><dict></dict></plist>'

    SQL="INSERT INTO devices (id, serial_number, authenticate, authenticate_at, created_at, updated_at)
          VALUES ('$UDID', '$SERIAL', '$PLACEHOLDER_AUTH', NULL, NOW(), NOW())
          ON DUPLICATE KEY UPDATE serial_number=VALUES(serial_number), updated_at=NOW();"

    SQL2="INSERT INTO wf_status (id, name)
          VALUES ('$UDID', '$WORKFLOW')
          ON DUPLICATE KEY UPDATE updated_at=NOW();"

    echo "--------------"
    echo "$SQL"
    echo "$SQL" | mysql -h 127.0.0.1 -u "$USER" -p"$PASS" "$DB"

    echo "$SQL2"
    echo "$SQL2" | mysql -h 127.0.0.1 -u "$USER" -p"$PASS" "$DB"

    echo "[OK] $UDID imported."
done

echo "[DONE] Import complete."
