"""
rt.core.recall_stt
Trascrizione delle risposte vocali durante l'active recall. Riusa il binario
macparakeet-cli già usato per le lezioni (rt/pipeline/setup.py::find_macparakeet_binary),
adattato a un singolo file breve invece che a una lezione intera.
"""
import json
import os
import subprocess
import tempfile


def transcribe_voice_answer(audio_path: str, stt_engine: str = "macparakeet") -> str:
    """Trascrive un breve file audio (risposta vocale) e ritorna il testo concatenato dei segmenti.

    Solleva un'eccezione chiara se la trascrizione non è possibile (macparakeet-cli non trovato/comando fallito,
    o motore non ancora implementato)."""
    if stt_engine == "macparakeet":
        from rt.pipeline.setup import find_macparakeet_binary

        parakeet_bin = find_macparakeet_binary()
        if not parakeet_bin:
            raise RuntimeError(
                "macparakeet-cli non trovato. Assicurati che sia installato con 'brew install moona3k/tap/macparakeet-cli'."
            )

        tmp_json_fd, tmp_json_path = tempfile.mkstemp(suffix=".json")
        os.close(tmp_json_fd)
        try:
            cmd = [parakeet_bin, "transcribe", "--format", "json", audio_path]
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

            raw_data = None
            if result.stdout and result.stdout.strip():
                try:
                    raw_data = json.loads(result.stdout)
                except Exception:
                    pass

            if raw_data is None and os.path.isfile(tmp_json_path) and os.path.getsize(tmp_json_path) > 0:
                try:
                    with open(tmp_json_path, "r", encoding="utf-8") as f:
                        raw_data = json.load(f)
                except Exception:
                    pass

            if result.returncode != 0 or raw_data is None:
                raise RuntimeError(
                    f"Trascrizione macparakeet-cli fallita (codice uscita: {result.returncode}). Dettagli: {result.stderr.strip()}"
                )

            raw_text = raw_data.get("rawTranscript") or raw_data.get("text")
            if raw_text:
                return raw_text.strip()

            segments = raw_data.get("transcriptSegments", raw_data.get("segments", []))
            text = " ".join(s.get("text", "").strip() for s in segments if s.get("text", "").strip())
            return text.strip()
        finally:
            if os.path.isfile(tmp_json_path):
                try:
                    os.remove(tmp_json_path)
                except Exception:
                    pass

    elif stt_engine == "api":
        raise NotImplementedError("STT via API non ancora configurato, usa macparakeet.")

    else:
        raise ValueError(f"stt_engine non riconosciuto: '{stt_engine}'.")

