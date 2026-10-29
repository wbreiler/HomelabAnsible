#!/usr/bin/env bash
# apply-manual-pack.sh — deploy a pack_source: manual server's mods/config
# from a local server pack file onto its LXC.
#
# Runs on the Ansible controller (not the LXC — unlike update-modpack.sh).
# Accepts either:
#   - a CurseForge/ServerPackCreator-style server pack zip (mods/, config/,
#     defaultconfigs/, kubejs/, datapacks/ at the zip root), or
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
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
python3 "$SCRIPT_DIR/pack_archive.py" assemble "$PACK" "$SERVERPACK"
[[ -d "$SERVERPACK/mods" ]] || { log "ERROR: Server pack has no mods directory."; exit 1; }

log "Assembled pack contents:"
for d in mods config defaultconfigs kubejs datapacks; do
  if [[ -d "$SERVERPACK/$d" ]]; then
    log "  $d/: $(find "$SERVERPACK/$d" -type f | wc -l | tr -d ' ') file(s)"
  fi
done

log "Stopping Minecraft service on $REMOTE and backing up existing dirs..."
TS=$(date +%Y%m%d_%H%M%S)
ssh "$REMOTE" "
  svc=\$(systemctl list-units 'minecraft@*' --no-legend | awk '{print \$1}')
  [[ -n \"\$svc\" ]] && systemctl stop \"\$svc\"
  runuser -u minecraft -- bash -eu -c '
  cd /opt/minecraft
  for d in mods config defaultconfigs kubejs; do
    [[ -d \"\$d\" ]] && mv \"\$d\" \"\${d}.pre-zip-recreate.${TS}\"
  done
  mkdir -p mods config defaultconfigs kubejs world/datapacks
  '
"

log "Syncing mods/config/defaultconfigs/kubejs/datapacks to $REMOTE..."
rsync -az --rsync-path='runuser -u minecraft -- rsync' "$SERVERPACK/mods/" "$REMOTE:/opt/minecraft/mods/"
[[ -d "$SERVERPACK/config" ]] && rsync -az --rsync-path='runuser -u minecraft -- rsync' "$SERVERPACK/config/" "$REMOTE:/opt/minecraft/config/"
[[ -d "$SERVERPACK/defaultconfigs" ]] && rsync -az --rsync-path='runuser -u minecraft -- rsync' "$SERVERPACK/defaultconfigs/" "$REMOTE:/opt/minecraft/defaultconfigs/"
[[ -d "$SERVERPACK/kubejs" ]] && rsync -az --rsync-path='runuser -u minecraft -- rsync' "$SERVERPACK/kubejs/" "$REMOTE:/opt/minecraft/kubejs/"
[[ -d "$SERVERPACK/datapacks" ]] && rsync -az --rsync-path='runuser -u minecraft -- rsync' "$SERVERPACK/datapacks/" "$REMOTE:/opt/minecraft/world/datapacks/"

log "Done. Old dirs backed up as *.pre-zip-recreate.${TS} on $REMOTE."
log "Next: ansible-playbook site.yml --vault-password-file ~/.vaultpass -e server_filter=<hostname>"
