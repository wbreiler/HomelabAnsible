import copy
import gzip
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import uuid

MODULE = Path(__file__).resolve().parents[1]
loader = importlib.util.spec_from_file_location("iso_install", MODULE / "scripts/iso_install.py")
install = importlib.util.module_from_spec(loader)
loader.loader.exec_module(install)


def example(family="debian"):
    return {"os": family, "name": "install-test", "username": "ansible", "uuid": str(uuid.uuid4()),
            "ipv4_address": "192.0.2.4/25", "gateway": "192.0.2.1", "dns_servers": ["192.0.2.1"],
            "iso_filename": "test.iso", "source_url": "http://iso.example/test.iso", "source_sha256": "a" * 64,
            "public_key": (MODULE / "tests/install.pub").read_text().strip(), "ssh_public_key_file": str(MODULE / "tests/install.pub")}


class InstallerTests(unittest.TestCase):
    def wait_spec(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return dict(example(), output_iso=str(Path(directory.name) / "autoinstall.iso"))

    def test_input_boundaries(self):
        source = example()
        for key, value in [("name", "bad;command"), ("username", "root"), ("iso_filename", "../test.iso"),
                           ("uuid", "../outside"), ("firmware", "legacy"), ("secure_boot", True), ("secure_boot", "true"), ("ipv4_address", "192.0.2.1/25"),
                           ("gateway", "198.51.100.1"), ("source_sha256", ""),
                           ("public_key", "PRIVATE KEY\nsecret"), ("source_url", "http://user:password@iso.example/test.iso")]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                install.validate(dict(source, **{key: value}))

    def test_cpio_file_permissions_and_contents(self):
        content = b"private answers\n"
        archive = install.newc("preseed.cfg", content)
        self.assertEqual(archive[:6], b"070701")
        fields = [int(archive[6 + i * 8:14 + i * 8], 16) for i in range(13)]
        self.assertEqual(fields[1], 0o100600)
        self.assertEqual(fields[2:4], [0, 0])
        self.assertEqual(archive[110:122], b"preseed.cfg\0")
        start = (110 + fields[11] + 3) & ~3
        self.assertEqual(archive[start:start + fields[6]], content)
        self.assertIn(b"TRAILER!!!\0", archive)

    def test_fedora_efi_patch_preserves_sizes_and_rejects_unknown_layouts(self):
        original = b"manual boot menu\n"
        image = b"FAT metadata\0" + original + b"\0another cluster\0" + original
        result = install.patch_fedora_efi(image, original, b"automatic\n")
        self.assertEqual(len(image), len(result))
        self.assertNotIn(original, result)
        self.assertEqual(result.count(b"automatic\n"), 2)
        for data, replacement in [(b"unknown layout", b"automatic"), (image, original * 2)]:
            with self.assertRaisesRegex(ValueError, "Unsupported Fedora EFI"):
                install.patch_fedora_efi(data, original, replacement)

    def test_profiles_have_uuid_disk_and_account_guards(self):
        for family in ["debian", "ubuntu", "fedora"]:
            with self.subTest(family=family):
                spec = example(family)
                files = install.payloads(spec)
                seed = files[{"debian": "preseed.cfg", "ubuntu": "/autoinstall.yaml", "fedora": "/ks.cfg"}[family]].decode()
                self.assertIn(spec["uuid"], seed)
                self.assertIn("/sys/class/dmi/id/product_uuid", seed)
                self.assertIn("/dev/sda" if family != "fedora" else "--only-use=sda", seed)
                self.assertNotRegex(seed, r"@[A-Z_]+@")
                script = files["/terraform/bootstrap.sh"].decode()
                self.assertIn("PasswordAuthentication no", script)
                self.assertIn("passwd -l root", script)
                self.assertIn("passwd -l ansible", script)
                self.assertLess(script.index("visudo -cf"), script.index("/var/lib/terraform-iso-install/complete"))
                subprocess.run(["sh", "-n"], input=script, text=True, check=True)
                if family == "ubuntu":
                    data = json.loads(seed)["autoinstall"]
                    self.assertFalse(data["ssh"]["allow-pw"])
                    self.assertEqual(data["network"]["ethernets"]["install"]["addresses"], ["192.0.2.4/25"])
                if family == "debian":
                    self.assertIn("255.255.255.128", seed)

    def test_ssh_comments_cannot_become_shell_commands(self):
        spec = example()
        spec["public_key"] += " ; touch /tmp/should-not-execute"
        install.validate(spec)
        self.assertNotIn("touch /tmp/should-not-execute", install.bootstrap(spec))

    def test_bad_download_is_not_cached(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(install.urllib.request, "urlopen", return_value=io.BytesIO(b"wrong image")):
                with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
                    install.source_iso(example(), Path(directory))
            self.assertFalse(list(Path(directory).rglob("*.iso")))

    def test_waiter_refuses_another_machine(self):
        spec = self.wait_spec()
        response = subprocess.CompletedProcess([], 0, json.dumps({"uuid": str(uuid.uuid4())}), "")
        with patch.object(install.subprocess, "run", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "another machine"):
                install.wait(spec, timeout=1)

    def test_failed_health_checks_never_report_ready(self):
        spec = self.wait_spec()
        data = {"uuid": spec["uuid"], "marker": spec["uuid"], "os": "debian", "root": "/dev/sda1",
                "agent": "active", "firmware": "bios", "failed_units": "bad.service failed", "password_auth_disabled": True,
                "root_ssh_disabled": True, "user_locked": True, "root_locked": True}
        response = subprocess.CompletedProcess([], 0, json.dumps(data), "")
        with patch.object(install.subprocess, "run", return_value=response), patch.object(install.time, "sleep"), patch.object(install.time, "monotonic", side_effect=[0, 0, 2]):
            with self.assertRaises(TimeoutError):
                install.wait(spec, timeout=1)

    def test_transient_ssh_timeout_is_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            spec = example(); spec["output_iso"] = str(Path(directory) / "autoinstall.iso")
            data = {"uuid": spec["uuid"], "marker": spec["uuid"], "os": "debian", "version": "13",
                    "root": "/dev/sda1", "agent": "active", "firmware": "bios", "failed_units": "", "password_auth_disabled": True,
                    "root_ssh_disabled": True, "user_locked": True, "root_locked": True}
            response = subprocess.CompletedProcess([], 0, json.dumps(data), "")
            calls = []
            def ssh(args, **kwargs):
                calls.append(args)
                if len(calls) == 1:
                    raise subprocess.TimeoutExpired("ssh", 30)
                p = next(a.split("=", 1)[1] for a in args if a.startswith("UserKnownHostsFile="))
                Path(p).write_text("installed-host-key\n")
                return response
            with patch.object(install.subprocess, "run", side_effect=ssh), patch.object(install.time, "sleep"):
                install.wait(spec, timeout=10)
            result = Path(directory) / "verified.json"
            self.assertEqual(json.loads(result.read_text())["uuid"], spec["uuid"])
            self.assertEqual(result.stat().st_mode & 0o777, 0o600)

    def test_live_installer_key_is_not_pinned(self):
        spec = self.wait_spec(); directory = Path(spec["output_iso"]).parent
        data = {"uuid": spec["uuid"], "marker": spec["uuid"], "os": "debian", "version": "13",
                "root": "/dev/sda1", "agent": "active", "firmware": "bios", "failed_units": "", "password_auth_disabled": True,
                "root_ssh_disabled": True, "user_locked": True, "root_locked": True}
        calls = []
        def ssh(args, **kwargs):
            p = Path(next(a.split("=", 1)[1] for a in args if a.startswith("UserKnownHostsFile=")))
            calls.append(p)
            p.write_text("live-key\n" if len(calls) == 1 else "installed-key\n")
            return subprocess.CompletedProcess([], 255 if len(calls) == 1 else 0, json.dumps(data), "")
        with patch.object(install.subprocess, "run", side_effect=ssh), patch.object(install.time, "sleep"):
            install.wait(spec, timeout=10)
        self.assertNotEqual(calls[0], calls[1])
        self.assertEqual((directory / "known_hosts").read_text(), "installed-key\n")
        self.assertFalse(list(directory.glob("host-key-probe-*")))

    def test_established_host_key_is_never_discarded(self):
        spec = self.wait_spec(); directory = Path(spec["output_iso"]).parent
        (directory / "verified.json").write_text(json.dumps({"uuid": spec["uuid"]}))
        (directory / "known_hosts").write_text("pinned-key\n")
        response = subprocess.CompletedProcess([], 255, "", "Host key verification failed")
        with patch.object(install.subprocess, "run", return_value=response), patch.object(install.time, "sleep"), patch.object(install.time, "monotonic", side_effect=[0, 0, 2]):
            with self.assertRaises(TimeoutError):
                install.wait(spec, timeout=1)
        self.assertEqual((directory / "known_hosts").read_text(), "pinned-key\n")

    def test_uefi_requires_esp_loader_and_boot_entries(self):
        spec = dict(self.wait_spec(), firmware="uefi")
        data = {"uuid": spec["uuid"], "marker": spec["uuid"], "os": "debian", "version": "13",
                "root": "/dev/sda2", "agent": "active", "failed_units": "", "firmware": "uefi",
                "efi_platform_bits": "64", "esp": {"source": "/dev/sda1", "fstype": "vfat", "target": "/boot/efi"},
                "efi_loaders": ["EFI/debian/grubx64.efi"], "efi_boot_entries": 2, "secure_boot": False,
                "password_auth_disabled": True, "root_ssh_disabled": True, "user_locked": True, "root_locked": True}
        for changes in [{"firmware": "bios"}, {"efi_platform_bits": "32"}, {"esp": None},
                        {"esp": {"source": "/dev/sda1", "fstype": "ext4", "target": "/boot/efi"}},
                        {"efi_loaders": []}, {"efi_boot_entries": 0}, {"secure_boot": True}]:
            with self.subTest(changes=changes):
                response = subprocess.CompletedProcess([], 0, json.dumps(data | changes), "")
                with patch.object(install.subprocess, "run", return_value=response), patch.object(install.time, "sleep"), patch.object(install.time, "monotonic", side_effect=[0, 0, 2]):
                    with self.assertRaises(TimeoutError):
                        install.wait(spec, timeout=1)
                self.assertFalse(Path(spec["output_iso"]).with_name("verified.json").exists())
        def ssh(args, **kwargs):
            p = next(a.split("=", 1)[1] for a in args if a.startswith("UserKnownHostsFile="))
            Path(p).write_text("verified-uefi-host-key\n")
            return subprocess.CompletedProcess([], 0, json.dumps(data), "")
        with patch.object(install.subprocess, "run", side_effect=ssh):
            install.wait(spec, timeout=1)
        self.assertEqual(json.loads(Path(spec["output_iso"]).with_name("verified.json").read_text())["firmware"], "uefi")

    def test_secure_boot_requires_enrollment_lockdown_and_shim_validation(self):
        spec = dict(self.wait_spec(), firmware="uefi", secure_boot=True)
        data = {"uuid": spec["uuid"], "marker": spec["uuid"], "os": "debian", "version": "13",
                "root": "/dev/sda2", "agent": "active", "failed_units": "", "firmware": "uefi",
                "efi_platform_bits": "64", "esp": {"source": "/dev/sda1", "fstype": "vfat", "target": "/boot/efi"},
                "efi_loaders": ["EFI/debian/grubx64.efi"], "efi_boot_entries": 2, "secure_boot": True,
                "setup_mode": False, "enrolled_keys": {"PK": True, "KEK": True, "db": True},
                "kernel_lockdown": "none [integrity] confidentiality", "shim_validation_disabled": False,
                "password_auth_disabled": True, "root_ssh_disabled": True, "user_locked": True, "root_locked": True}
        invalid = [{"secure_boot": False}, {"setup_mode": True}, {"setup_mode": None},
                   {"kernel_lockdown": "[none] integrity confidentiality"}, {"kernel_lockdown": None},
                   {"shim_validation_disabled": True}]
        invalid += [{"enrolled_keys": data["enrolled_keys"] | {key: False}} for key in ["PK", "KEK", "db"]]
        for changes in invalid:
            with self.subTest(changes=changes):
                response = subprocess.CompletedProcess([], 0, json.dumps(data | changes), "")
                with patch.object(install.subprocess, "run", return_value=response), patch.object(install.time, "sleep"), patch.object(install.time, "monotonic", side_effect=[0, 0, 2]):
                    with self.assertRaises(TimeoutError):
                        install.wait(spec, timeout=1)
                self.assertFalse(Path(spec["output_iso"]).with_name("verified.json").exists())
        def ssh(args, **kwargs):
            p = next(a.split("=", 1)[1] for a in args if a.startswith("UserKnownHostsFile="))
            Path(p).write_text("verified-secure-boot-host-key\n")
            return subprocess.CompletedProcess([], 0, json.dumps(data), "")
        with patch.object(install.subprocess, "run", side_effect=ssh):
            install.wait(spec, timeout=1)
        self.assertTrue(json.loads(Path(spec["output_iso"]).with_name("verified.json").read_text())["secure_boot"])

    @unittest.skipUnless(shutil.which("xorriso"), "xorriso is required for boot-image tests")
    def test_derived_boot_media_preserves_source_and_rejects_overwrite(self):
        for family in ["debian", "ubuntu", "fedora"]:
            with self.subTest(family=family), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                tree = root / "tree"
                contents = {"isolinux/isolinux.bin": b"\0" * 2048,
                            "isolinux/isolinux.cfg": b"default manual\ntimeout 300\n",
                            "boot/grub/grub.cfg": b"set timeout=300\n",
                            "EFI/BOOT/grub.cfg": b"set timeout=300\n",
                            "boot/efi.img": b"\0" * 1048576,
                            "md5sum.txt": b"0" * 32 + b"  ./isolinux/isolinux.cfg\n"}
                paths = {"debian": ("install.amd/vmlinuz", "install.amd/initrd.gz"),
                         "ubuntu": ("casper/vmlinuz", "casper/initrd"),
                         "fedora": ("images/pxeboot/vmlinuz", "images/pxeboot/initrd.img")}[family]
                contents[paths[0]] = b"kernel fixture"
                contents[paths[1]] = gzip.compress(b"initramfs fixture", mtime=0)
                if family == "fedora":
                    contents[".treeinfo"] = b"[general]\nfamily=Fedora\n"
                    old = b"set default=1\n#" + b"manual config padding " * 80 + b"\n"
                    contents["EFI/BOOT/grub.cfg"] = old
                    contents["images/efiboot.img"] = (b"\0" * 512 + old + b"\0" * 512 + old).ljust(1048576, b"\0")
                for name, content in contents.items():
                    p = tree / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(content)
                source = root / "source.iso"
                efi_args = ["-eltorito-alt-boot", "-e", "boot/efi.img", "-no-emul-boot"]
                if family == "fedora":
                    efi_args = ["-append_partition", "2", "0xef", str(tree / "images/efiboot.img"), "-appended_part_as_gpt",
                                "-eltorito-alt-boot", "-e", "--interval:appended_partition_2:all::", "-no-emul-boot"]
                install.run(["xorriso", "-as", "mkisofs", "-r", "-V", "INSTALL_TEST", "-b", "isolinux/isolinux.bin", "-c", "isolinux/boot.cat",
                             "-no-emul-boot", "-boot-load-size", "4", "-boot-info-table"] + efi_args + ["-o", str(source), str(tree)])
                spec = example(family); spec["source_sha256"] = install.digest(source)
                original = source.read_bytes()
                out = root / "cache" / spec["uuid"] / "autoinstall.iso"
                spec["output_iso"] = str(out)
                cache = out.parent.parent / "sources"; cache.mkdir(parents=True)
                shutil.copyfile(source, cache / (spec["source_sha256"] + ".iso"))
                install.build(spec)
                install.build(spec)
                install.build(dict(spec, cores=4, backup=True, on_boot=True))
                extracted = root / "boot.cfg"
                install.run(["xorriso", "-osirrox", "on", "-indev", str(out), "-extract", "/isolinux/isolinux.cfg", str(extracted)])
                boot = extracted.read_text()
                self.assertIn("default automatic", boot)
                self.assertIn({"debian": "auto=true", "ubuntu": "autoinstall", "fedora": "inst.ks=cdrom:/ks.cfg"}[family], boot)
                for path in ["/boot/grub/grub.cfg", "/EFI/BOOT/grub.cfg"]:
                    install.run(["xorriso", "-osirrox", "on", "-indev", str(out), "-extract", path, str(extracted)])
                    self.assertIn("set default=0", extracted.read_text())
                    self.assertIn("set timeout=1", extracted.read_text())
                    self.assertIn("Automatic " + family + " installation", extracted.read_text())
                catalog = install.run(["xorriso", "-indev", str(out), "-report_el_torito", "plain"])
                self.assertIn("UEFI", catalog)
                if family == "fedora":
                    boot_images = root / "boot-images"
                    install.run(["xorriso", "-indev", str(out), "-osirrox", "on", "-extract_boot_images", str(boot_images)])
                    actual = (boot_images / "eltorito_img2_uefi.img").read_bytes()
                    self.assertEqual(actual, (boot_images / "gpt_part2_efi.img").read_bytes())
                    self.assertNotIn(old, actual)
                    self.assertEqual(actual.count(b"inst.ks=cdrom:/ks.cfg"), 2)
                self.assertEqual(source.read_bytes(), original)
                if family == "debian":
                    initrd = root / "initrd.gz"
                    install.run(["xorriso", "-osirrox", "on", "-indev", str(out), "-extract", "/install.amd/initrd.gz", str(initrd)])
                    self.assertIn(b"preseed.cfg\0", gzip.decompress(initrd.read_bytes()))
                changed = copy.deepcopy(spec); changed["name"] = "another-name"
                with self.assertRaisesRegex(ValueError, "new VM UUID"):
                    install.build(changed)


if __name__ == "__main__":
    unittest.main()
