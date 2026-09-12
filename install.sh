#!/usr/bin/env bash
set -euo pipefail

# RT 2.0 — Script di installazione automatizzata per macOS

SECONDS=0

# Silenzia l'auto-update di Homebrew per la durata di questo script (output più
# pulito e installazioni più veloci/deterministiche) — non tocca la config globale
# dell'utente, vale solo per i comandi brew lanciati da qui.
export HOMEBREW_NO_AUTO_UPDATE=1

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"

LOG_FILE="${REPO_DIR}/install.log"
> "$LOG_FILE"

# Palette colori ANSI coerente con setup.py (disabilitata se non su terminale TTY)
if [ -t 1 ]; then
    CYAN=$'\033[1;36m'
    GREEN=$'\033[1;32m'
    YELLOW=$'\033[1;33m'
    RED=$'\033[1;31m'
    BOLD=$'\033[1m'
    RESET=$'\033[0m'
else
    CYAN=""
    GREEN=""
    YELLOW=""
    RED=""
    BOLD=""
    RESET=""
fi

echo "${BOLD}🚀 Inizio installazione di RT...${RESET}"
echo ""

model_pid=""
cleanup() {
    if [ -n "${model_pid:-}" ] && kill -0 "$model_pid" 2>/dev/null; then
        kill "$model_pid" 2>/dev/null || true
    fi
}
trap cleanup EXIT
# Un trap su INT/TERM che non chiama exit lascia bash RIPRENDERE lo script dopo
# l'handler invece di interromperlo (comportamento bash documentato) — senza
# questo exit esplicito, Ctrl+C durante l'attesa del download ucciderebbe solo
# il download in background e l'installazione proseguirebbe come se nulla fosse.
trap 'cleanup; echo ""; echo "${YELLOW}⚠️  Installazione interrotta dall'"'"'utente.${RESET}"; exit 130' INT TERM

brew_install_quiet() {
    local pkg="$1"
    local name="${2:-$pkg}"
    echo "🍺 Installazione di ${name} via Homebrew..."
    if brew install "$pkg" >>"$LOG_FILE" 2>&1; then
        echo "${GREEN}✅ ${name} installato.${RESET}"
    else
        echo "${RED}❌ Installazione di ${name} fallita — vedi install.log per i dettagli.${RESET}" >&2
        exit 1
    fi
}

# 1. Prerequisiti di sistema
echo "${CYAN}${BOLD}[1/5] Prerequisiti di sistema${RESET}"

if ! command -v brew &>/dev/null; then
    echo "${RED}❌ Homebrew non trovato.${RESET}"
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
    echo "${YELLOW}⚠️  Nessuna versione compatibile di Python (>= 3.10) trovata. Installazione via Homebrew...${RESET}"
    brew_install_quiet python@3.13 "python@3.13"
    PYTHON_BIN="$(find_compatible_python || true)"
fi

if [ -z "$PYTHON_BIN" ]; then
    echo "${RED}❌ Impossibile trovare o installare Python >= 3.10.${RESET}" >&2
    exit 1
fi

PYTHON_VER="$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")')"
echo "ℹ️ Utilizzo di Python $PYTHON_VER ($PYTHON_BIN)"

if command -v ffmpeg &>/dev/null; then
    echo "ℹ️ ffmpeg è già installato."
else
    brew_install_quiet ffmpeg "ffmpeg"
fi

if command -v macparakeet-cli &>/dev/null; then
    echo "ℹ️ macparakeet-cli è già installato."
else
    brew_install_quiet moona3k/tap/macparakeet-cli "macparakeet-cli"
fi
echo ""

# 2. Download modello Parakeet (in background)
echo "${CYAN}${BOLD}[2/5] Download modello Parakeet (in background)${RESET}"
echo "📥 Avvio scaricamento modello Parakeet v3 (~465MB)..."
macparakeet-cli models download parakeet-v3 >>"$LOG_FILE" 2>&1 &
model_pid=$!
echo "ℹ️ Download avviato in background (PID $model_pid). Proseguo con le altre fasi."
echo ""

# 3. Ambiente virtuale Python
echo "${CYAN}${BOLD}[3/5] Ambiente virtuale Python${RESET}"
if command -v micro &>/dev/null; then
    echo "ℹ️ Editor 'micro' già installato."
else
    brew_install_quiet micro "micro"
fi

VENV_DIR="${REPO_DIR}/.venv"
if [ -d "$VENV_DIR" ]; then
    echo "ℹ️ venv già presente, riuso."
else
    echo "⚙️ Creazione dell'ambiente virtuale .venv..."
    "$PYTHON_BIN" -m venv "$VENV_DIR" >>"$LOG_FILE" 2>&1
    echo "${GREEN}✅ Ambiente virtuale creato.${RESET}"
fi

echo "📦 Aggiornamento pip e installazione dipendenze in .venv..."
if "${VENV_DIR}/bin/python" -m pip install --upgrade pip -q >>"$LOG_FILE" 2>&1 && \
   "${VENV_DIR}/bin/pip" install -r requirements.txt -q >>"$LOG_FILE" 2>&1; then
    echo "${GREEN}✅ Dipendenze Python installate con successo.${RESET}"
else
    echo "${RED}❌ Installazione dipendenze Python fallita — vedi install.log per i dettagli.${RESET}" >&2
    exit 1
fi
echo ""

# 4. Configurazione
echo "${CYAN}${BOLD}[4/5] Configurazione${RESET}"
if [ -d "${REPO_DIR}/config" ]; then
    echo "ℹ️ config/ già presente, non toccata."
else
    echo "⚙️ Copia di config.example/ -> config/..."
    cp -r "${REPO_DIR}/config.example" "${REPO_DIR}/config"
    echo "${GREEN}✅ Cartella config/ creata.${RESET}"
fi

if [ -f "${REPO_DIR}/.env" ]; then
    echo "ℹ️ .env già presente, non toccato."
else
    echo "⚙️ Copia di .env.example -> .env..."
    cp "${REPO_DIR}/.env.example" "${REPO_DIR}/.env"
    echo "${GREEN}✅ File .env creato.${RESET}"
fi

echo "⚙️ Impostazione permessi di esecuzione su bin/rt..."
chmod +x "${REPO_DIR}/bin/rt"
echo "${GREEN}✅ Permessi impostati.${RESET}"
echo ""

# 5. Verifica finale
echo "${CYAN}${BOLD}[5/5] Verifica finale${RESET}"

if [ -n "$model_pid" ]; then
    if kill -0 "$model_pid" 2>/dev/null; then
        echo "⏳ In attesa del completamento del download del modello Parakeet v3..."
        elapsed=0
        while kill -0 "$model_pid" 2>/dev/null; do
            sleep 10
            elapsed=$((elapsed + 10))
            echo "   ⏳ ancora in corso (${elapsed}s)..."
        done
    fi

    if wait "$model_pid" 2>/dev/null; then
        echo "${GREEN}✅ Modello Parakeet v3 pronto.${RESET}"
    else
        echo "${YELLOW}⚠️  Download del modello fallito (verrà ritentato automaticamente alla prima trascrizione reale).${RESET}"
    fi
    model_pid=""
fi

echo "🔍 Verifica installazione..."
if "${VENV_DIR}/bin/python" "${REPO_DIR}/bin/rt" -h >>"$LOG_FILE" 2>&1; then
    echo "${GREEN}✅ Verification OK: ./bin/rt risponde correttamente.${RESET}"
else
    echo "${RED}❌ Errore durante la verifica di ./bin/rt -h — vedi install.log per i dettagli.${RESET}" >&2
    exit 1
fi

# Riepilogo finale
echo ""
echo "${GREEN}${BOLD}✅ Installazione completata in ${SECONDS}s.${RESET}"
echo ""
echo "Prossimi passi:"
echo "1. Esegui la configurazione guidata interattiva:"
echo "     ./bin/rt config"
echo "   (Oppure modifica manualmente config/general.yaml e .env, vedi docs/CONFIGURATION_REFERENCE.md)."
echo "2. Per usare 'rt' da qualunque cartella, aggiungi questa riga al tuo ~/.zshrc:"
echo "     export PATH=\"${REPO_DIR}/bin:\$PATH\""
echo "3. Verifica con: ./bin/rt -h"
echo "4. Prova una pipeline di test senza costi con: ./bin/rt run <cartella_lezione> --mock"
