#!/usr/bin/env bash
# Usage: ./pbs-restore.sh <node> <vmid[,vmid,...]> [--no-force] [--no-start]
#
# Examples:
#   ./pbs-restore.sh prometheus 104
#   ./pbs-restore.sh nyx 103,114
#   ./pbs-restore.sh atlas 200 --no-start
#   ./pbs-restore.sh nyx 103,114 --no-force --no-start

set -euo pipefail

NODE="${1:-}"
VMIDS="${2:-}"

if [[ -z "$NODE" || -z "$VMIDS" ]]; then
  echo "Usage: $0 <node> <vmid[,vmid,...]> [--no-force] [--no-start]" >&2
  exit 1
fi

FORCE=true
START=true

shift 2
for arg in "$@"; do
  case "$arg" in
    --no-force) FORCE=false ;;
    --no-start) START=false ;;
    *) echo "Unknown option: $arg" >&2; exit 1 ;;
  esac
done

# Build pbs_restore_containers JSON array from comma-separated VMIDs
CONTAINERS="["
first=true
IFS=',' read -ra VMID_LIST <<< "$VMIDS"
for vmid in "${VMID_LIST[@]}"; do
  vmid="${vmid// /}"  # strip spaces
  [[ -z "$vmid" ]] && continue
  if ! [[ "$vmid" =~ ^[0-9]+$ ]]; then
    echo "Error: Invalid VMID '${vmid}' - must be a positive integer" >&2
    exit 1
  fi
  "$first" && first=false || CONTAINERS+=","
  CONTAINERS+="{\"vmid\": ${vmid}, \"force\": ${FORCE}, \"start_after_restore\": ${START}}"
done
CONTAINERS+="]"

EXTRA_VARS="{\"restore_from_pbs\": true, \"pbs_restore_node\": \"${NODE}\", \"pbs_restore_containers\": ${CONTAINERS}}"

echo "Restoring on node: ${NODE}"
echo "Containers:        ${VMIDS}"
echo "Force:             ${FORCE}"
echo "Start after:       ${START}"
echo

cd "$(dirname "$0")"
ansible-playbook -i inventory.yml site.yml --tags restore \
  -e "$EXTRA_VARS" \
  --ask-vault-pass
