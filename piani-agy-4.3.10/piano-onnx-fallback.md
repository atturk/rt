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
   Dal test sul Pro (rete lenta, ~0,2 MB/s): il download arriva a blocchi da ~67 MB ogni 8-10 minuti e per mezz'ora il job
   mostra solo «Lezione creata». Quindi:
   - percentuale **e stima del tempo rimanente** («Scarico il modello di trascrizione: 410 di 652 MB, circa 20 minuti»), calcolata sui byte
     scaricati di tutti i file del modello (encoder + decoder + vocab), mostrata come fase del job;
   - download **riprendibile**: file temporaneo `.part` e header `Range` se il server lo supporta (Hugging Face sì), così un'interruzione o
     un riavvio del worker non riparte da zero; il file finale si rinomina solo a download completo e verificato (dimensione attesa).
   Se il download fallisce (rete assente): errore umano chiaro «Serve internet la prima volta per scaricare il
   modello di trascrizione (circa 700 MB). Riprova quando sei connesso.» (`rt/services/human_error.py`).

4. **Impostazioni › Trascrizione** (`frontend/src/components/settings/general.tsx` ~28-67, `settings_service.transcription_engines()`):
   - aggiungere al payload `effective_engine` e `macparakeet_fallback: bool` (true quando si usa ONNX al posto di macparakeet);
   - con fallback attivo, sotto «macparakeet» mostrare: «macparakeet-cli non è installato: RT usa Parakeet ONNX,
     che funziona senza installare nulla. Per la massima velocità puoi installare macparakeet-cli con Homebrew.»
     (niente comando brew in evidenza: un link «Come?» alla guida va bene);
   - aggiornare `frontend/src/api/schema.d.ts` e `testSettings.ts`.

4b. **Lezione senza trascritto dopo un errore** (test A sul Pro): quando la trascrizione fallisce subito (motore mancante) la lezione resta
   creata e vuota. Va bene che resti (l'utente può riprovare), ma l'elenco e la pagina della lezione devono mostrare l'errore con «Riprova»,
   non una lezione apparentemente pronta. Verifica che sia già così; se no, il minimo per mostrarlo.

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

## Aggiunte dal test sul Pro (27/11, macparakeet nascosto)

7. **Controllo prima di creare la lezione**: oggi il SetupError arriva dopo la creazione, e la lezione resta vuota. Il motore effettivo
   va deciso (e, se nessuno è disponibile, l'errore va dato) prima di creare la lezione, nel punto in cui si avvia l'ingest audio.
8. **`recommended`** in `settings_service.transcription_engines()`: oggi sul Mac è sempre «macparakeet» anche senza binario. Con
   `macparakeet_installed=false` e ONNX disponibile deve essere «parakeet».
9. **Modello caricato due volte** al primo avvio: le righe CoreML compaiono due volte, a 11 s di distanza (probabilmente `_models` viene chiamato
   prima per `ensure_model`/VAD e poi per la trascrizione). Caricarlo una volta sola (cache del modulo), test con un contatore.
10. **Coda dell'ultima frase troncata**: con ONNX la fine dell'audio esce «Grazie alla pros», mentre macparakeet dà «Grazie, alla prossima lezione.».
    Probabilmente il VAD (silero) chiude l'ultimo segmento troppo presto. Aggiungere un padding finale ai segmenti VAD (es. 300-500 ms, senza
    superare la durata dell'audio) e, se l'ultimo segmento finisce entro 1 s dalla fine del file, estenderlo fino alla fine. Test su un audio
    sintetico con parlato fino all'ultimo istante (o con un mock del VAD che verifica i limiti passati al modello).
11. Nota: con un audio già trascritto RT riusa la trascrizione dall'archivio (stessa impronta e stesso motore) e non controlla il binario. Va bene così,
    non cambiarlo.
