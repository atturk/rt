#!/usr/bin/env python3
"""
scripts/stt_smoke.py
Prova vera del motore Parakeet ONNX (CI dell'app): scarica il modello se manca
(RT_STT_MODELS_DIR), trascrive un audio con voce sintetica (say sul Mac, System.Speech su Windows) e
controlla parole attese, tempi e confidenza. Si lancia con il Python dell'app installata:

    <python dell'app> scripts/stt_smoke.py <cartella del codice dell'app> <audio> parola1,parola2
"""
import os
import sys
import time

root, audio, expected = os.path.abspath(sys.argv[1]), sys.argv[2], sys.argv[3].split(",")
sys.path.insert(0, root)

from rt.core.onnx_stt import MODEL_LABEL, transcribe_onnx  # noqa: E402

started = time.monotonic()
percents = []
result = transcribe_onnx(audio, on_percent=percents.append, on_progress=print)
elapsed = time.monotonic() - started
words = result["wordTimestamps"]
print(f"{MODEL_LABEL}: {len(result['transcriptSegments'])} segmenti, {len(words)} parole in {elapsed:.1f}s")
print(result["text"][:500])
assert result["model"] == MODEL_LABEL
text = result["text"].lower()
missing = [w for w in expected if w.lower() not in text]
assert not missing, f"parole attese non riconosciute: {missing}"
assert all(w["endMs"] >= w["startMs"] for w in words), "tempi delle parole non ordinati"
assert all(0 <= (w["confidence"] or 0) <= 1 for w in words)
assert percents and percents[-1] == 100
print("✅ Trascrizione Parakeet ONNX riuscita")
