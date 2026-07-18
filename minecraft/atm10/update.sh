#!/usr/bin/env bash
# update.sh — Update All the Mods 10 to the latest CurseForge release.
# Deployed to /usr/local/bin/atm10-update.sh on the server by setup.sh.
# Run by minecraft-update.timer nightly at 04:00.

set -euo pipefail

###############################################################################
# Config
###############################################################################

CF_PROJECT_ID="925200"
MC_VERSION="1.21.1"
LOADER_ID=6   # NeoForge
INSTANCE_NAME="atm10"
MINECRAFT_DIR="/opt/minecraft"
CONF_DIR="/etc/minecraft"
LOG="/var/log/atm10-update.log"
DRY_RUN=false
NO_WAIT=false

CF_API="https://api.curseforge.com/v1"
UA="MinecraftLXCAnsible/1.0 (will.breiler@gmail.com)"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)  DRY_RUN=true ;;
        --no-wait)  NO_WAIT=true ;;
        -h|--help)  echo "Usage: $0 [--dry-run] [--no-wait]"; exit 0 ;;
        *) echo "Unknown arg: $1" >&2; exit 1 ;;
    esac
    shift
done

###############################################################################
# Logging
###############################################################################

MAX_LOG_BYTES=$((10 * 1024 * 1024))

log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
    echo "$msg"
    local size
    size=$(stat -c%s "$LOG" 2>/dev/null || echo 0)
    if (( size > MAX_LOG_BYTES )); then
        mv "$LOG" "${LOG}.1"
    fi
    echo "$msg" >> "$LOG"
}

###############################################################################
# Discord
###############################################################################

discord_notify() {
    [[ -z "${DISCORD_WEBHOOK_URL:-}" ]] && return 0
    local payload
    payload=$(jq -nc --arg content "$1" '{"content":$content}')
    curl -fsSL -H "Content-Type: application/json" -d "$payload" \
        "$DISCORD_WEBHOOK_URL" 2>/dev/null \
        || log "WARN: Discord notify failed (non-fatal)."
}

on_error() {
    log "ERROR at line $1 (exit $?)"
    discord_notify "❌ ATM10 update failed at line $1. Check ${LOG}."
    exit 1
}
trap 'on_error $LINENO' ERR

###############################################################################
# Load config (API key, Discord webhook, etc.)
###############################################################################

CONF="${CONF_DIR}/atm10.conf"
[[ -f "$CONF" ]] && source "$CONF"

if [[ -z "${CURSEFORGE_API_KEY:-}" ]]; then
    log "ERROR: CURSEFORGE_API_KEY not set. Add it to ${CONF}."
    exit 1
fi

###############################################################################
# Check for update
###############################################################################

log "=== ATM10 update check (MC ${MC_VERSION}) ==="
[[ "$DRY_RUN" == true ]] && log "DRY-RUN mode."
[[ "$NO_WAIT" == true ]] && log "NO-WAIT mode."

cf_get() {
    curl -fsSL \
        -H "x-api-key: ${CURSEFORGE_API_KEY}" \
        -H "Accept: application/json" \
        -H "User-Agent: ${UA}" \
        "${CF_API}${1}"
}

FILES_JSON=$(cf_get "/mods/${CF_PROJECT_ID}/files?gameVersion=${MC_VERSION}&modLoaderType=${LOADER_ID}&pageSize=50")

CF_FILE=$(echo "$FILES_JSON" | jq -r '
    [.data[] | select(.releaseType == 1)]
    | sort_by(.fileDate) | reverse | .[0]
')

LATEST_ID=$(echo "$CF_FILE"   | jq -r '.id')
LATEST_NAME=$(echo "$CF_FILE" | jq -r '.displayName')
CF_SERVER_PACK_ID=$(echo "$CF_FILE" | jq -r '.serverPackFileId // empty')

CURRENT_ID="(none)"
[[ -f "${MINECRAFT_DIR}/.current_version" ]] && CURRENT_ID=$(cat "${MINECRAFT_DIR}/.current_version")

log "Installed: ${CURRENT_ID}  Latest: ${LATEST_NAME} (${LATEST_ID})"

if [[ "$CURRENT_ID" == "$LATEST_ID" ]]; then
    log "Already up to date."
    exit 0
fi

log "Update available: ${CURRENT_ID} → ${LATEST_NAME}"

if [[ "$DRY_RUN" == true ]]; then
    discord_notify "🔍 ATM10 update available: ${LATEST_NAME}. Run without --dry-run to apply."
    exit 0
fi

###############################################################################
# Announce + countdown
###############################################################################

discord_notify "⏳ ATM10 updating to ${LATEST_NAME} in 5 minutes. Server will restart."

if [[ "$NO_WAIT" == false ]]; then
    log "Waiting 300 seconds..."
    sleep 300
fi

###############################################################################
# Stop service
###############################################################################

SERVICE="minecraft@${INSTANCE_NAME}.service"
log "Stopping ${SERVICE}..."
if systemctl is-active --quiet "$SERVICE" 2>/dev/null; then
    systemctl stop "$SERVICE"
    log "Stopped."
else
    log "Service not running."
fi

###############################################################################
# Backup mods (keep 3)
###############################################################################

MODS_DIR="${MINECRAFT_DIR}/mods"
TIMESTAMP=$(date '+%Y%m%d_%H%M%S')
BACKUP="${MINECRAFT_DIR}/backups/mods.${TIMESTAMP}"

if [[ -d "$MODS_DIR" ]]; then
    log "Backing up mods → ${BACKUP}"
    cp -a "$MODS_DIR" "$BACKUP"
fi

mapfile -t OLD < <(ls -1dt "${MINECRAFT_DIR}/backups"/mods.* 2>/dev/null | tail -n +4)
for old in "${OLD[@]}"; do
    log "Pruning old backup: ${old}"
    rm -rf "$old"
done

###############################################################################
# Download server pack
###############################################################################

DOWNLOAD_URL=""
if [[ -n "$CF_SERVER_PACK_ID" ]]; then
    SP_URL=$(cf_get "/mods/${CF_PROJECT_ID}/files/${CF_SERVER_PACK_ID}/download-url" | jq -r '.data // empty')
    [[ -n "$SP_URL" ]] && DOWNLOAD_URL="$SP_URL"
fi
if [[ -z "$DOWNLOAD_URL" ]]; then
    DOWNLOAD_URL=$(echo "$CF_FILE" | jq -r '.downloadUrl // empty')
    [[ -z "$DOWNLOAD_URL" ]] && { log "ERROR: No download URL."; exit 1; }
fi

PACK_ZIP=$(mktemp --suffix='.zip')
EXTRACT_TMP=""
cleanup() {
    rm -f "$PACK_ZIP"
    [[ -n "${EXTRACT_TMP:-}" ]] && rm -rf "$EXTRACT_TMP"
}
trap cleanup EXIT

log "Downloading: ${DOWNLOAD_URL}"
curl -fsSL \
    -H "User-Agent: ${UA}" \
    -H "x-api-key: ${CURSEFORGE_API_KEY}" \
    -o "$PACK_ZIP" \
    "$DOWNLOAD_URL"
log "Download complete."

###############################################################################
# Extract mods from server pack
###############################################################################

EXTRACT_TMP=$(mktemp -d)
unzip -q "$PACK_ZIP" -d "$EXTRACT_TMP"

rm -rf "${MODS_DIR}"
mkdir -p "${MODS_DIR}"

if [[ -d "${EXTRACT_TMP}/mods" ]]; then
    cp -a "${EXTRACT_TMP}/mods/." "${MODS_DIR}/"
    log "Mods updated from server pack."
else
    log "WARN: No mods/ dir in pack. Extracting .jar files from root."
    find "$EXTRACT_TMP" -maxdepth 1 -name '*.jar' -exec cp {} "${MODS_DIR}/" \;
fi

chown -R minecraft:minecraft "${MODS_DIR}"

###############################################################################
# Write version and restart
###############################################################################

echo "$LATEST_ID" > "${MINECRAFT_DIR}/.current_version"
chown minecraft:minecraft "${MINECRAFT_DIR}/.current_version"

log "Starting ${SERVICE}..."
systemctl start "$SERVICE"

log "=== Update complete: ${LATEST_NAME} ==="
discord_notify "✅ ATM10 updated to ${LATEST_NAME}"
