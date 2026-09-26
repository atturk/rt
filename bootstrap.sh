#!/usr/bin/env bash
set -euo pipefail

# RT — Script di download e installazione one-liner (stile Homebrew).
# Scarica l'ultima Release pubblicata (archivio pulito, senza file di sviluppo),
# la estrae in ./rt, poi esegue install.sh (prerequisiti, dipendenze, web app, cartella dati
# ~/.rt, segreti cifrati, database, servizi launchd e apertura del browser).
# Idempotente: rilanciato dove c'è già RT ripara l'installazione (codice della release,
# dipendenze, servizi) senza toccare dati, configurazione e lezioni. Va lanciato con:
#   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/atturk/rt/main/bootstrap.sh)"
# (non "curl | bash": install.sh ha un prompt interattivo reale e ha bisogno
# dello stdin del terminale, che una pipe occuperebbe con il contenuto dello script).

REPO="atturk/rt"
TARGET_DIR="${RT_INSTALL_DIR:-rt}"

if [ -t 1 ]; then
    CYAN=$'\033[1;36m'
    GREEN=$'\033[1;32m'
    RED=$'\033[1;31m'
    BOLD=$'\033[1m'
    RESET=$'\033[0m'
else
    CYAN=""
    GREEN=""
    RED=""
    BOLD=""
    RESET=""
fi

echo "${BOLD}🚀 Download di RT...${RESET}"

REPAIR=false
if [ -e "$TARGET_DIR" ]; then
    if [ -f "$TARGET_DIR/bin/rt" ] && [ -f "$TARGET_DIR/install.sh" ]; then
        REPAIR=true
        if [ -d "$TARGET_DIR/.git" ]; then
            # checkout di sviluppo: il codice non si sovrascrive con la release
            echo "${CYAN}🔧 RT già presente in ./${TARGET_DIR} (checkout Git): ripeto l'installazione.${RESET}"
            cd "$TARGET_DIR"
            exec ./install.sh
        fi
        echo "${CYAN}🔧 RT già presente in ./${TARGET_DIR}: lo riparo con l'ultima release (dati e configurazione restano).${RESET}"
    else
        echo "${RED}❌ La cartella '${TARGET_DIR}' esiste già in questa directory e non è un'installazione di RT.${RESET}" >&2
        echo "   Rimuovila, rinominala, oppure esegui da un'altra directory." >&2
        exit 1
    fi
fi

echo "${CYAN}🔎 Verifica dell'ultima versione pubblicata...${RESET}"
RELEASE_JSON="$(curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest")" || {
    echo "${RED}❌ Impossibile contattare l'API di GitHub (verifica la connessione).${RESET}" >&2
    exit 1
}

TARBALL_URL="$(printf '%s' "$RELEASE_JSON" | grep '"tarball_url":' | cut -d '"' -f 4)"
TAG_NAME="$(printf '%s' "$RELEASE_JSON" | grep '"tag_name":' | cut -d '"' -f 4)"

if [ -z "$TARBALL_URL" ]; then
    echo "${RED}❌ Nessuna release pubblicata trovata per ${REPO}.${RESET}" >&2
    exit 1
fi

echo "${CYAN}⬇️  Download di RT ${TAG_NAME}...${RESET}"
mkdir -p "$TARGET_DIR"
# L'archivio contiene solo codice e modelli: config/, .env, .venv e i dati (in ~/.rt) non ci sono,
# quindi estrarlo sopra un'installazione esistente aggiorna il codice senza toccare nient'altro.
if ! curl -fsSL "$TARBALL_URL" | tar -xz -C "$TARGET_DIR" --strip-components=1; then
    echo "${RED}❌ Download o estrazione falliti.${RESET}" >&2
    [ "$REPAIR" = false ] && rm -rf "$TARGET_DIR"
    exit 1
fi
echo "${GREEN}✅ RT ${TAG_NAME} scaricato in ./${TARGET_DIR}${RESET}"
echo ""

cd "$TARGET_DIR"
exec ./install.sh
