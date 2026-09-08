# Wyze Bridge

Deploys the upstream Docker image in a dedicated unprivileged Debian LXC.
The image is pinned by version and registry manifest SHA-256 digest. Debian's
signed package repositories supply Docker, Compose, nginx and OpenSSL.

## Deployment

Run from `proxmox/` with the normal inventory and Vault access:

```sh
ansible-playbook site.yml --tags wyze_bridge -e install_wyze_bridge=true --ask-vault-pass
```

The role resolves an existing guest by hostname across the cluster before
using `wyze_bridge_node` as the fresh-install fallback. A new guest gets the
next available cluster VMID, DHCP on the configured VLAN, 2 CPUs, 2 GiB RAM,
8 GiB storage, nesting and boot autostart. It does not enroll the guest in HA.
Check live resources and ignored Minecraft assignments before provisioning.
Debian 13 is required for the packaged Docker Compose v2 used here; select a
Debian 13 template explicitly if the node lacks one.

All state lives in `/opt/wyze-bridge` inside the guest. `tokens/` holds Wyze
session data. `secrets/WB_PASSWORD` and `secrets/WB_API` are generated once,
root-only, and mounted into Docker as files. Never commit or paste their
contents into logs. Preserve this directory when upgrading or backing up.

nginx on port 5050 authenticates every web request, including the upstream
otherwise-unprotected initial `/login` page. Docker's web port binds only to
127.0.0.1:5051. RTSP is port 8554 and HLS is 8888; upstream stream
authentication remains enabled. No router port forwards are needed.

## Sign in

1. Open `http://BRIDGE_IP:5050` on the trusted LAN. For encrypted browser
   access, use an SSH tunnel instead:
   `ssh -L 5050:127.0.0.1:5050 root@BRIDGE_IP`, then open
   `http://localhost:5050`.
2. Use username `wbadmin`. Retrieve the password privately in the guest
   console: `cat /opt/wyze-bridge/secrets/WB_PASSWORD`.
3. Enter your Wyze email, password, API ID and API key in the setup page.
   Generate the API credentials through the
   [Wyze developer console](https://developer-api-console.wyze.com/#/apikey/view).
4. Confirm each camera streams before configuring HomeKit. Unsupported
   camera models cannot be fixed by HomeKit configuration.

## Apple Home with existing Homebridge

Wyze Bridge supplies video streams; Homebridge exposes cameras to HomeKit.

1. In Homebridge's Plugins page install `homebridge-camera-ffmpeg`.
2. Add one camera per Wyze stream. Set Video Source to
   `-rtsp_transport tcp -i rtsp://wb:WB_API@BRIDGE_IP:8554/CAMERA_NAME`.
   Use the exact stream path from Wyze Bridge. The stream username is `wb`;
   its password is the value of `/opt/wyze-bridge/secrets/WB_API`, not the
   web password or your Wyze account password. Enable audio only after confirming it works.
3. Save and restart the affected Homebridge instance or child bridge.
4. In Apple Home select **+ → Add Accessory → More options**, select the
   camera, and enter the pairing code shown in Homebridge. Cameras are
   unbridged by default and must be paired individually.
5. Test live view on the home LAN. Discovery requires multicast DNS between
   Homebridge and Apple devices; across VLANs, check the existing mDNS
   reflector and firewall. Do not change the core switch casually.

[Plugin configuration reference](https://github.com/homebridge-plugins/homebridge-camera-ffmpeg)

## HomeKit Secure Video recordings

For encrypted iCloud event recordings, use
[Scrypted's HomeKit integration](https://docs.scrypted.app/homekit.html).
Install its RTSP and HomeKit plugins, add the authenticated Wyze RTSP stream
for each camera, configure motion detection and prebuffering, and pair each
camera using its HomeKit QR code. Recording requires an Apple home hub and
an eligible iCloud+ plan. An RTSP stream alone does not provide motion events.
Scrypted is not installed by this role.

## Validation boundaries

The role checks that the web endpoint rejects unauthenticated requests.
An authenticated login-page check proves setup is reachable, not that cameras
stream. Wyze login, camera playback and Apple Home pairing require the user's
account and devices and must be verified separately.
