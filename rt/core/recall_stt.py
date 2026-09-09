"""
rt.core.recall_stt
Trascrizione delle risposte vocali durante l'active recall. Riusa il binario
MacWhisper (mw) già usato per le lezioni (rt/pipeline/setup.py::find_mw_binary),
adattato a un singolo file breve invece che a una lezione intera.
"""
import json
import os
import subprocess
import tempfile


def transcribe_voice_answer(audio_path: str, stt_engine: str = "macwhisper") -> str:
    """Trascrive un breve file audio (risposta vocale) e ritorna il testo concatenato dei segmenti.

    Solleva un'eccezione chiara se la trascrizione non è possibile (mw non trovato/comando fallito,
    o motore non ancora implementato)."""
    if stt_engine == "macwhisper":
        from rt.pipeline.setup import find_mw_binary

        mw_bin = find_mw_binary()
        if not mw_bin:
            raise RuntimeError(
                "MacWhisper CLI ('mw') non trovato. Assicurati che MacWhisper sia installato in /Applications/MacWhisper.app."
            )

        tmp_json_fd, tmp_json_path = tempfile.mkstemp(suffix=".json")
        os.close(tmp_json_fd)
        try:
            cmd = [mw_bin, "transcribe", "--format", "json", "--overwrite", "-o", tmp_json_path, audio_path]
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if result.returncode != 0 or not os.path.isfile(tmp_json_path) or os.path.getsize(tmp_json_path) == 0:
                raise RuntimeError(
                    f"Trascrizione MacWhisper fallita (codice uscita: {result.returncode}). Dettagli: {result.stderr.strip()}"
                )
            with open(tmp_json_path, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
            segments = raw_data.get("segments", [])
            text = " ".join(s.get("text", "").strip() for s in segments if s.get("text", "").strip())
            return text.strip()
        finally:
            if os.path.isfile(tmp_json_path):
                try:
                    os.remove(tmp_json_path)
                except Exception:
                    pass

    elif stt_engine == "api":
        raise NotImplementedError("STT via API non ancora configurato, usa MacWhisper.")

    else:
        raise ValueError(f"stt_engine non riconosciuto: '{stt_engine}'.")
