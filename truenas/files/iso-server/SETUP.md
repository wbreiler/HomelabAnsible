# ISO web server

Deployed as a TrueNAS custom app after explicit approval on 2026-10-26. The local
deployment file selects a dedicated macvlan address on Erebus's existing storage
interface. The app serves an existing ISO directory read-only through nginx on
port 80. Host addresses, routes, and all ten existing ISO files were unchanged.

## Configuration

Copy `vars.yml.example` to the ignored `vars.yml` and review the address,
subnet, gateway, existing parent interface, and existing ISO directory.
The app does not create datasets, source directories, or host port mappings.
It uses an immutable nginx image digest, an unprivileged user, a read-only
container filesystem, and a single-address Docker allocation pool.

A dedicated appdata directory contains `nginx.conf`, mounted read-only into
the service. This Compose runtime rejects inline configs for a read-only
service, so the playbook installs a file-backed config. Config changes notify
a targeted TrueNAS redeploy of this app only.

The proposed address passed repository inventory and live ARP checks. These
checks cannot establish that an offline device has no claim to the address.
Reserve and approve the selected address before deployment.

Macvlan containers cannot communicate directly with their host by default.
Clients on the storage network and routed controller network can use the
dedicated address. The ISO mount is local, so the server does not require
host-to-container networking. Do not add a host shim or alter the primary
interface to bypass this restriction without a separate approval.
See [Docker's macvlan documentation](https://docs.docker.com/engine/network/drivers/macvlan/).

## Deployment after approval

1. Obtain approval for the exact app address and macvlan parent/subnet/gateway.
2. Export a fresh protected TrueNAS configuration backup with `playbooks/backup.yml`.
3. Run the preview from `truenas/`:

   ```sh
   ansible-playbook playbooks/iso-server.yml --check --diff
   ```

4. Apply only this app:

   ```sh
   ansible-playbook playbooks/iso-server.yml \
     -e truenas_allow_changes=true \
     -e truenas_allow_management_access_changes=true
   ```

5. Verify HTTP listing and byte-range downloads from a controller/PVE client,
   then repeat the playbook and require `changed=0`.

Use a fresh dated path for the configuration backup. It contains secrets and
must remain ignored with mode `0600`. No file permission or dataset changes are
part of this app deployment. The existing ISO directory and its files passed
readability checks for the proposed service user.

## Terraform sources

After HTTP works, match ISO bytes to the existing PVE files using checksums.
Names and sizes alone are insufficient. Use the new server URL only for exact
matches or explicitly new image versions. Preserve existing cached guest media
and deletion guards. Do not change a Terraform source in a way that replaces
active boot files.

The deployed app passed:

- Two local storage/network boundary tests and Ansible lint/syntax validation.
- Directory listing from the Mac and byte-range HTTP 206 requests from both PVE nodes.
- A complete 791,674,880-byte ISO download streamed from Prometheus, with SHA256
  matching the trusted NAS source.
- A targeted app redeploy followed by successful HTTP service.
- A repeat application playbook with `changed=0` and no failures.

Docker inspection confirmed the non-root user, dropped capabilities, read-only
container filesystem, read-only ISO mount, dedicated address, and restart policy.
A protected dated TrueNAS configuration backup exists under ignored `artifacts/`.
The full NAS reboot path and reconstruction of missing ISO files remain untested.

Run `tests/test_iso_server.py` with the same Python environment as Ansible so
its existing Jinja2 and YAML dependencies are available.
