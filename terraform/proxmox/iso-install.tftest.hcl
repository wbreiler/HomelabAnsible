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
      proxmox_virtual_environment_vm.iso_installation["automated-test"].bios == "seabios" &&
      length(proxmox_virtual_environment_vm.iso_installation["automated-test"].efi_disk) == 0 &&
      !proxmox_virtual_environment_vm.iso_installation["automated-test"].on_boot &&
      length(proxmox_virtual_environment_vm.iso_installation["automated-test"].disk) == 1 &&
      proxmox_virtual_environment_vm.iso_installation["automated-test"].disk[0].size == 24 &&
      proxmox_virtual_environment_vm.iso_installation["automated-test"].boot_order[0] == "scsi0" &&
      !proxmox_virtual_environment_file.install_media["automated-test"].overwrite
    )
    error_message = "The installer must use a new disk-first VM and refuse to overwrite cached media."
  }
}

run "uefi_has_persistent_vars_and_no_secure_boot_keys" {
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
        firmware            = "uefi"
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
      proxmox_virtual_environment_vm.iso_installation["automated-test"].bios == "ovmf" &&
      proxmox_virtual_environment_vm.iso_installation["automated-test"].machine == "q35" &&
      length(proxmox_virtual_environment_vm.iso_installation["automated-test"].efi_disk) == 1 &&
      proxmox_virtual_environment_vm.iso_installation["automated-test"].efi_disk[0].datastore_id == "test-storage" &&
      proxmox_virtual_environment_vm.iso_installation["automated-test"].efi_disk[0].type == "4m" &&
      !proxmox_virtual_environment_vm.iso_installation["automated-test"].efi_disk[0].pre_enrolled_keys &&
      terraform_data.install_identity["automated-test"].input.firmware == "uefi"
    )
    error_message = "UEFI needs OVMF, q35, persistent 4m EFI variables, and explicit Secure Boot policy."
  }
}

run "secure_boot_enrolls_keys_and_sets_creation_policy" {
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
        firmware            = "uefi"
        secure_boot         = true
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
      proxmox_virtual_environment_vm.iso_installation["automated-test"].bios == "ovmf" &&
      proxmox_virtual_environment_vm.iso_installation["automated-test"].machine == "q35" &&
      length(proxmox_virtual_environment_vm.iso_installation["automated-test"].efi_disk) == 1 &&
      proxmox_virtual_environment_vm.iso_installation["automated-test"].efi_disk[0].datastore_id == "test-storage" &&
      proxmox_virtual_environment_vm.iso_installation["automated-test"].efi_disk[0].type == "4m" &&
      proxmox_virtual_environment_vm.iso_installation["automated-test"].efi_disk[0].pre_enrolled_keys &&
      terraform_data.install_identity["automated-test"].input.firmware == "uefi" &&
      terraform_data.install_identity["automated-test"].input.secure_boot
    )
    error_message = "UEFI needs OVMF, q35, persistent 4m EFI variables, and explicit Secure Boot policy."
  }
}

run "secure_boot_rejects_bios" {
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
        firmware            = "bios"
        secure_boot         = true
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
  expect_failures = [var.iso_installations]
}
