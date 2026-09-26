"""
rt.pipeline.setup
Modulo unificato per l'ingest di file audio, trascrizione macparakeet-cli ASR e inizializzazione lezione.
Fornisce funzioni riusabili per la CLI nativa (`rt setup`, `rt run <audio>`).
"""

import os
import sys
import re
import shutil
import tempfile
import json
import subprocess
import datetime
import time
from typing import Dict, Any, List, Optional, Tuple, Union, Callable, Protocol
from pydantic import BaseModel
from rich.console import Console
from rt.storage import fs

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


class MissingSetupFields(SetupError):
    """Mancano metadati obbligatori e nessuno può chiederli (API, worker, stdin non TTY)."""

    def __init__(self, fields: List[str], message: Optional[str] = None):
        self.fields = list(fields)
        super().__init__(message or f"Metadati di setup mancanti: {', '.join(self.fields)}")


class SetupCancelled(SetupError):
    """L'utente ha annullato la raccolta dei metadati (Ctrl+C/EOF su un prompt)."""


class SetupPrompter(Protocol):
    """Chiede all'utente i metadati mancanti. Implementato dalla CLI (rt.cli_prompts);
    ogni metodo può sollevare SetupCancelled."""

    def ask_audio(self) -> str: ...

    def ask_date(self, default: str) -> str: ...

    def invalid_date(self, raw: str) -> None: ...

    def ask_materia(self, default_guess: str) -> str: ...


class SetupRequest(BaseModel):
    """Metadati di setup completi e validati, pronti per l'esecuzione non interattiva."""
    audio: List[str]
    date: str
    materia: str
    argomenti: str = ""


def is_audio_file(path: str) -> bool:
    """Verifica se il percorso corrisponde a un file esistente con estensione audio supportata."""
    if not path or not isinstance(path, str):
        return False
    clean = clean_input_path(path)
    if not fs.isfile(clean):
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
    p = p.replace(r"\ ", " ").replace(r"\(", "(").replace(r"\)", ")").replace(r"\[", "[").replace(r"\]", "]").replace(r"\,", ",")
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
        if fs.exists(c) and os.access(c, os.X_OK):
            return c
    return ""


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

    with fs.open(json_path, "w", encoding="utf-8") as f:
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

    with fs.open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))

    return json_path, md_path


def _run_transcribe_with_spinner(cmd: List[str], label: str) -> subprocess.CompletedProcess:
    console = Console()
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )
    start = time.monotonic()
    last_status_text = label
    with console.status(f"[cyan]{label}...", spinner="dots") as status:
        if proc.stdout:
            while True:
                line = proc.stdout.readline()
                if not line and proc.poll() is not None:
                    break
                if line:
                    line_str = line.strip()
                    if line_str:
                        match = re.search(r"(\d+)%", line_str)
                        if match:
                            pct = match.group(1)
                            last_status_text = f"{label} ({pct}%)"
                        else:
                            last_status_text = f"{label} - {line_str}"
                    elapsed = int(time.monotonic() - start)
                    status.update(f"[cyan]{last_status_text} ({elapsed}s)")
    proc.wait()
    return subprocess.CompletedProcess(cmd, proc.returncode, stdout="", stderr="")


def resolve_setup_request(
    audio: Union[str, List[str], None],
    date: Optional[str] = None,
    materia: Optional[str] = None,
    argomenti: Optional[str] = None,
    prompter: Optional[SetupPrompter] = None,
    strict: bool = False,
) -> SetupRequest:
    """Raccoglie e valida i metadati di setup senza mai leggere da stdin.

    Con un prompter chiede all'utente i campi mancanti o non validi. Senza prompter:
    audio mancante -> MissingSetupFields; data/materia mancanti -> default (oggi, materia
    dedotta dal nome del file o 'LEZIONE'), oppure MissingSetupFields se strict=True.
    """
    audio_list = [audio] if isinstance(audio, str) else list(audio or [])
    cleaned_audios = [clean_input_path(a) for a in audio_list if a]

    if not cleaned_audios:
        if prompter is None:
            raise MissingSetupFields(["audio"], "Nessun file audio specificato.")
        cleaned_audios = [clean_input_path(prompter.ask_audio())]

    for a in cleaned_audios:
        if not fs.isfile(a):
            raise SetupError(f"File audio non trovato: '{a}'")

    missing: List[str] = []

    today_str = datetime.date.today().strftime("%Y-%m-%d")
    date_val = ""
    if date:
        try:
            date_val = parse_flexible_date(date)
        except ValueError as e:
            if prompter is None:
                raise SetupError(str(e))
    while not date_val:
        if prompter is not None:
            raw_date = prompter.ask_date(today_str)
            try:
                date_val = parse_flexible_date(raw_date)
            except ValueError:
                prompter.invalid_date(raw_date)
        elif strict:
            missing.append("date")
            break
        else:
            date_val = today_str

    guess_subject = guess_subject_from_filename(os.path.basename(cleaned_audios[0]))
    materia_val = materia.strip() if materia else ""
    while not materia_val:
        if prompter is not None:
            materia_val = prompter.ask_materia(guess_subject)
        elif strict:
            missing.append("materia")
            break
        else:
            materia_val = guess_subject if guess_subject else "LEZIONE"

    if missing:
        raise MissingSetupFields(missing)

    return SetupRequest(
        audio=cleaned_audios,
        date=date_val,
        materia=sanitize_filename_part(materia_val.upper()),
        # Argomenti opzionali: se vuoti non vengono registrati né mostrati all'LLM.
        argomenti=sanitize_filename_part(argomenti.strip()) if argomenti and argomenti.strip() else "",
    )


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
    on_progress: Optional[Callable[[str], None]] = None,
    prompter: Optional[SetupPrompter] = None,
    strict: bool = False,
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
    # 1-2. Metadati (audio, data, materia, argomenti) validati, eventualmente chiesti al prompter
    if not model:
        model = DEFAULT_MODEL
    request = resolve_setup_request(
        audio, date=date, materia=materia, argomenti=argomenti,
        prompter=prompter if interactive else None, strict=strict,
    )
    cleaned_audios = request.audio
    primary_audio = cleaned_audios[0]
    primary_audio_name = os.path.basename(primary_audio)
    audio_dir = os.path.dirname(os.path.abspath(primary_audio))
    date_val = request.date
    materia_val = request.materia
    argomenti_val = request.argomenti

    # 3. Risoluzione cartella di destinazione
    if dest_dir:
        clean_dest = clean_input_path(dest_dir)
        if not clean_dest:
            default_base = audio_dir if (audio_dir and fs.isdir(audio_dir)) else os.getcwd()
        elif fs.isfile(clean_dest):
            raise SetupError(
                f"La directory di destinazione specificata '{clean_dest}' è un file, non una directory."
            )
        else:
            default_base = clean_dest
            try:
                fs.makedirs(default_base, exist_ok=True)
            except OSError as e:
                raise SetupError(
                    f"Impossibile creare la directory di destinazione '{default_base}': {e}"
                )
    else:
        default_base = audio_dir if (audio_dir and fs.isdir(audio_dir)) else os.getcwd()

    folder_name = f"[{date_val}] {materia_val}" + (f" - {argomenti_val}" if argomenti_val else "")
    target_folder_path = os.path.join(default_base, folder_name)

    # 4. CONTROLLO DI SICUREZZA CARTELLA ESISTENTE (Parte Q)
    if fs.isdir(target_folder_path):
        from rt.core.lesson_paths import lesson_path
        existing_info = lesson_path(target_folder_path, "info.yaml")
        existing_decisions = lesson_path(target_folder_path, "review_decisions.json")
        existing_draft = lesson_path(target_folder_path, "draft.json")
        existing_rielab = lesson_path(target_folder_path, "rielaborato.md")

        has_protected_work = any(fs.isfile(p) for p in [existing_decisions, existing_draft, existing_rielab])

        if has_protected_work and not force:
            raise SetupError(
                f"La cartella '{target_folder_path}' esiste già e contiene una lezione RT con avanzamenti "
                f"o decisioni umane protette. Operazione rifiutata per prevenire perdite di dati. "
                f"Usa il flag --force per confermare la ripreparazione."
            )
        elif fs.isfile(existing_info) and not force:
            raise SetupError(
                f"La cartella '{target_folder_path}' è già inizializzata come lezione RT. "
                f"Usa --force per sovrascrivere o avvia 'rt run {target_folder_path}'."
            )

    if fs.is_db_lesson(target_folder_path) or (not os.path.isdir(target_folder_path) and fs.new_lessons_use_db()):
        # Lezione nel database: nessuna cartella, i media vanno nella cartella media di RT.
        target_folder_path = fs.create_db_lesson(target_folder_path)
        if on_progress:
            on_progress(f"✔ Lezione nel database: {folder_name}")
    else:
        fs.makedirs(target_folder_path, exist_ok=True)
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
        from rt.core.config import load_config, load_env_file
        from rt.core.custom_stt import transcribe_custom

        stt = load_config().transcription
        use_custom_stt = stt.engine == "custom"
        parakeet_bin = None if use_custom_stt else find_macparakeet_binary()
        if not use_custom_stt and not parakeet_bin:
            raise SetupError(
                "macparakeet-cli non trovato. Assicurati che sia installato con 'brew install moona3k/tap/macparakeet-cli'."
            )
        if use_custom_stt:
            model = stt.model or ""
            load_env_file()

        if on_progress:
            on_progress("\n[2/9] TRASCRIZIONE STT CUSTOM..." if use_custom_stt
                        else "\n[2/9] MACPARAKEET TRANSCRIPTION (ASR Timecoded)...")

        # Se sono presenti file audio multipli, gestiamo la concatenazione deterministica con offset cumulativo
        all_segments_combined = []
        all_word_timestamps_combined = []
        cumulative_offset_ms = 0.0
        cumulative_word_offset = 0
        combined_text_parts = []

        temp_dir = tempfile.mkdtemp(prefix="rt_stt_")
        try:
            for audio_idx, aud_file in enumerate(cleaned_audios, start=1):
                aud_abs = os.path.abspath(aud_file)
                temp_audio_dir = os.path.join(temp_dir, f"audio_{audio_idx}")
                fs.makedirs(temp_audio_dir, exist_ok=True)

                if use_custom_stt:
                    try:
                        raw_data = transcribe_custom(aud_abs, stt.base_url, stt.model, stt.timeout_seconds)
                    except (RuntimeError, ValueError) as exc:
                        raise SetupError(str(exc)) from None
                else:
                    cmd_json = [
                        parakeet_bin, "transcribe", "--format", "json", "--no-diarize",
                        "--output-dir", temp_audio_dir,
                    ]
                    if model:
                        model_param = model.replace("parakeet-", "") if model.startswith("parakeet-") else model
                        cmd_json.extend(["--parakeet-model", model_param])
                    cmd_json.append(aud_abs)
                    res_json = _run_transcribe_with_spinner(cmd_json, "Trascrizione macparakeet-cli (JSON)")
                    json_files = [f for f in fs.listdir(temp_audio_dir) if f.endswith(".json")]
                    raw_data = None
                    if json_files:
                        try:
                            with fs.open(os.path.join(temp_audio_dir, json_files[0]), "r", encoding="utf-8") as f:
                                raw_data = json.load(f)
                        except (OSError, ValueError):
                            raw_data = None
                    if res_json.returncode != 0 or raw_data is None:
                        raise SetupError(
                            f"Trascrizione macparakeet-cli JSON fallita per '{os.path.basename(aud_file)}' "
                            f"(codice uscita: {res_json.returncode}). Dettagli errore: {res_json.stderr.strip() if res_json.stderr else ''}"
                        )

                word_ts = raw_data.get("wordTimestamps", [])
                if isinstance(word_ts, list):
                    for wt in word_ts:
                        if isinstance(wt, dict):
                            wt_copy = dict(wt)
                            if "startMs" in wt_copy and isinstance(wt_copy["startMs"], (int, float)):
                                wt_copy["startMs"] = float(wt_copy["startMs"]) + cumulative_offset_ms
                            if "endMs" in wt_copy and isinstance(wt_copy["endMs"], (int, float)):
                                wt_copy["endMs"] = float(wt_copy["endMs"]) + cumulative_offset_ms
                            all_word_timestamps_combined.append(wt_copy)

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
                    if "wordRange" in s_copy and isinstance(s_copy["wordRange"], dict) and cumulative_word_offset > 0:
                        wr = dict(s_copy["wordRange"])
                        if "startIndex" in wr and isinstance(wr["startIndex"], int):
                            wr["startIndex"] += cumulative_word_offset
                        if "endIndexExclusive" in wr and isinstance(wr["endIndexExclusive"], int):
                            wr["endIndexExclusive"] += cumulative_word_offset
                        s_copy["wordRange"] = wr
                    all_segments_combined.append(s_copy)
                    if s_copy["endMs"] > max_seg_end:
                        max_seg_end = s_copy["endMs"]

                if isinstance(word_ts, list):
                    cumulative_word_offset += len(word_ts)

                raw_txt = raw_data.get("rawTranscript", raw_data.get("text"))
                if raw_txt:
                    combined_text_parts.append(raw_txt)

                cumulative_offset_ms = max_seg_end
        finally:
            fs.rmtree(temp_dir, ignore_errors=True)

        # Salvataggio deterministico unificato del JSON primario
        final_mw_payload = {
            "rawTranscript": " ".join(combined_text_parts),
            "text": " ".join(combined_text_parts),
            "transcriptSegments": all_segments_combined,
            "segments": all_segments_combined,
            "language": "it"
        }
        if all_word_timestamps_combined:
            final_mw_payload["wordTimestamps"] = all_word_timestamps_combined
        with fs.open(json_path, "w", encoding="utf-8") as f:
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

        with fs.open(md_path, "w", encoding="utf-8") as f:
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
        with fs.open(md_path, "w", encoding="utf-8") as f:
            f.write(yaml_frontmatter)

        current_state = "metadata_only"
        current_status = "in_attesa_di_trascrizione"

    # 6. Copia protetta dei file audio nella cartella della lezione
    for aud_file in cleaned_audios:
        dest_audio = os.path.join(target_folder_path, os.path.basename(aud_file))
        if os.path.abspath(aud_file) != os.path.abspath(dest_audio):
            fs.copy2(aud_file, dest_audio)

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
    with fs.open(tmp_info, "w", encoding="utf-8") as f:
        f.write(info_content)
    fs.replace(tmp_info, info_yaml_path)
    if fs.is_db_lesson(target_folder_path):
        from rt.db.sync import dual_write_lesson
        dual_write_lesson(target_folder_path)

    return {
        "status": current_state,
        "lesson_dir": target_folder_path,
        "folder_name": folder_name,
        "date": date_val,
        "materia": materia_val,
        "argomenti": argomenti_val,
        "audio_files": [os.path.join(target_folder_path, os.path.basename(a)) for a in cleaned_audios],
        "info_yaml": info_yaml_path,
        "trascritto_json": json_path if fs.isfile(json_path) else None,
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
