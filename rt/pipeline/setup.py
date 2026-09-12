"""
rt.pipeline.setup
Modulo unificato per l'ingest di file audio, trascrizione macparakeet-cli ASR e inizializzazione lezione.
Fornisce funzioni riusabili per la CLI nativa (`rt setup`, `rt run <audio>`).
"""

import os
import sys
import re
import shutil
import json
import subprocess
import datetime
import time
from typing import Dict, Any, List, Optional, Tuple, Union, Callable
from rich.console import Console

# Colori per il terminale
CYAN = "\033[1;36m"
GREEN = "\033[1;32m"
YELLOW = "\033[1;33m"
BLUE = "\033[1;34m"
MAGENTA = "\033[1;35m"
RED = "\033[1;31m"
BOLD = "\033[1m"
RESET = "\033[0m"

DEFAULT_MODEL = "parakeet-v3"
SUPPORTED_AUDIO_EXTENSIONS = {".m4a", ".mp3", ".wav", ".aac", ".flac", ".ogg", ".m4b", ".wma"}


class SetupError(Exception):
    """Eccezione bloccante per errori irreversibili durante la fase di setup."""
    pass


def is_audio_file(path: str) -> bool:
    """Verifica se il percorso corrisponde a un file esistente con estensione audio supportata."""
    if not path or not isinstance(path, str):
        return False
    clean = clean_input_path(path)
    if not os.path.isfile(clean):
        return False
    _, ext = os.path.splitext(clean.lower())
    return ext in SUPPORTED_AUDIO_EXTENSIONS


def clean_input_path(raw_path: str) -> str:
    """Pulisce percorsi con escape o virgolette derivanti da drag-and-drop nel terminale."""
    if not raw_path:
        return ""
    p = raw_path.strip()
    if (p.startswith('"') and p.endswith('"')) or (p.startswith("'") and p.endswith("'")):
        p = p[1:-1]
    p = p.replace(r"\ ", " ").replace(r"\(", "(").replace(r"\)", ")").replace(r"\[", "[").replace(r"\]", "]")
    return os.path.expanduser(p.strip())


def find_macparakeet_binary() -> str:
    """Individua il binario macparakeet-cli."""
    which_bin = shutil.which("macparakeet-cli")
    if which_bin:
        return which_bin
    candidates = [
        "/usr/local/bin/macparakeet-cli",
        "/opt/homebrew/bin/macparakeet-cli",
    ]
    for c in candidates:
        if os.path.exists(c) and os.access(c, os.X_OK):
            return c
    return ""


def prompt_clean(message: str, default: str = "") -> str:
    """Prompt interattivo formattato per terminale."""
    if not sys.stdin.isatty():
        return default
    if default:
        prompt_text = f"{CYAN}?{RESET} {BOLD}{message}{RESET} [{YELLOW}{default}{RESET}]: "
    else:
        prompt_text = f"{CYAN}?{RESET} {BOLD}{message}{RESET}: "
    
    try:
        val = input(prompt_text).strip()
    except (KeyboardInterrupt, EOFError):
        print(f"\n{YELLOW}Operazione annullata dall'utente.{RESET}")
        sys.exit(0)
    return val if val else default


MONTHS_MAP = {
    "gennaio": 1, "gen": 1, "january": 1, "jan": 1,
    "febbraio": 2, "feb": 2, "february": 2,
    "marzo": 3, "mar": 3, "march": 3,
    "aprile": 4, "apr": 4, "april": 4,
    "maggio": 5, "mag": 5, "may": 5,
    "giugno": 6, "giu": 6, "june": 6, "jun": 6,
    "luglio": 7, "lug": 7, "july": 7, "jul": 7,
    "agosto": 8, "ago": 8, "august": 8, "aug": 8,
    "settembre": 9, "sett": 9, "set": 9, "september": 9, "sept": 9, "sep": 9,
    "ottobre": 10, "ott": 10, "october": 10, "oct": 10,
    "novembre": 11, "nov": 11, "november": 11,
    "dicembre": 12, "dic": 12, "december": 12, "dec": 12
}


def parse_flexible_date(raw_input: str) -> str:
    """
    Parsa una data da molteplici formati (italiano testuale, ISO, DD/MM/YYYY, oggi/ieri)
    e restituisce sempre una stringa nel formato canonico YYYY-MM-DD.
    """
    if not raw_input:
        return datetime.date.today().strftime("%Y-%m-%d")
    
    text = raw_input.strip().lower()
    text = re.sub(r'[,]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    
    if not text or text in ("oggi", "today"):
        return datetime.date.today().strftime("%Y-%m-%d")
    if text in ("ieri", "yesterday"):
        return (datetime.date.today() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")

    # 1. ISO YYYY-MM-DD
    iso_match = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$", text)
    if iso_match:
        y, m, d = int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3))
        return datetime.date(y, m, d).strftime("%Y-%m-%d")

    # 2. DD-MM-YYYY o DD/MM/YYYY o DD.MM.YYYY
    dmy_match = re.match(r"^(\d{1,2})[-/.](\d{1,2})[-/.](?:(\d{4})|(\d{2}))$", text)
    if dmy_match:
        d = int(dmy_match.group(1))
        m = int(dmy_match.group(2))
        y = int(dmy_match.group(3)) if dmy_match.group(3) else (2000 + int(dmy_match.group(4)))
        return datetime.date(y, m, d).strftime("%Y-%m-%d")

    # 3. Formato testuale es: "26 sett 2025", "3 marzo 2024", "14 maggio"
    textual_match = re.match(r"^(\d{1,2})\s+([a-zA-Zà-ú]+)(?:\s+(?:del\s+)?(\d{2,4}))?$", text)
    if textual_match:
        d = int(textual_match.group(1))
        month_str = textual_match.group(2).lower()
        raw_year = textual_match.group(3)
        if month_str in MONTHS_MAP:
            m = MONTHS_MAP[month_str]
            if raw_year:
                y = int(raw_year) if len(raw_year) == 4 else (2000 + int(raw_year))
            else:
                y = datetime.date.today().year
            return datetime.date(y, m, d).strftime("%Y-%m-%d")

    raise ValueError(f"Formato data non riconosciuto: '{raw_input}'")


def _prompt_materia_select(default_guess: str = "") -> str:
    """Propone le materie già mappate in config (telegram.topics) come selezione,
    con una voce 'Altro' per materia libera. Degrada a prompt testuale libero se la
    config non è disponibile, topics è vuoto, questionary fallisce, o non siamo in un TTY."""
    try:
        from rt.core.config import load_config
        topic_keys = sorted(load_config().telegram.topics.keys())
    except Exception:
        topic_keys = []

    ALTRO = "➕ Altro (nuova materia)"
    if topic_keys:
        try:
            import questionary
            default_choice = default_guess.upper() if default_guess.upper() in topic_keys else None
            selection = questionary.select("Materia:", choices=topic_keys + [ALTRO], default=default_choice).ask()
            if selection is None:
                print(f"\nOperazione annullata dall'utente.")
                sys.exit(0)
            if selection != ALTRO:
                return selection
        except Exception:
            pass
    return prompt_clean("Materia (es. BIOINFORMATICA, BIOCHIMICA)", default=default_guess)


def guess_subject_from_filename(filename: str) -> str:
    """Tenta di dedurre la materia dal nome del file audio se non è generico."""
    base = os.path.splitext(filename)[0]
    m = re.match(r"^(?:\[[^\]]+\]\s*)?([a-zA-Zà-ú0-9_]+)", base)
    if m:
        guess = m.group(1).strip().upper()
        if guess not in ("AUDIO", "REC", "RECORDING", "LEZIONE", "REGISTRAZIONE", "VOICE", "NOTA"):
            return guess
    return ""


def sanitize_filename_part(text: str) -> str:
    """Rimuove caratteri non consentiti nei nomi dei file su macOS/Unix."""
    return text.replace("/", "-").replace(":", "-").strip()


def generate_deterministic_mock_asr(
    audio_path: str,
    date_val: str,
    materia_val: str,
    argomenti_val: str,
    target_folder: str
) -> Tuple[str, str]:
    """
    Genera una trascrizione ASR mock deterministica offline a costo zero,
    senza invocare macparakeet-cli, adatta a validare l'intera pipeline E2E.
    """
    json_path = os.path.join(target_folder, "trascritto grezzo.json")
    md_path = os.path.join(target_folder, "trascritto grezzo.md")

    argomenti_text_mock = argomenti_val if argomenti_val else "argomenti da definire"

    # Creiamo 4 segmenti realistici coerenti con la materia e gli argomenti
    mock_segments = [
        {
            "id": 1,
            "seek": 0,
            "start": 0,
            "end": 8500,
            "text": f"Buongiorno a tutti. Oggi iniziamo la lezione di {materia_val.lower()} trattando {argomenti_text_mock.lower()}."
        },
        {
            "id": 2,
            "seek": 0,
            "start": 8500,
            "end": 24000,
            "text": f"Nel dettaglio analizzeremo i meccanismi molecolari e i principi fondamentali che regolano questo processo biologico."
        },
        {
            "id": 3,
            "seek": 24000,
            "start": 24000,
            "end": 45000,
            "text": f"È opportuno osservare che la reazione avviene in condizioni fisiologiche precise con l'intervento di specifici cofattori enzimatici."
        },
        {
            "id": 4,
            "seek": 45000,
            "start": 45000,
            "end": 62000,
            "text": f"In conclusione, questo passaggio metabolico si rivela essenziale per il bilancio energetico e l'omeostasi cellulare complessiva."
        }
    ]

    mock_json_payload = {
        "text": " ".join(s["text"] for s in mock_segments),
        "segments": mock_segments,
        "language": "it"
    }

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(mock_json_payload, f, ensure_ascii=False, indent=2)

    # Trascritto Markdown derivato
    md_lines = [
        "---",
        f"data: '{date_val}'",
        f"materia: '{materia_val}'",
        f"argomenti: '{argomenti_val}'",
        f"file_audio: '{os.path.basename(audio_path)}'",
        "modello: 'mock-asr'",
        f"data_trascrizione: '{datetime.datetime.now().isoformat()}'",
        "fase: trascritto_grezzo",
        "stato: pronto_per_rielaborazione",
        "---",
        "",
        "# Trascritto Grezzo (Mock ASR)",
        ""
    ]
    for s in mock_segments:
        start_min = int(s["start"] // 60000)
        start_sec = int((s["start"] % 60000) // 1000)
        end_min = int(s["end"] // 60000)
        end_sec = int((s["end"] % 60000) // 1000)
        tc = f"{start_min:02d}:{start_sec:02d} - {end_min:02d}:{end_sec:02d}"
        md_lines.append(f"**[{tc}]** {s['text']}\n")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))

    return json_path, md_path


def _run_transcribe_with_spinner(cmd: List[str], label: str) -> subprocess.CompletedProcess:
    console = Console()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    start = time.monotonic()
    with console.status(f"[cyan]{label}...", spinner="dots") as status:
        while proc.poll() is None:
            elapsed = int(time.monotonic() - start)
            status.update(f"[cyan]{label}... ({elapsed}s)")
            time.sleep(0.5)
    stdout, stderr = proc.communicate()
    return subprocess.CompletedProcess(cmd, proc.returncode, stdout=stdout, stderr=stderr)


def run_setup(
    audio: Union[str, List[str]],
    date: Optional[str] = None,
    materia: Optional[str] = None,
    argomenti: Optional[str] = None,
    dest_dir: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    skip_transcribe: bool = False,
    force: bool = False,
    mock_asr: bool = False,
    interactive: bool = True,
    on_progress: Optional[Callable[[str], None]] = None
) -> Dict[str, Any]:
    """
    Esegue l'ingest audio e il setup strutturato della lezione.
    Garantisce:
    - Controllo cartella esistente e protezione dati (review_decisions.json non viene mai distrutto)
    - Hard-fail se macparakeet-cli o l'export ASR fallisce
    - Inizializzazione pulita dei soli artefatti necessari (audio, info.yaml, trascritto grezzo.json, trascritto grezzo.md)
    - Gestione coerente di --skip-transcribe (stato METADATA_ONLY)
    - Supporto a file audio singolo o lista di file audio (concatenazione deterministica con offset temporale cumulativo)
    """
    # 1. Normalizzazione lista audio
    if not model:
        model = DEFAULT_MODEL
    audio_list = [audio] if isinstance(audio, str) else list(audio)
    cleaned_audios = [clean_input_path(a) for a in audio_list if a]

    if not cleaned_audios:
        if interactive and sys.stdin.isatty():
            raw_audio = prompt_clean("File audio (trascina il file qui o inserisci il percorso)")
            cleaned_audios = [clean_input_path(raw_audio)]
        else:
            raise SetupError("Nessun file audio specificato.")

    # Validazione esistenza file audio
    for a in cleaned_audios:
        if not os.path.isfile(a):
            raise SetupError(f"File audio non trovato: '{a}'")

    primary_audio = cleaned_audios[0]
    primary_audio_name = os.path.basename(primary_audio)
    audio_dir = os.path.dirname(os.path.abspath(primary_audio))

    # 2. Risoluzione Metadati (Data, Materia, Argomenti)
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    date_val = ""
    if date:
        try:
            date_val = parse_flexible_date(date)
        except ValueError as e:
            if not interactive or not sys.stdin.isatty():
                raise SetupError(str(e))

    while not date_val:
        if interactive and sys.stdin.isatty():
            raw_date = prompt_clean("Data lezione (es. '26 sett 2025', '3 marzo 2024')", default=today_str)
            try:
                date_val = parse_flexible_date(raw_date)
            except ValueError:
                print(f"  {RED}Formato data non valido.{RESET}")
        else:
            date_val = today_str

    # Materia
    guess_subject = guess_subject_from_filename(primary_audio_name)
    materia_val = materia.strip() if materia else ""
    while not materia_val:
        if interactive and sys.stdin.isatty():
            materia_val = _prompt_materia_select(default_guess=guess_subject)
        else:
            materia_val = guess_subject if guess_subject else "LEZIONE"
    materia_val = sanitize_filename_part(materia_val.upper())

    # Argomenti (opzionale: se lasciato vuoto, nessun argomento viene registrato né mostrato all'LLM)
    argomenti_val = sanitize_filename_part(argomenti.strip()) if argomenti and argomenti.strip() else ""

    # 3. Risoluzione cartella di destinazione
    if dest_dir:
        clean_dest = clean_input_path(dest_dir)
        if not clean_dest:
            default_base = audio_dir if (audio_dir and os.path.isdir(audio_dir)) else os.getcwd()
        elif os.path.isfile(clean_dest):
            raise SetupError(
                f"La directory di destinazione specificata '{clean_dest}' è un file, non una directory."
            )
        else:
            default_base = clean_dest
            try:
                os.makedirs(default_base, exist_ok=True)
            except OSError as e:
                raise SetupError(
                    f"Impossibile creare la directory di destinazione '{default_base}': {e}"
                )
    else:
        default_base = audio_dir if (audio_dir and os.path.isdir(audio_dir)) else os.getcwd()

    folder_name = f"[{date_val}] {materia_val}" + (f" - {argomenti_val}" if argomenti_val else "")
    target_folder_path = os.path.join(default_base, folder_name)

    # 4. CONTROLLO DI SICUREZZA CARTELLA ESISTENTE (Parte Q)
    if os.path.isdir(target_folder_path):
        from rt.core.lesson_paths import lesson_path
        existing_info = lesson_path(target_folder_path, "info.yaml")
        existing_decisions = lesson_path(target_folder_path, "review_decisions.json")
        existing_draft = lesson_path(target_folder_path, "draft.json")
        existing_rielab = lesson_path(target_folder_path, "rielaborato.md")

        has_protected_work = any(os.path.isfile(p) for p in [existing_decisions, existing_draft, existing_rielab])

        if has_protected_work and not force:
            raise SetupError(
                f"La cartella '{target_folder_path}' esiste già e contiene una lezione RT con avanzamenti "
                f"o decisioni umane protette. Operazione rifiutata per prevenire perdite di dati. "
                f"Usa il flag --force per confermare la ripreparazione."
            )
        elif os.path.isfile(existing_info) and not force:
            raise SetupError(
                f"La cartella '{target_folder_path}' è già inizializzata come lezione RT. "
                f"Usa --force per sovrascrivere o avvia 'rt run {target_folder_path}'."
            )

    os.makedirs(target_folder_path, exist_ok=True)
    if on_progress:
        on_progress(f"✔ Cartella lezione: {target_folder_path}")
    now_iso = datetime.datetime.now().isoformat()

    # 5. ESECUZIONE TRASCRIZIONE ASR
    json_path = os.path.join(target_folder_path, "trascritto grezzo.json")
    md_path = os.path.join(target_folder_path, "trascritto grezzo.md")

    if mock_asr:
        # Mock ASR deterministico offline
        json_path, md_path = generate_deterministic_mock_asr(
            audio_path=primary_audio,
            date_val=date_val,
            materia_val=materia_val,
            argomenti_val=argomenti_val,
            target_folder=target_folder_path
        )
        current_state = "setup_completato"
        current_status = "pronto_per_rielaborazione"

    elif not skip_transcribe:
        parakeet_bin = find_macparakeet_binary()
        if not parakeet_bin:
            raise SetupError(
                "macparakeet-cli non trovato. Assicurati che sia installato con 'brew install moona3k/tap/macparakeet-cli'."
            )

        if on_progress:
            on_progress("\n[2/9] MACPARAKEET TRANSCRIPTION (ASR Timecoded)...")

        # Se sono presenti file audio multipli, gestiamo la concatenazione deterministica con offset cumulativo
        all_segments_combined = []
        cumulative_offset_ms = 0.0
        combined_text_parts = []

        for audio_idx, aud_file in enumerate(cleaned_audios, start=1):
            aud_abs = os.path.abspath(aud_file)

            cmd_json = [
                parakeet_bin, "transcribe",
                "--format", "json",
            ]
            if model:
                model_param = model.replace("parakeet-", "") if model.startswith("parakeet-") else model
                cmd_json.extend(["--parakeet-model", model_param])
            cmd_json.append(aud_abs)

            # HARD-FAIL CHECK: se macparakeet-cli fallisce, il setup si interrompe immediatamente
            res_json = _run_transcribe_with_spinner(cmd_json, "Trascrizione macparakeet-cli (JSON)")
            
            raw_data = None
            if res_json.stdout and res_json.stdout.strip():
                try:
                    raw_data = json.loads(res_json.stdout)
                except Exception:
                    pass

            if res_json.returncode != 0 or raw_data is None:
                raise SetupError(
                    f"Trascrizione macparakeet-cli JSON fallita per '{os.path.basename(aud_file)}' "
                    f"(codice uscita: {res_json.returncode}). Dettagli errore: {res_json.stderr.strip()}"
                )

            segs = raw_data.get("transcriptSegments", raw_data.get("segments", []))
            max_seg_end = 0.0
            for s in segs:
                s_copy = dict(s)
                start_val = float(s_copy.get("startMs", s_copy.get("start", 0)))
                end_val = float(s_copy.get("endMs", s_copy.get("end", 0)))
                s_copy["startMs"] = start_val + cumulative_offset_ms
                s_copy["endMs"] = end_val + cumulative_offset_ms
                s_copy["start"] = s_copy["startMs"]
                s_copy["end"] = s_copy["endMs"]
                all_segments_combined.append(s_copy)
                if s_copy["endMs"] > max_seg_end:
                    max_seg_end = s_copy["endMs"]

            raw_txt = raw_data.get("rawTranscript", raw_data.get("text"))
            if raw_txt:
                combined_text_parts.append(raw_txt)

            cumulative_offset_ms = max_seg_end

        # Salvataggio deterministico unificato del JSON primario
        final_mw_payload = {
            "rawTranscript": " ".join(combined_text_parts),
            "text": " ".join(combined_text_parts),
            "transcriptSegments": all_segments_combined,
            "segments": all_segments_combined,
            "language": "it"
        }
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(final_mw_payload, f, ensure_ascii=False, indent=2)

        # Generazione trascritto grezzo.md con frontmatter
        md_frontmatter = f"""---
data: '{date_val}'
materia: '{materia_val}'
argomenti: '{argomenti_val}'
cartella: '{folder_name}'
file_audio: '{primary_audio_name}'
modello: '{model}'
data_trascrizione: '{datetime.datetime.now().isoformat()}'
fase: trascritto_grezzo
stato: pronto_per_rielaborazione
---

"""
        md_body_lines = []
        for s in all_segments_combined:
            st_ms = float(s.get("startMs", s.get("start", 0)))
            en_ms = float(s.get("endMs", s.get("end", 0)))
            tc = f"{int(st_ms//60000):02d}:{int((st_ms%60000)//1000):02d} - {int(en_ms//60000):02d}:{int((en_ms%60000)//1000):02d}"
            md_body_lines.append(f"**[{tc}]** {s.get('text', '').strip()}\n")

        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_frontmatter + "\n".join(md_body_lines))

        current_state = "setup_completato"
        current_status = "pronto_per_rielaborazione"

    else:
        # Trascrizione saltata (--skip-transcribe): stato rigoroso METADATA_ONLY (Parte P)
        yaml_frontmatter = f"""---
data: '{date_val}'
materia: '{materia_val}'
argomenti: '{argomenti_val}'
cartella: '{folder_name}'
file_audio: '{primary_audio_name}'
stato: in_attesa_di_trascrizione
---

"""
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(yaml_frontmatter)

        current_state = "metadata_only"
        current_status = "in_attesa_di_trascrizione"

    # 6. Copia protetta dei file audio nella cartella della lezione
    for aud_file in cleaned_audios:
        dest_audio = os.path.join(target_folder_path, os.path.basename(aud_file))
        if os.path.abspath(aud_file) != os.path.abspath(dest_audio):
            shutil.copy2(aud_file, dest_audio)

    # 7. Creazione atomica di info.yaml (Parte N)
    info_yaml_path = os.path.join(target_folder_path, "info.yaml")
    info_content = f"""data: '{date_val}'
materia: {materia_val}
argomenti: {argomenti_val}
cartella: '{folder_name}'
file_audio: {primary_audio_name}
creato_il: '{now_iso}'
fase_corrente: {current_state}
stato: {current_status}
"""
    tmp_info = info_yaml_path + ".tmp"
    with open(tmp_info, "w", encoding="utf-8") as f:
        f.write(info_content)
    os.replace(tmp_info, info_yaml_path)

    return {
        "status": current_state,
        "lesson_dir": target_folder_path,
        "folder_name": folder_name,
        "date": date_val,
        "materia": materia_val,
        "argomenti": argomenti_val,
        "audio_files": [os.path.join(target_folder_path, os.path.basename(a)) for a in cleaned_audios],
        "info_yaml": info_yaml_path,
        "trascritto_json": json_path if os.path.isfile(json_path) else None,
        "trascritto_md": md_path
    }


def configure_setup_parser(parser: Any) -> Any:
    """Configura la definizione unificata degli argomenti CLI per il comando setup."""
    parser.add_argument("audio", nargs="*", help="Uno o più percorsi di file audio da trascrivere")
    parser.add_argument("-d", "--date", help="Data della lezione (es. '2026-09-05', '26 sett 2025', '3 marzo 2024')")
    parser.add_argument("-m", "--materia", help="Nome della materia (es. BIOCHIMICA, BIOINFORMATICA)")
    parser.add_argument("-a", "--argomenti", help="Argomenti trattati (es. 'Trigliceridi e beta-ossidazione')")
    parser.add_argument("-o", "--dest-dir", help="Directory base di destinazione")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Modello macparakeet-cli (default: {DEFAULT_MODEL})")
    parser.add_argument("--skip-transcribe", action="store_true", help="Salta trascrizione e crea segnaposto METADATA_ONLY")
    parser.add_argument("--force", action="store_true", help="Forza la riscrittura della cartella se già esistente")
    parser.add_argument("--mock", action="store_true", help="Usa mock deterministico ASR per test offline")
    return parser


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Workflow accademico RT: Setup cartella, trascrizione macparakeet-cli e metadati YAML."
    )
    configure_setup_parser(parser)
    args = parser.parse_args()

    try:
        res = run_setup(
            audio=args.audio,
            date=args.date,
            materia=args.materia,
            argomenti=args.argomenti,
            dest_dir=args.dest_dir,
            model=args.model,
            skip_transcribe=args.skip_transcribe,
            force=args.force,
            mock_asr=args.mock,
            interactive=True
        )
        print(f"\n{BOLD}{GREEN}✨ Setup completato con successo!{RESET}")
        print(f"📁 Percorso lezione: {BOLD}{res['lesson_dir']}{RESET}\n")
    except SetupError as se:
        print(f"\n{RED}❌ Errore Setup: {se}{RESET}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
