#!/usr/bin/env bash
# apply-manual-pack.sh — deploy a pack_source: manual server's mods/config
# from a local server pack file onto its LXC.
#
# Runs on the Ansible controller (not the LXC — unlike update-modpack.sh).
# Accepts either:
#   - a CurseForge/ServerPackCreator-style server pack zip (mods/, config/,
#     defaultconfigs/, datapacks/ at the zip root), or
#   - a Modrinth .mrpack file (modrinth.index.json + overrides/), which is
#     assembled into the same shape by downloading each server-side file
#     from its index URL and layering overrides/ (then server-overrides/) on top.
#
# Usage: apply-manual-pack.sh <pack.zip|pack.mrpack> <root@host>
#
# After this script finishes, run `ansible-playbook site.yml -e
# server_filter=<hostname>` to reconcile the rest (JVM env, systemd unit,
# loader install if run.sh is missing, update timer disabled).

set -euo pipefail

log() { echo "[apply-manual-pack] $*" >&2; }

if [[ $# -ne 2 ]]; then
  echo "Usage: $0 <pack.zip|pack.mrpack> <root@host>" >&2
  exit 1
fi

PACK="$1"
REMOTE="$2"

[[ -f "$PACK" ]] || { log "ERROR: '$PACK' not found."; exit 1; }

WORKDIR=$(mktemp -d)
trap 'rm -rf "$WORKDIR"' EXIT

SERVERPACK="$WORKDIR/serverpack"
mkdir -p "$SERVERPACK"

if unzip -l "$PACK" | grep -q "modrinth.index.json"; then
  log "Detected .mrpack format. Assembling server pack..."

  unzip -q -o "$PACK" -d "$WORKDIR/mrpack"
  INDEX="$WORKDIR/mrpack/modrinth.index.json"

  MC_VERSION=$(jq -r '.dependencies.minecraft // empty' "$INDEX")
  FORGE_VERSION=$(jq -r '.dependencies.forge // empty' "$INDEX")
  NEOFORGE_VERSION=$(jq -r '.dependencies.neoforge // empty' "$INDEX")
  FABRIC_VERSION=$(jq -r '.dependencies["fabric-loader"] // empty' "$INDEX")
  QUILT_VERSION=$(jq -r '.dependencies["quilt-loader"] // empty' "$INDEX")

  log "mc_version: ${MC_VERSION:-?}"
  [[ -n "$FORGE_VERSION" ]] && log "loader: forge, loader_version: $FORGE_VERSION"
  [[ -n "$NEOFORGE_VERSION" ]] && log "loader: neoforge, loader_version: $NEOFORGE_VERSION"
  [[ -n "$FABRIC_VERSION" ]] && log "loader: fabric, loader_version: $FABRIC_VERSION (fabric installs itself; loader_version informational only)"
  [[ -n "$QUILT_VERSION" ]] && log "loader: quilt, loader_version: $QUILT_VERSION (quilt installs itself; loader_version informational only)"
  log "Make sure servers.yml has matching loader/mc_version/loader_version values."

  FILE_COUNT=$(jq '[.files[] | select(.env.server != "unsupported")] | length' "$INDEX")
  log "Downloading ${FILE_COUNT} server-required file(s) from the index..."

  jq -c '.files[] | select(.env.server != "unsupported") | {path: .path, url: .downloads[0]}' "$INDEX" |
    while IFS= read -r row; do
      path=$(echo "$row" | jq -r '.path')
      url=$(echo "$row" | jq -r '.url')
      dest="$SERVERPACK/$path"
      mkdir -p "$(dirname "$dest")"
      curl -fsSL -o "$dest" "$url"
    done

  if [[ -d "$WORKDIR/mrpack/overrides" ]]; then
    log "Layering overrides/ onto the assembled pack..."
    cp -R "$WORKDIR/mrpack/overrides/." "$SERVERPACK/"
  fi
  if [[ -d "$WORKDIR/mrpack/server-overrides" ]]; then
    log "Layering server-overrides/ onto the assembled pack (takes priority)..."
    cp -R "$WORKDIR/mrpack/server-overrides/." "$SERVERPACK/"
  fi
else
  log "Detected plain server pack zip. Extracting..."
  unzip -q -o "$PACK" -d "$SERVERPACK"
fi

log "Assembled pack contents:"
for d in mods config defaultconfigs datapacks; do
  if [[ -d "$SERVERPACK/$d" ]]; then
    log "  $d/: $(find "$SERVERPACK/$d" -type f | wc -l | tr -d ' ') file(s)"
  fi
done

log "Stopping Minecraft service on $REMOTE and backing up existing dirs..."
TS=$(date +%Y%m%d_%H%M%S)
ssh "$REMOTE" "
  svc=\$(systemctl list-units 'minecraft@*' --no-legend | awk '{print \$1}')
  [[ -n \"\$svc\" ]] && systemctl stop \"\$svc\"
  cd /opt/minecraft
  for d in mods config defaultconfigs; do
    [[ -d \"\$d\" ]] && mv \"\$d\" \"\${d}.pre-zip-recreate.${TS}\"
  done
  mkdir -p mods config defaultconfigs world/datapacks
"

log "Syncing mods/config/defaultconfigs/datapacks to $REMOTE..."
rsync -az "$SERVERPACK/mods/" "$REMOTE:/opt/minecraft/mods/"
[[ -d "$SERVERPACK/config" ]] && rsync -az "$SERVERPACK/config/" "$REMOTE:/opt/minecraft/config/"
[[ -d "$SERVERPACK/defaultconfigs" ]] && rsync -az "$SERVERPACK/defaultconfigs/" "$REMOTE:/opt/minecraft/defaultconfigs/"
[[ -d "$SERVERPACK/datapacks" ]] && rsync -az "$SERVERPACK/datapacks/" "$REMOTE:/opt/minecraft/world/datapacks/"

ssh "$REMOTE" "chown -R minecraft:minecraft /opt/minecraft"

log "Done. Old dirs backed up as *.pre-zip-recreate.${TS} on $REMOTE."
log "Next: ansible-playbook site.yml --vault-password-file ~/.vaultpass -e server_filter=<hostname>"
