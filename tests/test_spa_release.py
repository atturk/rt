"""RT4-F8: 'rt -u' e install.sh installano la web app compilata dalla GitHub Release."""
import hashlib
import io
import tarfile
import urllib.error

import pytest

from rt.core import spa_release
from rt.core.version import _is_update_excluded


def _tarball(files):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, content in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    return buf.getvalue()


class FakeRelease:
    """Opener finto: serve gli allegati di una release come urllib.request.urlopen."""

    def __init__(self, version, files=None, sha=None, missing=False):
        self.version = version
        self.archive = _tarball(files or {"index.html": b"<html>v" + version.encode() + b"</html>",
                                          "assets/app.js": b"console.log(1)"})
        self.sha = sha or hashlib.sha256(self.archive).hexdigest()
        self.missing = missing
        self.urls = []

    def __call__(self, req, timeout=None):
        url = req.full_url
        self.urls.append(url)
        if self.missing:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        if url.endswith("/SHA256SUMS"):
            body = f"{self.sha}  rt-spa-{self.version}.tar.gz\nabc  rt-{self.version}.tar.gz\n".encode()
        else:
            assert url.endswith(f"/v{self.version}/rt-spa-{self.version}.tar.gz")
            body = self.archive
        return io.BytesIO(body)


def test_install_spa_puts_the_build_in_rt_spa_once(tmp_path):
    release = FakeRelease("4.1.0")
    assert spa_release.install_spa(str(tmp_path), "4.1.0", release) is True
    spa = tmp_path / "rt" / "spa"
    assert (spa / "index.html").read_bytes() == b"<html>v4.1.0</html>"
    assert (spa / "assets" / "app.js").is_file()
    assert spa_release.installed_version(str(tmp_path)) == "4.1.0"
    calls = len(release.urls)
    assert spa_release.install_spa(str(tmp_path), "4.1.0", release) is False
    assert len(release.urls) == calls

    assert spa_release.install_spa(str(tmp_path), "4.2.0", FakeRelease("4.2.0")) is True
    assert (spa / "index.html").read_bytes() == b"<html>v4.2.0</html>"
    assert not [p for p in (tmp_path / "rt").iterdir() if p.name.startswith(".spa-")]


def test_wrong_sha_leaves_the_installed_spa_untouched(tmp_path):
    spa_release.install_spa(str(tmp_path), "4.1.0", FakeRelease("4.1.0"))
    with pytest.raises(ValueError, match="sha256"):
        spa_release.install_spa(str(tmp_path), "4.2.0", FakeRelease("4.2.0", sha="0" * 64))
    assert (tmp_path / "rt" / "spa" / "index.html").read_bytes() == b"<html>v4.1.0</html>"
    assert not spa_release.update_spa(str(tmp_path), "4.2.0", FakeRelease("4.2.0", sha="0" * 64))


def test_unsafe_or_incomplete_packages_are_rejected(tmp_path):
    with pytest.raises(ValueError, match="percorso"):
        spa_release.install_spa(str(tmp_path), "4.1.0", FakeRelease("4.1.0", files={"../x": b"x"}))
    with pytest.raises(ValueError, match="index.html"):
        spa_release.install_spa(str(tmp_path), "4.1.0", FakeRelease("4.1.0", files={"a.js": b"x"}))
    assert not (tmp_path / "rt" / "spa").exists()


def test_release_without_spa_is_only_a_warning(tmp_path, capsys):
    assert spa_release.update_spa(str(tmp_path), "3.9.0", FakeRelease("3.9.0", missing=True))
    assert "non contiene la web app" in capsys.readouterr().err


def test_update_keeps_rt_spa_out_of_the_code_sync():
    assert _is_update_excluded("rt/spa/index.html")
    assert _is_update_excluded("rt/spa")
    assert not _is_update_excluded("rt/api/spa.py")
