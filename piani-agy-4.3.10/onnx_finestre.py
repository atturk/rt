"""Parakeet ONNX a finestre sovrapposte (come FluidAudio/macparakeet: ~15 s con sovrapposizione,
senza VAD), con volume normalizzato. Una variante per processo, così il picco di RAM è suo.

Uso sul Pro con il Python dell'app (legge solo i modelli già scaricati, non tocca ~/.rt):
    APP=/Applications/RT.app/Contents/Resources/app
    /usr/bin/time -l $APP/python/bin/python3 -I onnx_finestre.py "$APP" AUDIO VARIANTE [secondi]

VARIANTE:
  G  = finestre 15 s, sovrapposizione 3 s, cucitura a metà sovrapposizione, normalizzato
  H  = come G ma senza arena di memoria di onnxruntime (enable_cpu_mem_arena=False)
  H8 = come H con finestre 8 s / sovrapp. 2 s (meno RAM?)
  HC = come H con CoreML (Neural Engine/GPU) se onnxruntime lo offre, altrimenti CPU
  HQ = come H con il modello non quantizzato in /tmp/stt-fp32 (se scaricato)
  HQM  = HQ con opzioni a basso consumo di RAM (no mem pattern, no prepacking, 4 thread)
  HQ10 = HQM con finestre 10 s / sovrapp. 2 s
  HQ8  = HQ con finestre 8 s / sovrapp. 2 s
  HP / HP8 / HP6 = int8 per canale solo MatMul (quantizza_pc.py) in /tmp/stt-q8pc, finestre 15 / 8 / 6 s
  HP8M / HP6M = HP8 / HP6 con le opzioni a basso consumo di RAM di HQM (4 thread, no prepacking)
Stampa: tempo, parole, testo iniziale; salva il testo intero in /tmp/stt-<VARIANTE>.txt
"""
import sys
import time

app, audio, variant = sys.argv[1], sys.argv[2], sys.argv[3]
limit = float(sys.argv[4]) if len(sys.argv) > 4 else None
sys.path.insert(0, app)

import numpy as np  # noqa: E402
import onnx_asr  # noqa: E402
import onnxruntime as ort  # noqa: E402

from rt.core import onnx_stt  # noqa: E402

SR = 16000
win_s, ovl_s = ((8.0, 2.0) if variant in ("H8", "HQ8", "HP8", "HP8M") else (10.0, 2.0) if variant == "HQ10"
                else (6.0, 1.5) if variant in ("HP6", "HP6M") else (15.0, 3.0))

wave = onnx_stt._decode(audio)
if limit:
    wave = wave[: int(limit * SR)]
rms = float(np.sqrt(np.mean(wave ** 2))) or 1e-6
peak = float(np.max(np.abs(wave))) or 1.0
gain = min(0.1 / rms, 1.0 / peak * 4)
wave = np.clip(wave * gain, -1, 1).astype(np.float32)
print(f"audio {len(wave) / SR:.1f} s, rms {rms:.4f}, guadagno x{gain:.1f}")

kw = {}
if variant != "G":
    so = ort.SessionOptions()
    so.enable_cpu_mem_arena = False
    if variant in ("HQM", "HQ10", "HP8M", "HP6M"):
        # meno RAM: niente pattern di memoria, niente copie pre-impacchettate dei pesi, 4 thread
        so.enable_mem_pattern = False
        so.add_session_config_entry("session.disable_prepacking", "1")
        so.intra_op_num_threads = 4
    kw["sess_options"] = so
if variant == "HC":
    avail = ort.get_available_providers()
    print("provider disponibili:", avail)
    if "CoreMLExecutionProvider" in avail:
        kw["providers"] = ["CoreMLExecutionProvider", "CPUExecutionProvider"]

if variant in ("HQ", "HQM", "HQ10", "HQ8"):
    model = onnx_asr.load_model(onnx_stt.MODEL_NAME, "/tmp/stt-fp32", **kw)
elif variant in ("HP", "HP8", "HP6", "HP8M", "HP6M"):
    model = onnx_asr.load_model(onnx_stt.MODEL_NAME, "/tmp/stt-q8pc", quantization="q8pc", **kw)
else:
    model = onnx_asr.load_model(onnx_stt.MODEL_NAME, onnx_stt._model_dir(onnx_stt.MODEL_NAME),
                                quantization=onnx_stt.QUANTIZATION, **kw)
asr = model.with_timestamps()

t0 = time.monotonic()
win, step = int(win_s * SR), int((win_s - ovl_s) * SR)
kept = []  # parole tenute: (inizio assoluto, testo)


def to_words(tokens, stamps, off):
    """Token SentencePiece -> parole (un token che inizia con spazio apre una parola)."""
    words = []
    for tok, ts in zip(tokens or [], stamps or []):
        t = off + float(ts)
        if not words or tok.startswith(" "):
            words.append([t, tok.strip()])
        else:
            words[-1][1] += tok
    return [(t, w) for t, w in words if w]


start = 0
prev_cut = 0.0
while start < len(wave):
    chunk = wave[start:start + win]
    if len(chunk) < SR // 2:
        break
    res = asr.recognize(chunk, sample_rate=SR)
    off = start / SR
    last = start + win >= len(wave)
    cut = float("inf") if last else off + (win_s - ovl_s) + ovl_s / 2
    # Cucitura per PAROLE (non per token): una parola appartiene alla finestra in cui inizia
    # prima del taglio; in più si scartano le prime parole che ripetono le ultime tenute
    # (stesso testo, inizio entro 0,6 s), dovute ai tempi leggermente diversi tra finestre.
    new = [(t, w) for t, w in to_words(res.tokens, res.timestamps, off) if prev_cut - 0.6 <= t < cut]
    while new and kept:
        tail = [w.lower().strip(".,;:!?") for _, w in kept[-3:]]
        t0w, w0 = new[0]
        if t0w < prev_cut or (w0.lower().strip(".,;:!?") in tail and abs(t0w - kept[-1][0]) < 1.5):
            new.pop(0)
        else:
            break
    kept.extend(new)
    prev_cut = cut
    if last:
        break
    start += step
elapsed = time.monotonic() - t0
text = " ".join(w for _, w in kept).strip()
words = text.split()
print(f"[{variant}] {elapsed:.1f} s, {len(words)} parole")
print("  " + text[:600])
with open(f"/tmp/stt-{variant}.txt", "w", encoding="utf-8") as f:
    f.write(text + "\n")
