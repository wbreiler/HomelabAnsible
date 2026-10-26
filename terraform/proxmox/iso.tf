variable "iso_library" {
  description = "Versioned ISO filenames and trusted SHA256 hashes, cached on each selected node."
  type = object({
    base_url     = string
    nodes        = set(string)
    datastore_id = optional(string, "local")
    files        = map(string)
  })
  default = null

  validation {
    condition = var.iso_library == null ? true : (
      can(regex("^https?://[^[:space:]]+$", var.iso_library.base_url)) &&
      length(var.iso_library.nodes) > 0 &&
      alltrue([for name, checksum in var.iso_library.files :
        can(regex("^[A-Za-z0-9][A-Za-z0-9_.-]*\\.iso$", name)) &&
        can(regex("^[a-f0-9]{64}$", checksum))
      ])
    )
    error_message = "Use an HTTP(S) base URL, at least one node, plain ISO filenames, and lowercase SHA256 hashes."
  }
}

locals {
  iso_targets = var.iso_library == null ? {} : {
    for pair in setproduct(var.iso_library.nodes, keys(var.iso_library.files)) :
    "${pair[0]}/${pair[1]}" => {
      node_name = pair[0]
      file_name = pair[1]
      checksum  = var.iso_library.files[pair[1]]
    }
  }
}

resource "proxmox_download_file" "iso" {
  for_each = local.iso_targets

  content_type        = "iso"
  datastore_id        = var.iso_library.datastore_id
  node_name           = each.value.node_name
  file_name           = each.value.file_name
  url                 = "${trimsuffix(var.iso_library.base_url, "/")}/${each.value.file_name}"
  checksum            = each.value.checksum
  checksum_algorithm  = "sha256"
  overwrite           = false
  overwrite_unmanaged = false
  upload_timeout      = 1800

  lifecycle {
    prevent_destroy = true
    # Sources pin creation. A new version must use a new filename, including after import.
    ignore_changes = [url, checksum, checksum_algorithm]
  }
}
