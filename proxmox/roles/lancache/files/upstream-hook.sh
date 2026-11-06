#!/bin/sh
set -eu
# The image rewrites its nginx files before it runs this final hook.
cp /etc/lancache-upstream.conf /etc/nginx/sites-available/20_upstream.conf
