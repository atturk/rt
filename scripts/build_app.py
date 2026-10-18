#!/usr/bin/env python3
"""
scripts/build_app.py
Costruisce l'app installabile di RT con dentro tutto quello che serve (niente Homebrew,
Python o Node sul computer dell'utente):

    macOS    dist/RT-<versione>-macos-arm64.dmg        (RT.app da trascinare in Applicazioni)
    Windows  dist/RT-<versione>-windows-x64-setup.exe  (installazione per l'utente, senza admin)

Contenuto: un Python autonomo (python-build-standalone), le dipendenze di requirements.txt,
il codice di RT, la web app già compilata (frontend/dist, da costruire prima con
'npm run build') e il file BUNDLE che segnala l'app (vedi rt/core/bundle.py).

Gira sul sistema di destinazione (macOS per il .dmg, Windows per il setup): le dipendenze
binarie vanno installate per quella piattaforma. Su Windows serve Inno Setup (iscc), che i
runner di GitHub hanno già.

    python scripts/build_app.py [--out dist] [--python 3.12]
"""
import argparse
import hashlib
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PBS_API = "https://api.github.com/repos/astral-sh/python-build-standalone/releases/{release}"
TRIPLES = {"macos": "aarch64-apple-darwin", "windows": "x86_64-pc-windows-msvc"}
ASSET_NAMES = {"macos": "RT-{version}-macos-arm64.dmg", "windows": "RT-{version}-windows-x64-setup.exe"}
CODE = ("rt", "bin", "config.example", "VERSION", "CHANGELOG.md", "requirements.txt", "constraints.txt")
BUNDLE_ID = "com.atturk.rt"


def say(message: str) -> None:
    print(message, flush=True)


def _request(url: str, accept: str = "application/octet-stream"):
    headers = {"User-Agent": "rt-build-app", "Accept": accept}
    token = os.environ.get("GITHUB_TOKEN")
    if token and "api.github.com" in url:
        headers["Authorization"] = f"Bearer {token}"
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=120)


def find_python(target: str, minor: str, release: str) -> dict:
    """L'archivio install_only di python-build-standalone per il sistema e la versione."""
    with _request(PBS_API.format(release="latest" if release == "latest" else f"tags/{release}"),
                  "application/vnd.github+json") as resp:
        data = json.load(resp)
    pattern = re.compile(rf"^cpython-{re.escape(minor)}\.(\d+)\+\d+-{TRIPLES[target]}-install_only\.tar\.gz$")
    matches = [(int(m.group(1)), a) for a in data["assets"] if (m := pattern.match(a["name"]))]
    if not matches:
        raise SystemExit(f"Nessun Python {minor} per {TRIPLES[target]} nella release {data.get('tag_name')}.")
    asset = max(matches, key=lambda item: item[0])[1]
    sums = next((a for a in data["assets"] if a["name"] == "SHA256SUMS"), None)
    return {"asset": asset, "sums": sums, "release": data.get("tag_name")}


def download_python(found: dict, cache: str) -> str:
    asset = found["asset"]
    os.makedirs(cache, exist_ok=True)
    path = os.path.join(cache, asset["name"])
    if not os.path.isfile(path):
        say(f"⬇️  {asset['name']} ({found['release']})")
        with _request(asset["browser_download_url"]) as resp, open(path + ".part", "wb") as out:
            shutil.copyfileobj(resp, out, 1 << 20)
        os.replace(path + ".part", path)
    if found["sums"]:
        with _request(found["sums"]["browser_download_url"]) as resp:
            sums = resp.read().decode()
        expected = next((line.split()[0] for line in sums.splitlines()
                         if line.split()[-1:] == [asset["name"]]), None)
        digest = hashlib.sha256(open(path, "rb").read()).hexdigest()
        if expected and digest != expected:
            os.remove(path)
            raise SystemExit(f"sha256 di {asset['name']} non corrisponde.")
    return path


def python_exe(payload: str, target: str) -> str:
    if target == "windows":
        return os.path.join(payload, "python", "python.exe")
    return os.path.join(payload, "python", "bin", "python3")


def build_payload(target: str, payload: str, archive: str, spa_dist: str) -> str:
    """La cartella dell'app: python/, codice di RT, web app e marcatore BUNDLE."""
    shutil.rmtree(payload, ignore_errors=True)
    os.makedirs(payload)
    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(payload, filter="tar")
    python = python_exe(payload, target)
    say("📦 Dipendenze Python...")
    subprocess.run([python, "-m", "pip", "install", "--no-warn-script-location", "--disable-pip-version-check",
                    "-q", "-r", os.path.join(ROOT, "requirements.txt")], check=True, cwd=ROOT)
    subprocess.run([python, "-m", "pip", "install", "--no-warn-script-location", "--disable-pip-version-check",
                    "-q", "-r", os.path.join(ROOT, "packaging", "requirements-app.txt")], check=True, cwd=ROOT)
    subprocess.run([python, "-m", "pip", "check"], check=True)
    if target == "windows" and not os.path.isfile(os.path.join(payload, "python", "pythonw.exe")):
        raise SystemExit("Il Python dell'app non contiene pythonw.exe.")
    if target == "macos":
        _prepare_macos_dependencies(payload)
    subprocess.run([python, "-c", "import webview"], check=True)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store")
    for name in CODE:
        source = os.path.join(ROOT, name)
        if os.path.isdir(source):
            shutil.copytree(source, os.path.join(payload, name), ignore=ignore)
        else:
            shutil.copy2(source, payload)
    spa = os.path.join(payload, "rt", "spa")
    shutil.rmtree(spa, ignore_errors=True)
    if not os.path.isfile(os.path.join(spa_dist, "index.html")):
        raise SystemExit(f"Web app non compilata in {spa_dist}: esegui 'npm run build' in frontend/.")
    shutil.copytree(spa_dist, spa)
    version = read_version()
    with open(os.path.join(spa, "VERSION"), "w", encoding="utf-8") as f:
        f.write(version + "\n")
    with open(os.path.join(payload, "BUNDLE"), "w", encoding="utf-8") as f:
        f.write(target + "\n")
    _trim(payload, target)
    # prova: il Python dell'app importa RT e risponde alla versione
    subprocess.run([python, os.path.join(payload, "bin", "rt"), "desktop", "--help"], check=True,
                   stdout=subprocess.DEVNULL, env={**os.environ, "RT_UPDATE_OFFLINE": "1"})
    return python


def _prepare_macos_dependencies(payload: str) -> None:
    """L'app è solo arm64: toglie test, simboli e copie Intel dalle dipendenze native."""
    for directory, folders, files in os.walk(os.path.join(payload, "python", "lib")):
        for name in list(folders):
            # Le wheel di pyobjc-core includono i test compilati e i simboli di debug.
            if name == "PyObjCTest" or name.endswith(".dSYM"):
                shutil.rmtree(os.path.join(directory, name))
                folders.remove(name)
        for name in files:
            if not name.endswith((".so", ".dylib")):
                continue
            path = os.path.join(directory, name)
            archs = subprocess.run(["lipo", "-archs", path], check=True, capture_output=True, text=True).stdout.split()
            if "arm64" in archs and len(archs) > 1:
                temporary = path + ".arm64"
                subprocess.run(["lipo", path, "-thin", "arm64", "-output", temporary], check=True)
                os.chmod(temporary, os.stat(path).st_mode)
                os.replace(temporary, path)


def _trim(payload: str, target: str) -> None:
    """Toglie quello che all'app non serve (test e IDE della libreria standard)."""
    lib = os.path.join(payload, "python", "Lib") if target == "windows" else None
    if lib is None:
        base = os.path.join(payload, "python", "lib")
        lib = next((os.path.join(base, d) for d in os.listdir(base) if d.startswith("python3")), base)
    for name in ("test", "idlelib", "tkinter", "turtledemo", "ensurepip"):
        shutil.rmtree(os.path.join(lib, name), ignore_errors=True)


def read_version() -> str:
    with open(os.path.join(ROOT, "VERSION"), encoding="utf-8") as f:
        return f.read().strip()


# ------------------------------------------------------------------ macOS

LAUNCHER = """#!/bin/sh
# Doppio clic su RT: prepara dati e servizi, poi apre la finestra RT (rt/desktop.py)
APP="$(cd "$(dirname "$0")/../Resources/app" && pwd)"
cd "$HOME" || exit 1
exec "$APP/python/bin/python3" "$APP/bin/rt" desktop "$@"
"""


def build_macos(work: str, out: str, archive: str, spa_dist: str) -> str:
    version = read_version()
    app = os.path.join(work, "dmg", "RT.app")
    shutil.rmtree(os.path.join(work, "dmg"), ignore_errors=True)
    contents = os.path.join(app, "Contents")
    for sub in ("MacOS", "Resources"):
        os.makedirs(os.path.join(contents, sub))
    build_payload("macos", os.path.join(contents, "Resources", "app"), archive, spa_dist)
    launcher = os.path.join(contents, "MacOS", "RT")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER)
    os.chmod(launcher, 0o755)
    shutil.copy2(os.path.join(ROOT, "packaging", "icons", "rt.icns"), os.path.join(contents, "Resources", "rt.icns"))
    short = re.match(r"^\d+(\.\d+){0,2}", version).group(0)
    with open(os.path.join(contents, "Info.plist"), "wb") as f:
        plistlib.dump({
            "CFBundleName": "RT", "CFBundleDisplayName": "RT", "CFBundleIdentifier": BUNDLE_ID,
            "CFBundleExecutable": "RT", "CFBundleIconFile": "rt", "CFBundlePackageType": "APPL",
            "CFBundleShortVersionString": short, "CFBundleVersion": version,
            "LSMinimumSystemVersion": "14.0", "NSHighResolutionCapable": True,
            "LSApplicationCategoryType": "public.app-category.education",
            "NSMicrophoneUsageDescription": "RT usa il microfono per registrare note vocali.",
            "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
        }, f)
    os.symlink("/Applications", os.path.join(work, "dmg", "Applications"))
    os.makedirs(out, exist_ok=True)
    dmg = os.path.join(out, ASSET_NAMES["macos"].format(version=version))
    if os.path.exists(dmg):
        os.remove(dmg)
    say("💿 Creo il .dmg...")
    subprocess.run(["hdiutil", "create", "-volname", "RT", "-srcfolder", os.path.join(work, "dmg"),
                    "-ov", "-format", "UDZO", dmg], check=True)
    return dmg


# ------------------------------------------------------------------ Windows

def _iscc() -> str:
    found = shutil.which("iscc")
    if found:
        return found
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
        candidate = os.path.join(base or "", "Inno Setup 6", "ISCC.exe")
        if os.path.isfile(candidate):
            return candidate
    raise SystemExit("Inno Setup (iscc) non trovato: installalo con 'choco install innosetup'.")


def build_windows(work: str, out: str, archive: str, spa_dist: str) -> str:
    version = read_version()
    payload = os.path.join(work, "app")
    build_payload("windows", payload, archive, spa_dist)
    os.makedirs(out, exist_ok=True)
    name = ASSET_NAMES["windows"].format(version=version)
    numeric = re.match(r"^\d+(\.\d+){0,3}", version).group(0)
    say("🪟 Creo il setup...")
    subprocess.run([_iscc(), f"/DAppVersion={version}", f"/DAppNumericVersion={numeric}",
                    f"/DSourceDir={payload}", f"/DOutputDir={os.path.abspath(out)}",
                    f"/DOutputName={name[:-len('.exe')]}",
                    f"/DIconFile={os.path.join(ROOT, 'packaging', 'icons', 'rt.ico')}",
                    os.path.join(ROOT, "packaging", "windows", "rt.iss")], check=True)
    return os.path.join(out, name)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--target", choices=sorted(TRIPLES),
                        default="windows" if sys.platform == "win32" else "macos")
    parser.add_argument("--out", default=os.path.join(ROOT, "dist"))
    parser.add_argument("--work", default=os.path.join(ROOT, "build", "app"))
    parser.add_argument("--spa-dist", default=os.path.join(ROOT, "frontend", "dist"))
    parser.add_argument("--python", default="3.12", help="Versione minore di Python da includere")
    parser.add_argument("--pbs-release", default=os.environ.get("RT_PBS_RELEASE", "latest"),
                        help="Release di python-build-standalone (default: la più recente)")
    args = parser.parse_args(argv)
    found = find_python(args.target, args.python, args.pbs_release)
    archive = download_python(found, os.path.join(args.work, "cache"))
    builder = build_macos if args.target == "macos" else build_windows
    result = builder(args.work, args.out, archive, args.spa_dist)
    size = os.path.getsize(result) / (1 << 20)
    say(f"✅ {result} ({size:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
