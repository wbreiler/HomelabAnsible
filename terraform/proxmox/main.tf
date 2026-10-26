terraform {
  required_version = ">= 1.6.0, < 2.0.0"

  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = "0.118.0"
    }
  }
}

# Endpoint and token come from PROXMOX_VE_* environment variables.
provider "proxmox" {
  insecure = false
}

data "proxmox_virtual_environment_nodes" "cluster" {}

output "node_names" {
  description = "Names visible to the Proxmox API identity. No guests are managed yet."
  value       = data.proxmox_virtual_environment_nodes.cluster.names
}
