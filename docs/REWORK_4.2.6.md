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

---

## 4.2.6b5 · Media delle fonti, Arricchimento più ricco, popup Chiedi, LaTeX (giro notturno Codex + Antigravity)
15 ott 2026 sera, approvato da Attilio nel thread "Raccolta feature 4.2.6". Un solo giro notturno, diviso per file. Valgono le "Regole per tutti" in cima (cartella dati separata, niente migrazioni: se servisse davvero Codex 0019 e Antigravity 0020, down 0018). Regola in più, ripetuta da Attilio: **azioni come icone con tooltip, mai bottoni con scritta**; l'unica eccezione è il popup di conferma di "Sostituisci la pagina" (Annulla / Sostituisci).
Wireframe approvati in docs/wireframes-4.2.6/: RT-media.html (MS1, ritaglio, AR5), RT-chiedi.html (CH2), RT-fonti-unite.html (FU1). Aprirli e seguirli; dove il wireframe e il piano dicono cose diverse vale il piano.

### Divisione
| Agente | Branch | Lavoro | File principali (gli altri non li tocca) |
|---|---|---|---|
| Codex | rt426b5/codex | AR4, LX1, FP1, FU1, SN1, CM1, CH2 | rt/pipeline/material_mapping.py, rt/core/materials.py, l'estrazione delle pagine usata da add_images (extract_images e ExtractedImage), rt/core/config.py (soglia), rt/llm/prompts.py, il prompt della sostituzione della verifica, NewLessonDialog.tsx, jobs.py (solo `principale`), materials_lesson_service.py, SourcesSection.tsx, lessonStudyNotes.ts, LessonEditor.tsx, Study.tsx, StudyNotePopup.tsx, Layout.tsx, DocumentMenu.tsx, DocumentView |
| Antigravity | rt426b5/antigravity | MS1 (media di tutte le fonti, inserimento a mano, colloca le selezionate, togli dal testo, ritaglio, proporzioni), AR5 | EnrichmentPanel.tsx e componenti nuovi del pannello, lessonImages.ts, GlobalFileDrop.tsx e globalFileDropUtils.ts, rt/api/routers/images.py, editor_media_service.py o un servizio nuovo dei media, run_add_images in add_images.py (solo il parametro della modalità "Solo pagine" e la collocazione delle selezionate), job_handlers.py e jobs.py (solo il job dei media), CSS delle immagini in index.css, ImageViewer |
add_images.py, jobs.py, index.css, docs/openapi.json, schema.d.ts e CHANGELOG.md li toccano entrambi in punti diversi: i conflitti li risolvo io alla fusione. Antigravity non cambia material_mapping.py: chiama `place_page_in_outline` com'è.

### Codex

#### AR4 · Arricchimento meno conservativo, senza slide vuote
Caso: Patologia generale 2 (PDF di 33 pagine, 6 immagini collocate). Vale per l'import con materiali e per Arricchimento › Aggiungi PDF o foto, che passano entrambi da `place_page_in_outline` / `classify_material_page` (rt/pipeline/material_mapping.py). Prova fatta sul Mac di Attilio: a soglia 0,7 le finestre battono i primi 1.500 caratteri; la domanda sul contenuto scarta la scaletta ma non copertina e titoli di sezione, che servono la regola delle poche parole.
- **AR4a · Pagine vuote fuori prima del giudice, senza modello.** Per ogni documento si tolgono dal testo di ogni pagina le righe ripetute su quasi tutte le pagine (intestazioni, piè di pagina, nome del corso; es. presenti in almeno il 60% delle pagine, documenti di almeno 4 pagine). Se restano poche parole (soglia nel codice, es. meno di 12 parole significative) e la pagina non ha figure, è scartata: niente candidate, niente chiamata (copertina, titolo di sezione, "Grazie", "Domande?"). Se ha poche parole ma una figura (immagini incorporate nel PDF o disegni vettoriali estesi; nelle pptx le immagini della slide), passa dalla descrizione visiva come le pagine senza testo di oggi (la descrizione fa da testo). Serve un'informazione "ha figure" per pagina nella lettura dei materiali e in `extract_images`.
- **AR4b · Finestre al giudice.** Al giudice di ogni candidata non vanno più i primi 1.500 caratteri del parlato (`c.transcript[:1500]`) ma i 2 passaggi (~600 caratteri ciascuno, tagliati a confine di frase) della sottounità più simili alla pagina (TF-IDF già usato per le candidate). La chiave della cache include le finestre.
- **AR4c · Domanda sul contenuto.** Nella stessa chiamata del giudice (stessa `decision`, una domanda in più) si chiede se la pagina ha contenuto didattico vero; la domanda nomina copertina, titolo, indice, scaletta, ringraziamenti, vignette e immagini decorative. Se la risposta è sotto soglia la pagina non va da nessuna parte.
- **AR4d · Soglia 0,7.** Il default della soglia del job immagini (classifier_job "images", rt/core/config.py) passa da 0,8 a 0,7. Una configurazione salvata con esattamente 0,8 (il vecchio default) passa a 0,7 una volta sola, nello stile delle altre migrazioni della configurazione; valori diversi scelti dall'utente restano.
- **AR4e · Una pagina, un posto.** Delle sottounità approvate la pagina va a quella con probabilità più alta; sotto la macro solo se 3 o più sottounità della stessa macro sono approvate (regola di oggi). Le pagine scelte restano il contesto della rielaborazione (pages_by_unit/pages_by_macro): non cambiare questa parte.
- Test (mock del classificatore): copertina, titolo di sezione, scaletta e una vignetta senza somiglianza col parlato restano fuori; uno schema senza testo con figura entra; le righe ripetute non contano come parole; la finestra scelta è quella giusta; la soglia migrata. Se cambiano golden della pipeline, il motivo nel commit.

#### LX1 · Formule in LaTeX nella rielaborazione, chimica compresa
REWRITE_SYSTEM_PROMPT (rt/llm/prompts.py) non dice nulla sulle formule e il modello scrive pedici e apici Unicode o HTML (es. M_j = {i ∈ I : d_ij ≤ T}). Editor, lettura, Studio e lettura veloce rendono già `$...$` e `$$...$$` (Temml; lettura veloce con pausa adattiva in rsvp.ts).
- Un punto in più negli obiettivi del prompt, breve: formule, insiemi, variabili con indici, frazioni ed equazioni in LaTeX (`$...$` in riga, `$$...$$` a blocco), mai pedici o apici Unicode né `<sub>`/`<sup>`. Anche la chimica: reazioni a blocco con `$$\mathrm{...}$$` e `\rightarrow` / `\rightleftharpoons`, specie nel testo in riga come `$\mathrm{CO_2}$`; mai `\ce` (Temml non ha mhchem). Testo normale e sigle non chimiche restano testo.
- La stessa regola nel prompt che propone il testo sostitutivo nella verifica.
- Il prefisso in cache cambia una volta: va bene. Le lezioni già fatte cambiano solo con Ricostruisci.
- Test: il prompt contiene la regola; nessun golden da cambiare oltre ai prompt fissati nei test, con il motivo nel commit.

#### FP1 · Fonte principale sempre scelta nell'import senza audio
Oggi in NewLessonDialog con soli documenti la stellina parte vuota e, se non la tocchi, il server sceglie il documento con più pagine (materials_lesson_service.py, `max(... page_count ...)`).
- Senza audio il primo file caricato è subito la principale (stellina piena) con una frase sotto la lista: "La scaletta segue «nome»; la stellina sceglie un altro file". Togliendo la principale, passa al primo file rimasto. Il popup manda sempre `principale`.
- Il server, se `principale` manca (client vecchi, API), prende il primo documento caricato invece di quello con più pagine.
- Con audio la principale resta l'audio, come oggi.
- Test: vitest del popup e pytest del servizio.

#### FU1 · Fonti unite nel pannello Fonti
Wireframe RT-fonti-unite.html. Una registrazione unita da più parti appare nel pannello Fonti (SourcesSection.tsx) come una riga sola "Registrazione unita · durata", con un chip "N parti" che apre l'elenco delle parti a tutta larghezza, una barra con le parti in proporzione alla durata e nomi accorciati al centro. Tutto resta dentro il pannello anche a 390 px (min-w-0, testo troncato): e2e a 390 px che controlla che niente sfori la card.

#### SN1 · Sottolineature di Verifica e Chiedi solo col pannello aperto
Oggi i passaggi verificati o chiesti hanno sempre la sottolineatura a puntini nell'editor e nella lettura (lessonStudyNotes.ts; LessonEditor.tsx manda sempre tutte le note con `setStudyNotes`) e nello Studio (Study.tsx, span `.rt-sn`).
- Editor e lettura: le sottolineature compaiono solo mentre il pannello Dettagli › Verifiche e domande è aperto (parametro `panel=note`); chiuso il pannello spariscono. Il clic su una nota del pannello porta al passaggio e lo evidenzia, come oggi.
- Studio: si vede solo il passaggio della nota il cui popup è aperto; chiuso il popup, nessuna sottolineatura.
- Test vitest per editor e Studio.

#### CM1 · Menu del tasto destro sempre di RT nel testo
Oggi (DocumentMenu.tsx, LessonEditor.tsx) il menu RT esce solo con una selezione fatta prima del clic destro o su un titolo, altrimenti esce il menu del browser. Il ctrl+clic del Mac arriva come mousedown con button 0 e lascia `selectedBefore` vecchio; in lettura Safari seleziona la parola prima del contextmenu, nell'editor no.
- Nel testo della lezione (editor e lettura, stesso comportamento) il clic destro apre sempre il menu RT. Senza selezione le voci valgono per il paragrafo o l'unità sotto il clic.
- ⌥ + clic destro apre il menu del browser (correttore, strumenti di scrittura). In fondo al menu RT una riga piccola e attenuata lo ricorda: "⌥ + clic destro: menu del browser".
- ctrl+clic trattato come clic destro.
- Test vitest; e2e solo se uno spec esistente copre già il menu.

#### CH2 · Popup Chiedi/Verifica che resta nello schermo, ridimensionabile, invio su iPhone
Wireframe RT-chiedi.html (v2). Cause (StudyNotePopup.tsx): posizione calcolata con 340 px fissi, nessuna altezza massima né scorrimento, quindi esce dallo schermo con campo e pulsante; su iPhone il foglio sta sotto la barra delle sezioni (Layout.tsx, stesso z-50 e dopo nel DOM) che copre il pulsante; invio solo con ⌘↵; risposta in markdown grezzo.
- **Desktop.** Altezza massima = schermo meno un margine, posizione dall'altezza vera misurata dal vivo (ResizeObserver, anche mentre arriva la risposta). Struttura: intestazione / centro che scorre / fondo fisso con campo e freccia d'invio (icona). Citazione su 2 righe con "Mostra tutto". ↵ invia, ⇧↵ va a capo. Trascinabile dall'intestazione e ridimensionabile da angolo e bordi (min 320×240), sempre dentro lo schermo; posizione e misura tenute per la sessione; rientra se la finestra cambia; icona ⤢ che lo allarga a pannello a destra alto quanto lo schermo; doppio clic sull'intestazione torna alla misura iniziale. Dopo la risposta il fondo ha le icone Copia e "Salvata in Dettagli".
- **iPhone.** Foglio sopra la barra delle sezioni, a tre altezze (bassa, metà, piena) con maniglia; parte a metà, va a piena con una risposta lunga; il campo resta sopra la tastiera (visualViewport).
- **Risposta formattata.** La risposta oggi è testo grezzo (whitespace-pre-wrap, `**` e `###` visibili): renderla in markdown sanificato con lo stesso renderer già usato nell'app per il markdown (titoli, grassetti, elenchi, formule), senza HTML grezzo.
- Vale per Chiedi e per Verifica. Test vitest (posizione dentro lo schermo con una citazione lunga, ↵ e ⇧↵, risposta formattata) ed e2e a 390 px che il pulsante d'invio sia visibile e cliccabile sopra la barra.

#### Ordine Codex
LX1, FP1, AR4 (a, b, c, d, e), SN1, CM1, CH2, FU1. Sezione "## 4.2.6b5 — <data>" in cima a CHANGELOG.md con "### Novità" e "### Correzioni", scritta per l'utente, senza codici dei task; le righe di Antigravity le aggiungo io alla fusione.

### Antigravity

#### MS1 · Media della lezione: tutte le pagine delle fonti, inserite a mano o collocate quando vuoi
Wireframe RT-media.html (v8). Oggi in Arricchimento › Media della lezione si vedono solo le immagini in descriptions.json e il clic porta al testo; le pagine dei PDF importati come materiali (materials/<impronta>/pages.json, immagini `page-N-i.png`) che il giudice non ha scelto non si vedono da nessuna parte; nell'editor si possono solo trascinare o incollare file dal computer (lessonImages.ts).
- **MS1a · Un elenco unico, raggruppato per fonte.** Il pannello resta quello di oggi (stesso posto, stesso stile, stesse sezioni). La griglia mostra tutte le pagine e le foto: quelle in descriptions.json (Arricchimento, web, editor, materiali già collocati) e le pagine dei materiali delle fonti non ancora copiate in assets. Raggruppate per fonte (nome del file; "Dal web"; "Dall'editor"), in ordine di pagina. Didascalia "Pag. N · 2.1" se è nel testo (unità dove compare), "Pag. N · non usata" altrimenti. Un endpoint di elenco nuovo o esteso (GET /lessons/{id}/images o uno nuovo dei media) che restituisce per ogni elemento: fonte, pagina, url della miniatura, se è già in assets, unità in cui compare nel documento. Le pagine dei materiali si servono dal loro file senza copiarle finché non servono.
- **MS1b · Selezione.** Clic seleziona (secondo clic toglie), ⇧+clic intervallo, doppio clic apre il visore (tocco lungo su iPhone). Icona accanto al nome di ogni fonte "Seleziona tutte le pagine di questa fonte" (secondo clic deseleziona), icona "Seleziona tutte" nella barra, ⌘A col fuoco sulle miniature, Esc annulla.
- **MS1c · Barra della selezione, solo icone con tooltip:** Inserisci al cursore, Colloca in automatico, Togli dal testo, Annulla. Il ritaglio NON è nella barra (vedi MS1f).
  - *Inserisci al cursore*: le pagine selezionate entrano nell'editor al punto del cursore con la stessa regola del drop di oggi (mai sopra titoli e timecode, lessonImages.ts); più pagine diventano una striscia (righe consecutive, come IM1). Senza un editor aperto con il cursore nel testo, l'icona è spenta con il tooltip "Clicca nel testo dove vuoi le pagine". Una pagina dei materiali non ancora in assets si copia prima in assets/images con una chiamata che restituisce `EditorImage` (stesse regole di lock e lease di `upload_image`; descrizione con `source` "material:<id>:<pagina>" e `alt_text` "file, pagina N"). Il collegamento fra pannello ed editor passa da un evento come `EDITOR_SCROLL_EVENT`, gestito dentro lessonImages.ts, senza cambiare LessonEditor.tsx. Su desktop si può anche trascinare una miniatura nel testo (linea tratteggiata dove cade). Le immagini inserite a mano sono come quelle caricate dall'editor oggi: stanno solo nel testo, non in placement.json, e una nuova collocazione automatica non le tocca.
  - *Colloca in automatico*: avvia in background la collocazione solo delle pagine selezionate, con lo stesso giudice dell'Arricchimento (`place_page_in_outline`, senza cambiarlo), aggiungendo a placement.json senza togliere nulla; avanzamento come Aggiungi PDF o foto. Solo posizionamento: nessuna rielaborazione.
  - *Togli dal testo*: toglie dal documento i riferimenti alle immagini selezionate e le toglie da placement.json; restano nei media come "non usata". Le modifiche al documento rispettano la sessione di modifica (lease) come `upload_image`; se l'editor è aperto, la modifica passa dall'editor (evento) così non si perde nulla di non salvato. Non toccare le fotografie delle versioni (history/*/).
- **MS1d · Caricamento in due modi.** Nel riquadro "Aggiungi PDF o foto" un'icona a due stati (come Unisci): "Colloca in automatico" (il flusso di oggi) o "Solo pagine" (il PDF diviso in pagine e salvato nei media, nessun modello, nessun costo, nessuna collocazione). L'ultima scelta resta ricordata (preferenza lato server come le altre del pannello o localStorage protetto da try/catch: la più semplice coerente con il resto). In `run_add_images` basta un parametro che salta descrizione e collocazione; le pagine senza testo in modalità "Solo pagine" restano senza descrizione finché non vengono collocate.
- **MS1e · Proporzioni.** Il ritaglio e le pagine sono immagini normali con le loro dimensioni. Miniature (griglia del pannello, striscia `.rt-strip .thumb`, `.rt-vstrip`) con `object-fit: contain` su fondo neutro invece di `cover`, così strisce lunghe, slide 16:9 e pagine A4 si vedono intere. Nel testo (`.rt-document img`, `.rt-editor-image img`) altezza massima circa 70vh (le larghezze restano come oggi, nessun ingrandimento oltre la misura vera); il clic apre il visore come oggi.
- **MS1f · Ritaglio.** Piccola icona forbici in alto a destra di ogni miniatura, visibile al passaggio del mouse (sempre visibile su touch, `@media (hover:none)`). Apre la vista di ritaglio: riquadro rettangolare libero con 4 maniglie, anche touch; icona "Pagina intera" che riporta il riquadro a tutta la pagina; niente rotazioni o filtri. Due icone di conferma:
  - *Salva come nuova immagine* (predefinita): animazione di sdoppiamento dalla pagina; nuova immagine nei media con nome "Pag. N · ritaglio K" (K cresce per pagina e non si riusa) e piccolo segno forbici; l'originale resta com'era. Si può ritagliare più volte la stessa pagina e anche un ritaglio.
  - *Sostituisci la pagina*: popup di conferma (unica eccezione con bottoni a testo: Annulla / Sostituisci) che dice in quali unità la pagina compare nel testo ("È nel testo delle unità 2.1 e 2.4: lì comparirà il ritaglio"). Confermando, il ritaglio prende il posto della pagina nel documento e in placement.json, nome "Pag. N (ritagliata)"; il file originale resta su disco per le versioni.
  - Il ritaglio si fa sul server con Pillow (coordinate relative 0-1 della pagina), file nuovo con il suo hash, descrizione con `source` dell'originale, `crop_of` e il nome.
- Test: pytest dei nuovi endpoint (elenco con pagine dei materiali, copia in assets, ritaglio nuovo e sostituisci, togli dal testo che non tocca history, colloca le selezionate che non toglie nulla, modalità Solo pagine senza chiamate ai modelli) e vitest della griglia (selezione, ⇧, seleziona tutte, icona spenta senza cursore). E2e: dalla griglia, inserire due pagine al cursore e trovarle nel testo; ritagliare come nuova immagine.

#### AR5 · Trascinare PDF o foto col pannello Arricchimento aperto
Oggi GlobalFileDrop apre il velo a tutto schermo dell'import di una nuova lezione anche col pannello Arricchimento aperto: l'esclusione `data-file-drop-target` vale solo sul riquadro di caricamento già aperto, che il velo copre. Nuovo: col pannello Arricchimento aperto, se i file trascinati sono solo PDF e immagini, il velo grande non compare; si illumina il pannello ("Rilascia per aggiungere ai media della lezione", wireframe RT-media.html schermo 2) e al rilascio, ovunque nella pagina, si apre il riquadro di caricamento con quei file. Audio, zip e file misti aprono l'import normale. Test vitest di GlobalFileDrop ed e2e con DataTransfer simulato.

#### Ordine Antigravity
AR5, MS1e, MS1a, MS1b, MS1c (Inserisci al cursore, poi Togli dal testo, poi Colloca in automatico), MS1d, MS1f. Niente CHANGELOG.md: righe per l'utente nella descrizione della PR.
