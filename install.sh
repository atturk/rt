#!/usr/bin/env bash
set -euo pipefail

# RT — Script di installazione automatizzata per macOS (lo lancia bootstrap.sh).
# Idempotente: rilanciarlo ripara un'installazione rotta senza toccare dati e configurazione.
#
# Variabili (tutte facoltative):
#   RT_NONINTERACTIVE=1    nessuna domanda (CI, script); non apre il browser né una nuova shell
#   RT_INSTALL_PARAKEET=0|1  installa o no macparakeet-cli e il modello (default: chiede; senza
#                          terminale sì su Apple Silicon)
#   RT_INSTALL_EXTRAS=0    salta gli strumenti facoltativi della CLI (micro, mpv)
#   RT_NO_SERVICES=1       non installa i servizi in background (launchd)
#   RT_SPA_TARBALL=<file>  web app già compilata da un file locale invece che dalla release
#   RT_DATA_DIR=<cartella> cartella dati diversa da ~/.rt

SECONDS=0
NONINTERACTIVE="${RT_NONINTERACTIVE:-0}"

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

# Ultime righe di install.log sul terminale: la causa di un errore senza aprire il file.
show_log_tail() {
    echo "   Ultime righe di install.log:" >&2
    tail -n "${1:-15}" "$LOG_FILE" 2>/dev/null | sed 's/^/   │ /' >&2 || true
}

# Cartelle di Homebrew non scrivibili dall'utente (es. Homebrew installato da un altro
# account del Mac): ogni 'brew install' fallirebbe. Stampa le cartelle, una per riga; niente
# se va tutto bene. Il prefisso in sé non si controlla: su Intel /usr/local è di root per
# costruzione, Homebrew scrive solo nelle sottocartelle.
brew_unwritable_dirs() {
    local prefix dir
    prefix="$(brew --prefix 2>/dev/null)" || return 0
    for dir in bin Cellar Caskroom etc include lib opt sbin share var var/homebrew; do
        if [ -e "$prefix/$dir" ] && [ ! -w "$prefix/$dir" ]; then
            echo "$prefix/$dir"
        fi
    done
}

# Controllo fatto una volta, prima del primo 'brew install': 0 se Homebrew è scrivibile,
# altrimenti spiega come sistemare (non lancia sudo) e restituisce 1.
BREW_WRITABLE=""
check_brew_writable() {
    if [ -z "$BREW_WRITABLE" ]; then
        local dirs dir
        dirs="$(brew_unwritable_dirs)"
        if [ -z "$dirs" ]; then
            BREW_WRITABLE=yes
        else
            BREW_WRITABLE=no
            echo "${RED}❌ Homebrew non è scrivibile dal tuo utente ($(whoami)): queste cartelle appartengono a un altro utente:${RESET}" >&2
            while IFS= read -r dir; do echo "   $dir" >&2; done <<<"$dirs"
            echo "   Succede quando Homebrew è stato installato da un altro account del Mac. Per sistemare, lancia:" >&2
            # shellcheck disable=SC2016  # il comando va mostrato così com'è, da copiare
            echo '   sudo chown -R "$(whoami)" "$(brew --prefix)"' >&2
            echo "   poi rilancia l'installazione." >&2
        fi
    fi
    [ "$BREW_WRITABLE" = yes ]
}

# brew install silenzioso. Con "optional" come terzo argomento un errore avvisa soltanto e
# l'installazione prosegue (strumenti facoltativi: micro, mpv); senza, la ferma.
brew_install_quiet() {
    local pkg="$1"
    local name="${2:-$pkg}"
    local optional="${3:-}"
    if ! check_brew_writable; then
        if [ "$optional" = optional ]; then
            echo "${YELLOW}⚠️  ${name} (facoltativo) non installato: Homebrew non è scrivibile, vedi sopra. Proseguo.${RESET}" >&2
            return 0
        fi
        echo "${RED}❌ ${name} è necessario: sistema Homebrew come indicato sopra e rilancia l'installazione.${RESET}" >&2
        exit 1
    fi
    echo "🍺 Installazione di ${name} via Homebrew..."
    if brew install "$pkg" >>"$LOG_FILE" 2>&1; then
        echo "${GREEN}✅ ${name} installato.${RESET}"
    elif [ "$optional" = optional ]; then
        echo "${YELLOW}⚠️  Installazione di ${name} non riuscita (facoltativo): proseguo senza. Dettagli in install.log.${RESET}" >&2
    else
        echo "${RED}❌ Installazione di ${name} fallita.${RESET}" >&2
        show_log_tail
        exit 1
    fi
}

show_download_progress() {
    local pid="$1"
    local spin='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
    local i=0
    local start_ts=$SECONDS
    local spin_len=${#spin}
    while kill -0 "$pid" 2>/dev/null; do
        local elapsed=$((SECONDS - start_ts))
        local status
        status="$(grep -oE '[0-9]+% \([0-9]+/[0-9]+\)' "$LOG_FILE" 2>/dev/null | tail -1 || true)"
        local spin_char="${spin:i:1}"
        i=$(( (i + 1) % spin_len ))
        if [ -n "$status" ]; then
            printf "\r   %s Download modello Parakeet: %s (%ss)\033[K" "$spin_char" "$status" "$elapsed"
        else
            printf "\r   %s Download modello Parakeet in corso... (%ss)\033[K" "$spin_char" "$elapsed"
        fi
        sleep 0.3
    done
    printf "\r\033[K"
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
    for py in python3 python3.13 python3.12 python3.11; do
        if command -v "$py" &>/dev/null; then
            if "$py" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' &>/dev/null; then
                echo "$py"
                return 0
            fi
        fi
    done
    return 1
}

PYTHON_BIN="$(find_compatible_python || true)"

if [ -z "$PYTHON_BIN" ]; then
    echo "${YELLOW}⚠️  Nessuna versione compatibile di Python (>= 3.11) trovata. Installazione via Homebrew...${RESET}"
    brew_install_quiet python@3.13 "python@3.13"
    PYTHON_BIN="$(find_compatible_python || true)"
fi

if [ -z "$PYTHON_BIN" ]; then
    echo "${RED}❌ Impossibile trovare o installare Python >= 3.11.${RESET}" >&2
    exit 1
fi

PYTHON_VER="$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")')"
echo "ℹ️ Utilizzo di Python $PYTHON_VER ($PYTHON_BIN)"

VENV_DIR="${REPO_DIR}/.venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "⚙️ Creazione dell'ambiente virtuale .venv..."
    "$PYTHON_BIN" -m venv "$VENV_DIR" >>"$LOG_FILE" 2>&1 || true
fi
"${VENV_DIR}/bin/pip" install --quiet questionary >>"$LOG_FILE" 2>&1 || true

IS_APPLE_SILICON=false
if [ "$(sysctl -n hw.optional.arm64 2>/dev/null)" = "1" ]; then
    IS_APPLE_SILICON=true
fi

ask_stt_choice() {
    local script answer_file
    script="$(mktemp "${TMPDIR:-/tmp}/rt_install_ask.XXXXXX.py" 2>/dev/null)" || script=""
    if [ -z "$script" ]; then
        return 1
    fi
    answer_file="$(mktemp "${TMPDIR:-/tmp}/rt_install_answer.XXXXXX" 2>/dev/null)" || answer_file=""
    if [ -z "$answer_file" ]; then
        rm -f "$script"
        return 1
    fi
    cat > "$script" <<PYEOF
import questionary

RECOMMENDED = "🎙️  Sì, installa macparakeet-cli e Parakeet v3 (consigliato: gratuito, locale, veloce su Apple Silicon)"
ALTERNATIVE = "🔧 No, configurerò un motore ASR alternativo"

answer = questionary.select(
    "Motore ASR per la trascrizione delle lezioni:",
    choices=[RECOMMENDED, ALTERNATIVE],
    default=RECOMMENDED,
).ask()

with open(r"$answer_file", "w") as f:
    f.write("yes" if answer == RECOMMENDED else "no")
PYEOF
    # Non reindirizzare mai lo stdout né di questa funzione né dell'invocazione python: anche
    # avvolgere SOLO la chiamata alla funzione in "$(...)" al call site (come si faceva prima)
    # trasforma comunque lo stdout ereditato dal sottoprocesso python in una pipe — bastava
    # rimuovere il "| tail -1" interno a QUESTA funzione per non essere sufficiente, il problema
    # si ripresentava un livello più in alto. questionary/prompt_toolkit ha bisogno di un vero
    # terminale su stdout per disegnare il menu interattivo: se stdout finisce in una pipe o in
    # un file, il menu non viene mai disegnato ma il processo resta comunque in attesa di un
    # tasto su stdin — lo script sembra bloccato senza alcun prompt visibile (bug reale
    # riscontrato: invio "alla cieca" selezionava sempre l'opzione di default). Per questo la
    # funzione NON usa "echo"/valore di ritorno via stdout: scrive il risultato nella variabile
    # globale ASK_STT_RESULT, e il chiamante non deve MAI invocarla dentro "$(...)".
    if ! "${VENV_DIR}/bin/python" "$script" 2>>"$LOG_FILE"; then
        rm -f "$script" "$answer_file"
        return 1
    fi
    ASK_STT_RESULT=""
    [ -f "$answer_file" ] && ASK_STT_RESULT="$(cat "$answer_file")"
    rm -f "$script" "$answer_file"
}

INSTALL_PARAKEET=false
if [ "$IS_APPLE_SILICON" = true ]; then
    if [ -n "${RT_INSTALL_PARAKEET:-}" ]; then
        [ "${RT_INSTALL_PARAKEET}" = "1" ] && INSTALL_PARAKEET=true
    elif [ ! -t 0 ] || [ "$NONINTERACTIVE" = "1" ]; then
        INSTALL_PARAKEET=true
    else
        ASK_STT_RESULT=""
        choice=""
        if ask_stt_choice 2>>"$LOG_FILE"; then
            choice="$ASK_STT_RESULT"
        fi
        if [ "$choice" = "yes" ]; then
            INSTALL_PARAKEET=true
        elif [ "$choice" = "no" ]; then
            INSTALL_PARAKEET=false
        else
            echo "⚠️  Prompt interattivo avanzato non disponibile, uso il prompt testuale semplice."
            echo "💡 macparakeet-cli + Parakeet v3 è il motore ASR consigliato (gratuito, locale e veloce su Apple Silicon)."
            read -rp "   Vuoi installare macparakeet-cli e scaricare il modello Parakeet? [S/n] " choice_text
            case "$choice_text" in
                [Nn]* ) INSTALL_PARAKEET=false ;;
                * ) INSTALL_PARAKEET=true ;;
            esac
        fi
    fi
else
    echo "ℹ️ macparakeet-cli richiede Apple Silicon (M1 o successivo), non disponibile su questo Mac."
    echo "   Configura un motore ASR alternativo, vedi docs/ALTERNATIVE_TRANSCRIPTION.md."
    INSTALL_PARAKEET=false
fi

if command -v ffmpeg &>/dev/null; then
    echo "ℹ️ ffmpeg è già installato."
else
    brew_install_quiet ffmpeg "ffmpeg"
fi

if [ "$INSTALL_PARAKEET" = true ]; then
    if command -v macparakeet-cli &>/dev/null; then
        echo "ℹ️ macparakeet-cli è già installato."
    else
        brew_install_quiet moona3k/tap/macparakeet-cli "macparakeet-cli"
    fi
fi
echo ""

# 2. Download modello Parakeet (in background)
echo "${CYAN}${BOLD}[2/5] Download modello Parakeet (in background)${RESET}"
if [ "$INSTALL_PARAKEET" = true ]; then
    echo "📥 Avvio scaricamento modello Parakeet v3 (~465MB)..."
    macparakeet-cli models download parakeet-v3 >>"$LOG_FILE" 2>&1 &
    model_pid=$!
    echo "ℹ️ Download avviato in background (PID $model_pid). Proseguo con le altre fasi."
else
    echo "ℹ️ Download del modello Parakeet saltato."
fi
echo ""

# 3. Ambiente virtuale Python
echo "${CYAN}${BOLD}[3/5] Ambiente virtuale Python${RESET}"
if [ "${RT_INSTALL_EXTRAS:-1}" = "0" ]; then
    echo "ℹ️ Strumenti facoltativi (micro, mpv) saltati (RT_INSTALL_EXTRAS=0)."
else
    if command -v micro &>/dev/null; then
        echo "ℹ️ Editor 'micro' già installato."
    else
        brew_install_quiet micro "micro" optional
    fi

    if command -v mpv &>/dev/null; then
        echo "ℹ️ Media player 'mpv' già installato."
    else
        brew_install_quiet mpv "mpv" optional
    fi
fi

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

# 4. Cartella dati, segreti, database e web app
echo "${CYAN}${BOLD}[4/5] Dati, segreti, database e web app${RESET}"
chmod +x "${REPO_DIR}/bin/rt"
RT_BIN=("${VENV_DIR}/bin/python" "${REPO_DIR}/bin/rt")

# RT4-G2: la web app compilata della release (niente Node), prima di dati e servizi
echo "🌐 Installazione della web app..."
if ! "${VENV_DIR}/bin/python" -c "import sys; sys.path.insert(0, sys.argv[1]); from rt.core.spa_release import main; sys.exit(main(sys.argv[1]))" "$REPO_DIR" 2>&1 | tee -a "$LOG_FILE"; then
    echo "${YELLOW}⚠️  Web app non installata: riprova più tardi con 'rt -u'.${RESET}"
fi

# Cartella dati (~/.rt o RT_DATA_DIR): la crea, o sposta lì i dati di una 3.x; poi crea o
# migra il database e importa le lezioni esistenti. Idempotente.
if [ "$NONINTERACTIVE" = "1" ] || [ ! -t 0 ]; then
    export RT_NONINTERACTIVE=1
fi
if ! "${RT_BIN[@]}" data post-update 2>&1 | tee -a "$LOG_FILE"; then
    echo "${RED}❌ Preparazione di dati e database non riuscita — vedi install.log.${RESET}" >&2
    exit 1
fi

# Segreti cifrati: chiave master nel portachiavi di macOS, archivio in <cartella dati>/config
if "${VENV_DIR}/bin/python" -c "import sys; sys.path.insert(0, sys.argv[1]); from rt.security.secrets import default_store_path; sys.exit(0 if default_store_path().is_file() else 1)" "$REPO_DIR" >>"$LOG_FILE" 2>&1; then
    echo "ℹ️ Archivio dei segreti cifrati già presente."
else
    echo "🔐 Creazione dell'archivio cifrato per chiavi API e token..."
    # niente tee: se il portachiavi non è disponibile la chiave master viene mostrata una volta
    # sul terminale e non deve finire in install.log
    if "${RT_BIN[@]}" secrets init; then
        echo "${GREEN}✅ Segreti cifrati pronti.${RESET}"
    else
        echo "${YELLOW}⚠️  Archivio cifrato non creato: riprova con 'rt secrets init'.${RESET}"
    fi
fi

# Servizi in background (launchd): API + web app, worker, bot Telegram
if [ "${RT_NO_SERVICES:-0}" = "1" ]; then
    echo "ℹ️ Servizi in background non installati (RT_NO_SERVICES=1): usa 'rt web'."
elif "${RT_BIN[@]}" service install 2>&1 | tee -a "$LOG_FILE"; then
    :
else
    echo "${YELLOW}⚠️  Servizi non installati: riprova con 'rt service install' (vedi install.log).${RESET}"
fi

if [ -z "${SHELL_PROFILE:-}" ]; then
    case "${SHELL:-}" in
        */zsh) SHELL_PROFILE="$HOME/.zshrc" ;;
        */bash) SHELL_PROFILE="$HOME/.bash_profile" ;;
        *) SHELL_PROFILE="$HOME/.zshrc" ;;
    esac
fi

display_profile="${SHELL_PROFILE/#$HOME/\~}"
path_line="export PATH=\"${REPO_DIR}/bin:\$PATH\""
if [ -f "$SHELL_PROFILE" ] && grep -Fq "${REPO_DIR}/bin" "$SHELL_PROFILE"; then
    echo "ℹ️ PATH è già configurato in ${display_profile}."
else
    echo "⚙️ Aggiunta di bin/ al PATH in ${display_profile}..."
    mkdir -p "$(dirname "$SHELL_PROFILE")"
    {
        echo ""
        echo "# Aggiunto da RT install.sh"
        echo "$path_line"
    } >> "$SHELL_PROFILE"
    echo "${GREEN}✅ PATH aggiornato in ${display_profile}.${RESET}"
fi
echo ""

# 5. Verifica finale
echo "${CYAN}${BOLD}[5/5] Verifica finale${RESET}"

if [ -n "$model_pid" ]; then
    if kill -0 "$model_pid" 2>/dev/null; then
        echo "⏳ In attesa del completamento del download del modello Parakeet v3..."
        show_download_progress "$model_pid"
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
# rt doctor: controlla tutto e dice cosa sistemare (non blocca: gli avvisi sono normali qui)
"${RT_BIN[@]}" doctor 2>&1 | tee -a "$LOG_FILE" || true

# Riepilogo finale
echo ""
echo "${GREEN}${BOLD}✅ Installazione completata in ${SECONDS}s.${RESET}"
echo ""
if [ "$NONINTERACTIVE" != "1" ] && [ -t 0 ] && [ -t 1 ]; then
    echo "🌐 Apro RT nel browser per la configurazione guidata (provider e chiavi, modelli, Telegram)..."
    api_up=false
    if [ "${RT_NO_SERVICES:-0}" != "1" ]; then
        for _ in $(seq 1 30); do
            if curl -fsS "http://127.0.0.1:${RT_API_PORT:-8765}/api/v1/health" >/dev/null 2>&1; then
                api_up=true
                break
            fi
            sleep 1
        done
    fi
    if [ "$api_up" = true ]; then
        "${RT_BIN[@]}" web || echo "   Aprila con: rt web"
    else
        echo "   Avvia la web app con: rt web"
    fi
    echo ""
fi
echo "Prossimi passi:"
if [ -t 0 ] && [ -t 1 ]; then
    echo "1. Completa la configurazione guidata nel browser (o riaprila con: rt web)"
    echo "2. Controlla l'installazione quando vuoi con: rt doctor"
    echo "3. Backup completo dei dati con: rt backup --dest <disco esterno>"
    echo "4. Documentazione: https://github.com/atturk/rt"
else
    echo "1. Apri la configurazione guidata con: ./bin/rt web"
    echo "2. Controlla l'installazione con: ./bin/rt doctor"
    echo "3. Backup completo dei dati con: ./bin/rt backup --dest <disco esterno>"
    echo "4. Documentazione: https://github.com/atturk/rt"
fi

if [ "$INSTALL_PARAKEET" = false ]; then
    echo ""
    echo "ℹ️ Motore ASR Parakeet non installato. Per configurare un motore ASR alternativo, vedi docs/ALTERNATIVE_TRANSCRIPTION.md."
fi

if [ "$NONINTERACTIVE" != "1" ] && [ -t 0 ] && [ -t 1 ]; then
    exec_shell="${SHELL:-/bin/zsh}"
    exec "$exec_shell" -l
fi
