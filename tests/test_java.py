import hashlib
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest import mock

from minecraft_manager import provision
from minecraft_manager.provision import extract_tar, java_arch, java_install


def tarball(entries):
    """A .tar.gz from (name, content or None for a dir, or ("link", target))."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, content in entries:
            info = tarfile.TarInfo(name)
            if content is None:
                info.type, info.mode = tarfile.DIRTYPE, 0o755
                archive.addfile(info)
            elif isinstance(content, tuple):
                info.type, info.linkname = tarfile.SYMTYPE, content[1]
                archive.addfile(info)
            else:
                info.size, info.mode = len(content), 0o755
                archive.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


JRE = tarball([("jdk-25.0.5+8-jre/", None), ("jdk-25.0.5+8-jre/bin/", None),
               ("jdk-25.0.5+8-jre/bin/java", b"#!/bin/sh\n"),
               ("jdk-25.0.5+8-jre/lib/link", ("link", "../bin/java"))])


def assets(data, release="jdk-25.0.5+8"):
    return [{"release_name": release, "binary": {"package": {
        "name": "jre.tar.gz", "link": "https://example.invalid/jre.tar.gz", "size": len(data),
        "checksum": hashlib.sha256(data).hexdigest()}}}]


class JavaArchTest(unittest.TestCase):
    def test_maps_64_bit_machines(self):
        self.assertEqual(java_arch("aarch64", 64), "aarch64")
        self.assertEqual(java_arch("x86_64", 64), "x64")

    def test_32_bit_userland_on_a_64_bit_kernel_has_no_build(self):
        self.assertIsNone(java_arch("aarch64", 32))
        self.assertIsNone(java_arch("armv7l", 32))


class ExtractTest(unittest.TestCase):
    def test_refuses_paths_outside_the_target(self):
        for entries in ([("../evil", b"x")], [("/etc/evil", b"x")], [("a", ("link", "/etc/passwd"))]):
            with tempfile.TemporaryDirectory() as tmp, self.assertRaises(SystemExit):
                extract_tar(tarball(entries), tmp)


@mock.patch.object(provision, "java_arch", return_value="aarch64")
class JavaInstallTest(unittest.TestCase):
    def test_downloads_once_and_removes_older_releases_not_in_use(self, _arch):
        with tempfile.TemporaryDirectory() as tmp:
            for old in ("jdk-25.0.1+1-jre", "jdk-25.0.2+1-jre"):
                (Path(tmp) / old / "bin").mkdir(parents=True)
            in_use = [(Path(tmp) / "jdk-25.0.2+1-jre/bin/java").resolve()]
            download = mock.Mock(return_value=JRE)
            with mock.patch("sys.stdout", new_callable=io.StringIO) as out, mock.patch("sys.stderr"), \
                    mock.patch.object(provision, "running_executables", return_value=in_use):
                java_install("25", tmp, lookup=lambda url: assets(JRE), download=download)
                java_install("25", tmp, lookup=lambda url: assets(JRE), download=download)
            java = Path(tmp) / "jdk-25.0.5+8-jre/bin/java"
            self.assertEqual(out.getvalue().split(), [str(java)] * 2)
            self.assertTrue(java.is_file())
            download.assert_called_once()
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()),
                             ["jdk-25.0.2+1-jre", "jdk-25.0.5+8-jre"])

    def test_rejects_a_corrupt_download(self, _arch):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(SystemExit), mock.patch("sys.stderr"):
            java_install("25", tmp, lookup=lambda url: assets(JRE), download=lambda *a, **k: JRE + b"x")


if __name__ == "__main__":
    unittest.main()
