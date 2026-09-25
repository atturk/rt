"""
tests/golden_support.py
Scenari "golden" della pipeline completa in modalità mock (RT4-A0).

Ogni scenario esegue la CLI reale ('rt run ... --mock') in un sottoprocesso isolato, con
stdin scriptato, e raccoglie l'output del terminale e i file finali della lezione dopo
averli normalizzati (percorsi temporanei, timestamp e hash variabili). Il risultato viene
confrontato con le copie salvate in tests/golden/ da tests/test_golden_run.py e rigenerato
in modo esplicito da scripts/update_golden.py.
"""
import os
import re
import shutil
import subprocess
import sys
from typing import Dict, List, Tuple

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOLDEN_DIR = os.path.join(PROJECT_ROOT, "tests", "golden")
AUDIO_FIXTURE = os.path.join(PROJECT_ROOT, "tests", "fixtures", "demo_lecture.wav")

LESSON_NAME = "[2026-09-05] BIOCHIMICA - Lipidi"

# File della lezione confrontati (percorsi relativi alla cartella lezione). llm_debug.log e
# telemetry_summary.json sono diagnostici e restano fuori; l'audio è una copia della fixture.
COMPARED_FILES = [
    "info.yaml",
    "trascritto grezzo.md",
    "trascritto grezzo.json",
    "Errori concettuali.md",
    "[2026-09-05] BIOCHIMICA - Lezione Accademica Rielaborata.md",
    "_state/manifest.json",
    "_state/segments.json",
    "_state/transcript_normalized.md",
    "_state/outline.json",
    "_state/draft.json",
    "_state/science_issues.json",
    "_state/review_decisions.json",
    "_state/rielaborato.md",
    "_state/pre-elaborato.md",
]

TRANSCRIPT_MD = """---
data: '2026-09-05'
materia: BIOCHIMICA
---

*00:02*
Allora ieri abbiamo visto tutti questione, abbiamo visto

*00:14*
I lipidi sono depositati nel tessuto adiposo.

*00:22*
Quando c'è necessità di degradarli entra in gioco la lipasi.

*00:30*
licorolo finansi converte il glicerolo libero in glicerolo 3 fosfato.

*00:45-00:55*
Nei muscoli lisci ci sono sarcomeri per estrarre energia.

*01:00-01:10*
La via prosegue con la beta-ossidazione mitocondriale degli acidi grassi.
"""

INFO_YAML = """data: '2026-09-05'
materia: BIOCHIMICA
argomenti: Lipidi
cartella: '[2026-09-05] BIOCHIMICA - Lipidi'
file_audio: lezione.m4a
fase_corrente: setup_completato
stato: setup_completato
"""

_ISO_TS = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:\d{2}|Z)?")
_SHA256 = re.compile(r"\b[0-9a-f]{64}\b")


def normalize_text(text: str, root: str) -> str:
    """Rende confrontabile un testo: percorso temporaneo, timestamp ISO e hash SHA-256."""
    for variant in {root, os.path.realpath(root)}:
        text = text.replace(variant, "<ROOT>")
    text = text.replace("\\", "/") if os.name == "nt" else text
    text = _ISO_TS.sub("<TS>", text)
    text = _SHA256.sub("<SHA256>", text)
    return text


def _run_cli(argv: List[str], cwd: str, stdin: str) -> Tuple[int, str, str]:
    env = dict(os.environ)
    # Nessun contatto con Telegram reale anche se la macchina ha un .env configurato.
    env["RT_TELEGRAM_BOT_TOKEN"] = "test-disabled-token"
    env["RT_TELEGRAM_CHAT_ID"] = "0"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = PROJECT_ROOT + os.pathsep + env.get("PYTHONPATH", "")
    env.pop("COLUMNS", None)
    proc = subprocess.run(
        [sys.executable, "-c", "from rt.cli import main; main()"] + argv,
        cwd=cwd,
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=300,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _collect_files(lesson_dir: str, root: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for rel in COMPARED_FILES:
        path = os.path.join(lesson_dir, rel)
        if not os.path.isfile(path):
            out[rel] = "<MISSING>"
            continue
        with open(path, "r", encoding="utf-8") as f:
            out[rel] = normalize_text(f.read(), root)
    return out


def _cli_record(code: int, stdout: str, stderr: str, root: str) -> str:
    return (
        f"exit_code: {code}\n"
        f"--- stdout ---\n{normalize_text(stdout, root)}"
        f"--- stderr ---\n{normalize_text(stderr, root)}"
    )


def scenario_audio_full(root: str) -> Dict[str, str]:
    """Audio mock → setup → prepare → outline (approvata da stdin) → rewrite → review con
    auto-accept → build; poi seconda esecuzione sulla cartella (tutte le fasi in SKIP)."""
    shutil.copy(AUDIO_FIXTURE, os.path.join(root, "demo_lecture.wav"))
    out_dir = os.path.join(root, "out")
    first = _run_cli(
        ["run", "demo_lecture.wav", "--mock", "--auto-accept", "--with-review",
         "--channel", "terminal", "--no-rename",
         "-d", "2026-09-05", "-m", "BIOCHIMICA", "-a", "Lipidi", "-o", out_dir],
        cwd=root, stdin="a\n",
    )
    lesson_dir = os.path.join(out_dir, LESSON_NAME)
    second = _run_cli(
        ["run", lesson_dir, "--mock", "--auto-accept", "--with-review",
         "--channel", "terminal", "--no-rename"],
        cwd=root, stdin="",
    )
    result = {
        "cli_first_run.txt": _cli_record(*first, root),
        "cli_second_run.txt": _cli_record(*second, root),
    }
    result.update({f"lesson/{k}": v for k, v in _collect_files(lesson_dir, root).items()})
    return result


def scenario_folder_no_review(root: str) -> Dict[str, str]:
    """Cartella lezione già inizializzata con trascritto Markdown → run senza review, con
    una richiesta di modifica dell'outline e poi l'approvazione dal fallback non-TTY."""
    lesson_dir = os.path.join(root, LESSON_NAME)
    os.makedirs(lesson_dir)
    with open(os.path.join(lesson_dir, "info.yaml"), "w", encoding="utf-8") as f:
        f.write(INFO_YAML)
    with open(os.path.join(lesson_dir, "trascritto grezzo.md"), "w", encoding="utf-8") as f:
        f.write(TRANSCRIPT_MD)
    run = _run_cli(
        ["run", lesson_dir, "--mock", "--channel", "terminal", "--no-rename"],
        cwd=root, stdin="m\nDividi in due unità\na\n",
    )
    result = {"cli_run.txt": _cli_record(*run, root)}
    files = _collect_files(lesson_dir, root)
    result.update({f"lesson/{k}": v for k, v in files.items() if v != "<MISSING>"})
    return result


SCENARIOS = {
    "audio_full": scenario_audio_full,
    "folder_no_review": scenario_folder_no_review,
}


def run_scenario(name: str, root: str) -> Dict[str, str]:
    return SCENARIOS[name](root)


def golden_path(name: str, rel: str) -> str:
    return os.path.join(GOLDEN_DIR, name, rel)


def load_golden(name: str) -> Dict[str, str]:
    base = os.path.join(GOLDEN_DIR, name)
    out: Dict[str, str] = {}
    for dirpath, _dirs, files in os.walk(base):
        for fn in files:
            path = os.path.join(dirpath, fn)
            rel = os.path.relpath(path, base).replace(os.sep, "/")
            with open(path, "r", encoding="utf-8", newline="") as f:
                out[rel] = f.read()
    return out


def write_golden(name: str, data: Dict[str, str]) -> None:
    base = os.path.join(GOLDEN_DIR, name)
    if os.path.isdir(base):
        shutil.rmtree(base)
    for rel, content in data.items():
        path = os.path.join(base, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(content)

