"""
rt.core.lesson_paths
Punto di verità unico per i percorsi dei file interni a una cartella di lezione.
Separa i pochi file "deliverable" (quelli che l'utente apre/legge/condivide) dallo
stato interno della pipeline, che finisce in una sottocartella dedicata `_state/`.

Retrocompatibilità con le lezioni già costruite prima di questa riorganizzazione:
per un file di stato, se esiste già alla radice (layout piatto di una lezione
vecchia) si continua a usare quella posizione, sia in lettura che in scrittura —
nessuna migrazione automatica, nessuno stato "misto" root/_state per la stessa
lezione. Una lezione mai toccata dal codice vecchio usa da subito `_state/`.
"""
import os
from typing import Set

STATE_SUBDIR = "_state"

# File/cartelle di stato interno della pipeline: mai aperti a mano dall'utente.
# Tutto ciò che NON è in questo insieme resta alla radice della lezione (deliverable),
# comportamento identico a oggi.
_STATE_ENTRIES: Set[str] = {
    "info.yaml",
    "manifest.json",
    "segments.json",
    "draft.json",
    "outline.json",
    "asr_issues.json",
    "science_issues.json",
    "review_decisions.json",
    "recall_questions.json",
    "telegram_recall_session.json",
    "telegram_audio_sent.json",
    "telegram_issue_queue.json",
    "telegram_pending.json",
    "telemetry_summary.json",
    "llm_debug.log",
    "pre-elaborato.md",
    "rielaborato.md",
    "transcript_normalized.md",
    "trascritto grezzo.json",
    "trascritto grezzo.md",
    "segments_raw.json",  # nome legacy, vedi find_raw_transcript_source
    "transcript.json",  # nome legacy, vedi find_raw_transcript_source
    "recall_audio_clips",  # sottocartella cache clip audio, non un singolo file
}


def lesson_path(lesson_dir: str, filename: str) -> str:
    """Risolve il percorso di un file/sottocartella interno a una lezione.

    Deliverable (non in _STATE_ENTRIES): sempre alla radice, comportamento invariato.

    Stato interno (in _STATE_ENTRIES):
    1. Se esiste già alla radice (file o cartella: os.path.exists, non isfile — vale
       anche per recall_audio_clips/) -> radice (lezione vecchia, layout piatto).
    2. Altrimenti -> _state/<filename>, creando la sottocartella se manca (lezione
       nuova, o file mai scritto prima in nessuna delle due posizioni).
    """
    root_path = os.path.join(lesson_dir, filename)
    if filename not in _STATE_ENTRIES:
        return root_path

    if os.path.exists(root_path):
        return root_path

    state_dir = os.path.join(lesson_dir, STATE_SUBDIR)
    os.makedirs(state_dir, exist_ok=True)
    return os.path.join(state_dir, filename)
