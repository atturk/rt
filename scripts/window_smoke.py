#!/usr/bin/env python3
"""Apre la finestra dell'app installata e controlla il caricamento autenticato (CI).

Uso: python scripts/window_smoke.py <python dell'app> <codice dell'app> [--data cartella]
Il server Windows resta acceso: il successivo setup prova a sostituirlo e a riaprire RT.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request


def get(base, path):
    with urllib.request.urlopen(base + path, timeout=3) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("python")
    parser.add_argument("root")
    parser.add_argument("--data")
    parser.add_argument("--wait-only", action="store_true", help="Controlla il rilancio già fatto dal setup")
    parser.add_argument("--quit", action="store_true", help="Prova anche l'uscita usata dal menu")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    data = Path(args.data or tempfile.mkdtemp(prefix="rt-window-smoke-")).resolve()
    data.mkdir(parents=True, exist_ok=True)
    result_path = data / "logs" / "window-smoke.json"
    port = 8798
    base = f"http://127.0.0.1:{port}"
    settings = {"RT_DATA_DIR": str(data), "RT_WINDOW_SMOKE": "1", "RT_API_PORT": str(port),
                "RT_UPDATE_OFFLINE": "1"}
    # Il "python -c" di Esci salta bin/rt: senza questa variabile scriverebbe __pycache__ nel bundle.
    env = {**os.environ, **settings, "PYTHONDONTWRITEBYTECODE": "1"}
    env.pop("RT_NO_SERVICES", None)
    env.pop("RT_NO_WINDOW", None)
    proc = None
    success = False
    log_path = data / "window-console.log"
    try:
        if not args.wait_only:
            result_path.unlink(missing_ok=True)
            if sys.platform == "darwin":
                app = root.parents[2]
                command = ["open", "-W", str(app)]
                for key, value in settings.items():
                    command.extend(["--env", f"{key}={value}"])
                command.extend(["--args", "--port", str(port)])
            else:
                command = [str(Path(args.python).resolve()), str(root / "bin" / "rt"),
                           "desktop", "--port", str(port)]
            with log_path.open("w", encoding="utf-8") as log:
                proc = subprocess.Popen(command, cwd=Path.home(), env=env, stdin=subprocess.DEVNULL,
                                        stdout=log, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            if result_path.is_file():
                try:
                    result = json.loads(result_path.read_text(encoding="utf-8"))
                    break
                except ValueError:
                    pass
            if proc is not None and proc.poll() is not None:
                raise RuntimeError(f"La finestra è uscita senza risultato (codice {proc.returncode}).")
            time.sleep(0.5)
        else:
            raise RuntimeError("La finestra non ha caricato la pagina entro 120 secondi.")
        if proc is not None:
            if proc.wait(timeout=max(1, deadline - time.monotonic())) != 0:
                raise RuntimeError(f"La finestra è uscita con codice {proc.returncode}.")
        if not result.get("page") or result.get("authenticated") is not True or result.get("error"):
            raise RuntimeError(f"Pagina non caricata o non autenticata: {result}")
        if result.get("downloads") != ["lezione.zip", "nota.md", "domande.json"]:
            raise RuntimeError(f"Download non riusciti nel motore nativo: {result}")
        if sys.platform == "darwin" and result.get("menu") != ["Esci da RT", "Modifica"]:
            raise RuntimeError(f"Il menu nativo del Mac non è pronto: {result}")
        pid_deadline = min(deadline, time.monotonic() + 10)
        while (data / "run" / "window.pid").exists() and time.monotonic() < pid_deadline:
            time.sleep(0.1)
        if (data / "run" / "window.pid").exists():
            raise RuntimeError("Il pid della finestra è rimasto dopo la chiusura.")
        health = get(base, "/api/v1/health")
        version = (root / "VERSION").read_text(encoding="utf-8").strip()
        if health["version"] != version or not health["database"]:
            raise RuntimeError(f"Il server dopo la chiusura della finestra non è pronto: {health}")
        print(f"✅ Finestra RT {version} caricata e autenticata; il server resta acceso. {result}")
        if args.quit:
            command = ("import sys; sys.path.insert(0, sys.argv[1]); "
                       "from rt.desktop import stop_background; stop_background(sys.argv[2])")
            stopped = subprocess.run([args.python, "-c", command, str(root), base], env=env,
                                     capture_output=True, text=True, encoding="utf-8", timeout=45)
            if stopped.returncode:
                raise RuntimeError(f"Esci da RT non riuscito: {stopped.stdout} {stopped.stderr}")
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                try:
                    get(base, "/api/v1/health")
                except OSError:
                    break
                time.sleep(0.2)
            else:
                raise RuntimeError("Il server risponde ancora dopo Esci da RT.")
            print("✅ Esci da RT ha fermato il server e il worker.")
        success = True
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=15)
        for path in [log_path, *sorted((data / "logs").glob("*"))]:
            if path.is_file():
                print(f"{path.name}:\n{path.read_text(encoding='utf-8', errors='replace')[-6000:]}")
        if sys.platform == "darwin" and not (success and args.quit):
            subprocess.run([args.python, str(root / "bin" / "rt"), "service", "uninstall"],
                           env=env, check=True)
        elif not success:
            pid_path = data / "run" / "server.pid"
            if pid_path.is_file():
                subprocess.run(["taskkill", "/PID", pid_path.read_text().strip(), "/T", "/F"],
                               capture_output=True, check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
