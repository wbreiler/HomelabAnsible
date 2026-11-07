#!/bin/sh
set -eu
# The image rewrites its nginx files before it runs this final hook.
cp /etc/lancache-upstream.conf /etc/nginx/sites-available/20_upstream.conf
cp /etc/lancache-cache-upstream.conf /etc/nginx/sites-available/cache.conf.d/root/90_upstream.conf

cache_server=/etc/nginx/sites-available/10_cache.conf
sed -i 's|access_log /data/logs/access\.log cachelog;|access_log /data/logs/access.log cachelog if=$lancache_log_client;|' "$cache_server"
grep -Fq 'access_log /data/logs/access.log cachelog if=$lancache_log_client;' "$cache_server"
