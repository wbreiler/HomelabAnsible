variable "debian_install_test" {
  description = "Disposable ISO installation VM. Null leaves the test disabled."
  type = object({
    vm_id             = number
    node_name         = string
    datastore_id      = string
    installer_file_id = string
    bridge            = string
    vlan_id           = number
    uuid              = string
    installed         = optional(bool, false)
  })
  default = null
}

resource "proxmox_virtual_environment_vm" "debian_install_test" {
  count = var.debian_install_test == null ? 0 : 1

  name                = "terraform-debian-test"
  description         = "Disposable Debian ISO installation test. Provisioning owned by Terraform."
  node_name           = var.debian_install_test.node_name
  vm_id               = var.debian_install_test.vm_id
  started             = true
  on_boot             = false
  boot_order          = var.debian_install_test.installed ? ["scsi0"] : ["scsi0", "ide2"]
  scsi_hardware       = "virtio-scsi-single"
  stop_on_destroy     = true
  reboot_after_update = false
  tags                = ["disposable", "terraform", "test"]

  cpu {
    cores = 2
    limit = 2
    type  = "x86-64-v2-AES"
  }

  memory {
    dedicated = 2048
    floating  = 2048
  }

  disk {
    datastore_id = var.debian_install_test.datastore_id
    interface    = "scsi0"
    size         = 12
    backup       = false
    replicate    = false
    discard      = "on"
  }

  cdrom {
    file_id   = var.debian_install_test.installed ? "none" : var.debian_install_test.installer_file_id
    interface = "ide2"
  }

  network_device {
    bridge  = var.debian_install_test.bridge
    vlan_id = var.debian_install_test.vlan_id
    model   = "virtio"
  }

  operating_system {
    type = "l26"
  }

  smbios {
    uuid = var.debian_install_test.uuid
  }

  serial_device {}

  agent {
    enabled = true
    wait_for_ip {
      disabled = true
    }
  }

  lifecycle {
    prevent_destroy = true
    ignore_changes  = [tags]
  }
}
