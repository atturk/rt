"""Ingresso web non interattivo per il setup audio già usato dalla CLI."""
from __future__ import annotations

from pathlib import Path

from rt.pipeline.setup import SetupError, find_macparakeet_binary, is_audio_file, run_setup


def ingest_audio(
    uploaded_file: str | None, root: str, date: str, subject: str,
    topics: str = "", transcribe: bool = True,
) -> str:
    """Crea una lezione nella cartella configurata, senza sovrascriverne altre."""
    if not uploaded_file or not is_audio_file(uploaded_file):
        raise ValueError("Seleziona un file audio supportato (MP3, M4A, WAV, FLAC…).")
    if not Path(root).is_dir():
        raise ValueError("La cartella delle lezioni non esiste.")
    if not subject.strip():
        raise ValueError("Inserisci la materia della lezione.")
    if not date.strip():
        raise ValueError("Inserisci la data della lezione.")
    if transcribe and not find_macparakeet_binary():
        raise ValueError("macparakeet-cli non trovato: installalo oppure disattiva la trascrizione immediata.")

    try:
        result = run_setup(
            audio=uploaded_file, date=date, materia=subject, argomenti=topics,
            dest_dir=root, interactive=False, skip_transcribe=not transcribe,
            force=False,
        )
    except SetupError as exc:
        raise ValueError(str(exc)) from exc
    return result["lesson_dir"]
