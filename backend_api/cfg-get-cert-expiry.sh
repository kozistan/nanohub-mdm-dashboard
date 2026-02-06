#!/bin/bash
# NanoHUB Certificate and Token Expiry Script
# Shows expiry dates for all MDM tokens and certificates
# Output format: name|usage|expiry|renewal_url

CERTDIR="/opt/nanohub/certs"
ENV_FILE="/opt/nanohub/environment.sh"

# Renewal URLs
URL_DEP="https://business.apple.com"
URL_VPP="https://business.apple.com"
URL_APPLE_DEV="https://developer.apple.com/account"
URL_APNS_PUSH="https://identity.apple.com/pushcert/"
URL_APPLE_CERTS="https://www.apple.com/certificateauthority/"

# Helper function to get cert expiry (handles both PEM and DER formats)
get_cert_expiry() {
    local cert_file="$1"
    local format="${2:-PEM}"
    if [ "$format" = "DER" ]; then
        openssl x509 -in "$cert_file" -inform DER -noout -enddate 2>/dev/null | cut -d= -f2
    else
        openssl x509 -in "$cert_file" -noout -enddate 2>/dev/null | cut -d= -f2
    fi
}

# Source environment for database credentials
if [ -f "$ENV_FILE" ]; then
    source "$ENV_FILE"
fi

# ============================================
# TOKENS (from database/environment)
# ============================================

# 1. DEP Token (from MySQL database)
DEP_EXPIRY=$(mysql -h 127.0.0.1 -u "${DB_USER:-nanohub}" -p"${DB_PASSWORD}" dep -N -s -e \
    "SELECT DATE_FORMAT(access_token_expiry, '%b %d %H:%i:%s %Y') FROM dep_names WHERE name='${DEP_NAME}' LIMIT 1;" 2>/dev/null)
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

# ============================================
# MDM CERTIFICATES (from /opt/nanohub/certs/)
# ============================================

# 3. MDM Vendor Certificate
CERT="$CERTDIR/mdm_cert_clean.pem"
if [ -f "$CERT" ] && [ -s "$CERT" ]; then
    EXP=$(get_cert_expiry "$CERT" "PEM")
    [ -n "$EXP" ] && printf "%s|%s|%s|%s\n" "MDM Vendor Cert" "MDM Vendor Certificate" "$EXP" "$URL_APPLE_DEV"
fi

# 4. APNs Push Certificate
CERT="$CERTDIR/MDM_ Martin Kubovciak_Certificate.pem"
if [ -f "$CERT" ] && [ -s "$CERT" ]; then
    EXP=$(get_cert_expiry "$CERT" "PEM")
    [ -n "$EXP" ] && printf "%s|%s|%s|%s\n" "APNs Push Cert" "Apple Push Notification Service" "$EXP" "$URL_APNS_PUSH"
fi

# ============================================
# DEVELOPER CERTIFICATES (from /opt/nanohub/certs/)
# ============================================

# 5. Developer ID Application
CERT="$CERTDIR/developerID_application.cer"
if [ -f "$CERT" ] && [ -s "$CERT" ]; then
    EXP=$(get_cert_expiry "$CERT" "DER")
    [ -n "$EXP" ] && printf "%s|%s|%s|%s\n" "Developer ID App" "Developer ID Application (Team)" "$EXP" "$URL_APPLE_DEV"
fi

# 6. Developer ID Installer
CERT="$CERTDIR/developerID_installer.cer"
if [ -f "$CERT" ] && [ -s "$CERT" ]; then
    EXP=$(get_cert_expiry "$CERT" "DER")
    [ -n "$EXP" ] && printf "%s|%s|%s|%s\n" "Developer ID Installer" "Developer ID Installer (Team)" "$EXP" "$URL_APPLE_DEV"
fi

# 7. Apple Development (Personal)
CERT="$CERTDIR/development.cer"
if [ -f "$CERT" ] && [ -s "$CERT" ]; then
    EXP=$(get_cert_expiry "$CERT" "DER")
    [ -n "$EXP" ] && printf "%s|%s|%s|%s\n" "Apple Development" "Personal Development Certificate" "$EXP" "$URL_APPLE_DEV"
fi

# ============================================
# APPLE ROOT CERTIFICATES (from /opt/nanohub/certs/)
# ============================================

# 8. Apple WWDR CA G3
CERT="$CERTDIR/AppleWWDRCAG3.pem"
if [ -f "$CERT" ] && [ -s "$CERT" ]; then
    EXP=$(get_cert_expiry "$CERT" "PEM")
    [ -n "$EXP" ] && printf "%s|%s|%s|%s\n" "Apple WWDR CA G3" "Apple Worldwide Developer Relations" "$EXP" "$URL_APPLE_CERTS"
fi

# 9. Apple Root CA
CERT="$CERTDIR/AppleRootCA.pem"
if [ -f "$CERT" ] && [ -s "$CERT" ]; then
    EXP=$(get_cert_expiry "$CERT" "PEM")
    [ -n "$EXP" ] && printf "%s|%s|%s|%s\n" "Apple Root CA" "Apple Root Certificate Authority" "$EXP" "$URL_APPLE_CERTS"
fi
