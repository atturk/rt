"""
tests/test_app_update.py
L'app installata (RT.app, setup per Windows) si aggiorna solo alle release stabili, con il
nuovo installer verificato da SHA256SUMS; install.sh, git e Docker restano su 'rt -u'.
"""
import hashlib
import io
import os

import pytest

from rt.core import app_update, bundle

DMG = "RT-4.3.0-macos-arm64.dmg"
EXE = "RT-4.3.0-windows-x64-setup.exe"


def release(tag="v4.3.0", prerelease=False, names=(DMG, EXE, "SHA256SUMS")):
    return {"tag_name": tag, "prerelease": prerelease, "draft": False,
            "html_url": f"https://github.com/atturk/rt/releases/tag/{tag}",
            "assets": [{"name": n, "size": 10, "browser_download_url": f"https://example.invalid/{n}"} for n in names]}


def test_newer_stable_with_installer_is_available():
    info = app_update.evaluate(release(), bundle.WINDOWS, "4.2.5")
    assert info.available and info.latest == "4.3.0" and info.asset_name == EXE
    assert app_update.evaluate(release(), bundle.MACOS, "4.2.5").asset_name == DMG


@pytest.mark.parametrize("rel, kind, current", [
    (release(), bundle.WINDOWS, "4.3.0"),                        # già aggiornato
    (release(), bundle.WINDOWS, "4.3.1b1"),                      # beta installata a mano, più recente
    (release(prerelease=True, tag="v4.4.0b1"), bundle.WINDOWS, "4.2.5"),  # le beta non arrivano mai
    (release(names=(DMG, "SHA256SUMS")), bundle.WINDOWS, "4.2.5"),         # installer non ancora allegato
    (release(names=(EXE,)), bundle.WINDOWS, "4.2.5"),                      # manca SHA256SUMS
    (release(), None, "4.2.5"),                                  # install.sh o git: 'rt -u'
])
def test_not_available(rel, kind, current):
    info = app_update.evaluate(rel, kind, current)
    assert not info.available
    assert info.supported is (kind is not None)


class _Resp(io.BytesIO):
    headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _opener(files):
    def opener(request, timeout=None):
        return _Resp(files[request.full_url.rsplit("/", 1)[-1]])
    return opener


def _info():
    return app_update.evaluate(release(), bundle.WINDOWS, "4.2.5")


def test_download_verifies_sha256(tmp_path, monkeypatch):
    monkeypatch.setenv("RT_DATA_DIR", str(tmp_path))
    payload = b"setup" * 1000
    sums = f"{hashlib.sha256(payload).hexdigest()}  {EXE}\n".encode()
    seen = []
    path = app_update.download(_info(), lambda done, total: seen.append(done),
                               opener=_opener({EXE: payload, "SHA256SUMS": sums}))
    assert open(path, "rb").read() == payload and seen[-1] == len(payload)

    bad = f"{'0' * 64}  {EXE}\n".encode()
    os.remove(path)
    with pytest.raises(app_update.AppUpdateError, match="SHA256SUMS"):
        app_update.download(_info(), opener=_opener({EXE: payload, "SHA256SUMS": bad}))
    assert not os.path.exists(path) and not os.path.exists(path + ".part")


def test_bundle_marker_and_app_path(tmp_path):
    root = tmp_path / "RT.app" / "Contents" / "Resources" / "app"
    root.mkdir(parents=True)
    assert bundle.kind(str(root)) is None
    (root / "BUNDLE").write_text("macos\n")
    assert bundle.kind(str(root)) == bundle.MACOS
    assert bundle.app_path(str(root)) == str(tmp_path / "RT.app")
    assert bundle.app_path(str(tmp_path)) is None


def test_rt_u_in_the_app_uses_the_installer(tmp_path, monkeypatch, capsys):
    from rt.core import version
    (tmp_path / "BUNDLE").write_text("windows")
    (tmp_path / "VERSION").write_text("4.2.5")
    monkeypatch.setattr(app_update, "_get_json", lambda url, timeout: release(tag="v4.2.5"))
    assert version.run_update(str(tmp_path)) == 0
    assert "già aggiornato" in capsys.readouterr().out
    assert version.run_update(str(tmp_path), version.BETA) == 0
    assert "releases" in capsys.readouterr().out


def test_api_reports_update_state(api_client):
    data = api_client.get("/api/v1/system/update").json()
    assert data["supported"] is False and data["available"] is False
    assert data["progress"]["phase"] == "idle"
    assert data["releases_url"].endswith("/releases")
    res = api_client.post("/api/v1/system/update")
    assert res.status_code == 409 and res.json()["error"]["code"] == "update_unsupported"


def test_desktop_setup_runs_once_per_version(tmp_path, monkeypatch):
    from rt import desktop
    monkeypatch.setenv("RT_DATA_DIR", str(tmp_path))
    assert desktop.needs_setup("4.2.5")
    (tmp_path / "rt-data.json").write_text("{}")
    (tmp_path / desktop.STAMP_FILE).write_text("4.2.5\n")
    assert not desktop.needs_setup("4.2.5")
    assert desktop.needs_setup("4.3.0")
