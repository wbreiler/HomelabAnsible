# ISO web server

Prepared as a TrueNAS custom app. It is not deployed yet. The local deployment
file selects a dedicated macvlan address on Erebus's existing storage interface.
The app serves an existing ISO directory read-only through nginx on port 80.

## Configuration

Copy `vars.yml.example` to the ignored `vars.yml` and review the address,
subnet, gateway, existing parent interface, and existing ISO directory.
The app does not create datasets, source directories, or host port mappings.
It uses an immutable nginx image digest, an unprivileged user, a read-only
container filesystem, and a single-address Docker allocation pool.

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

The staged app passed two local storage/network boundary tests, Erebus's Docker
Compose parser, Ansible lint, syntax validation, and a read-only Ansible preview.
The preview reported that the app would be created and skipped every mutation.
Runtime nginx startup, HTTP service, range downloads, restart persistence, and
the final no-change application run remain untested until deployment approval.

Run `tests/test_iso_server.py` with the same Python environment as Ansible so
its existing Jinja2 and YAML dependencies are available.
