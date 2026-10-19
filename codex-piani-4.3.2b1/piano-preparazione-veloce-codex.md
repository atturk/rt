# Piano per Codex · 4.3.2b1 · Preparazione più veloce

Base: `claude/rt-4.3.2-beta`. File principali: `rt/core/materials.py` (`material_pages`, `_describe`, `_extract`), `rt/pipeline/source_update.py` (`prepare_source_update`, `_transcribe`), `rt/core/config.py`.

## Il problema (Attilio)
La fase "Preparazione" di una lezione nuova è molto lenta.

## Cosa fa oggi la Preparazione
In un import con fonti (`ingest_sources_job` → `run_prepare` → `prepare_source_update`) la Preparazione è dove avviene davvero tutto il lavoro pesante:
- **trascrizione** di ogni audio (macparakeet / parakeet ONNX / server), una fonte dopo l'altra;
- **lettura dei materiali** (`material_pages`): ogni pagina del PDF/PPTX viene renderizzata a 2x in PNG e salvata. Le pagine con poche parole ma con figure (tipico delle slide) vanno al modello visivo (`_describe`, job `image_description`), **una chiamata alla volta**. Su un pacco di 60 slide sono decine di chiamate in fila, ognuna di parecchi secondi;
- con più audio, l'**unione** in un m4a per il lettore (`merge_audio_for_transcription`).

Tutto è sequenziale: prima finisce un audio, poi l'altro, poi il PDF pagina per pagina. In più la Preparazione **non emette nessun avanzamento**: la riga resta ferma su "Preparazione" per minuti, senza dire a che punto è.

Nota: oggi RT non registra cosa succede dentro la Preparazione: nessun log esistente dice dove va il tempo. Le cause sotto vengono dal codice; il punto 5 aggiunge la misura direttamente nel registro del lavoro.

## Cosa fare

### 1. Lettura delle pagine in parallelo (il guadagno più grande)
In `material_pages` separare due passaggi:
- **Passaggio A (veloce, nel thread del job):** estrazione di testo e immagini (`_extract`), `cleaned_page_texts`, scrittura dei PNG. Si decide quali pagine hanno bisogno di Vision (`few_words(mapping_text) and has_figures`) e si riusano le pagine già in cache (`page-N.json`).
- **Passaggio B (in parallelo):** le chiamate `_describe` delle sole pagine che ne hanno bisogno vanno in un `ThreadPoolExecutor` con `max_workers = cfg.pipeline.parallel_pages`. È un nuovo campo in `rt/core/config.py`, accanto a `parallel_units`: default 4, `ge=1, le=16`, descrizione "Pagine dei materiali lette in parallelo dal modello visivo". Usare `contextvars.copy_context()` per ogni chiamata, come fa `_parallel_units` in `rt/pipeline/review.py`, così il contesto del job (lezione, telemetria) arriva ai thread.
- Ogni pagina finita scrive subito il suo `page-N.json` sotto `lesson_lock`, come oggi, così una ripresa dopo un errore non ripete le pagine già lette. L'ordine finale di `pages` resta per numero di pagina.
- Annullamento: prima di avviare ogni chiamata controllare `ctx.check_cancelled()`. Se arriva l'annullamento, non avviarne altre, aspettare quelle in corso e rilanciare `RunCancelled`.
- Errore su una pagina: le altre in corso finiscono e vengono salvate, poi l'errore si propaga come oggi.

### 2. Materiali e trascrizione insieme
In `prepare_source_update` le fonti vengono lavorate in fila. La trascrizione gira sul Mac (macparakeet) e Vision è una chiamata remota: possono andare in contemporanea.
- Prima del ciclo, avviare in un thread separato (`ThreadPoolExecutor(max_workers=1)`) `material_pages(...)` per tutte le fonti `materiale` non in cache, una dopo l'altra.
- Il ciclo resta identico, ma quando arriva a una fonte `materiale` prende il risultato del future invece di chiamare `material_pages`. Nel thread va passato lo stesso `ctx` dentro `copy_context()`.
- L'assegnazione degli ID dei segmenti resta nell'ordine delle fonti, nel thread principale: non cambia nulla per scaletta e versioni.
- Se la trascrizione fallisce o il job viene annullato, chiedere l'annullamento anche al thread dei materiali e aspettarlo prima di uscire (nessun thread orfano che scrive nella lezione).

### 3. Avanzamento visibile
Durante la Preparazione chiamare `ctx.progress("prepare", ...)`, se `ctx` c'è:
- prima di ogni audio: `message="Trascrizione di <nome file> (i di n)"`;
- nella lettura dei materiali, a ogni pagina completata: `current=pagine_fatte, total=pagine_totali, message="Lettura di <nome file>: pagina k di N"`, con le pagine in cache contate subito come fatte;
- prima dell'unione degli audio: `message="Unione degli audio"`.
Controllare che `LessonProgress` / `JobProgress` mostrino già `message` e `current/total` della fase `prepare`. Se la fase prepare non ha una barra, mostrare almeno il messaggio sotto la riga "Preparazione", come per le altre fasi.

### 4. Piccoli sprechi
- `compute_file_sha256` dello stesso file viene calcolato due volte per ogni materiale (in `prepare_source_update` e di nuovo in `material_pages`), e per ogni audio a ogni ripresa. Su audio lunghi (centinaia di MB) costa secondi. Calcolarlo una volta per fonte e per esecuzione: un parametro `checked=True` per `material_pages`, oppure una piccola cache in memoria `{(path, mtime, size): sha}` nella funzione.
- `_extract` mette in memoria i PNG di tutte le pagine prima di iniziare (`list(_extract(real))`). Con il passaggio A va bene così, ma i PNG vanno scritti su disco e liberati man mano, senza tenerli tutti in RAM fino alla fine.

### 5. Misura: i tempi nel registro del lavoro (quello che Attilio vede già)
Il registro sotto la riga "Preparazione" (In coda, Avviato dal worker, Lezione creata, Preparazione: avviata) oggi si ferma lì per minuti. Deve diventare lui stesso la diagnosi, senza file da cercare. Per ogni passaggio emettere un evento del job (lo stesso canale delle righe esistenti, `ctx.emit`/`ctx.progress`) all'inizio e alla fine, con la durata alla fine:
- "Trascrizione di <file> (durata audio 1h 32m): avvio del motore"; poi "Trascrizione di <file>: finita in 4m 10s". Se il motore scrive su stdout le sue fasi (caricamento del modello, avanzamento), inoltrarle come messaggi di avanzamento: in `_run_transcribe_with_spinner` leggere l'output riga per riga invece di aspettare la fine. Così si vede se il tempo va nel caricamento del modello o nella trascrizione.
- "Lettura di <file>: 63 pagine, 41 da descrivere col modello visivo (modello: <nome>)"; poi a ogni pagina "pagina k di N"; alla fine "Lettura di <file>: finita in 3m 05s (Vision 41 chiamate, media 4,4 s)".
- "Unione degli audio: finita in 22s".
- Alla fine della preparazione, una riga di riepilogo: "Preparazione finita in 7m 40s: trascrizione 4m 10s, lettura materiali 3m 05s (in parallelo), unione audio 22s".
Gli stessi numeri vanno in `_state/prepare_timing.json` nella cartella della lezione e in una riga di `logs/worker.log`, così una lezione vecchia si può controllare anche dopo.

## Test (pytest)
- `material_pages` con 6 pagine "sparse con figure" e `_describe` finto che dorme 0,2 s: con `parallel_pages=3` dura meno di 0,8 s. L'ordine di `pages` è 1..6 e ogni `page-N.json` esiste.
- Ripresa: con 3 `page-N.json` già presenti, `_describe` viene chiamato solo per le altre 3.
- Annullamento a metà: nessuna nuova chiamata dopo l'annullamento, `RunCancelled` propagato, le pagine finite restano salvate.
- `prepare_source_update` con un audio (trascrizione finta che dorme 0,5 s) e un PDF (Vision finta 0,5 s): durata totale sotto 0,9 s. Gli ID dei segmenti sono uguali a quelli dell'esecuzione sequenziale.
- Avanzamento: un `ctx` finto riceve messaggi "Trascrizione di …" e "Lettura di …: pagina k di N".
- I test esistenti di `test_source_update.py`, `test_materials*.py` e `test_material_mapping*.py` restano verdi.

Comandi: `python -m pytest tests/test_source_update.py tests/test_materials*.py tests/test_material* -q`, poi la suite completa (anche su Windows in CI).

## Changelog
Sezione 4.3.2b1, Novità: "La preparazione di una lezione è più veloce: le pagine dei materiali si leggono più alla volta, mentre l'audio si trascrive. Durante la preparazione si vede a che punto è (audio in trascrizione, pagina in lettura)."
