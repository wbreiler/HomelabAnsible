variable "pilot" {
  description = "Local deployment settings for the disposable Debian pilot. Null keeps discovery-only mode."
  type = object({
    vm_id            = number
    node_name        = string
    datastore_id     = string
    template_file_id = string
    bridge           = string
    vlan_id          = number
    ipv4_address     = string
    gateway          = string
    dns_servers      = list(string)
    ssh_public_key   = string
  })
  default = null
}

resource "proxmox_virtual_environment_container" "pilot" {
  count = var.pilot == null ? 0 : 1

  node_name     = var.pilot.node_name
  vm_id         = var.pilot.vm_id
  description   = "Disposable Debian pilot. Provisioning owned by Terraform."
  unprivileged  = true
  started       = true
  start_on_boot = true
  tags          = ["pilot", "terraform"]

  # shortcut: bootstrap nesting via the API until the provider omits extra feature flags.
  features {
    nesting = true
  }

  cpu {
    cores = 1
    limit = 1
  }

  memory {
    dedicated = 512
    swap      = 0
  }

  disk {
    datastore_id = var.pilot.datastore_id
    size         = 4
    replicate    = false
  }

  operating_system {
    template_file_id = var.pilot.template_file_id
    type             = "debian"
  }

  initialization {
    hostname = "terraform-pilot"

    dns {
      servers = var.pilot.dns_servers
    }

    ip_config {
      ipv4 {
        address = var.pilot.ipv4_address
        gateway = var.pilot.gateway
      }
    }

    user_account {
      keys = [var.pilot.ssh_public_key]
    }
  }

  network_interface {
    name    = "eth0"
    bridge  = var.pilot.bridge
    vlan_id = var.pilot.vlan_id
  }

  lifecycle {
    prevent_destroy = true
    # The existing iptag service adds address tags after guest creation.
    ignore_changes = [tags]
  }
}

output "pilot" {
  description = "Identity of the Terraform-owned pilot, if enabled."
  value = try({
    vm_id     = proxmox_virtual_environment_container.pilot[0].vm_id
    node_name = proxmox_virtual_environment_container.pilot[0].node_name
  }, null)
}
