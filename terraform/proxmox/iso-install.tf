variable "iso_installations" {
  description = "New, automatically installed server VMs. Source filenames must exist in the pinned ISO library."
  type = map(object({
    vm_id               = number
    node_name           = string
    datastore_id        = string
    os                  = string
    iso_filename        = string
    bridge              = string
    vlan_id             = number
    ipv4_address        = string
    gateway             = string
    dns_servers         = list(string)
    ssh_public_key_file = string
    username            = optional(string, "ansible")
    cores               = optional(number, 2)
    memory_mb           = optional(number, 2048)
    disk_gb             = optional(number, 24)
    on_boot             = optional(bool, true)
    backup              = optional(bool, true)
  }))
  default = {}

  validation {
    condition = alltrue([for name, vm in var.iso_installations :
      can(regex("^[a-z][a-z0-9-]{0,61}[a-z0-9]$", name)) &&
      contains(["debian", "ubuntu", "fedora"], vm.os) &&
      can(cidrnetmask(vm.ipv4_address)) &&
      can(regex("^[a-z_][a-z0-9_-]{0,31}$", vm.username)) && vm.username != "root" &&
      can(regex("^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(256|384|521)) [A-Za-z0-9+/]+=*( [^\\r\\n]*)?$", trimspace(file(pathexpand(vm.ssh_public_key_file))))) &&
      vm.vm_id >= 100 && vm.cores >= 1 && vm.memory_mb >= 2048 && vm.disk_gb >= 24 &&
      try(contains(var.iso_library.nodes, vm.node_name), false) &&
      can(var.iso_library.files[vm.iso_filename])
    ])
    error_message = "Use valid hostnames, a non-root user, a public SSH key file, IPv4 CIDRs, supported OS families, bounded server resources, and a node/image in the pinned ISO library."
  }

  validation {
    condition = (
      length(distinct([for vm in var.iso_installations : vm.vm_id])) == length(var.iso_installations) &&
      length(distinct([for vm in var.iso_installations : split("/", vm.ipv4_address)[0]])) == length(var.iso_installations)
    )
    error_message = "Installation VMs must have distinct VMIDs and IP addresses."
  }
}

resource "terraform_data" "install_identity" {
  for_each         = var.iso_installations
  input            = { vm_id = each.value.vm_id, node_name = each.value.node_name }
  triggers_replace = [each.value.vm_id, each.value.node_name]
}

locals {
  install_specs = {
    for name, vm in var.iso_installations : name => merge(vm, {
      name          = name
      uuid          = terraform_data.install_identity[name].id
      public_key    = trimspace(file(pathexpand(vm.ssh_public_key_file)))
      source_url    = "${try(trimsuffix(var.iso_library.base_url, "/"), "")}/${vm.iso_filename}"
      source_sha256 = try(var.iso_library.files[vm.iso_filename], "")
      output_iso    = "${abspath(path.module)}/artifacts/iso-install/${terraform_data.install_identity[name].id}/autoinstall.iso"
    })
  }
  install_media_specs = {
    for name, spec in local.install_specs : name => {
      for key, value in spec : key => value if contains([
        "name", "os", "uuid", "username", "public_key", "ipv4_address", "gateway", "dns_servers",
        "source_url", "source_sha256", "iso_filename", "output_iso",
      ], key)
    }
  }
}

resource "terraform_data" "install_media" {
  for_each = local.install_media_specs
  input    = each.value
  # Existing boot media is immutable. Builder updates apply to newly declared VMs.
  triggers_replace = [each.value]

  provisioner "local-exec" {
    interpreter = ["python3", "${path.module}/scripts/iso_install.py"]
    command     = "build"
    environment = {
      ISO_INSTALL_SPEC = jsonencode(self.input)
    }
  }
}

resource "proxmox_virtual_environment_file" "install_media" {
  for_each     = local.install_specs
  content_type = "iso"
  datastore_id = var.iso_library.datastore_id
  node_name    = each.value.node_name
  overwrite    = false

  source_file {
    path      = terraform_data.install_media[each.key].output.output_iso
    file_name = "tf-install-${each.value.os}-${each.value.uuid}.iso"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "proxmox_virtual_environment_vm" "iso_installation" {
  for_each            = local.install_specs
  name                = each.key
  node_name           = each.value.node_name
  vm_id               = each.value.vm_id
  description         = "Automatic ${each.value.os} ISO installation. Provisioning owned by Terraform."
  started             = true
  on_boot             = each.value.on_boot
  boot_order          = ["scsi0", "ide2"]
  scsi_hardware       = "virtio-scsi-single"
  stop_on_destroy     = true
  reboot_after_update = false
  tags                = ["terraform", "iso-install"]

  cpu {
    cores = each.value.cores
    limit = each.value.cores
    type  = "x86-64-v2-AES"
  }
  memory {
    dedicated = each.value.memory_mb
    floating  = each.value.memory_mb
  }
  disk {
    datastore_id = each.value.datastore_id
    interface    = "scsi0"
    size         = each.value.disk_gb
    backup       = each.value.backup
    replicate    = false
    discard      = "on"
  }
  cdrom {
    file_id   = proxmox_virtual_environment_file.install_media[each.key].id
    interface = "ide2"
  }
  network_device {
    bridge  = each.value.bridge
    vlan_id = each.value.vlan_id
    model   = "virtio"
  }
  operating_system {
    type = "l26"
  }
  smbios {
    uuid = each.value.uuid
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

resource "terraform_data" "installation_ready" {
  for_each         = local.install_specs
  input            = each.value
  triggers_replace = [proxmox_virtual_environment_vm.iso_installation[each.key].id, each.value]

  provisioner "local-exec" {
    interpreter = ["python3", "${path.module}/scripts/iso_install.py"]
    command     = "wait"
    environment = {
      ISO_INSTALL_SPEC = jsonencode(self.input)
    }
  }
}

output "installed_vms" {
  description = "VMs whose automatic installation and SSH verification completed."
  value = {
    for name, vm in var.iso_installations : name => {
      vm_id        = vm.vm_id
      node_name    = vm.node_name
      ipv4_address = vm.ipv4_address
      os           = vm.os
    }
  }
  depends_on = [terraform_data.installation_ready]
}
