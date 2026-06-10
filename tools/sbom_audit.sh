#!/bin/bash
# NanoHUB SBOM Daily Audit — pip-audit + system check + disk stats → Telegram
# Cron: 06:00 daily

set -euo pipefail

source /opt/nanohub/environment.sh

REPORT_DIR="/var/log/nanohub/sbom"
mkdir -p "$REPORT_DIR"
DATE=$(date +%Y-%m-%d)
TIMESTAMP=$(date '+%d.%m.%Y %H:%M')
REPORT="$REPORT_DIR/$DATE.txt"

# --- Gather data ---

# Python pip-audit
AUDIT_OUT=$(/opt/nanohub/venv/bin/pip-audit 2>&1) || true
VULN_COUNT=$(echo "$AUDIT_OUT" | grep -c "CVE-" || true)

# Python packages
PKG_TOTAL=$(/opt/nanohub/venv/bin/pip list --format=columns 2>/dev/null | tail -n +3 | grep -c '\S' || true)
OUTDATED_OUT=$(/opt/nanohub/venv/bin/pip list --outdated --format=columns 2>&1) || true
OUTDATED_COUNT=$(echo "$OUTDATED_OUT" | tail -n +3 | grep -c '\S' || true)
DEPRECATED_OUT=$(/opt/nanohub/venv/bin/pip list --outdated --format=columns 2>/dev/null | grep -i deprecated || true)
DEPRECATED_COUNT=$(echo "$DEPRECATED_OUT" | grep -c '\S' || true)

# Docker container versions
NANOHUB_VER=$(docker inspect nanohub --format '{{.Config.Image}}' 2>/dev/null || echo "N/A")
NANODEP_VER=$(docker inspect nanodep --format '{{.Config.Image}}' 2>/dev/null || echo "N/A")
MYSQL_VER=$(docker exec mysql-nanohub mysql --version 2>/dev/null | grep -oP '\d+\.\d+\.\d+' | head -1 || echo "N/A")
SCEP_IMG=$(docker inspect scep-server --format '{{.Config.Image}}' 2>/dev/null || echo "N/A")

# System versions
NGINX_VER=$(nginx -v 2>&1 | grep -oP '\d+\.\d+\.\d+' || echo "N/A")
PYTHON_VER=$(python3 --version 2>&1 | grep -oP '\d+\.\d+\.\d+' || echo "N/A")
GO_VER=$(go version 2>&1 | grep -oP '\d+\.\d+\.\d+' || echo "N/A")
KERNEL_VER=$(uname -r)
DEBIAN_VER=$(grep -oP 'DEBIAN_VERSION_FULL=\K.*' /etc/os-release 2>/dev/null || grep -oP 'VERSION_ID="\K[^"]+' /etc/os-release)
DOCKER_VER=$(docker --version 2>&1 | grep -oP '\d+\.\d+\.\d+' | head -1 || echo "N/A")
OPENSSL_VER=$(openssl version 2>&1 | head -1 | grep -oP "\d+\.\d+\.\d+" | head -1 || echo "N/A")

# Service status
SVC_OK=0
SVC_FAIL=0
SVC_DETAILS=""
for svc in nanohub nanodep scep nanohub-web mdm-flask-api nanohub-webhook; do
    SVC_STATUS=$(systemctl is-active "$svc" 2>/dev/null || echo "not-found")
    if [ "$SVC_STATUS" = "active" ]; then
        SVC_OK=$((SVC_OK + 1))
    else
        SVC_FAIL=$((SVC_FAIL + 1))
        SVC_DETAILS="${SVC_DETAILS}  ❌ ${svc}: ${SVC_STATUS}\n"
    fi
done

# APT updates
APT_COUNT=$(apt list --upgradable 2>/dev/null | grep -v "^Listing" | grep -c '\S' || true)

# --- Disk Stats (VM — no SMART) ---
DISK_TEXT=""

# Filesystem usage
ROOT_USAGE=$(df -h / | awk 'NR==2 {printf "%s / %s (%s)", $3, $2, $5}')
ROOT_PCT=$(df / | awk 'NR==2 {print $5}' | tr -d '%')
if [ "$ROOT_PCT" -ge 90 ]; then
    DISK_TEXT+="• /: 🚨 ${ROOT_USAGE}"$'\n'
elif [ "$ROOT_PCT" -ge 75 ]; then
    DISK_TEXT+="• /: ⚠️ ${ROOT_USAGE}"$'\n'
else
    DISK_TEXT+="• /: ✅ ${ROOT_USAGE}"$'\n'
fi

# Inode usage
INODE_PCT=$(df -i / | awk 'NR==2 {print $5}' | tr -d '%')
if [ "$INODE_PCT" -ge 80 ]; then
    DISK_TEXT+="• Inodes: 🚨 ${INODE_PCT}%"$'\n'
elif [ "$INODE_PCT" -ge 50 ]; then
    DISK_TEXT+="• Inodes: ⚠️ ${INODE_PCT}%"$'\n'
else
    DISK_TEXT+="• Inodes: ✅ ${INODE_PCT}%"$'\n'
fi

# Docker disk usage
DOCKER_IMG_SIZE=$(docker system df --format '{{.Size}}' 2>/dev/null | head -1)
DOCKER_VOL_SIZE=$(docker system df --format '{{.Size}}' 2>/dev/null | sed -n '3p')
DISK_TEXT+="• Docker images: ${DOCKER_IMG_SIZE:-N/A}"$'\n'
DISK_TEXT+="• Docker volumes: ${DOCKER_VOL_SIZE:-N/A}"

# --- Write full report to file ---
{
    echo "=== NanoHUB SBOM Audit — $DATE ==="
    echo ""
    echo "--- Python Dependencies (pip-audit) ---"
    echo "$AUDIT_OUT"
    echo ""
    echo "--- Outdated Packages ---"
    echo "$OUTDATED_OUT"
    echo ""
    echo "--- Docker Images ---"
    docker images --format '{{.Repository}}:{{.Tag}}  Created: {{.CreatedSince}}' 2>&1 | grep -v '<none>' || true
    echo ""
    echo "--- Pending System Updates ---"
    if [ "$APT_COUNT" -eq 0 ]; then echo "None"; else apt list --upgradable 2>/dev/null | grep -v "^Listing"; fi
    echo ""
    echo "--- Service Status ---"
    for svc in nanohub nanodep scep nanohub-web mdm-flask-api nanohub-webhook; do
        printf "%-25s %s\n" "$svc" "$(systemctl is-active "$svc" 2>/dev/null || echo "not-found")"
    done
    echo ""
    echo "--- Disk Stats ---"
    echo "$DISK_TEXT"
    echo ""
    echo "--- System ---"
    echo "MySQL: $MYSQL_VER | nginx: $NGINX_VER | Python: $PYTHON_VER | Go: $GO_VER"
    echo "Docker: $DOCKER_VER | OpenSSL: $OPENSSL_VER | Kernel: $KERNEL_VER | Debian: $DEBIAN_VER"
} > "$REPORT" 2>&1

# --- Build Telegram message ---

if [ "$VULN_COUNT" -gt 0 ]; then
    ICON="🚨"
else
    ICON="✅"
fi

MSG="${ICON} <b>NanoHUB SBOM Report</b>

📦 <b>Python (pip)</b>
• Balíčků celkem: ${PKG_TOTAL}
• Zranitelné: ${VULN_COUNT}
• Outdated: ${OUTDATED_COUNT}"

# CVE details
if [ "$VULN_COUNT" -gt 0 ]; then
    CVE_DETAILS=$(echo "$AUDIT_OUT" | grep "CVE-" | awk '{printf "  ⚠️ %s %s → %s (%s)\n", $1, $2, $4, $3}' | head -10)
    MSG="${MSG}
<pre>${CVE_DETAILS}</pre>"
fi

# Outdated details
if [ "$OUTDATED_COUNT" -gt 0 ]; then
    OUTDATED_DETAIL=$(echo "$OUTDATED_OUT" | tail -n +3 | awk 'NF>=3 {printf "  %s %s → %s\n", $1, $2, $3}')
    MSG="${MSG}
<pre>${OUTDATED_DETAIL}</pre>"
fi

MSG="${MSG}

🐳 <b>Docker kontejnery</b>
• NanoHUB: ${NANOHUB_VER}
• NanoDEP: ${NANODEP_VER}
• SCEP: ${SCEP_IMG}
• MySQL: ${MYSQL_VER}

🖥 <b>Systémové komponenty</b>
• nginx: ${NGINX_VER}
• Python: ${PYTHON_VER}
• Go: ${GO_VER}
• Docker: ${DOCKER_VER}
• OpenSSL: ${OPENSSL_VER}
• MySQL: ${MYSQL_VER}
• Kernel: ${KERNEL_VER}
• Debian: ${DEBIAN_VER}
• APT updates: ${APT_COUNT}

💾 <b>Disk Stats</b>
${DISK_TEXT}"

# Services
if [ "$SVC_FAIL" -eq 0 ]; then
    MSG="${MSG}

⚙️ <b>Služby:</b> ${SVC_OK}/${SVC_OK} active"
else
    MSG="${MSG}

⚙️ <b>Služby:</b> ${SVC_OK}/$((SVC_OK + SVC_FAIL)) active
$(echo -e "$SVC_DETAILS")"
fi

MSG="${MSG}

🕒 ${TIMESTAMP}"

# Send to Telegram
curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -d chat_id="${TELEGRAM_CHAT_ID}" \
    -d parse_mode="HTML" \
    -d disable_web_page_preview=true \
    -d text="${MSG}" > /dev/null 2>&1

# Cleanup old reports (keep 90 days)
find "$REPORT_DIR" -name "*.txt" -mtime +90 -delete 2>/dev/null || true

echo "SBOM audit complete: $REPORT"
