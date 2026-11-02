set -euo pipefail
cd /opt/nexdeck/app/frontend
patch_file=$(mktemp /tmp/nexdeck-topology.XXXXXX)
trap 'rm -f "$patch_file"' EXIT
cat > "$patch_file"
needs_build=false
if patch --batch --fuzz=0 --forward --dry-run -p1 < "$patch_file" >/dev/null 2>&1; then
  needs_build=true
  if [ "$1" != check ]; then
    install -d -m 0700 /opt/nexdeck/frontend-backups
    source_backup=$(mktemp -d /opt/nexdeck/frontend-backups/source.XXXXXX)
    cp src/components/TopologyCard.tsx src/components/TopologyCard.test.tsx "$source_backup/"
    patch --batch --fuzz=0 --forward -p1 < "$patch_file"
  fi
elif ! patch --batch --fuzz=0 --reverse --dry-run -p1 < "$patch_file" >/dev/null 2>&1; then
  echo 'The topology renderer differs from the supported source. Review the patch before deployment.' >&2
  exit 1
fi
fingerprint=$(sha256sum package.json package-lock.json src/components/TopologyCard.tsx src/components/TopologyCard.test.tsx | sha256sum | cut -d ' ' -f 1)
built=$(cat .homelab-topology-build 2>/dev/null || true)
if [ "$fingerprint" != "$built" ]; then
  needs_build=true
fi
if [ "$needs_build" = false ]; then
  exit 0
fi
if [ "$1" = check ]; then
  echo changed
  exit 0
fi
npm test -- src/components/TopologyCard.test.tsx
build_dir=$(mktemp -d "$PWD/.topology-build.XXXXXX")
npm run build -- --outDir "$build_dir"
test -s "$build_dir/index.html"
install -d -m 0700 /opt/nexdeck/frontend-backups
build_backup=$(mktemp -d /opt/nexdeck/frontend-backups/build.XXXXXX)
if [ -d dist ]; then
  mv dist "$build_backup/dist"
fi
if ! mv "$build_dir" dist; then
  if [ -d "$build_backup/dist" ]; then
    mv "$build_backup/dist" dist
  fi
  exit 1
fi
printf '%s\n' "$fingerprint" > .homelab-topology-build.new
mv .homelab-topology-build.new .homelab-topology-build
echo changed
