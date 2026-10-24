#!/bin/bash
# Read-only smoke check. Run as the development user after a live installation.
set -eu
for tool in git gh cmake ninja node uv ansible ansible-lint; do
    /usr/bin/env PATH="/opt/homebrew/bin:$PATH" /usr/bin/which "$tool" >/dev/null
done
test -d /Applications/Codex.app
/bin/launchctl print system/com.openssh.sshd >/dev/null
/bin/launchctl print system/com.apple.screensharing >/dev/null
for group in com.apple.access_ssh com.apple.access_screensharing; do
    /usr/sbin/dseditgroup -o checkmember -m "$(id -un)" "$group"
done
/usr/bin/pmset -g custom
printf '%s\n' 'Local checks passed. Verify SSH and Screen Sharing from another Mac.'
