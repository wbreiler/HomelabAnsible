mock_provider "proxmox" {}

run "no_media_by_default" {
  command = plan

  variables {
    iso_library          = null
    pilot                = null
    pbs_storage_password = "mock-pbs-password"
  }

  assert {
    condition     = length(proxmox_download_file.iso) == 0
    error_message = "An unconfigured library must not create media."
  }
}

run "pinned_media_on_each_node" {
  command = plan

  variables {
    pilot                = null
    pbs_storage_password = "mock-pbs-password"
    iso_library = {
      base_url = "http://iso.example/"
      nodes    = ["first", "second"]
      files = {
        "installer-1.iso" = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
      }
    }
  }

  assert {
    condition = (
      length(proxmox_download_file.iso) == 2 &&
      alltrue([for key, media in proxmox_download_file.iso :
        !media.overwrite &&
        !media.overwrite_unmanaged &&
        media.content_type == "iso" &&
        media.datastore_id == "local" &&
        key == "${media.node_name}/installer-1.iso" &&
        media.url == "http://iso.example/installer-1.iso" &&
        media.checksum_algorithm == "sha256" &&
        media.checksum == var.iso_library.files["installer-1.iso"]
      ])
    )
    error_message = "Each node must receive the checksum-pinned ISO without overwriting existing media."
  }
}

run "reject_unpinned_media" {
  command = plan

  variables {
    pilot                = null
    pbs_storage_password = "mock-pbs-password"
    iso_library = {
      base_url = "http://iso.example"
      nodes    = ["first"]
      files    = { "installer-1.iso" = "" }
    }
  }

  expect_failures = [var.iso_library]
}

run "reject_path_traversal" {
  command = plan

  variables {
    pilot                = null
    pbs_storage_password = "mock-pbs-password"
    iso_library = {
      base_url = "http://iso.example"
      nodes    = ["first"]
      files    = { "../installer.iso" = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef" }
    }
  }

  expect_failures = [var.iso_library]
}
