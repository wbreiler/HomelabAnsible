#!/usr/bin/env bash
# update-modpack.sh — Modrinth and CurseForge modpack update script
# Sources config from /etc/minecraft/update.conf or --config path.

set -euo pipefail

###############################################################################
# Defaults & arg parsing
###############################################################################

CONFIG_FILE="/etc/minecraft/update.conf"
DRY_RUN=false
NO_WAIT=false
LOG_FILE="/var/log/minecraft-update.log"
MODRINTH_API="https://api.modrinth.com/v2"
CF_API="https://api.curseforge.com/v1"
UA="MinecraftLXCAnsible/1.0 (will.breiler@gmail.com)"

usage() {
    echo "Usage: $0 [--config <path>] [--dry-run] [--no-wait]" >&2
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --config)   shift; CONFIG_FILE="${1:?--config requires a path argument}" ;;
        --dry-run)  DRY_RUN=true ;;
        --no-wait)  NO_WAIT=true ;;
        -h|--help)  usage ;;
        *)          echo "Unknown argument: $1" >&2; usage ;;
    esac
    shift
done

###############################################################################
# Logging helpers
###############################################################################

MAX_LOG_BYTES=$((10 * 1024 * 1024))

rotate_log() {
    if [[ -f "$LOG_FILE" ]]; then
        local size
        size=$(stat -c%s "$LOG_FILE" 2>/dev/null || echo 0)
        if (( size > MAX_LOG_BYTES )); then
            mv "$LOG_FILE" "${LOG_FILE}.1"
        fi
    fi
}

log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
    echo "$msg"
    rotate_log
    echo "$msg" >> "$LOG_FILE"
}

###############################################################################
# Discord notification helper
###############################################################################

discord_notify() {
    local message="$1"
    if [[ -z "${DISCORD_WEBHOOK_URL:-}" ]]; then
        log "WARN: DISCORD_WEBHOOK_URL not set; skipping notification."
        return 0
    fi
    local payload
    payload=$(jq -nc --arg content "$message" '{"content": $content}')
    curl -fsSL \
        -H "Content-Type: application/json" \
        -d "$payload" \
        "$DISCORD_WEBHOOK_URL" \
        || log "WARN: Discord notification failed (non-fatal)."
}

###############################################################################
# Error handler
###############################################################################

PACK_NAME_SAFE="unknown pack"
SERVICE=""
SERVICE_WAS_RUNNING=false
SWAP_COMPLETE=false
BACKUP_DIR=""
MODS_STAGE=""

on_error() {
    local exit_code=$?
    local line_no=${1:-unknown}
    local error_msg="Script error at line ${line_no} (exit ${exit_code})"
    trap - ERR
    set +e
    if [[ "$SWAP_COMPLETE" == true ]]; then
        if [[ "$SERVICE_WAS_RUNNING" == true && -n "$SERVICE" ]]; then
            systemctl stop "$SERVICE" \
                || log "ERROR: Failed to stop ${SERVICE} before rollback."
        fi
        log "Rolling back mod directory after failed update..."
        rm -rf "$MODS_DIR"
        if [[ -n "$BACKUP_DIR" && -d "$BACKUP_DIR" ]]; then
            mv "$BACKUP_DIR" "$MODS_DIR"
        else
            mkdir -p "$MODS_DIR"
            chown minecraft:minecraft "$MODS_DIR"
        fi
    fi
    if [[ "$SERVICE_WAS_RUNNING" == true && -n "$SERVICE" ]]; then
        systemctl start "$SERVICE" \
            || log "ERROR: Failed to restart ${SERVICE} during rollback."
    fi
    log "ERROR: $error_msg"
    discord_notify "❌ Update failed for ${PACK_NAME_SAFE}: ${error_msg}"
    exit "$exit_code"
}

trap 'on_error $LINENO' ERR

###############################################################################
# Load and validate config
###############################################################################

if [[ ! -f "$CONFIG_FILE" ]]; then
    log "ERROR: Config file not found: $CONFIG_FILE"
    exit 1
fi

# shellcheck source=/dev/null
source "$CONFIG_FILE"

PACK_SOURCE="${PACK_SOURCE:-modrinth}"
MINECRAFT_DIR="${MINECRAFT_DIR:-/opt/minecraft}"
CURRENT_VERSION_FILE="${MINECRAFT_DIR}/.current_version"
CURRENT_EXCLUDES_FILE="${MINECRAFT_DIR}/.current_excludes"
MODS_DIR="${MINECRAFT_DIR}/mods"
PACK_NAME_SAFE="${PACK_NAME:-unknown pack}"

for var in PACK_NAME INSTANCE_NAME MC_VERSION LOADER; do
    if [[ -z "${!var:-}" ]]; then
        log "ERROR: Required variable ${var} is not set in ${CONFIG_FILE}"
        exit 1
    fi
done

case "$PACK_SOURCE" in
    modrinth)
        if [[ -z "${MODPACK_SLUG:-}" ]]; then
            log "ERROR: MODPACK_SLUG is required for PACK_SOURCE=modrinth"
            exit 1
        fi
        ;;
    curseforge)
        for var in CURSEFORGE_PROJECT_ID CURSEFORGE_API_KEY; do
            if [[ -z "${!var:-}" ]]; then
                log "ERROR: ${var} is required for PACK_SOURCE=curseforge"
                exit 1
            fi
        done
        ;;
    *)
        log "ERROR: Unknown PACK_SOURCE '${PACK_SOURCE}'. Must be 'modrinth' or 'curseforge'."
        exit 1
        ;;
esac

declare -A CF_EXCLUDE_SET
for _id in ${EXCLUDE_CF_PROJECTS:-}; do
    CF_EXCLUDE_SET["$_id"]=1
done

log "=== Update check: ${PACK_NAME} (${PACK_SOURCE}, MC ${MC_VERSION}, ${LOADER}) ==="
[[ "$DRY_RUN"  == true ]] && log "DRY-RUN mode: no changes will be applied."
[[ "$NO_WAIT"  == true ]] && log "NO-WAIT mode: skipping 5-minute countdown."

###############################################################################
# CurseForge helpers
###############################################################################

cf_loader_id() {
    # CurseForge modLoaderType enum
    case "${LOADER,,}" in
        forge)    echo 1 ;;
        fabric)   echo 4 ;;
        quilt)    echo 5 ;;
        neoforge) echo 6 ;;
        *)        echo 0 ;;
    esac
}

cf_get() {
    curl -fsSL \
        -H "x-api-key: ${CURSEFORGE_API_KEY}" \
        -H "Accept: application/json" \
        -H "User-Agent: ${UA}" \
        "${CF_API}${1}"
}

###############################################################################
# Fetch latest version
###############################################################################

LATEST_ID=""
LATEST_NAME=""
DOWNLOAD_URL=""
CF_DOWNLOAD_METHOD=""   # "server_pack" or "manifest"
CF_SERVER_PACK_ID=""

if [[ "$PACK_SOURCE" == "modrinth" ]]; then

    log "Querying Modrinth API for ${MODPACK_SLUG}..."
    VERSIONS_JSON=$(curl -fsSL \
        -H "User-Agent: ${UA}" \
        "${MODRINTH_API}/project/${MODPACK_SLUG}/version?game_versions=%5B%22${MC_VERSION}%22%5D&loaders=%5B%22${LOADER}%22%5D")

    LATEST_VERSION=$(echo "$VERSIONS_JSON" | jq -r '
        [.[] | select(.version_type == "release")]
        | sort_by(.date_published) | reverse | .[0]
        | {id, name, date_published,
           download_url: (.files[] | select(.primary == true) | .url)}
    ')

    if [[ -z "$LATEST_VERSION" || "$LATEST_VERSION" == "null" ]]; then
        log "ERROR: No stable release found for ${MODPACK_SLUG} on MC ${MC_VERSION} / ${LOADER}."
        discord_notify "❌ Update check failed for ${PACK_NAME}: no stable Modrinth release found."
        exit 1
    fi

    LATEST_ID=$(echo "$LATEST_VERSION"   | jq -r '.id')
    LATEST_NAME=$(echo "$LATEST_VERSION" | jq -r '.name')
    DOWNLOAD_URL=$(echo "$LATEST_VERSION" | jq -r '.download_url')

elif [[ "$PACK_SOURCE" == "curseforge" ]]; then

    log "Querying CurseForge API for project ${CURSEFORGE_PROJECT_ID}..."
    loader_id=$(cf_loader_id)
    FILES_JSON=$(cf_get "/mods/${CURSEFORGE_PROJECT_ID}/files?gameVersion=${MC_VERSION}&modLoaderType=${loader_id}&pageSize=50")

    CF_FILE_JSON=$(echo "$FILES_JSON" | jq -r '
        [.data[] | select(.releaseType == 1)]
        | sort_by(.fileDate) | reverse | .[0]
    ')

    if [[ -z "$CF_FILE_JSON" || "$CF_FILE_JSON" == "null" ]]; then
        log "ERROR: No stable release found for CurseForge project ${CURSEFORGE_PROJECT_ID} on MC ${MC_VERSION}."
        discord_notify "❌ Update check failed for ${PACK_NAME}: no stable CurseForge release found."
        exit 1
    fi

    LATEST_ID=$(echo "$CF_FILE_JSON"   | jq -r '.id')
    LATEST_NAME=$(echo "$CF_FILE_JSON" | jq -r '.displayName')
    CF_SERVER_PACK_ID=$(echo "$CF_FILE_JSON" | jq -r '.serverPackFileId // empty')

    if [[ -n "$CF_SERVER_PACK_ID" ]]; then
        log "Server pack available (file ID: ${CF_SERVER_PACK_ID}). Fetching download URL..."
        SP_URL=$(cf_get "/mods/${CURSEFORGE_PROJECT_ID}/files/${CF_SERVER_PACK_ID}/download-url" | jq -r '.data // empty')
        if [[ -n "$SP_URL" ]]; then
            DOWNLOAD_URL="$SP_URL"
            CF_DOWNLOAD_METHOD="server_pack"
            log "Will use server pack."
        else
            log "WARN: Server pack URL is CDN-restricted. Falling back to manifest method."
        fi
    fi

    if [[ -z "$DOWNLOAD_URL" ]]; then
        CLIENT_URL=$(echo "$CF_FILE_JSON" | jq -r '.downloadUrl // empty')
        if [[ -z "$CLIENT_URL" ]]; then
            log "ERROR: No download URL for CurseForge pack (project ${CURSEFORGE_PROJECT_ID}, file ${LATEST_ID})."
            discord_notify "❌ Update check failed for ${PACK_NAME}: CurseForge download URL unavailable."
            exit 1
        fi
        DOWNLOAD_URL="$CLIENT_URL"
        CF_DOWNLOAD_METHOD="manifest"
        log "Will use client pack + manifest."
    fi

fi

log "Latest: ${LATEST_NAME} (ID: ${LATEST_ID})"

###############################################################################
# Compare against current version
###############################################################################

CURRENT_ID="(none)"
[[ -f "$CURRENT_VERSION_FILE" ]] && CURRENT_ID=$(cat "$CURRENT_VERSION_FILE")

CURRENT_EXCLUDES=""
[[ -f "$CURRENT_EXCLUDES_FILE" ]] && CURRENT_EXCLUDES=$(cat "$CURRENT_EXCLUDES_FILE")

log "Installed: ${CURRENT_ID}"

if [[ "$CURRENT_ID" == "$LATEST_ID" && "$CURRENT_EXCLUDES" == "${EXCLUDE_CF_PROJECTS:-}" ]]; then
    log "Already up to date. Exiting."
    exit 0
elif [[ "$CURRENT_ID" == "$LATEST_ID" ]]; then
    log "Pack version unchanged but exclusion list changed — reinstalling to remove excluded mods."
fi

log "Update: ${CURRENT_ID} → ${LATEST_ID} (${LATEST_NAME})"

if [[ "$DRY_RUN" == true ]]; then
    discord_notify "🔍 [Dry-run] Update available for ${PACK_NAME}: ${CURRENT_ID} → ${LATEST_NAME}. No changes applied."
    exit 0
fi

###############################################################################
# Announce + countdown
###############################################################################

discord_notify "⏳ Update available for ${PACK_NAME}: ${CURRENT_ID} → ${LATEST_NAME}. Updating in 5 minutes..."

if [[ "$NO_WAIT" == true ]]; then
    log "Skipping countdown (--no-wait)."
else
    log "Sleeping 300 seconds before applying update..."
    sleep 300
fi

SERVICE="minecraft@${INSTANCE_NAME}.service"
if systemctl is-active --quiet "$SERVICE" 2>/dev/null; then
    SERVICE_WAS_RUNNING=true
fi

TIMESTAMP=$(date '+%Y%m%d_%H%M%S')
BACKUP_DIR="${MINECRAFT_DIR}/mods.bak.${TIMESTAMP}"
MODS_STAGE=$(mktemp -d "${MINECRAFT_DIR}/.mods.stage.XXXXXX")
log "Building new mod directory in ${MODS_STAGE}."

###############################################################################
# Download pack
###############################################################################

PACK_FILE="$(mktemp --suffix='.zip')"
EXTRACT_TMP=""
INFRA_TMP=""
VERSION_TMP=""
EXCLUDES_TMP=""

cleanup() {
    rm -f "$PACK_FILE"
    [[ -n "${VERSION_TMP:-}" ]] && rm -f "$VERSION_TMP"
    [[ -n "${EXCLUDES_TMP:-}" ]] && rm -f "$EXCLUDES_TMP"
    if [[ -n "${MODS_STAGE:-}" && -d "$MODS_STAGE" ]]; then
        rm -rf "$MODS_STAGE"
    fi
    if [[ -n "${EXTRACT_TMP:-}" ]]; then
        rm -rf "$EXTRACT_TMP"
    fi
    if [[ -n "${INFRA_TMP:-}" ]]; then
        rm -rf "$INFRA_TMP"
    fi
}
trap 'cleanup' EXIT

log "Downloading: ${DOWNLOAD_URL}"
if [[ "$PACK_SOURCE" == "curseforge" ]]; then
    curl -fsSL \
        -H "User-Agent: ${UA}" \
        -H "x-api-key: ${CURSEFORGE_API_KEY}" \
        -o "$PACK_FILE" \
        "$DOWNLOAD_URL"
else
    curl -fsSL \
        -H "User-Agent: ${UA}" \
        -o "$PACK_FILE" \
        "$DOWNLOAD_URL"
fi
log "Download complete. $(du -h "$PACK_FILE" | cut -f1) (${DOWNLOAD_URL##*/})"

###############################################################################
# Extract mods
###############################################################################

EXTRACT_TMP=$(mktemp -d --tmpdir mc-pack-XXXXXX)

if [[ "$PACK_SOURCE" == "modrinth" ]]; then

    # Extract bundled overrides (mods that ship directly in the mrpack)
    unzip -o "$PACK_FILE" "overrides/mods/*" -d "$EXTRACT_TMP" 2>/dev/null || true
    if [[ -d "${EXTRACT_TMP}/overrides/mods" ]]; then
        cp -a "${EXTRACT_TMP}/overrides/mods/." "$MODS_STAGE/"
        log "Mods extracted from mrpack overrides/mods/."
    fi

    # Download mods listed in modrinth.index.json (the majority of mods in most packs)
    unzip -o "$PACK_FILE" "modrinth.index.json" -d "$EXTRACT_TMP" 2>/dev/null || true
    INDEX="${EXTRACT_TMP}/modrinth.index.json"
    if [[ -f "$INDEX" ]]; then
        SERVER_MODS=$(jq -c '[.files[] | select((.env.server // "required") != "unsupported")] | .[]' "$INDEX")
        MOD_COUNT=$(echo "$SERVER_MODS" | grep -c '^' || true)
        log "Downloading ${MOD_COUNT} server-side mods from Modrinth index..."
        FAILED_MODS=0
        MOD_NUM=0
        while IFS= read -r mod_entry; do
            [[ -z "$mod_entry" ]] && continue
            MOD_NUM=$(( MOD_NUM + 1 ))
            mod_url=$(echo "$mod_entry"  | jq -r '.downloads[0]')
            filename=$(echo "$mod_entry" | jq -r '.path | split("/") | last')
            required=$(echo "$mod_entry" | jq -r '(.env.server // "required") == "required"')
            log "[${MOD_NUM}/${MOD_COUNT}] ${filename}"
            curl -fsSL \
                -H "User-Agent: ${UA}" \
                -o "${MODS_STAGE}/${filename}" \
                "$mod_url" \
            || {
                rm -f "${MODS_STAGE}/${filename}"
                if [[ "$required" == "true" ]]; then
                    log "ERROR: Required mod ${filename} failed to download."
                    FAILED_MODS=$(( FAILED_MODS + 1 ))
                else
                    log "WARN: Optional mod ${filename} failed to download."
                fi
            }
        done <<< "$SERVER_MODS"
        if (( FAILED_MODS > 0 )); then
            log "ERROR: ${FAILED_MODS} required mod(s) failed to download; live installation is unchanged."
            exit 1
        fi
    else
        log "WARN: modrinth.index.json not found in mrpack; only overrides/ mods were installed."
    fi

elif [[ "$PACK_SOURCE" == "curseforge" && "$CF_DOWNLOAD_METHOD" == "server_pack" ]]; then

    unzip -o "$PACK_FILE" "mods/*" -d "$EXTRACT_TMP" 2>/dev/null || true
    if [[ -d "${EXTRACT_TMP}/mods" ]] && [[ -n "$(ls -A "${EXTRACT_TMP}/mods" 2>/dev/null)" ]]; then
        cp -a "${EXTRACT_TMP}/mods/." "$MODS_STAGE/"
        log "Mods extracted from server pack mods/."
    else
        # Some server packs put JARs at the root alongside launcher files
        log "No mods/ dir in server pack; extracting .jar files from root..."
        unzip -o "$PACK_FILE" "*.jar" -d "$MODS_STAGE" 2>/dev/null || true
        log "Extracted .jar files from server pack root."
    fi

    # Extract NeoForge/Forge launcher infrastructure so run.sh and libraries/
    # stay in sync with the pack version whenever NeoForge is updated.
    INFRA_TMP=$(mktemp -d /var/tmp/mc-infra-XXXXXX)
    log "Extracting launcher infrastructure (libraries/, run.sh) from server pack..."
    unzip -o "$PACK_FILE" "libraries/*" "run.sh" "run.bat" -d "$INFRA_TMP" 2>/dev/null || true
    if [[ -d "${INFRA_TMP}/libraries" ]]; then
        log "Launcher libraries staged."
    else
        log "WARN: No libraries/ in server pack; NeoForge/Forge may not be installed."
    fi

elif [[ "$PACK_SOURCE" == "curseforge" && "$CF_DOWNLOAD_METHOD" == "manifest" ]]; then

    unzip -o "$PACK_FILE" "manifest.json" -d "$EXTRACT_TMP"
    unzip -o "$PACK_FILE" "overrides/*" -d "$EXTRACT_TMP" 2>/dev/null || true

    MANIFEST="${EXTRACT_TMP}/manifest.json"
    MOD_COUNT=$(jq '.files | length' "$MANIFEST")
    log "Downloading ${MOD_COUNT} mods from CurseForge manifest..."

    FAILED_MODS=0
    MOD_NUM=0
    while IFS= read -r mod_entry; do
        proj_id=$(echo "$mod_entry" | jq -r '.projectID')
        file_id=$(echo "$mod_entry" | jq -r '.fileID')
        required=$(echo "$mod_entry" | jq -r '.required')
        MOD_NUM=$(( MOD_NUM + 1 ))

        if [[ -n "${CF_EXCLUDE_SET[${proj_id}]:-}" ]]; then
            log "[${MOD_NUM}/${MOD_COUNT}] Skipping excluded project ${proj_id} (client-only mod)."
            continue
        fi

        if ! mod_url=$(cf_get "/mods/${proj_id}/files/${file_id}/download-url" | jq -r '.data // empty'); then
            if [[ "$required" == "true" ]]; then
                log "ERROR: Required mod ${proj_id}/${file_id}: download-url API lookup failed."
                FAILED_MODS=$(( FAILED_MODS + 1 ))
            else
                log "WARN: Optional mod ${proj_id}/${file_id}: download-url API lookup failed. Skipping."
            fi
            continue
        fi

        if [[ -z "$mod_url" ]]; then
            if [[ "$required" == "true" ]]; then
                log "ERROR: Required mod ${proj_id}/${file_id} has no download URL (CDN restricted)."
                FAILED_MODS=$(( FAILED_MODS + 1 ))
            else
                log "WARN: Optional mod ${proj_id}/${file_id} has no download URL. Skipping."
            fi
            continue
        fi

        filename=$(basename "${mod_url%%\?*}")
        log "[${MOD_NUM}/${MOD_COUNT}] ${filename}"
        curl -fsSL \
            -H "User-Agent: ${UA}" \
            -o "${MODS_STAGE}/${filename}" \
            "$mod_url" \
        || {
            rm -f "${MODS_STAGE}/${filename}"
            if [[ "$required" == "true" ]]; then
                log "ERROR: Required mod ${proj_id}/${file_id} failed to download."
                FAILED_MODS=$(( FAILED_MODS + 1 ))
            else
                log "WARN: Optional mod ${proj_id}/${file_id} failed to download."
            fi
        }

    done < <(jq -c '.files[]' "$MANIFEST")

    if [[ -d "${EXTRACT_TMP}/overrides/mods" ]]; then
        cp -a "${EXTRACT_TMP}/overrides/mods/." "$MODS_STAGE/"
    fi

    if (( FAILED_MODS > 0 )); then
        log "ERROR: ${FAILED_MODS} required mod(s) could not be downloaded; live installation is unchanged."
        exit 1
    fi

fi

chown -R minecraft:minecraft "$MODS_STAGE"
find "$MODS_STAGE" -type d -exec chmod 755 {} +
find "$MODS_STAGE" -type f -exec chmod 644 {} +

###############################################################################
# Stop service and atomically install staged content
###############################################################################

if [[ "$SERVICE_WAS_RUNNING" == true ]]; then
    log "Stopping ${SERVICE}..."
    systemctl stop "$SERVICE"
fi

if [[ -d "$MODS_DIR" ]]; then
    log "Moving current mods to ${BACKUP_DIR}..."
    mv "$MODS_DIR" "$BACKUP_DIR"
fi
mv "$MODS_STAGE" "$MODS_DIR"
MODS_STAGE=""
SWAP_COMPLETE=true

# Apply non-mod overrides only after all required downloads have succeeded.
if [[ "$PACK_SOURCE" == "curseforge" && "$CF_DOWNLOAD_METHOD" == "manifest" && -d "${EXTRACT_TMP}/overrides" ]]; then
    while IFS= read -r override_path; do
        cp -a "$override_path" "${MINECRAFT_DIR}/"
    done < <(find "${EXTRACT_TMP}/overrides" -mindepth 1 -maxdepth 1 ! -name mods -print)
    log "Non-mod overrides applied."
fi

if [[ -n "$INFRA_TMP" ]]; then
    if [[ -d "${INFRA_TMP}/libraries" ]]; then
        rm -rf "${MINECRAFT_DIR}/libraries"
        mv "${INFRA_TMP}/libraries" "${MINECRAFT_DIR}/libraries"
        chown -R minecraft:minecraft "${MINECRAFT_DIR}/libraries"
    fi
    for _f in run.sh run.bat; do
        if [[ -f "${INFRA_TMP}/${_f}" ]]; then
            cp "${INFRA_TMP}/${_f}" "${MINECRAFT_DIR}/${_f}"
            chown minecraft:minecraft "${MINECRAFT_DIR}/${_f}"
        fi
    done
    [[ -f "${MINECRAFT_DIR}/run.sh" ]] && chmod +x "${MINECRAFT_DIR}/run.sh"
    log "Launcher infrastructure updated."
fi

###############################################################################
# Start service
###############################################################################

if [[ "$SERVICE_WAS_RUNNING" == true ]]; then
    log "Starting ${SERVICE}..."
    systemctl start "$SERVICE"
    log "${SERVICE} started."
elif systemctl cat "$SERVICE" &>/dev/null; then
    log "${SERVICE} was stopped before the update; leaving it stopped."
else
    log "${SERVICE} unit not installed yet; skipping start (Ansible will handle it)."
fi

###############################################################################
# Write version ID only after installation and service startup succeed
###############################################################################

EXCLUDES_TMP=$(mktemp "${MINECRAFT_DIR}/.current_excludes.XXXXXX")
printf '%s' "${EXCLUDE_CF_PROJECTS:-}" > "$EXCLUDES_TMP"
chown minecraft:minecraft "$EXCLUDES_TMP"
chmod 0644 "$EXCLUDES_TMP"

VERSION_TMP=$(mktemp "${MINECRAFT_DIR}/.current_version.XXXXXX")
printf '%s\n' "$LATEST_ID" > "$VERSION_TMP"
chown minecraft:minecraft "$VERSION_TMP"
chmod 0644 "$VERSION_TMP"

# Move the version marker last: if committing the exclusion marker fails, the
# old version remains authoritative and the next run retries the installation.
mv "$EXCLUDES_TMP" "$CURRENT_EXCLUDES_FILE"
mv "$VERSION_TMP" "$CURRENT_VERSION_FILE"
SWAP_COMPLETE=false

log "Pruning old backups (keeping latest 3)..."
mapfile -t OLD_BACKUPS < <(
    find "$MINECRAFT_DIR" -maxdepth 1 -type d -name 'mods.bak.*' -printf '%T@ %p\n' \
        | sort -rn | cut -d' ' -f2- | tail -n +4
)
for old in "${OLD_BACKUPS[@]}"; do
    log "Removing: ${old}"
    rm -rf "$old"
done

###############################################################################
# Success
###############################################################################

log "Update complete: ${PACK_NAME} is now ${LATEST_NAME} (${LATEST_ID})."
discord_notify "✅ ${PACK_NAME} updated to ${LATEST_NAME}"

exit 0
