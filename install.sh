#!/usr/bin/env bash
set -euo pipefail

# RT 2.0 — Script di installazione automatizzata per macOS

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"

echo "🚀 Inizio installazione di RT..."

# 1. Controllo prerequisiti di sistema
if ! command -v brew &>/dev/null; then
    echo "❌ Homebrew non trovato."
    echo "Homebrew è richiesto per installare le dipendenze di sistema (ffmpeg, python)."
    echo "Per installarlo, visita: https://brew.sh"
    exit 1
fi

find_compatible_python() {
    for py in python3 python3.13 python3.12 python3.11 python3.10; do
        if command -v "$py" &>/dev/null; then
            if "$py" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' &>/dev/null; then
                echo "$py"
                return 0
            fi
        fi
    done
    return 1
}

PYTHON_BIN="$(find_compatible_python || true)"

if [ -z "$PYTHON_BIN" ]; then
    echo "🍺 Nessuna versione compatibile di Python (>= 3.10) trovata. Installazione via Homebrew..."
    brew install python@3.13
    PYTHON_BIN="$(find_compatible_python || true)"
fi

if [ -z "$PYTHON_BIN" ]; then
    echo "❌ Impossibile trovare o installare Python >= 3.10." >&2
    exit 1
fi

PYTHON_VER="$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")')"
echo "ℹ️ Utilizzo di Python $PYTHON_VER ($PYTHON_BIN)"

if ! command -v ffmpeg &>/dev/null; then
    echo "🍺 Installazione di ffmpeg via Homebrew..."
    brew install ffmpeg
else
    echo "ℹ️ ffmpeg è già installato."
fi

if command -v macparakeet-cli &>/dev/null; then
    echo "ℹ️ macparakeet-cli è già installato."
else
    echo "🍺 Installazione di macparakeet-cli via Homebrew..."
    brew install moona3k/tap/macparakeet-cli
fi
macparakeet-cli models download parakeet-v3 &>/dev/null || true

if command -v micro &>/dev/null; then
    echo "ℹ️ Editor 'micro' già installato."
else
    if [ -t 0 ]; then
        read -r -p "Vuoi installare l'editor raccomandato 'micro' via Homebrew? [y/N] " reply
        case "$reply" in
            [yY][eE][sS]|[yY]|[sS][ìI]|[sS])
                echo "🍺 Installazione di micro..."
                brew install micro
                ;;
            *)
                echo "ℹ️ Salto l'installazione di micro."
                ;;
        esac
    else
        echo "ℹ️ Sessione non interattiva, salto l'installazione di micro."
    fi
fi

# 2. Ambiente virtuale
VENV_DIR="${REPO_DIR}/.venv"
if [ -d "$VENV_DIR" ]; then
    echo "ℹ️ venv già presente, riuso."
else
    echo "⚙️ Creazione dell'ambiente virtuale .venv..."
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

echo "📦 Aggiornamento pip e installazione dipendenze in .venv..."
"${VENV_DIR}/bin/python" -m pip install --upgrade pip -q
"${VENV_DIR}/bin/pip" install -r requirements.txt -q

# 3. Configurazione
if [ -d "${REPO_DIR}/config" ]; then
    echo "ℹ️ config/ già presente, non toccata."
else
    echo "⚙️ Copia di config.example/ -> config/..."
    cp -r "${REPO_DIR}/config.example" "${REPO_DIR}/config"
fi

if [ -f "${REPO_DIR}/.env" ]; then
    echo "ℹ️ .env già presente, non toccato."
else
    echo "⚙️ Copia di .env.example -> .env..."
    cp "${REPO_DIR}/.env.example" "${REPO_DIR}/.env"
fi

# 4. Permessi ed eseguibilità
echo "⚙️ Impostazione permessi di esecuzione su bin/rt..."
chmod +x "${REPO_DIR}/bin/rt"

# 6. Verifica finale
echo "🔍 Verifica installazione..."
if "${VENV_DIR}/bin/python" "${REPO_DIR}/bin/rt" -h &>/dev/null; then
    echo "✅ Verification OK: ./bin/rt risponde correttamente."
else
    echo "❌ Errore durante la verifica di ./bin/rt -h." >&2
    exit 1
fi

# 7. Riepilogo finale
echo ""
echo "✅ Installazione completata."
echo ""
echo "Prossimi passi:"
echo "1. Apri config/general.yaml e .env, inserisci le tue credenziali/API key"
echo "   (vedi docs/CONFIGURATION_REFERENCE.md per la sintassi)."
echo "2. Per usare 'rt' da qualunque cartella, aggiungi questa riga al tuo ~/.zshrc:"
echo "     export PATH=\"${REPO_DIR}/bin:\$PATH\""
echo "3. Verifica con: ./bin/rt -h"
echo "4. Prova una pipeline di test senza costi con: ./bin/rt run <cartella_lezione> --mock"
