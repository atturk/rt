# Piano 4.3.6b2: correzioni dal QA del 2 novembre (agy)

Questo piano raccoglie undici voci. Vengono da un QA su lezioni reali fatto con un modello giudice: nessun bug era bloccante.

- **Base:** `claude/project-thread-tk54yz` (beta 4.3.6b1).
- **Branch di lavoro:** `agy/4.3.6b2`, un commit per voce, una sola PR verso la base.
- **Interfaccia:** testi in italiano, minimalismo, pulsanti a icona con suggerimento, niente testo superfluo.
- **Test:** ogni voce ha i suoi, nel file indicato o in uno nuovo accanto.

**Già fatto, non rifare:** la cache del prompt per i modelli `openai/*` (PR #154, `rt/llm/client.py`, `_cache_lesson_prefix`).
**Escluso di proposito, non fare:**
- il provider fisso per lezione;
- `prompt_cache_key`;
- toccare la soglia del prefiltro della verifica (`task_a_skip_confidence_threshold` resta com'è).

---

## 1. Il revisore consulta le fonti prima di segnalare

**Problema.** Il revisore scientifico vede solo il testo rielaborato. `build_science_review_user_prompt` in `rt/llm/prompts.py` non riceve né il trascritto né i materiali. Per questo segnala come errori le definizioni e le convenzioni del corso: in una lezione di ottimizzazione voleva cambiare un indice temporale `w+1` in `w-1`, mentre trascritto e slide dicono `w+1`, e la formula era nella slide. Dall'altra parte, il revisore deve poter ancora contraddire il docente quando sbaglia su un fatto della materia: in una lezione di elettromagnetismo il docente diceva che tutta l'energia va nel condensatore, mentre metà si dissipa nel resistore.

**Cosa fare.**
1. **Fonti nel prompt.** In `_review_unit` (`rt/pipeline/review.py`), passa a `build_science_review_user_prompt` due nuovi argomenti:
   - `source_context`: i segmenti del trascritto dell'unità, già calcolati lì come `source_context`;
   - `materials_context`: il testo delle pagine agganciate all'unità e alla sua macro-sezione, da `material_context_for_unit(lesson_dir, unit_id, macro_id)` in `rt/pipeline/material_mapping.py`.

   Nel prompt aggiungi due blocchi, «TRASCRITTO DEL DOCENTE» e «MATERIALI DEL DOCENTE», separati come i blocchi già presenti.
2. **Indice delle pagine.** Nuovo modulo `rt/services/source_index.py`. Per ogni pagina dei materiali della lezione costruisce un indice che unisce:
   - il testo estratto dal PDF;
   - l'OCR o la descrizione del modello di visione, dove esistono. La descrizione delle immagini si legge come in `rt/pipeline/add_images.py` (`load_image_descriptions`, `descrizione.json` nell'archivio).

   Normalizza il testo per la ricerca: minuscole, via spazi e comandi LaTeX (`\mathrm`, `\left`, ecc.), via le graffe. Così «w + 1», «(w+1)» e «w+1» diventano uguali. Ricerca BM25, scritta a mano senza nuove dipendenze, oppure TF-IDF come in `find_candidate_subunits_for_page`. Prima cerca nelle pagine agganciate all'unità, poi in tutte le pagine della lezione. Restituisce le 3 pagine migliori, ognuna con fonte, numero di pagina, testo e un'indicazione `da_descrizione: bool` (vera se la corrispondenza viene solo dalla descrizione).
3. **Seconda passata sulle segnalazioni.** Dopo la prima risposta del revisore, per ogni segnalazione concettuale (non quelle ASR) cerca nell'indice con le parole e i simboli di `claim` e `suggested_fix`. Se trova pagine pertinenti, fa una seconda chiamata breve al revisore con la segnalazione, le pagine trovate e il trascritto dell'unità. Gli chiede di classificarla:
   - `definizione_del_corso`: il testo coincide con le fonti ed è una definizione, una notazione o una convenzione del corso. La segnalazione **viene scartata**.
   - `possibile_errore_del_docente`: il testo coincide con le fonti ma contraddice un fatto della materia. La segnalazione resta, con un nuovo campo `origine = "docente"`. La correzione **non** si applica in automatico: diventa una nota «Il docente dice X; in generale vale Y», mostrata nel pannello Verifica.
   - `errore_della_rielaborazione`: il testo si discosta dalle fonti. Si comporta come oggi.

   La risposta indica anche la prova, per esempio «slide 16: …» o «trascritto: …». Salvala nella segnalazione in un campo `prova`, da mostrare nel pannello.
4. **Prova solo dalla descrizione, o ricerca ambigua.** Se la prova viene solo dalla descrizione (`da_descrizione`), oppure il punteggio della pagina migliore è vicino a quello della seconda, la seconda chiamata riceve anche l'immagine della pagina. La pagina si rende in PNG come in `rt/core/materials.py`, `get_pixmap(matrix=fitz.Matrix(2, 2))`. Al massimo 2 immagini per segnalazione, e solo con un modello che accetta immagini: altrimenti si va avanti senza. La descrizione è scritta da un LLM e può sbagliare un pedice: non è mai una prova da sola.
5. **Le foto** (lavagna, slide fotografate) entrano nello stesso indice: OCR o descrizione per trovarle, immagine per decidere.

**Modelli e schemi.**
- In `rt/core/models.py`: nuovi campi facoltativi di `ScienceIssue`, cioè `origine: Optional[Literal["docente", "rielaborazione"]]` e `prova: Optional[str]`.
- Il nuovo schema di risposta della seconda passata deve essere compatibile con lo strict JSON schema di OpenAI: tutti i campi `required`, quelli facoltativi come `type: [..., "null"]`. Guarda come è stato risolto `ReviewFindingList` (PR #145).
- Frontend, pannello Verifica (`frontend/src/components/lesson/panels/`): per `origine = "docente"` mostra l'etichetta «Possibile errore del docente» e la nota, senza il pulsante che applica la correzione al testo. La `prova` va in una riga piccola sotto la segnalazione.

**Costo.** La seconda passata riguarda solo le segnalazioni concettuali: poche per lezione. Le immagini solo nei casi del punto 4.

**Test** (`tests/test_review_sources.py`, con LLM finto):
- la normalizzazione rende uguali «w + 1» e «(w+1)»;
- la ricerca trova la pagina giusta prima tra quelle agganciate, poi in tutto il PDF;
- `definizione_del_corso` scarta la segnalazione;
- `possibile_errore_del_docente` la tiene, con `origine` e senza correzione automatica;
- se la prova viene solo dalla descrizione, viene chiesta l'immagine;
- il prompt della prima passata contiene trascritto e materiali.

## 2. La deriva della rielaborazione tiene conto dei materiali

**Problema.** `run_jev_task_b` in `rt/pipeline/review.py` confronta il testo rielaborato solo con i segmenti ASR. Il contenuto preso dalle slide risulta così «non supportato» e produce falsi `ERR_REWRITE_DRIFT`: 3 su 12 segnalazioni in una lezione con PDF.

**Cosa fare.**
- Aggiungi a `run_jev_task_b` un argomento `materials_context` e mettilo nello `state` come terzo blocco: «MATERIALI DEL DOCENTE (slide, foto)».
- Nelle istruzioni della domanda `unsupported_content`, il contenuto che ha riscontro nei materiali conta come supportato.
- In `_review_unit` passa `material_context_for_unit(...)`, lo stesso testo della voce 1.

**Test:** con un materiale che contiene la sigla usata nel testo, lo `state` inviato al classificatore la contiene. Lezione senza materiali: lo `state` resta come oggi.

## 3. Domande e Studio con le segnalazioni aperte

**Problema.** Le domande si generano anche dalle unità con segnalazioni della verifica non ancora decise, e ne ripetono l'errore. Un quiz aveva come risposta giusta proprio l'affermazione che la verifica segnala come errata. Nello Studio poi non c'è nessun avviso delle segnalazioni aperte.

**Cosa fare.**
- In `generate_recall_batch` (`rt/pipeline/recall.py`): dopo aver scelto `units`, togli quelle con segnalazioni aperte. Le segnalazioni aperte si leggono con `get_pending_issues(lesson_dir)` di `rt/pipeline/ledger.py`, guardando l'`unit_id` di ciascuna e solo quelle concettuali (non `ERR_ASR_*`).
  - Riporta con `report(...)` un messaggio come «2 unità saltate: hanno segnalazioni da decidere nella Verifica».
  - Fanno eccezione le unità che l'utente chiede in modo esplicito con `unit_ids`: si generano lo stesso, ma la domanda nasce con un nuovo campo `da_verificare: true`.
- Quando una segnalazione viene decisa (accettata o rifiutata), le domande già esistenti su quell'unità:
  - se la decisione ha cambiato il testo, vanno marcate `stale` come fa già il ricalcolo dell'impronta delle unità (`_compute_units_fingerprint`), così vengono rigenerate;
  - se il testo non è cambiato, restano.

  Verifica il flusso esistente e completalo dove manca.
- Studio (`frontend/src/components/study/Study.tsx`):
  - se la lezione ha segnalazioni aperte, mostra una barra discreta «N punti da verificare» con un link al pannello Verifica;
  - sulle unità coinvolte, un piccolo segno con un suggerimento.

  Usa l'API delle segnalazioni già esistente (`GET /api/v1/lessons/{id}/issues`, oppure il campo che il pannello Verifica usa già).

**Test:**
- Python: un'unità con segnalazione aperta non riceve domande; con `unit_ids` esplicito sì, ma con `da_verificare`.
- vitest: la barra compare con segnalazioni aperte e non compare con zero.

## 4. LaTeX rovinato dagli escape JSON

**Problema.** Il modello ha scritto `\trm{RTPL}` con una sola barra. Il JSON lo ha letto come un carattere TAB seguito da `rm{RTPL}`. `repair_latex_escapes` in `rt/core/encoding.py` ripara solo una lista di comandi noti (`_LATEX_AFTER_ESCAPE`), e `rm` dopo il TAB non c'è. Nell'editor la formula si apre male e ingloba la frase.

**Cosa fare** (`rt/core/encoding.py`):
- **Riparazione dentro le formule.** Dentro le formule (`$…$`, `$$…$$`, `\(…\)`, `\[…\]`), qualunque carattere di controllo `\t`, `\r`, `\n`, `\x08`, `\x0c` seguito da una lettera torna la sequenza con la barra: `\t` → `\\t`, `\r` → `\\r`, eccetera. Fuori dalle formule resta la logica di oggi, con la lista.
- **Comandi non validi.** Dopo la riparazione, sostituisci i comandi non validi più comuni: `\trm{`, `\rm{` e `\textrm{` dentro una formula diventano `\mathrm{`.
- **Ultimo controllo.** Se dopo la riparazione restano caratteri di controllo dentro una formula, togli il carattere: meglio una lettera in meno che una formula che ingloba il testo.

**Test** (`tests/test_encoding.py` o accanto):
- `"($\trm{RTPL}$)"` diventa `"($\\mathrm{RTPL}$)"`;
- `\theta`, `\frac`, `\nabla` e `\rho` rovinati vengono riparati;
- un TAB fuori dalle formule resta TAB;
- un testo senza formule non cambia.

## 5. Avviso di registrazione già caricata

**Problema.** Ricaricare la stessa registrazione crea in silenzio una nuova lezione «(2)». RT riconosce l'impronta (`find(upload_sha)` in `rt/pipeline/setup.py`, intorno alla riga 618, e riusa il trascritto), ma l'utente non lo sa.

**Cosa fare.**
- In `create_lesson` (`rt/api/routers/jobs.py`), dopo `_save_uploads` e prima di mettere il job in coda: se c'è un solo audio, calcola `compute_file_sha256` e cerca una lezione esistente con la stessa impronta tra le fonti. L'impronta è in `rt/core/sources.py`, campo `impronta`; scrivi una funzione `lesson_with_audio(sha)` in `rt/services/lesson_conflicts.py`.
  - Se la trovi e il nuovo campo di form `consenti_duplicato` non è vero, rispondi **409**, codice `audio_duplicate`, con `details: {lesson_id, titolo, data}`.
  - Pulisci gli upload come già fa `_with_upload_cleanup`.
- Frontend, popup di import: per il 409 `audio_duplicate` mostra «Questa registrazione è già nella lezione <titolo> del <data>» con tre pulsanti:
  - **Apri la lezione:** va alla lezione esistente;
  - **Crea comunque:** ripete l'invio con `consenti_duplicato=true`;
  - **Annulla.**

**Test:**
- API: secondo upload dello stesso file → 409 `audio_duplicate`; con `consenti_duplicato` → 202.
- vitest: il dialogo e i tre pulsanti.

## 6. Audio non valido e lezioni fallite visibili

**Problema.**
- Un file di testo rinominato `.mp3` viene accettato: si controlla solo l'estensione.
- La trascrizione poi fallisce con «SetupError: Trascrizione macparakeet-cli JSON fallita … Dettagli errore: », con i dettagli vuoti.
- La lezione resta in elenco come «Da completare». La sua pagina mostra il testo tecnico `NO_PREVIEW_MARKDOWN` di `rt/services/lesson_service.py`: «Serve almeno la fase di *rewrite* …».

**Cosa fare.**
- **Controllo all'upload.** In `create_lesson`, e in ogni altro punto che salva audio caricati (cerca `SUPPORTED_AUDIO_EXTENSIONS`), dopo il salvataggio chiama `audio_duration(path)` di `rt/core/media_tools.py`. Se solleva `ValueError` o `CalledProcessError`, rispondi 422 con codice `invalid_audio` e messaggio «"<nome file>" non è un file audio leggibile.»
- **Errore leggibile.** In `rt/pipeline/setup.py`, se `stderr` è vuoto, metti nel messaggio di `SetupError` lo `stdout` o almeno il codice di uscita in parole: «Il file audio non è leggibile o è danneggiato.»
- **Lezione fallita visibile.** Nella pagina della lezione, se l'ultimo job della lezione è fallito, mostra in alto un riquadro con il messaggio d'errore e due pulsanti:
  - **Riprova:** stessa azione di Job → dettaglio;
  - **Elimina:** con conferma.

  `NO_PREVIEW_MARKDOWN` diventa un testo per utenti: «Questa lezione non è ancora pronta. Avvia l'elaborazione o riprova se si è interrotta.»

**Test:** API, upload di un testo rinominato `.mp3` → 422 `invalid_audio`, e nessuna lezione creata. vitest: il riquadro di errore con Riprova.

## 7. Impostazione «Contesto della rielaborazione»

**Problema.** Il rewrite elabora le unità una alla volta, con tutte le unità precedenti come contesto. Su una lezione di 27 unità occupa 5 min 48 s su 6 min 43 s di pipeline, con il contesto che cresce da 3,4k a 14,4k token per unità.

**Decisione dell'utente.** Nuova impostazione con due valori:
- **«Macro-sezione, in parallelo» (predefinito):** ogni unità riceve come contesto solo le unità già rielaborate della **stessa macro-sezione**. Le macro-sezioni girano in parallelo; dentro una macro-sezione le unità restano in ordine.
- **«Tutte le unità precedenti, in sequenza (più lento)»:** il comportamento di oggi.

**Cosa fare.**
- **Configurazione.** In `rt/core/config.py`, una nuova `RewriteConfig` dentro `RTConfig` con:
  - `context_mode: Literal["macro", "all"] = "macro"`;
  - `parallel_macros: int = Field(default=4, ge=1, le=8)`.
- **Pipeline** (`rt/pipeline/rewrite.py`, `_run_rewrite`, ciclo `for idx, u in enumerate(units_to_process …)` intorno alla riga 330).
  - Con `"macro"`:
    - raggruppa `units_to_process` per macro-sezione (`unit_to_macro`);
    - per ogni gruppo, `previous_units` sono le unità della stessa macro già in `draft_units_map`;
    - esegui i gruppi in parallelo con al massimo `parallel_macros` thread: prendi a modello `_parallel_units` in `rt/pipeline/review.py`, con `copy_context().run` e l'annullamento tramite `raise_if_cancelled`.
  - Scritture condivise (`draft_units_map`, `save_draft`, `record_phase_checkpoint`, eventi di avanzamento) sotto un `threading.Lock`. Il checkpoint resta atomico e nell'ordine canonico dell'outline, come oggi.
  - Con `"all"`: il codice di oggi, senza cambiamenti.
- **Cache.** Il prefisso di cache (`build_rewrite_prefix_parts`) resta: scaletta e materiali fissi in testa, poi le unità precedenti **della macro**, aggiunte solo in coda. Ogni macro-sezione scrive la propria cache.
- **Impostazioni.** API dove stanno le altre impostazioni dei job, e frontend in Impostazioni → Modelli, nella riga della rielaborazione (`frontend/src/components/settings/models.tsx`): un selettore con i due valori e un suggerimento di una riga.

**Test:**
- con `"macro"` il contesto di un'unità contiene solo unità della sua macro;
- due macro-sezioni girano davvero in parallelo (LLM finto con `sleep`; tempo totale minore della somma);
- il checkpoint e la ripresa funzionano a metà;
- con `"all"` il prompt è identico a oggi (test esistenti in `tests/test_rewrite_previous_context.py`).

## 8. Domande, classificatore ed etichette in parallelo

**Problema.** La generazione delle domande fa una chiamata alla volta: 6 min per 98 domande (51 chiamate), contro 41 s per la verifica della stessa lezione, che va in parallelo. In fila vanno anche il classificatore di rilevanza e le etichette delle sezioni: circa 19 s a lezione.

**Cosa fare.**
- **Domande.** In `generate_recall_batch` (`rt/pipeline/recall.py`), il ciclo `for position, group in enumerate(active)` diventa parallelo, con al massimo `RecallConfig.parallel_units` chiamate (nuovo campo, default 4). Prendi a modello `_parallel_units`.
  - La chiamata LLM e la costruzione del prompt vanno nel thread; la scrittura nel bank (`_persist_generation`, sotto `recall_bank_lock`) e `report(...)` restano nel thread chiamante, come fa la verifica.
  - Gli id delle domande (`_next_id`) si assegnano solo al momento del salvataggio.
  - I passaggi successivi (`round_index`) restano in sequenza tra loro.
- **Classificatore di rilevanza** (`refresh` in `rt/services/unit_relevance.py`, ciclo `for unit in units`): le chiamate `call_jev` in parallelo, al massimo 4; il calcolo del risultato e la scrittura restano in ordine.
- **Etichette delle sezioni:** stesso schema, nel punto dove vengono generate dopo il rewrite. Cerca il job che produce le 7 chiamate di etichetta per le macro-sezioni.

**Test:** con LLM finto lento, la generazione di N gruppi dura circa N/4 volte una chiamata. Gli id delle domande restano unici. L'annullamento ferma l'avvio di nuove chiamate.

## 9. Materiali didattici non collocati

**Problema.** In `classify_material_page` (`rt/pipeline/material_mapping.py`, intorno alla riga 458), una pagina didattica (`didactic_content` ≥ soglia) senza nessuna unità sopra la soglia viene scartata in silenzio (`return [], []`). È successo a una foto e a due pagine di PDF in due lezioni.

**Cosa fare.**
- Se la pagina è didattica ma `approved_candidates` è vuoto e ci sono candidate, assegnala alla **macro-sezione** della candidata con probabilità più alta (`return [], [best.macro_id]`).
- Marca la pagina come «non collocata» nello stato (`material_attachments.json`, nuovo elenco `unplaced`), così nel documento finisce in fondo alla macro-sezione con la didascalia «Materiale non collocato».
- Se non ci sono candidate, la pagina va in `unplaced` senza macro. Nel pannello Fonti compare in un elenco «Materiali non collocati», da cui l'utente può trascinarla o assegnarla.

**Test:** pagina didattica con tutte le probabilità di unità sotto la soglia → assegnata alla macro e in `unplaced`. Pagina non didattica → scartata come oggi.

## 10. Conferma prima di creare una materia nuova

**Problema.** Creare una lezione con una materia che non esiste crea la materia senza chiedere. Con un refuso («Data minig») nascono materie doppie.

**Cosa fare.**
- Nel popup di import (frontend), prima di inviare: se la materia scritta non è nell'elenco delle materie (API già esistente in `rt/api/routers/subjects.py`), chiedi «Creare la nuova materia «X»?».
- Se c'è una materia simile, suggeriscila: «Forse intendevi «PGSS»?». Simile vuol dire distanza di Levenshtein ≤ 2, oppure uguale senza spazi e maiuscole.
- Pulsanti: **Usa «<simile>»**, **Crea «X»**, **Annulla**.
- Nessun cambiamento all'API: la conferma è solo nell'interfaccia.

**Test** vitest: materia nuova → richiesta di conferma; refuso → suggerimento; materia esistente → nessuna domanda.

## 11. Correzioni minori

Una per commit, oppure raggruppate in un solo commit «11. Correzioni minori».

1. **422 su `GET /api/v1/recall/subject?materia=`** aprendo «Mettimi alla prova» dallo Studio. In `useSubjectRecall` (`frontend/src/api/recall.ts`) aggiungi `enabled: !!materia`. Nello Studio passa la materia della lezione.
2. **Conteggi diversi nel pannello Dettagli** («12 da decidere» e subito sotto «11 ancora da valutare»). La differenza è una segnalazione senza `anchor`, che non si trova nel testo. Usa un solo conteggio. La segnalazione senza ancora va mostrata nel pannello Verifica con «Posizione nel testo non trovata».
3. **Dopo «Riprova», la pagina del nuovo job mostra gli eventi del job fallito.** Mostra solo gli eventi del nuovo job, con in cima un link «Tentativo precedente».
4. **Annullare un job già concluso risponde 200.** Deve rispondere 409 `job_not_running` (`rt/api/routers/jobs.py`).
5. **`GET /jobs/{id}` di un job in corso** riporta ancora `result.status` della fase precedente. Durante l'esecuzione, `result` deve essere `null` o aggiornato. I job creati via API hanno inoltre `options.channel: "terminal"` in `create_lesson`: usa `"api"`, controllando che nessun codice dipenda da `"terminal"`.
6. **Errori di rete a ogni apertura di una lezione senza scaletta o rielaborazione:** 404 su `GET /lessons/{id}/outline` e 409 su `GET /lessons/{id}/enrichment`. Il frontend non deve fare queste richieste quando lo stato della lezione dice che mancano (`enabled` nelle query).
7. **Rinomina a metà:** con `rename=true` cambia il titolo ma la cartella resta «(2)». Rinomina anche la cartella, con la stessa logica di `free_lesson_path`.
8. **Campo `uso` dei materiali:** vale `null` nelle lezioni create dall'import e `"contesto"` in quelle aggiornate con l'aggiunta di fonti. Usa lo stesso valore in entrambi i casi.
9. **Durata dell'audio:** in `prepare` è riportata in due modi diversi nello stesso job (5425,70 e 5424,88 s). Usa una sola misura (`audio_duration`).
10. **Testi da sistemare:**
    - Dettagli → «Registrazione unita» diventa «Registrazione unita da N parti» (`SourcesSection.tsx`);
    - Impostazioni → Zoom mostra «100%» due volte: lascia solo quello del valore;
    - i messaggi 422 «Richiesta non valida.» elencano in italiano i campi mancanti o errati («Manca la data», «Manca la materia»), al posto di «Field required» (`rt/api/errors.py`).
11. **Export «solo fonti» di un audio unito da più parti:** aggiungi all'export un file `parti.txt` con i nomi e l'ordine dei file originali.

---

### Come verificare la qualità (facoltativo)

`scripts/eval_quality.py` (PR #154) giudica una lezione esportata con un modello più forte. Serve una chiave OpenRouter con budget limitato, da passare solo come `OPENROUTER_API_KEY`, mai in un file del repo.

Su una lezione con PDF ri-elaborata dopo le voci 1-4, il numero di segnalazioni giudicate «falso allarme» e di affermazioni «inventate» dovrebbe scendere.
