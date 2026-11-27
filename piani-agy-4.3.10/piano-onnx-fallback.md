# Piano agy: trascrizione sul Mac senza Homebrew (R1, fallback Parakeet ONNX)

Base: main (104f9d1). Prima di tutto: `git pull` di questo branch. Solo codice e test unitari, niente verifiche Playwright (le fa Claude sul Pro).

## Problema

Sul Mac il motore predefinito è `macparakeet`, un binario esterno che si installa solo con
`brew install moona3k/tap/macparakeet-cli`. Un utente normale non ha Homebrew: oggi la prima
lezione da audio fallisce con «macparakeet-cli non trovato…». Parakeet ONNX (onnx_asr +
onnxruntime) è già incluso nell'app Mac: manca solo il modello (~700 MB) che si scarica al primo uso.

Obiettivo: su un Mac senza macparakeet-cli RT trascrive comunque, da solo, con Parakeet ONNX.
Chi ha macparakeet-cli continua a usarlo (è più veloce, Neural Engine).

## Da fare

1. **Motore effettivo** (nuovo helper in `rt/core/config.py` o `rt/services/settings_service.py`):
   `effective_engine(cfg) -> str`:
   - `custom` → `custom`;
   - `parakeet` → `parakeet`;
   - `macparakeet`: se `sys.platform == "darwin"` e `find_macparakeet_binary()` lo trova → `macparakeet`;
     altrimenti, se `rt.core.onnx_stt.available()` → `parakeet` (fallback); altrimenti resta `macparakeet`
     (così l'errore resta quello di oggi).
   Il valore salvato in config NON cambia: se domani l'utente installa macparakeet-cli, torna a usarlo.

2. **Usarlo ovunque si decide il motore**:
   - `rt/pipeline/setup.py` ~684: `use_onnx = effective_engine(stt) == "parakeet"`; il `SetupError` resta solo
     se né macparakeet né ONNX sono disponibili. Nel log: `[2/9] TRASCRIZIONE PARAKEET ONNX (macparakeet-cli non trovato)...`.
   - `rt/services/jobs.py` `detect_stt_capability`: con engine `macparakeet` sul Mac senza binario e ONNX disponibile → `"parakeet"`.
   - Controllare anche `rt/pipeline/source_update.py`, `rt/pipeline/prepare.py`, `rt/core/recall_stt.py`, `rt/cli_jobs.py`
     (grep `macparakeet` / `transcription.engine`) e passare tutti dall'helper.
   - `rt/services/pipeline_service.py` `transcription_unavailable_reason()`: sul Mac restituisce un motivo solo se
     manca sia macparakeet sia ONNX.

3. **Download del modello visibile**: in `onnx_stt._models` il messaggio «Scarico il modello di trascrizione
   (circa 700 MB, solo la prima volta)…» arriva già a `on_progress`. Verificare che nel job di setup arrivi
   all'avanzamento della lezione (fase Trascrizione) e aggiungere, se manca, la percentuale del download
   (dimensione scaricata / totale) con lo stesso callback, al massimo un aggiornamento al secondo.
   Se il download fallisce (rete assente): errore umano chiaro «Serve internet la prima volta per scaricare il
   modello di trascrizione (circa 700 MB). Riprova quando sei connesso.» (`rt/services/human_error.py`).

4. **Impostazioni › Trascrizione** (`frontend/src/components/settings/general.tsx` ~28-67, `settings_service.transcription_engines()`):
   - aggiungere al payload `effective_engine` e `macparakeet_fallback: bool` (true quando si usa ONNX al posto di macparakeet);
   - con fallback attivo, sotto «macparakeet» mostrare: «macparakeet-cli non è installato: RT usa Parakeet ONNX,
     che funziona senza installare nulla. Per la massima velocità puoi installare macparakeet-cli con Homebrew.»
     (niente comando brew in evidenza: un link «Come?» alla guida va bene);
   - aggiornare `frontend/src/api/schema.d.ts` e `testSettings.ts`.

5. **Diagnostica** (`rt/services/doctor_service.py` 66-75): senza macparakeet ma con ONNX → OK
   «Parakeet ONNX (macparakeet-cli non installato)», con nota «modello da scaricare al primo uso» se `model_ready()` è falso.
   WARN solo se mancano entrambi.

6. **Test** (pytest, `RT_DEFAULT_STT_ENGINE` come fanno i test esistenti, monkeypatch di `find_macparakeet_binary`,
   `onnx_stt.available`, `sys.platform`):
   - Mac senza binario + ONNX → `effective_engine == "parakeet"`, `detect_stt_capability() == "parakeet"`, setup non solleva;
   - Mac con binario → `macparakeet`;
   - Mac senza binario e senza ONNX → SetupError di oggi;
   - engine `custom`/`parakeet` invariati;
   - doctor: i tre casi;
   - frontend: messaggio di fallback in `transcription.test.tsx`.

## Fuori da questo piano
Non cambiare il default salvato né migrare config esistenti. Non toccare il wizard (piano separato).
