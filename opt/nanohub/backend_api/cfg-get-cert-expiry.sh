#!/bin/bash
# NanoHUB Certificate and Token Expiry Script
# Shows expiry dates for: DEP Token, VPP Token, MDM Vendor Cert, APNs Push Cert
# Output format: name|usage|expiry|renewal_url

CERTDIR="/opt/nanohub/dep"
ENV_FILE="/home/user/nanohub/environment.sh"

# Renewal URLs
URL_DEP="https://business.apple.com"
URL_VPP="https://business.apple.com"
URL_MDM_VENDOR="https://developer.apple.com/account"
URL_APNS_PUSH="https://identity.apple.com/pushcert/"

# Source environment for database credentials
if [ -f "$ENV_FILE" ]; then
    source "$ENV_FILE"
fi

# 1. DEP Token (from MySQL database)
DEP_EXPIRY=$(mysql -h 127.0.0.1 -u nanohub -p'YOUR_DB_PASSWORD' dep -N -s -e \
    "SELECT DATE_FORMAT(access_token_expiry, '%b %d %H:%i:%s %Y') FROM dep_names WHERE name='your-mdm-server' LIMIT 1;" 2>/dev/null)
if [ -n "$DEP_EXPIRY" ]; then
    printf "%s|%s|%s|%s\n" "DEP Token" "Device Enrollment Program" "$DEP_EXPIRY" "$URL_DEP"
fi

# 2. VPP Token (from environment.sh, base64 encoded)
if [ -n "$VPP_TOKEN" ]; then
    VPP_EXPIRY=$(echo "$VPP_TOKEN" | base64 -d 2>/dev/null | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    exp = d.get('expDate', '')
    if exp:
        # Format: 2026-05-01T13:57:02+0000
        from datetime import datetime
        dt = datetime.strptime(exp[:19], '%Y-%m-%dT%H:%M:%S')
        print(dt.strftime('%b %d %H:%M:%S %Y'))
except:
    pass
" 2>/dev/null)
    if [ -n "$VPP_EXPIRY" ]; then
        printf "%s|%s|%s|%s\n" "VPP Token" "Volume Purchase Program" "$VPP_EXPIRY" "$URL_VPP"
    fi
fi

# 3. MDM Vendor Certificate
MDM_CERT="$CERTDIR/mdm_cert_clean.pem"
if [ -f "$MDM_CERT" ] && [ -s "$MDM_CERT" ]; then
    MDM_EXP=$(openssl x509 -in "$MDM_CERT" -noout -enddate 2>/dev/null | cut -d= -f2)
    if [ -n "$MDM_EXP" ]; then
        printf "%s|%s|%s|%s\n" "MDM Vendor Cert" "MDM Vendor Certificate" "$MDM_EXP" "$URL_MDM_VENDOR"
    fi
fi

# 4. APNs Push Certificate
PUSH_CERT="$CERTDIR/MDM_ Your Name_Certificate.pem"
if [ -f "$PUSH_CERT" ] && [ -s "$PUSH_CERT" ]; then
    PUSH_EXP=$(openssl x509 -in "$PUSH_CERT" -noout -enddate 2>/dev/null | cut -d= -f2)
    if [ -n "$PUSH_EXP" ]; then
        printf "%s|%s|%s|%s\n" "APNs Push Cert" "Apple Push Notification Service" "$PUSH_EXP" "$URL_APNS_PUSH"
    fi
fi

# 5. Apple WWDR CA G3 Certificate
APPLE_CERTS_DIR="/home/user/nanohub/certs"
URL_APPLE_CERTS="https://www.apple.com/certificateauthority/"

WWDR_CERT="$APPLE_CERTS_DIR/AppleWWDRCAG3.pem"
if [ -f "$WWDR_CERT" ] && [ -s "$WWDR_CERT" ]; then
    WWDR_EXP=$(openssl x509 -in "$WWDR_CERT" -noout -enddate 2>/dev/null | cut -d= -f2)
    if [ -n "$WWDR_EXP" ]; then
        printf "%s|%s|%s|%s\n" "Apple WWDR CA G3" "Apple Worldwide Developer Relations" "$WWDR_EXP" "$URL_APPLE_CERTS"
    fi
fi

# 6. Apple Root CA Certificate
ROOT_CERT="$APPLE_CERTS_DIR/AppleRootCA.pem"
if [ -f "$ROOT_CERT" ] && [ -s "$ROOT_CERT" ]; then
    ROOT_EXP=$(openssl x509 -in "$ROOT_CERT" -noout -enddate 2>/dev/null | cut -d= -f2)
    if [ -n "$ROOT_EXP" ]; then
        printf "%s|%s|%s|%s\n" "Apple Root CA" "Apple Root Certificate Authority" "$ROOT_EXP" "$URL_APPLE_CERTS"
    fi
fi
