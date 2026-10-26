mock_provider "proxmox" {}

run "no_automatic_vms_by_default" {
  command = plan
  variables {
    iso_installations    = {}
    pbs_storage_password = "mock-pbs-password"
  }
  assert {
    condition = (
      length(proxmox_virtual_environment_vm.iso_installation) == 0 &&
      length(proxmox_virtual_environment_file.install_media) == 0
    )
    error_message = "The automatic installer must not create VMs or media until configured."
  }
}

run "automatic_vm_is_bounded_and_disk_first" {
  command = plan
  variables {
    pbs_storage_password = "mock-pbs-password"
    iso_library = {
      base_url = "http://iso.example"
      nodes    = ["test-node"]
      files    = { "debian-test.iso" = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" }
    }
    iso_installations = {
      automated-test = {
        vm_id               = 999
        node_name           = "test-node"
        datastore_id        = "test-storage"
        os                  = "debian"
        iso_filename        = "debian-test.iso"
        bridge              = "vmbr0"
        vlan_id             = 40
        ipv4_address        = "192.0.2.4/24"
        gateway             = "192.0.2.1"
        dns_servers         = ["192.0.2.1"]
        ssh_public_key_file = "tests/install.pub"
        on_boot             = false
        backup              = false
      }
    }
  }
  assert {
    condition = (
      length(proxmox_virtual_environment_vm.iso_installation) == 1 &&
      length(terraform_data.install_identity) == 1 &&
      !proxmox_virtual_environment_vm.iso_installation["automated-test"].on_boot &&
      length(proxmox_virtual_environment_vm.iso_installation["automated-test"].disk) == 1 &&
      proxmox_virtual_environment_vm.iso_installation["automated-test"].disk[0].size == 24 &&
      proxmox_virtual_environment_vm.iso_installation["automated-test"].boot_order[0] == "scsi0" &&
      !proxmox_virtual_environment_file.install_media["automated-test"].overwrite
    )
    error_message = "The installer must use a new disk-first VM and refuse to overwrite cached media."
  }
}
