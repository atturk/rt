#!/usr/bin/env bash
set -euo pipefail

# Ponte per le installazioni RT precedenti alla 3.4.2. Si esegue una volta;
# dopo, rt -u gestisce sia gli archivi sia i checkout Git puliti su main.
rt_bin="$(python3 -c 'import os, shutil, sys; p = shutil.which("rt"); sys.exit("rt non trovato nel PATH") if not p else print(os.path.realpath(p))')"
rt_root="$(cd "$(dirname "$rt_bin")/.." && pwd)"
if [ ! -f "$rt_root/rt/core/version.py" ]; then
    echo "❌ Il comando rt non punta a una installazione RT riconosciuta." >&2
    exit 1
fi

latest_tag="$(curl -fsSL https://api.github.com/repos/atturk/rt/releases/latest | python3 -c 'import json,sys; print(json.load(sys.stdin)["tag_name"])')"
if [[ ! "$latest_tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "❌ La versione della release non è valida: $latest_tag" >&2
    exit 1
fi

if [ -e "$rt_root/.git" ]; then
    branch="$(git -C "$rt_root" rev-parse --abbrev-ref HEAD)"
    if [ "$branch" != main ]; then
        echo "❌ Il checkout RT è sul branch '$branch'. Passa a main dopo aver salvato il tuo lavoro." >&2
        exit 1
    fi
    if [ -n "$(git -C "$rt_root" status --porcelain --untracked-files=no)" ]; then
        echo "❌ Il checkout RT ha modifiche locali tracciate. Salvale prima di aggiornare." >&2
        exit 1
    fi

    echo "Aggiornamento del checkout RT alla release $latest_tag..."
    git -C "$rt_root" fetch --no-tags https://github.com/atturk/rt.git "refs/tags/$latest_tag"
    git -C "$rt_root" merge --ff-only FETCH_HEAD
    "$rt_bin" -u
else
    # Non eseguire il vecchio updater: tra 3.3.9 e 3.3.12 poteva eliminare
    # file locali non gestiti. Usa l'updater corretto della 3.4.2, senza toccare
    # l'installazione finché il download non è completato.
    tmp_dir="$(mktemp -d)"
    trap 'rm -rf "$tmp_dir"' EXIT
    curl -fsSL https://raw.githubusercontent.com/atturk/rt/v3.4.2/rt/core/version.py -o "$tmp_dir/version.py"
    venv_python="$rt_root/.venv/bin/python3"
    if [ ! -f "$venv_python" ]; then
        echo "❌ Ambiente Python di RT assente: esegui install.sh per ripristinarlo." >&2
        exit 1
    fi
    "$venv_python" - "$tmp_dir/version.py" "$rt_root" <<'PY'
import importlib.util
import sys

spec = importlib.util.spec_from_file_location("rt_legacy_upgrade", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.run_update(sys.argv[2])
PY
fi

echo "✅ RT aggiornato. Avvia la web app con: rt web"
