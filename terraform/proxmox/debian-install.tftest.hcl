mock_provider "proxmox" {}

variables {
  iso_installations = {}
}

run "test_disabled" {
  command = plan
  variables {
    debian_install_test  = null
    pbs_storage_password = "mock-pbs-password"
  }
  assert {
    condition     = length(proxmox_virtual_environment_vm.debian_install_test) == 0
    error_message = "The installer test must be disabled by default."
  }
}

run "bounded_iso_vm" {
  command = plan
  variables {
    pbs_storage_password = "mock-pbs-password"
    debian_install_test = {
      vm_id             = 999
      node_name         = "test-node"
      datastore_id      = "test-storage"
      installer_file_id = "local:iso/debian-test.iso"
      bridge            = "vmbr0"
      vlan_id           = 40
      uuid              = "11111111-2222-3333-4444-555555555555"
    }
  }
  assert {
    condition = (
      length(proxmox_virtual_environment_vm.debian_install_test) == 1 &&
      !proxmox_virtual_environment_vm.debian_install_test[0].on_boot &&
      proxmox_virtual_environment_vm.debian_install_test[0].cpu[0].limit == 2 &&
      proxmox_virtual_environment_vm.debian_install_test[0].memory[0].dedicated == 2048 &&
      length(proxmox_virtual_environment_vm.debian_install_test[0].disk) == 1 &&
      proxmox_virtual_environment_vm.debian_install_test[0].disk[0].size == 12 &&
      !proxmox_virtual_environment_vm.debian_install_test[0].disk[0].backup &&
      proxmox_virtual_environment_vm.debian_install_test[0].cdrom[0].file_id == "local:iso/debian-test.iso"
    )
    error_message = "The test must use one small disk, bounded resources, and the selected ISO without host autostart."
  }
}

run "installed_disk_boot" {
  command = plan
  variables {
    pbs_storage_password = "mock-pbs-password"
    debian_install_test = {
      vm_id             = 999
      node_name         = "test-node"
      datastore_id      = "test-storage"
      installer_file_id = "local:iso/debian-test.iso"
      bridge            = "vmbr0"
      vlan_id           = 40
      uuid              = "11111111-2222-3333-4444-555555555555"
      installed         = true
    }
  }
  assert {
    condition = (
      proxmox_virtual_environment_vm.debian_install_test[0].cdrom[0].file_id == "none" &&
      length(proxmox_virtual_environment_vm.debian_install_test[0].boot_order) == 1 &&
      proxmox_virtual_environment_vm.debian_install_test[0].boot_order[0] == "scsi0"
    )
    error_message = "After installation, the VM must boot only its disk with no ISO attached."
  }
}
