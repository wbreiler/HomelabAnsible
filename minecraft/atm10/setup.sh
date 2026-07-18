#!/usr/bin/env bash
# setup.sh — Bootstrap an All the Mods 10 server on a fresh Debian 13 LXC.
# Run as root on the target LXC: bash setup.sh
#
# Prerequisites on the LXC:
#   - Debian 13 (trixie), internet access
#   - CURSEFORGE_API_KEY set in environment or /etc/minecraft/atm10.conf
#
# What this script does:
#   1. Installs Java 21, curl, jq, unzip
#   2. Creates the 'minecraft' system user and /opt/minecraft directories
#   3. Downloads the ATM10 server pack from CurseForge
#   4. Extracts the pack and runs the NeoForge installer
#   5. Accepts the Minecraft EULA
#   6. Writes server.properties and /etc/minecraft/atm10.env
#   7. Deploys and enables systemd units
#   8. Starts the server

set -euo pipefail

###############################################################################
# Configuration — override via environment or edit here
###############################################################################

CF_PROJECT_ID="925200"         # ATM10 CurseForge project ID
MC_VERSION="1.21.1"
LOADER="neoforge"
INSTANCE_NAME="atm10"
MINECRAFT_DIR="/opt/minecraft"
CONF_DIR="/etc/minecraft"
SYSTEMD_DIR="/etc/systemd/system"
LOG="/var/log/atm10-setup.log"

# JVM heap (adjust to ~60% of available RAM for ATM10)
XMX="${XMX:-10G}"
XMS="${XMS:-4G}"

CF_API="https://api.curseforge.com/v1"
UA="MinecraftLXCAnsible/1.0 (will.breiler@gmail.com)"

###############################################################################
# Logging
###############################################################################

log() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG"; }

###############################################################################
# Resolve CurseForge API key
###############################################################################

if [[ -z "${CURSEFORGE_API_KEY:-}" ]]; then
    CONF="${CONF_DIR}/atm10.conf"
    if [[ -f "$CONF" ]]; then
        # shellcheck source=/dev/null
        source "$CONF"
    fi
fi

if [[ -z "${CURSEFORGE_API_KEY:-}" ]]; then
    echo "ERROR: CURSEFORGE_API_KEY is not set."
    echo "  Set it in the environment:  CURSEFORGE_API_KEY='...' bash setup.sh"
    echo "  Or add it to ${CONF_DIR}/atm10.conf:  CURSEFORGE_API_KEY='...'"
    exit 1
fi

###############################################################################
# 1. Install dependencies
###############################################################################

log "=== Step 1: Installing dependencies ==="
apt-get update -qq
apt-get install -y openjdk-21-jre-headless curl jq unzip
java -version 2>&1 | tee -a "$LOG"

###############################################################################
# 2. Create minecraft user and directories
###############################################################################

log "=== Step 2: Creating minecraft user and directories ==="

if ! id minecraft &>/dev/null; then
    useradd --system --shell /usr/sbin/nologin \
        --home "${MINECRAFT_DIR}" --no-create-home \
        --comment "Minecraft daemon" minecraft
    log "Created 'minecraft' system user."
else
    log "'minecraft' user already exists."
fi

mkdir -p "${MINECRAFT_DIR}"/{mods,world,backups}
mkdir -p "${CONF_DIR}"
chown -R minecraft:minecraft "${MINECRAFT_DIR}"
chown root:minecraft "${CONF_DIR}"
chmod 750 "${CONF_DIR}"
log "Directories ready."

###############################################################################
# 3. Download ATM10 server pack from CurseForge
###############################################################################

log "=== Step 3: Fetching ATM10 server pack from CurseForge ==="

cf_get() {
    curl -fsSL \
        -H "x-api-key: ${CURSEFORGE_API_KEY}" \
        -H "Accept: application/json" \
        -H "User-Agent: ${UA}" \
        "${CF_API}${1}"
}

# NeoForge loader ID in CurseForge enum
LOADER_ID=6

FILES_JSON=$(cf_get "/mods/${CF_PROJECT_ID}/files?gameVersion=${MC_VERSION}&modLoaderType=${LOADER_ID}&pageSize=50")

CF_FILE=$(echo "$FILES_JSON" | jq -r '
    [.data[] | select(.releaseType == 1)]
    | sort_by(.fileDate) | reverse | .[0]
')

LATEST_ID=$(echo "$CF_FILE"   | jq -r '.id')
LATEST_NAME=$(echo "$CF_FILE" | jq -r '.displayName')
CF_SERVER_PACK_ID=$(echo "$CF_FILE" | jq -r '.serverPackFileId // empty')

log "Latest release: ${LATEST_NAME} (file ID: ${LATEST_ID})"

# Prefer server pack over client pack
DOWNLOAD_URL=""
if [[ -n "$CF_SERVER_PACK_ID" ]]; then
    log "Server pack found (file ID: ${CF_SERVER_PACK_ID}). Fetching URL..."
    SP_URL=$(cf_get "/mods/${CF_PROJECT_ID}/files/${CF_SERVER_PACK_ID}/download-url" | jq -r '.data // empty')
    if [[ -n "$SP_URL" ]]; then
        DOWNLOAD_URL="$SP_URL"
        log "Using server pack: ${DOWNLOAD_URL}"
    else
        log "WARN: Server pack URL is CDN-restricted. Falling back to client pack."
    fi
fi

if [[ -z "$DOWNLOAD_URL" ]]; then
    DOWNLOAD_URL=$(echo "$CF_FILE" | jq -r '.downloadUrl // empty')
    [[ -z "$DOWNLOAD_URL" ]] && { log "ERROR: No usable download URL found."; exit 1; }
    log "Using client pack: ${DOWNLOAD_URL}"
fi

PACK_ZIP="/tmp/atm10-${LATEST_ID}.zip"
log "Downloading pack..."
curl -fsSL \
    -H "User-Agent: ${UA}" \
    -H "x-api-key: ${CURSEFORGE_API_KEY}" \
    --progress-bar \
    -o "$PACK_ZIP" \
    "$DOWNLOAD_URL"
log "Download complete: ${PACK_ZIP}"

###############################################################################
# 4. Extract server pack and run NeoForge installer
###############################################################################

log "=== Step 4: Extracting server pack ==="

EXTRACT_TMP=$(mktemp -d /tmp/atm10-extract-XXXXXX)
trap 'rm -rf "$EXTRACT_TMP" "$PACK_ZIP" 2>/dev/null || true' EXIT

unzip -q "$PACK_ZIP" -d "$EXTRACT_TMP"
log "Extracted to ${EXTRACT_TMP}"
ls "$EXTRACT_TMP"

# Copy extracted contents into MINECRAFT_DIR
# Server packs typically contain: mods/, config/, defaultconfigs/, etc.
# and a NeoForge installer jar or install script.
shopt -s dotglob
cp -a "${EXTRACT_TMP}"/. "${MINECRAFT_DIR}/"
shopt -u dotglob
chown -R minecraft:minecraft "${MINECRAFT_DIR}"
log "Server pack contents copied to ${MINECRAFT_DIR}"

# Run NeoForge installer if present
INSTALLER=$(find "${MINECRAFT_DIR}" -maxdepth 1 -name 'neoforge-*-installer.jar' 2>/dev/null | head -1)
if [[ -n "$INSTALLER" ]]; then
    log "Running NeoForge installer: ${INSTALLER}"
    cd "${MINECRAFT_DIR}"
    java -jar "$INSTALLER" --installServer 2>&1 | tee -a "$LOG"
    rm -f "$INSTALLER"
    log "NeoForge installer complete."
elif [[ -f "${MINECRAFT_DIR}/run.sh" ]]; then
    log "run.sh found — NeoForge may already be installed. Skipping installer step."
fi

###############################################################################
# 5. Accept EULA
###############################################################################

log "=== Step 5: Accepting EULA ==="
echo "eula=true" > "${MINECRAFT_DIR}/eula.txt"
chown minecraft:minecraft "${MINECRAFT_DIR}/eula.txt"
log "eula=true written."

###############################################################################
# 6. Write server.properties and env file
###############################################################################

log "=== Step 6: Writing server.properties and env ==="

# Only write server.properties if one wasn't included in the server pack
if [[ ! -f "${MINECRAFT_DIR}/server.properties" ]]; then
    cat > "${MINECRAFT_DIR}/server.properties" << 'PROPS'
allow-flight=true
difficulty=normal
enforce-secure-profile=false
gamemode=survival
max-players=20
motd=All the Mods 10
online-mode=true
pvp=true
server-port=25565
simulation-distance=10
spawn-protection=0
view-distance=10
white-list=false
PROPS
    chown minecraft:minecraft "${MINECRAFT_DIR}/server.properties"
    log "server.properties written."
else
    log "server.properties already present (from server pack)."
fi

cat > "${CONF_DIR}/atm10.env" << ENVFILE
XMX=${XMX}
XMS=${XMS}
ENVFILE
chmod 640 "${CONF_DIR}/atm10.env"
chown root:minecraft "${CONF_DIR}/atm10.env"
log "atm10.env written (XMX=${XMX}, XMS=${XMS})."

# Write current version ID so the update script knows what's installed
echo "$LATEST_ID" > "${MINECRAFT_DIR}/.current_version"
chown minecraft:minecraft "${MINECRAFT_DIR}/.current_version"

###############################################################################
# 7. Deploy systemd units
###############################################################################

log "=== Step 7: Deploying systemd units ==="

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

for unit in "minecraft@atm10.service" "minecraft-update.service" "minecraft-update.timer"; do
    src="${SCRIPT_DIR}/systemd/${unit}"
    if [[ -f "$src" ]]; then
        cp "$src" "${SYSTEMD_DIR}/${unit}"
        log "Deployed ${unit}"
    else
        log "WARN: ${src} not found — skipping ${unit}"
    fi
done

# Deploy the update script
if [[ -f "${SCRIPT_DIR}/update.sh" ]]; then
    cp "${SCRIPT_DIR}/update.sh" /usr/local/bin/atm10-update.sh
    chmod 755 /usr/local/bin/atm10-update.sh
    log "Deployed atm10-update.sh"
fi

systemctl daemon-reload

###############################################################################
# 8. Enable and start the server
###############################################################################

log "=== Step 8: Starting the server ==="

systemctl enable --now "minecraft@${INSTANCE_NAME}.service"
systemctl enable --now minecraft-update.timer

log "=== Setup complete ==="
log "Server status:"
systemctl status "minecraft@${INSTANCE_NAME}.service" --no-pager || true
log ""
log "Useful commands:"
log "  journalctl -fu minecraft@${INSTANCE_NAME}    # follow logs"
log "  systemctl stop minecraft@${INSTANCE_NAME}    # stop server"
log "  systemctl start minecraft@${INSTANCE_NAME}   # start server"
log "  atm10-update.sh --dry-run                    # check for updates"
