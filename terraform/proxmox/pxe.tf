variable "pxe_server" {
  description = "Existing PXE service configured by proxmox/pxe-guests.yml. Terraform owns its ISO library and per-VM installers."
  type = object({
    host                = string
    container_id        = optional(number)
    http_url            = string
    ssh_public_key_file = string
  })
  default = null
}

resource "terraform_data" "pxe_library" {
  count = var.pxe_server == null || var.iso_library == null ? 0 : 1
  input = {
    pxe_server = var.pxe_server
    base_url   = var.iso_library.base_url
    files      = var.iso_library.files
  }
  triggers_replace = [var.pxe_server, try(var.iso_library.files, {})]
  # Updating this resource only adds/verifies files. It never removes existing media.
  provisioner "local-exec" {
    interpreter = ["python3", "${path.module}/scripts/pxe_install.py"]
    command     = "sync-library"
    environment = { ISO_INSTALL_SPEC = jsonencode(self.input) }
  }
}

resource "terraform_data" "pxe_media" {
  for_each = { for name, spec in local.install_specs : name => spec if spec.boot_method == "pxe" }
  input = merge(each.value, {
    pxe_server = var.pxe_server
    source_url = "${try(trimsuffix(var.pxe_server.http_url, "/"), "")}/iso/${each.value.iso_filename}"
  })
  triggers_replace = [each.value, var.pxe_server]
  depends_on       = [terraform_data.pxe_library]
  provisioner "local-exec" {
    interpreter = ["python3", "${path.module}/scripts/pxe_install.py"]
    command     = "build"
    environment = { ISO_INSTALL_SPEC = jsonencode(self.input) }
  }
}
