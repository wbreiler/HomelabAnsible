mock_provider "proxmox" {}

run "discovery_only" {
  command = plan

  variables {
    pilot                = null
    pbs_storage_password = "mock-pbs-password"
  }

  assert {
    condition     = length(proxmox_virtual_environment_container.pilot) == 0
    error_message = "Discovery-only mode must not manage a guest."
  }
}

run "isolated_pilot" {
  command = plan

  variables {
    pbs_storage_password = "mock-pbs-password"
    pilot = {
      vm_id            = 100
      node_name        = "test-node"
      datastore_id     = "test-storage"
      template_file_id = "local:vztmpl/debian-test.tar.zst"
      bridge           = "vmbr0"
      vlan_id          = 40
      ipv4_address     = "192.0.2.5/24"
      gateway          = "192.0.2.1"
      dns_servers      = ["192.0.2.1"]
      ssh_public_key   = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBsLAPW1H6GXxKExXTJ4dPP1dyiNrZgRvpXbE2jH8R8K test"
    }
  }

  assert {
    condition = (
      length(proxmox_virtual_environment_container.pilot) == 1 &&
      proxmox_virtual_environment_container.pilot[0].unprivileged &&
      proxmox_virtual_environment_container.pilot[0].features[0].nesting &&
      proxmox_virtual_environment_container.pilot[0].cpu[0].limit == 1 &&
      proxmox_virtual_environment_container.pilot[0].memory[0].dedicated == 512 &&
      proxmox_virtual_environment_container.pilot[0].disk[0].size == 4 &&
      length(proxmox_virtual_environment_container.pilot[0].mount_point) == 0
    )
    error_message = "The pilot must remain one small, unprivileged guest without extra mounts."
  }
}
