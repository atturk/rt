# Piano 4.2.6

14 ott 2026, approvato da Attilio nel thread "Raccolta feature 4.2.5". Tutto ciò che era destinato alla 4.2.5b3 passa qui. La 4.2.6b1 si fa in **un solo giro notturno**, diviso fra Codex e Antigravity per argomento: ciascuno fa backend e interfaccia delle sue parti, così niente contratto scritto a mano fra i due (lezione della 4.2.5b2).
Wireframe: docs/wireframes-4.2.6/RT-immagini.html (striscia di immagini, bottone Unisci) e RT-flusso-fonti.html (flusso dei materiali, oggi e proposta).

## Regole per tutti
- **Innestare, non rimpiazzare.** Gli elementi che esistono restano dove sono e come sono; si aggiunge o si adatta solo quello che il task nomina. Estetica minimale di RT: icone con tooltip, niente controlli o stati che il piano non chiede. Eccezione voluta: il bottone **Unisci** nel popup di import è un bottone con scritta.
- **Cartella dati separata.** Chi avvia RT, una CLI o uno script fuori dalla suite esporta prima `RT_DATA_DIR` verso una cartella di prova (es. ~/rt-dev-data), mai la ~/.rt vera.
- **Niente migrazioni** in questa beta: i dati nuovi stanno in file JSON (cartella di stato o della lezione) o nella configurazione. Se una servisse davvero: Codex 0019 (down 0018), Antigravity 0020 (down 0018, la riaggancio io).
- Test mirati per passo; suite completa due volte; e2e una volta alla fine. Non si aggiornano golden o test esistenti per far passare cambiamenti che il piano non chiede; se cambiano per un motivo voluto, il motivo va nel commit.
- Commit con push a ogni passo; PR in bozza subito verso claude/rt-4.2.6-beta.
- CHANGELOG: sezione "## 4.2.6b1" scritta per l'utente, senza codici dei task.

## Divisione
| Agente | Branch | Lavoro | File principali (gli altri non li tocca) |
|---|---|---|---|
| Codex | rt426b1/codex | RQ1-RQ6 recall, FS1 togliere una fonte | rt/pipeline/recall*.py, rt/llm/prompts.py (solo prompt del recall e delle varianti), rt/services/recall*, api_jobs.py (recall_batch_job), settings/questions.tsx, Study.tsx, QuestionsPanel.tsx, EmptyGeneration.tsx, LightweightSession.tsx; rt/core/source_selection.py, source_update.py (`sources_pending`), remove_source in rt/core/sources.py, SourcesSection.tsx (solo la ×) |
| Antigravity | rt426b1/antigravity | MF1 flusso dei materiali, IM1 immagini, AU2 audio, UI1-UI3 | rt/core/materials.py, rt/pipeline/material_attachments.py e il modulo nuovo dell'assegnazione, rewrite.py, REWRITE_SYSTEM_PROMPT, build.py, image_placement.py, document_edit_service.py, componenti delle immagini nell'editor e nelle viste, add_source e l'import in rt/core/sources.py e materials_lesson_service.py, setup.py, info.tsx, NewLessonDialog.tsx, CalendarPopups.tsx, Layout.tsx |
rt/core/sources.py, SourcesSection.tsx, rt/api/routers/lesson_sources.py, docs/openapi.json, schema.d.ts e CHANGELOG.md li toccano entrambi in punti diversi: i conflitti li risolvo io alla fusione.

---

## Codex · Recall (RQ1-RQ6)

Obiettivo: il numero scelto dall'utente diventa un tetto e non una quota, le varianti degli esercizi riempiono il numero, i voti diventano regole per tipo e materia, e una serie di controlli locali (senza LLM) scarta le risposte insensate dei modelli gratuiti.

### Stato di oggi (per orientarsi)
- `generate_recall_batch` (rt/pipeline/recall.py) fa una chiamata per unità (vaste: gruppi di 4). `count` è solo un obiettivo fra un gruppo e l'altro, non arriva al modello; con un'unità sola c'è una chiamata sola. Un esito vuoto è valido e viene ricordato come "exhausted".
- `contextualize_recall_prompt` (rt/llm/prompts.py) aggiunge le domande già presenti **dello stesso tipo** sull'unità (ultime 30, ~12k caratteri).
- Doppioni: si scartano solo i testi identici.
- Tipi personalizzati con "Varianti verificate" (rt/pipeline/recall_special.py): gli originali salvano un "tipo" (scenario, variabili, obiettivo, procedimento) legato alle unità; `generate_variant` fa una chiamata per la variante e una di verifica indipendente, 2 tentativi; al massimo 2 varianti per job (`templates[:min(wanted, 2)]`).
- Voti: `record_fewshot_vote` tiene per tipo gli ultimi 5 👍 e gli ultimi 5 👎/⚡ da tutte le lezioni, e `recall_fewshot_block` li incolla nel prompt come "ESEMPI BUONI DA SEGUIRE" / "ESEMPI DA EVITARE".
- A fine job `recall_batch_job` (rt/services/api_jobs.py) manda un Notice "Recall …: obiettivo N, generate M."

### RQ1 · Il numero è un tetto, con più giri
- Il numero non va mai al modello. Nel prompt la libertà di fermarsi resta **una frase sola**, come oggi ("Genera zero, una o più domande… nessuna quota"): non aggiungere altre frasi che insistono, rischiano di inibire il modello.
- Se dopo il primo passaggio sui gruppi non si è arrivati a N, si fa un altro passaggio sui gruppi che nel passaggio precedente hanno dato almeno una domanda. Ci si ferma quando: si arriva a N, nessun gruppo ha dato domande nuove, oppure dopo **3 passaggi**. Dal secondo passaggio il modello vede anche le domande appena create (sono già nel pool, quindi basta rileggerlo).
- Niente tagli: se l'ultimo giro supera N le domande in più restano nel pool.
- Vale per quiz, mirate, vaste e per gli originali dei tipi personalizzati.
- I campi "Quante" (Study.tsx, QuestionsPanel.tsx, EmptyGeneration.tsx) diventano "Fino a". Nient'altro cambia nei popup.

### RQ2 · Le domande già presenti di ogni tipo
- `contextualize_recall_prompt` riceve le domande dell'unità di **tutti i tipi**, ognuna preceduta dal tipo (es. "[quiz] …"), con gli stessi limiti di oggi (ultime 30, ~12k caratteri, array JSON mai troncato a metà). Titolo: "DOMANDE GIÀ PRESENTI SULL'UNITÀ (di ogni tipo: cerca altri concetti, non parafrasi)".
- Vale anche per gli originali dei tipi personalizzati.

### RQ3 · Varianti fino al numero
- Tolto il limite di 2. Dopo gli originali, il resto fino a N si riempie con varianti dei "tipi" delle unità richieste, distribuite a turno fra i tipi.
- Per contenere i costi una chiamata crea più tracce dello stesso tipo (al massimo 5 per chiamata, nuovo modello di risposta con una lista), poi la verifica indipendente le risolve **una per una**, come oggi. Quelle che non la superano si scartano senza nuovo tentativo; se mancano ancora domande, il giro successivo (RQ1, max 3) ne chiede altre.
- Prompt delle varianti: rendere esplicito che si può cambiare il contesto mantenendo struttura e procedimento, non solo i numeri (es. nei problemi di miscelazione: profumi, integratori, farmaci; nei casi clinici: età, sesso, situazione). Lo scenario di partenza resta quello del tipo della propria unità, come oggi.
- Il conteggio di varianti scartate dalla verifica va nell'avviso finale (RQ6).

### RQ4 · Voti: regole distillate, esempi pertinenti, interruttori
- **Storico completo.** Ogni voto si salva con tipo, materia della lezione, lezione, unità, testo, motivi e commento, fino a 300 voti per tipo (si tolgono i più vecchi). Il file di oggi si legge ancora (compatibilità con l'elenco vecchio, come `_fewshot_groups`).
- **Regole distillate per tipo e materia.** Una chiamata riassume i voti di quel tipo e materia (tutti, con motivi e commenti) in poche regole brevi (al massimo 8), per esempio "evita le date storiche". Si aggiornano:
  - in automatico quando un tipo e materia ha almeno **5 voti nuovi** dall'ultimo aggiornamento, all'inizio della generazione successiva di quel tipo (niente processi in background);
  - a mano con **Aggiorna ora** in Impostazioni › Domande.
  Le regole modificate a mano restano così finché l'utente non preme Aggiorna ora; l'aggiornamento automatico non le sovrascrive.
  Le regole si salvano in `<state_dir>/recall_rules.json`.
- **Esempi scelti per pertinenza.** Al posto degli ultimi 5: prima quelli della stessa materia, poi gli altri; dentro ogni gruppo quelli con più parole in comune con l'unità (calcolo locale, niente LLM); 5 buoni e 5 da evitare come oggi.
- **Forma, non contenuto.** `recall_fewshot_block` presenta gli esempi come esempi di forma e livello, non di argomento: lo scenario e i contenuti si prendono solo dall'unità. Le regole entrano nel prompt prima degli esempi.
- **Controllo prima di salvare.** Una chiamata confronta le domande nuove di un gruppo con le regole del tipo e materia e scarta quelle che le violano (una chiamata per gruppo, non per domanda). Solo se ci sono regole. Le scartate contano nell'avviso finale come "scartate dai controlli".
- **Impostazioni › Domande**, sezione nuova "Regole dai voti" sotto "Tipi personalizzati" (Section come le altre):
  - due interruttori: **Voti** (acceso di default) e **Controllo prima di salvare** (acceso di default);
  - per ogni tipo con voti, le materie con le loro regole in un campo modificabile, il numero di voti e la data dell'ultimo aggiornamento, icona **Aggiorna ora** con tooltip (job, si vede in Job come gli altri).
  - Configurazione: `recall.votes_enabled: bool = True`, `recall.presave_check: bool = True` in RecallConfig.
- **Voti spenti:** spariscono i pulsanti di voto in Study.tsx e LightweightSession.tsx, e nei prompt non entrano né esempi né regole; il controllo prima di salvare non parte. I voti già dati restano salvati.

### RQ5 · Controlli locali (senza LLM)
Un modulo nuovo (es. rt/pipeline/recall_checks.py) con soglie in costanti in cima. Ogni domanda che fallisce un controllo si scarta prima del salvataggio e conta nell'avviso finale.
- **Forma:** lunghezza minima e massima della domanda; niente segnaposto ("[...]", "XXX", "Domanda 1:", "lorem"); niente testo che si ripete (stessa frase o n-gramma ripetuto molte volte); italiano, controllato con le parole più comuni (soglia bassa: i termini tecnici sono tanti); per le vaste, scaletta non vuota.
- **Quiz:** 4 opzioni non vuote e tutte diverse, indice della corretta valido, corretta non molto più lunga delle altre (es. più di 1,8 volte la media e la più lunga di tutte).
- **Pertinenza grezza:** almeno qualche parola chiave dell'unità (parole significative, senza le comuni) nella domanda o nel materiale. Non vale per le varianti, che cambiano contesto di proposito.
- **Quasi doppioni:** somiglianza fra insiemi di parole con le domande già nel pool sulla stessa unità e con quelle dello stesso job; sopra soglia si scarta.
- **Varianti:** i numeri della traccia devono essere diversi da quelli delle versioni già usate e stare negli intervalli dichiarati dal tipo quando l'intervallo è leggibile (es. "7,10–7,50"); se c'è una soluzione, deve contenere un risultato.
- **Valutazioni delle risposte** (mirate, vaste, personalizzate): percentuali fra 0 e 100, commento non vuoto, esito coerente con le percentuali. Se non va, si rifà la chiamata una volta; se è ancora incoerente si mostra con l'esito ricavato dalle percentuali.

### RQ6 · Avviso a fine generazione
- `generate_recall_batch` e `generate_special_batch` raccolgono un riepilogo (richieste, generate, scartate dai controlli locali, scartate dal controllo prima di salvare, varianti che non hanno superato la verifica, motivo dello stop). Restituiscono sempre la lista come oggi; il riepilogo esce da un argomento in più o da un oggetto, a scelta di chi implementa, senza rompere i chiamanti.
- Il Notice di `recall_batch_job` diventa, per esempio: "Generate 6 su 10: il modello non ha trovato altri contenuti utili. 2 scartate dai controlli, 1 esercizio non ha superato la verifica." Le parti a zero non si scrivono; con N raggiunto basta "Generate 10 su 10." Il Notice si vede dove si vede oggi.

### Fuori da RQ
- Nessun cambiamento alla valutazione del classificatore, al rifornimento automatico (salvo che usa le stesse funzioni) e a Telegram (deprecato).

### FS1 · Togliere una fonte in sicurezza (14 ott)
Oggi la × su una fonte in Dettagli la toglie subito, senza conferma (SourcesSection.tsx, `DELETE /lessons/{id}/sources/{sid}` → `remove_source`). Poi `sources_pending` (rt/pipeline/source_update.py) confronta solo gli id usati con quelli attuali, quindi una fonte tolta fa comparire "Fonti nuove non ancora usate" con Estendi, che non ha senso. Il file resta su disco ma non c'è modo di rimetterla.
- **Conferma.** La × apre sempre il popup di conferma già usato per le azioni che obbligano a ricostruire. Se la fonte è già usata nel testo: "Il testo della lezione contiene ancora questa parte: per toglierla serve Ricostruisci." Se non è usata: conferma semplice.
- **Fonti tolte, non cancellate.** Il registro tiene la fonte con `rimossa_il` (data) invece di eliminarla; le viste e la pipeline la ignorano, il file resta com'è oggi.
- **Riga sopra il testo, distinta per caso:**
  - solo fonti nuove → come oggi (Estendi o Ricostruisci);
  - fonti già usate tolte → "Hai tolto N fonti già usate" con solo Ricostruisci, più l'icona "Rimetti com'era" (come per l'ordine) che le rimette al loro posto;
  - fonti mai usate tolte → nessuna riga.
  `sources_pending` e `selection()` vanno corretti di conseguenza: una fonte tolta non è mai "nuova".
- **Storico.** Una Ricostruisci dopo una rimozione è una versione come le altre (LE1j), quindi si torna indietro dalle Versioni. Il ripristino di una versione rimette anche le fonti com'erano in quella versione.
- Test: togli una fonte usata, la riga dice "tolte" e offre solo Ricostruisci; Rimetti com'era la riporta e la riga sparisce; togli una fonte mai usata, nessuna riga.


---

## Antigravity · Materiali, immagini, audio, calendario e import

### MF1 · Flusso dei materiali (docs/wireframes-4.2.6/RT-flusso-fonti.html)
Oggi: la rielaborazione riceve tutte le pagine dei materiali a ogni unità (`material_context_parts` in rt/core/materials.py, fino a 60.000 caratteri, `cap_material_parts` in rewrite.py) e il prompt non dice come usarle; dopo la rielaborazione `attach_material_pages` (rt/pipeline/material_attachments.py) fa una domanda a scelta al classificatore per ogni pagina, con tutto il testo della lezione, e sceglie una sola unità madre. Nuovo ordine: **prima l'assegnazione delle pagine alle sottounità, poi la rielaborazione**, e la stessa assegnazione serve al contesto e alle immagini.
- **MF1a · Candidate locali.** Modulo nuovo (es. rt/pipeline/material_mapping.py). Per ogni pagina dei materiali non principali, fino a 5 sottounità candidate per somiglianza con il **trascritto** della sottounità (segmenti fra start_segment_id ed end_segment_id della scaletta): parole vuote italiane tolte, compresi gli intercalari del parlato ("quindi", "diciamo", "cioè"…); parole ridotte alla radice (stemmer italiano semplice, senza dipendenze pesanti; se serve una libreria, solo una piccola e pura Python in requirements.txt); pesi TF-IDF calcolati sulla lezione, così i termini rari pesano più di quelli ovunque. Si tengono le candidate con punteggio almeno metà del migliore, al massimo 5. Pagina senza testo utile o senza candidate: non assegnata, nessuna chiamata.
- **MF1b · Classificatore sì/no.** Una chiamata per pagina con domande `noul` (JevNoulQuestion), una per candidata, tutte nella stessa chiamata. Lo stato contiene solo la pagina e le candidate (titolo e un estratto del trascritto di ciascuna, ~1.500 caratteri), mai la lezione intera. Testo della domanda: "La pagina spiega o illustra un argomento trattato in modo specifico nella sottounità «titolo», non solo la stessa materia." La pagina va a ogni sottounità con probabilità ≥ soglia (default 0,8, campo nuovo nel job "images" del classificatore, regolabile in Impostazioni › Classificatore accanto al modello). Se passa per 3 o più sottounità della stessa unità madre, va sotto l'unità madre al posto loro. Cache per pagina come oggi (digest di pagina, candidate, domande e modello). Mock deterministico per i test.
- **MF1c · Quando.** L'assegnazione gira dopo la scaletta e prima della rielaborazione, anche per Estendi e Ricostruisci; `attach_material_pages` dopo la rielaborazione sparisce (il suo stato e la graffetta restano: graffetta spenta = pagine solo contesto, nessuna immagine nel testo). Il classificatore spento o in errore: nessuna pagina assegnata, la lezione si fa lo stesso.
- **MF1d · Rielaborazione.** Ogni sottounità riceve come materiali solo il testo delle sue pagine (e di quelle assegnate alla sua unità madre), nella parte variabile del prompt dopo i segmenti, non nel prefisso in cache. Gli appunti non principali restano contesto come oggi. Regola nuova nel REWRITE_SYSTEM_PROMPT, una frase: la fonte principale guida; dalle pagine dei materiali si prendono termini, valori, definizioni, classificazioni ed esempi che approfondiscono ciò che la principale tratta in questa unità; argomenti che la principale non tocca non entrano. Con solo materiali, le pagine della principale sono già i segmenti e la regola vale per gli altri materiali.
- **MF1e · Materiale principale.** Le pagine del materiale principale diventano segmenti come oggi; le loro immagini vanno alla sottounità i cui segmenti le contengono, senza classificatore.
- Lezioni già fatte: invariate finché l'utente non fa Ricostruisci.

### IM1 · Immagini in striscia (docs/wireframes-4.2.6/RT-immagini.html)
- **IM1a · Dove.** placement.json impara le sottounità (`units: {unit_id: [hash]}` accanto a `macros`; il formato vecchio si legge ancora). build.py scrive le immagini di una sottounità subito dopo la riga del timestamp sotto `### N.M`, quelle dell'unità madre come oggi sotto `## N.`. Ordine sempre quello del documento: fonte nell'ordine delle Fonti, poi numero di pagina; le immagini aggiunte a mano o dal web restano dopo, nel loro ordine. document_edit_service.py accetta le righe immagine anche sotto i titoli delle sottounità e aggiorna placement.json.
- **IM1b · Markdown.** Un link immagine per riga, separati da una riga vuota, così ogni lettore li mette uno sotto l'altro. Nient'altro cambia nell'export.
- **IM1c · Striscia.** Le righe immagine consecutive (due o più) diventano nell'editor (LessonEditor, atomic-editor), nella vista di sola lettura (DocumentView) e nello Studio una striscia di miniature alta circa 90 px, in una riga sola che scorre di lato, con sfumatura sul bordo dove c'è altro e due frecce al passaggio del mouse; in testa la graffetta, "N pagine · nome del documento, p. a–b" e la freccina che chiude o apre tutte le strisce (preferenza ricordata con usePreference, nome minuscolo). Un'immagine sola resta com'è oggi. Quando il cursore entra nella striscia si vedono le righe markdown. Le immagini incollate a mano e gli elementi di Arricchimento restano come sono.
- **IM1d · Visore.** Clic su una miniatura: visore a schermo pieno con le sole pagine di quella striscia, didascalia (alt), "n / N", frecce, tastiera ← → Esc, miniature in basso; sul telefono swipe, senza frecce.

### AU2 · Audio leggero e unito
Oggi l'import con soli audio unisce e converte in m4a (rt/pipeline/setup.py, `merge_audio_for_transcription`, `transcode_audio_for_storage`), ma l'import con materiali e "Aggiungi fonte" salvano i wav così come sono (`add_source`), e ogni preparazione scrive un nuovo `audio-<uuid>.m4a` unito senza cancellare il precedente (source_update.py).
- **AU2a · Conversione.** Ogni audio che diventa fonte (import con materiali, Aggiungi fonte) viene prima convertito in m4a con le stesse opzioni di setup.py (AAC 96k, mono); il wav non si tiene. L'impronta è quella del file salvato. Se ffmpeg fallisce si tiene l'originale, come oggi.
- **AU2b · Unisci.** Più audio caricati insieme diventano una sola fonte, nell'ordine scelto, con l'elenco delle parti (nome e durata) dentro la fonte, mostrato in Fonti sotto il suo nome. Bottone **Unisci** (con scritta, acceso di default) nella riga "N parti · …" del popup di import e in Aggiungi fonte, solo con 2 o più audio; spento, restano fonti separate come oggi. Campo `unisci: bool` nelle due API. Un audio unito all'import è la principale; aggiunto dopo è secondario con Estendi o Ricostruisci.
- **AU2c · Pulizia.** Scrivendo un nuovo audio unito per la riproduzione si cancella quello vecchio non più indicato da info.yaml.
- **AU2d · Alleggerisci.** In Impostazioni › Spazio e cache (info.tsx, accanto alla cache) "Alleggerisci l'audio delle lezioni": prima mostra quanto spazio si libera, poi con conferma converte in m4a i wav e flac delle fonti di tutte le lezioni (anche delle fonti tolte, che servono alle versioni) e cancella gli audio uniti orfani. Job, visibile in Job. Nessuna lezione deve risultare cambiata: si aggiornano impronta e cache della trascrizione (source_update.json) della fonte convertita, mai la trascrizione stessa. Test: dopo l'alleggerimento `sources_pending` e `selection` non cambiano e nessuna trascrizione si rifà.

### UI1-UI3 · Calendario, import e trascinamento (aggiunte del 14 ott)
File: CalendarPopups.tsx, NewLessonDialog.tsx, Layout.tsx e components/shell/newLesson; nessun cambio al backend.
- **UI1 · + nel popup di un'ora del calendario.** Quando l'ora non ha una lezione collegata, accanto all'icona "Collega una lezione" (riga "Nessuna registrazione") c'è un'icona + con tooltip "Importa una lezione per quest'ora". Apre il popup di import con la data di quell'ora e quell'ora già scelta fra le ore del calendario, come se l'utente l'avesse cliccata; a import finito la lezione è collegata (stessi campi `calendar_entry_id` e `calendar_date` di oggi). Il contesto NewLessonContext impara ad aprire il popup con opzioni (data, ora, file iniziali); aperto senza opzioni si comporta come oggi.
- **UI2 · Contrasto dell'ora scelta nel popup di import.** Oggi l'ora scelta si distingue appena dalle altre (`border-primary ring-1 bg-primary/10`, e la barretta colorata è uguale su tutte). Nuovo stile, in tema chiaro e scuro: ora scelta con bordo di 2 px del colore primario, sfondo primario più pieno (circa /20) e barretta primaria; le altre ore con bordo normale e barretta grigia (muted). Il bordo dell'ora scelta deve avere un contrasto di almeno 3:1 con lo sfondo in entrambi i temi (controllarlo con i colori dei token). Le ore già registrate restano come oggi.
- **UI3 · Trascinare file su tutta la pagina.** Quando si trascina sulla finestra di RT un file che l'import accetta (gli stessi tipi del campo del popup: audio, materiali, .zip), compare sopra tutta la pagina un velo con la scritta "Rilascia per importare". Rilasciando, si apre il popup di import con quei file già caricati, che li smista come se fossero stati trascinati nel suo riquadro (audio e materiali, oppure pacchetti .zip; stessa regola e stesso messaggio di oggi se sono mescolati). Il velo non compare per file non accettati, per testo o link trascinati, quando il popup di import è già aperto (lì vale il suo riquadro) e mentre si trascina dentro un editor o un pannello che accetta già file (es. Fonti in Dettagli). Si chiude se il trascinamento esce dalla finestra o con Esc.



---

## 4.2.6b3 · Calendario e Arricchimento (Codex, branch rt426b3/codex)
15 ott 2026, richiesto da Attilio dopo la prova della b2. Un solo agente, nessun conflitto previsto. Valgono le "Regole per tutti" (niente migrazioni; se servisse davvero: 0019, down 0018).

### CA2 · Collegare una lezione alle ore seguite
Oggi un'ora segnata "seguita" senza lezione (anche quando la lezione collegata è stata cancellata) risulta "già registrata": `is_recorded` in `_resolve_day_events` (rt/services/calendar_service.py, `lesson_summary is not None or effective_status == "seguita"`). Il popup di import (NewLessonDialog, GET /calendar/day) la mostra grigia e non selezionabile.
- **CA2a.** Un'ora è registrata solo se ha una lezione (`is_recorded = lesson_summary is not None`). Un'ora "seguita" senza lezione si può scegliere nell'import e collegare dal popup dell'ora (Collega una lezione, +), come un'ora "da seguire". Collegando, lo stato resta "seguita".
- **CA2b.** Le ore **annullate** (stato dell'ora o del giorno) non accettano una lezione: nel popup di import restano visibili ma non selezionabili, con tooltip "Ora annullata"; nel popup dell'ora non compaiono "Collega una lezione" e il +; l'API dell'import (`calendar_entry_id` in rt/api/routers/jobs.py) e `link_lesson` rifiutano un'ora annullata con un errore chiaro. Tutti gli altri stati (seguire, seguita, non seguita, saltare) accettano una lezione.
- **CA2c.** Cancellando una lezione, il collegamento a mano della sua ora (`CalendarEntryState.lesson_id`) si azzera nella stessa transazione; lo stato "seguita" resta.
- Test: backend (ora seguita senza lezione importabile e collegabile, annullata rifiutata da import e link, cancellazione che libera l'ora) e un e2e nello spec esistente del calendario/import (segno seguita → importo per quell'ora → collegata).

### AR1 · Trascinare file in "Aggiungi PDF o foto"
In Arricchimento › Media della lezione (frontend/src/components/lesson/panels/EnrichmentPanel.tsx) il riquadro "Aggiungi PDF o foto" accetta file trascinati sopra di sé (stessi tipi di ACCEPT), con lo stesso evidenziamento del riquadro delle Fonti; il campo "Scegli file" resta. I file trascinati si aggiungono a quelli scelti; tipi non accettati ignorati con lo stesso messaggio delle Fonti. Il velo globale "Rilascia per importare" (GlobalFileDrop) non compare mentre si trascina sul riquadro (come per le Fonti). Test vitest.

### AR2 · Avanzamento di "Aggiungi PDF o foto"
`run_add_images` e i suoi passi (rt/pipeline/add_images.py) non chiamano mai `ctx.progress`: la barra resta a 0% per tutto il job. Passare il contesto del job (`add_images_job` in rt/services/job_handlers.py) e segnalare i passi con conteggio, nello stesso stile degli altri job: "Leggo le pagine i/N" (estrazione e, solo dove serve, descrizione), "Cerco immagini sul web" (se c'è la ricerca), "Colloco le immagini i/N". La percentuale deve salire durante il job. Test che il job emette progressi crescenti.

### AR3 · Arricchimento allineato all'import con materiali
Oggi sono due flussi diversi:
- **Import audio + PDF (MF1, rt/pipeline/material_mapping.py).** Ogni pagina del PDF va alle sottounità candidate (TF-IDF, `find_candidate_subunits_for_page`) con il sì/no del classificatore (`classify_material_page`, job image_unit_judge, soglia), sotto la macro solo se tocca 3 o più sottounità della stessa macro. Il testo della pagina viene dal PDF; la Vision serve solo per le pagine senza testo.
- **Arricchimento › Aggiungi PDF o foto (rt/pipeline/add_images.py).** Ogni pagina viene descritta con il modello visivo (image_description), poi `judge_images_by_macro` sceglie UNA macro per immagine confrontandola con tutta la lezione: le immagini non arrivano mai alle sottounità e si ammassano dove il giudice preferisce (nella lezione di Attilio, l'unità 1).

Cosa cambia:
- **AR3a · PDF e foto caricati.** `run_add_images` con `input_path` legge le pagine come l'import: per un PDF il testo con `page.get_text()` e la pagina renderizzata (stesso rendering di oggi); la descrizione con il modello visivo solo per le pagine senza testo e per le foto singole (la descrizione fa da testo). Poi per ogni pagina: candidate con `find_candidate_subunits_for_page` e decisione con `classify_material_page` (stessa soglia, stesso job, stessa cache per pagina). Pagina approvata → sottounità, o macro se 3+ sottounità della stessa macro. Pagina senza candidate o rifiutata → non collocata (resta nei Media della lezione, come oggi le immagini "none"). Estrarre le parti comuni da material_mapping.py in funzioni riusabili invece di copiarle; `classify_material_page` oggi vuole una fonte (`source.id`, `source.impronta`): usare come identità l'impronta del file caricato.
- **AR3b · Solo posizionamento.** Non si rifà la rielaborazione e le pagine non entrano nel contesto della riscrittura (`pages_by_unit`/`pages_by_macro` di material_mapping non cambiano). Il posizionamento si aggiunge a placement.json (`units` e `macros`) senza togliere le immagini delle fonti materiali, quelle messe a mano o dal web e quelle già collocate da caricamenti precedenti.
- **AR3c · Immagini dal web.** Restano con il giudice di oggi (`judge_images_by_macro`) per non allargare il lavoro, ma la query è già per sottounità: un'immagine web trovata per una sottounità va a quella sottounità senza giudice. Il giudice per macro resta solo per le immagini senza unità di provenienza.
- **AR3d · Descrizioni.** Le immagini collocate con AR3a hanno in descriptions.json `source` come oggi (`pdf:nome#pagina`, `folder:nome`) e `alt_text` "nome del file, pagina N"; la striscia e il visore le mostrano come quelle dei materiali.
- Test: un PDF di prova con pagine di testo su argomenti di sottounità diverse finisce nelle sottounità giuste (mock del classificatore), una pagina senza testo passa dalla Vision, una foto passa dalla descrizione, nessuna immagine esistente (materiale, a mano, web) viene tolta, la riscrittura non viene toccata. Aggiornare i test di add_images che si aspettano il giudice per macro, scrivendo il motivo nel commit.

### Ordine
CA2, AR1, AR2, AR3 (a, b, d, poi c). Sezione "## 4.2.6b3" in cima a CHANGELOG.md con "### Correzioni" (CA2, AR1, AR2) e "### Novità" (AR3), scritta per l'utente.
