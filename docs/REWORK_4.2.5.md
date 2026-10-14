# Piano 4.2.5

12 ott 2026, approvato da Attilio. I wireframe approvati sono in docs/wireframes-4.2.5/ (calendario, import, fonti e materie, pannelli, linea audio).

## Regole per tutti i lotti
- **Innestare, non rimpiazzare.** Gli elementi che esistono restano dove sono e come sono: lettore audio, contenuto dei pannelli, campi e bottoni del popup di import, voci della barra laterale. Si aggiungono le parti nuove e si adatta solo quello che il task nomina.
- Estetica di RT: icone con tooltip, non bottoni con scritte. Niente controlli o stati che il piano non chiede.
- Le fonti non si modificano mai. Ogni aggiornamento della lezione parte solo su richiesta e si può annullare.
- Test mirati per passo; suite completa due volte; e2e una volta alla fine (metodo della 4.2.4b3). Non si aggiornano golden o test esistenti per far passare cambiamenti che il piano non chiede.
- Migrazioni assegnate per evitare conflitti: Codex 0015 (down_revision 0014), Antigravity 0016 (down_revision 0014; alla fusione la riaggancio a 0015).
- CHANGELOG scritto per l'utente, senza codici dei task.

## Branch
Il branch beta claude/rt-4.2.5-beta nasce da main dopo la 4.2.4 stabile. Se Attilio vuole partire prima, i branch dei lotti partono da claude/rt-4.2.4-beta e il beta 4.2.5 si allinea a main prima della prima release (i tag beta devono discendere da main).

## Lotti
| Lotto | Codex | Antigravity |
|---|---|---|
| b1 | LE1 backend + RC1 | CA1 calendario (completo) |
| b2 | DS1, MA1, LE1i-k backend (40%) | Interfaccia di tutta la b2 + AP1, WS1, AU1, PN1 completi (60%) |
| b3 | accorpata nella b2 (Attilio, 12 ott sera) | |
| b3 (nuova, 13 ott) | Recall: tetto, varianti, voti, controlli locali (tutto) | — |

I file sono divisi in modo che i due agenti dello stesso lotto non si tocchino. b2 parte dopo la fusione di b1, b3 dopo b2.

---

## 4.2.5b1

### Codex · LE1 backend (lezioni espandibili)
Stato di oggi: una lezione ha un audio (info.yaml `file_audio`), un trascritto grezzo, segments.json con ID `seg_{index:06d}` legati all'indice (rt/core/models.py, validatore su id = index), fasi prepare → outline → rewrite → review → build con impronte e "da rifare" (rt/core/idempotency.py).

- **LE1a · Fonti.** Nuovo `sources.json` nella cartella della lezione: elenco ordinato di fonti `{id, tipo: audio|appunti|materiale, file, impronta, aggiunta_il, ordine}`. Per le lezioni esistenti si crea da solo con una fonte audio (nessuna migrazione dei file). Le fonti non si modificano: si aggiungono o si tolgono.
- **LE1b · ID stabili.** L'ID di un segmento resta `seg_NNNNNN`, ma diventa un contatore di arrivo: non dipende più dalla posizione. `index` resta la posizione nell'ordine della lezione. Togli il vincolo id = index e adatta chi lo presuppone (asr_risk.py, segments.py, mock in llm/client.py). Ogni segmento sa da quale fonte viene (`source_file` esiste già: usa l'id della fonte). Aggiungere una parte non cambia gli ID dei segmenti esistenti, quindi decisioni, correzioni, evidenziazioni, note di studio e stato delle unità restano validi.
- **LE1c · Aggiunta di una parte di audio.** Trascrizione solo della parte nuova; l'audio della lezione si ricompone nell'ordine delle fonti (stessa logica dell'import con più file); i tempi dei segmenti delle parti successive si spostano. Appunti scritti: testo diviso in paragrafi, segmenti con flag `appunti` e tempi della posizione in cui sono inseriti (durata zero non ammessa: usa la convenzione più semplice e scrivila nel commit; l'interfaccia non mostrerà il timecode dei segmenti `appunti`).
- **LE1d · Scaletta estesa.** Nuova modalità dell'outline: riceve la scaletta attuale come fissa e i segmenti nuovi, e può solo aggiungere unità o allungare le unità confinanti. Le unità esistenti tengono id e titolo. Validazione: ogni segmento coperto, nessuna unità esistente spostata. Modalità "Ricostruisci" = outline da zero come oggi.
- **LE1e · Rielaborazione mirata.** Si rielaborano solo le unità nuove o con segmenti cambiati. Le altre restano, con le loro decisioni.
- **LE1f · Fotografia e Annulla.** Prima di ogni aggiornamento si salvano sources.json, segments.json, outline.json, draft.json, review_decisions.json (cartella `history/<timestamp>/`). "Annulla aggiornamento" li rimette. Una sola fotografia per volta basta.
- **LE1g · API.** `GET /lessons/{id}/sources`; `POST /lessons/{id}/sources` (upload audio o testo appunti; i materiali arrivano in b2); `DELETE /lessons/{id}/sources/{sid}`; `GET` con lo stato "fonti nuove non ancora usate"; `POST /lessons/{id}/update` con `mode: extend|rebuild` che avvia il job; `POST /lessons/{id}/update/undo`. Rigenera openapi.json e schema.d.ts: Antigravity li userà in b2.
- **LE1h · Lezione senza audio.** Una lezione può nascere senza audio (solo appunti ora, materiali in b2). Se arriva l'audio dopo: Estendi o Ricostruisci come sopra.

### Codex · RC1 (rielaborazione con le unità precedenti)
In rt/pipeline/rewrite.py e rt/llm/prompts.py:
- Ordine del prompt per la cache: sistema; scaletta; (posto per i materiali, b2); unità precedenti già rielaborate, in ordine; poi in coda ID e titolo dell'unità, 90 s prima, segmenti, 90 s dopo. Oggi ID e titolo stanno in testa: spostali. Il trascritto delle unità successive non si passa.
- Cache: estendi `_cache_lesson_prefix` (rt/llm/client.py) al prefisso che cresce (marcatore sull'ultima unità precedente) per OpenRouter con Anthropic e Gemini; gli altri provider fanno da soli.
- Contesto senza stime: la lunghezza massima viene dai metadati del modello (context_length di OpenRouter, già letto per i prezzi in rt/llm/pricing.py); i token usati vengono da usage della chiamata precedente (prompt_tokens + completion_tokens). Se uno dei due manca non si taglia niente. Se si supera, si tolgono le unità più vecchie.
- Rielaborando una sola unità, riceve le precedenti già presenti nel draft.

Ordine dei commit: LE1a, LE1b, LE1c, LE1d, LE1e, LE1f, LE1g, LE1h, RC1, poi la PR verso il beta. Migrazione DB solo se serve (0015).

### Antigravity · CA1 calendario
Wireframe: docs/wireframes-4.2.5/RT-calendario.html. Tutto il calendario, backend e frontend.
- **CA1a · Dati.** Migrazione 0016: tabelle per la settimana tipo (con data di inizio validità), le ore di una settimana precisa (aggiunte, tolte o spostate solo quella settimana), lo stato di un'ora (da seguire, seguita, non seguita, da saltare, annullata), lo stato del giorno intero, le note e il collegamento ora → lezione. Router `/calendar`.
- **CA1b · Collegamento automatico.** Una lezione con stessa data, ora e materia si collega all'ora e la segna Seguita (calcolato, non scritto a mano; il collegamento manuale vince).
- **CA1c · Pagina Calendario.** Settimana su Mac, giorno su iPhone, popup al posto del pannello, riepilogo nel bottone ⓘ, matita che si divide in due icone (solo questa settimana / settimana tipo), solo icona di stato nei blocchi con tooltip, menu del giorno intero.
- **CA1d · Barra laterale.** Importa da solo in alto; poi Lezioni (nuova icona, BookOpen) e Calendario (icona Calendar); in basso Job e Impostazioni. Su iPhone il Calendario entra nella tab bar.
- **CA1e · API per l'import.** `GET /calendar/day?date=` con le ore del giorno e lo stato "già registrata": in b2 lo usa il popup di import.
Non toccare rewrite.py, prepare.py, outline.py, segments né le API delle lezioni: sono di Codex.

---

## 4.2.5b2

Branch: Codex su `rt425b2/codex`, Antigravity su `rt425b2/antigravity`, entrambi da claude/rt-4.2.5-beta dopo la b1.1. Wireframe: docs/wireframes-4.2.5/RT-import.html (import) e RT-fonti-materie.html (fonti della lezione, Materie, Consigliato).
La b3 è accorpata qui (Attilio, 12 ott sera): lavoro diviso 60% Antigravity, 40% Codex. Codex fa il backend di DS1, MA1 e LE1i-k; Antigravity tutta l'interfaccia della b2 e, completi di backend e interfaccia, AP1, WS1, AU1 e PN1. Il punto di contatto è il contratto API qui sotto: Antigravity lo usa con tipi scritti a mano e mock nei test, alla fusione passo io ai tipi generati.
Migrazioni: solo Codex, revision 0018 con down_revision 0017. Antigravity non ne crea: l'indice FTS5 di AP1 è un dato derivato creato e riempito all'avvio (CREATE VIRTUAL TABLE IF NOT EXISTS) e la chiave di AP1 sta nella configurazione come la chiave API di oggi.
File di backend di Antigravity: solo i moduli nuovi di AP1, il codice della verifica contestuale (WS1) e quello che serve ad AU1. Codex non li tocca. rt/api/app.py, docs/openapi.json e schema.d.ts li cambiano entrambi: i conflitti li risolvo io.
Cartella dati: chi avvia RT fuori dalla suite esporta prima `RT_DATA_DIR` verso una cartella di prova (es. ~/rt-dev-data), mai la ~/.rt vera.

### Contratto API della b2
- `GET /subjects` → `[{nome: str, lezioni: int}]`, ordinato senza maiuscole; unisce materie registrate, delle lezioni e del calendario, senza doppioni (confronto casefold, vince la grafia registrata).
- `POST /subjects` body `{nome}` → 201 `{nome, lezioni}`; 409 `subject_exists` se c'è già.
- `DELETE /subjects/{nome}` → 204; 409 `subject_in_use` se ha lezioni; 409 `subject_in_calendar` se la usano voci del calendario (resterebbe in elenco: si cambia prima nel calendario).
- `GET /lessons/{id}/sources`: ogni fonte ha in più `nome` (nome del file o "Appunti"), `durata_s` (audio), `pagine` (materiale), `parole` (appunti), `usata: bool`; la vista ha in più `ultimo_aggiornamento: {modo: "extend"|"rebuild", unita_nuove: int, unita_cambiate: int, il: str} | null`, che resta finché non si annulla o arriva un altro aggiornamento.
- Ordine e fonte principale (LE1l): la vista delle fonti ha in più `principale: str` (id della fonte principale; con l'audio, l'id della prima parte audio), `ordine_usato: [str]` e `principale_usato: str | null` (com'erano all'ultimo aggiornamento riuscito) e `solo_ricostruzione: bool`, vero quando l'ordine delle parti audio già usate o la principale sono diversi da quelli usati. Si calcola confrontando, quindi rimettendo l'ordine o la principale di prima torna falso da solo.
- `PUT /lessons/{id}/sources/order` body `{ids: [str]}` (tutte le fonti nel nuovo ordine; conta solo l'ordine dei file audio) → vista delle fonti. `PUT /lessons/{id}/sources/primary` body `{id}` → vista delle fonti. 409 `lesson_busy` come le altre modifiche.
- `POST /lessons/{id}/update` con `mode: "extend"` mentre `solo_ricostruzione` è vero → 409 `rebuild_required`. Aggiungere fonti nuove, anche in mezzo alle parti audio, lascia sempre la scelta fra Estendi e Ricostruisci.
- `POST /lessons/{id}/sources`: `tipo` accetta anche `materiale` (file PDF, PNG, JPG, HEIC, PPTX; più file in una chiamata con `file` ripetuto → lista di fonti).
- `POST /lessons` (import): l'ordine dei file `audio` è quello scelto nel popup. In più `materiali: List[UploadFile]` (facoltativi; con soli materiali e niente audio né appunti nasce la lezione solo da materiali), `principale: str` (nome del file principale quando non c'è audio; di default il documento con più pagine), `allega_materiali: bool` (graffetta; default true se ci sono materiali), `calendar_entry_id: str` + `calendar_date: YYYY-MM-DD` (facoltativi: a lezione creata la collega a quell'ora).
- `POST /lessons/{id}/recall/generate` con `qtype: "consigliato"` esiste già.
- `GET /lessons/{id}/versions` → `[{id: str, il: str, modo: "import"|"extend"|"rebuild"|"restore", fonti_aggiunte: [str], unita_nuove: int, unita_cambiate: int, attuale: bool}]`, dalla più recente; al massimo 5 oltre all'attuale. Ogni versione è lo stato della lezione dopo quell'evento; le lezioni di prima della b2 mostrano solo quelle che hanno.
- `POST /lessons/{id}/versions/{vid}/restore` → 202 job; prima fa una fotografia dello stato attuale (quindi si annulla anche il ripristino). 409 `lesson_busy` come le fonti.
- Domande del ripasso, evidenziazioni e note di studio hanno in più `precedente: bool`: vero se l'unità è cambiata in un aggiornamento successivo alla loro creazione.

### Codex · DS1 backend (materiali)
- **DS1a · Materiali come fonti.** `tipo="materiale"` in POST sources (PDF, immagini, PowerPoint). Ogni pagina o slide diventa testo una volta sola e si tiene in cache con l'impronta della fonte: testo del PDF con PyMuPDF; descrizione Vision per foto e pagine senza testo, col modello di Descrizione immagine già configurato. PowerPoint con python-pptx (nuova dipendenza in requirements.txt) per testo e immagini; per l'immagine della slide prova la resa di sistema di macOS (qlmanage) e, se non c'è, usa le immagini contenute. Nessun programma da far installare all'utente.
- **DS1b · Contesto.** Il testo dei materiali entra in `materials_text` di `build_rewrite_prefix_parts` (posto lasciato da RC1). Nel taglio per il contesto si tolgono prima le unità precedenti, i materiali per ultimi.
- **DS1c · Graffetta.** Con `allega_materiali` acceso il classificatore di Arricchimento assegna ogni pagina a una macro unità o a nessuna (docs/ENRICHMENT.md) e le pagine assegnate vengono allegate all'unità come immagini, mai il testo. Spento, i materiali sono solo contesto.
- **DS1d · Lezione solo da materiali.** Le pagine diventano segmenti con prefisso della fonte (come LE1) e la pipeline è la stessa; togliere il blocco "I materiali saranno disponibili nel prossimo lotto" in source_update.py. Se dopo arriva l'audio vale Estendi o Ricostruisci.
- **DS1e · Import.** I nuovi campi di `POST /lessons` del contratto. Il collegamento al calendario usa la funzione che già collega a mano.
- **LE1i · Vista delle fonti.** I campi in più di `GET /lessons/{id}/sources` del contratto (tranne quelli di LE1l).
- **LE1j · Versioni della lezione.** update_history tiene le ultime 5 fotografie invece di una (stessa cartella history/, stessi file), ciascuna con modo, fonti aggiunte e conteggi. Annulla aggiornamento = ripristino della più recente. Il ripristino non cancella mai dati di studio nel database. Endpoint del contratto.
- **LE1l · Ordine e fonte principale.** Endpoint e campi del contratto. La fonte principale è quella su cui si costruisce la scaletta: l'audio (tutte le parti, in ordine) se c'è, altrimenti il materiale o gli appunti scelti; le altre fonti sono contesto e, per i materiali, si allegano alle unità. Quando arriva l'audio in una lezione nata dai materiali la principale non cambia da sola: la cambia l'utente. Cambiare ordine delle parti usate o principale vale solo per Ricostruisci.
- **LE1k · Studio precedente.** Ogni aggiornamento riuscito registra per unità cambiata (o tutte, con Ricostruisci) l'ora del cambio; domande, evidenziazioni e note create prima di quell'ora su quell'unità hanno `precedente: true`. Niente migrazioni dei dati esistenti: si calcola al volo.

### Codex · MA1 backend (materie)
- **MA1a.** Tabella `subjects` (nome, creata_il) con migrazione 0018 (down 0017, idempotente come la 0017). Servizio e router `/subjects` del contratto.
- **MA1b.** Creare una lezione o una voce di calendario con una materia nuova la registra. `custom_question_settings.view` e `telegram_topics.known_materie` leggono dall'elenco unito.

### Antigravity · Import nuovo
Wireframe RT-import.html. Si parte da NewLessonDialog.tsx così com'è e si aggiunge:
- un solo riquadro che accetta audio e materiali e li separa per tipo; miniature dei materiali con + e ×;
- con più file audio: righe numerate con maniglia, riordino trascinando (e con le frecce della tastiera sulla maniglia); ordine di partenza per data di modifica del file, poi per nome; i materiali non hanno ordine;
- senza audio: stellina sulla miniatura del documento principale (di partenza quello con più pagine), un clic la sposta; manda `principale`;
- le ore del giorno dal calendario (`GET /calendar/day`) come scelte rapide, con l'ora in corso o appena finita già scelta, quelle già registrate spente, frecce per il giorno, matita per i campi a mano (i campi di oggi restano identici); la scelta manda `calendar_entry_id` e `calendar_date`;
- la graffetta accanto a Revisione e Arricchimento (accesa di default; spenta e non cliccabile senza materiali; si accende da sola quando se ne caricano) → `allega_materiali`;
- il menu delle materie legge `GET /subjects`.

### Antigravity · Fonti nella lezione (LE1)
Wireframe RT-fonti-materie.html, scene 1, 2 e 4.
- Sezione **Fonti** in cima al pannello Dettagli, sopra Fasi: icona per tipo, nome, misura, puntino sulle fonti non ancora usate, × al passaggio del mouse (toglie con `DELETE`), + con menu Parte di registrazione / Appunti / Materiali.
- Parti audio numerate con maniglia, riordino trascinando (una parte nuova si può mettere anche in mezzo). Stellina sulla fonte principale; al passaggio del mouse sulle altre fonti, stellina vuota per sceglierla.
- Regola: ogni azione in Dettagli che obbliga a ricostruire una lezione già creata chiede prima conferma (popup del wireframe): spostare parti audio già usate e cambiare la principale. Aggiungere fonti non chiede conferma.
- Con `solo_ricostruzione` la riga sopra il testo dice cosa è cambiato e offre solo Ricostruisci, più l'icona "Rimetti com'era" che rimanda `ordine_usato` e `principale_usato`. Se l'utente rimette tutto com'era, anche trascinando, la riga sparisce perché il server risponde `solo_ricostruzione: false`.
- Audio aggiunto a una lezione nata dai materiali: la riga Aggiorna propone di rendere principale l'audio (stellina), ma si può tenere il documento, e restano Estendi e Ricostruisci.
- Riga sopra il testo della lezione quando `has_unused_sources`: "Fonti nuove non ancora usate: …" e **Aggiorna**, che al passaggio del mouse si divide in Estendi e Ricostruisci (icone con tooltip, come la matita del calendario). Estendi parte subito; Ricostruisci chiede conferma avvisando che le unità cambiate perdono decisioni e stato di studio. Durante il job la riga mostra l'avanzamento.
- Dopo l'aggiornamento (`ultimo_aggiornamento` e `can_undo`): riga "Lezione aggiornata · N unità nuove, M cambiate" con Annulla aggiornamento e ×. La × la nasconde solo nel browser.
- Puntino sull'icona Dettagli quando ci sono fonti non usate.
- Sezione **Versioni** sotto Fonti, chiusa di default: data, modo (icona Estendi, Ricostruisci o Ripristino con tooltip), fonti aggiunte; icona Ripristina con conferma.
- Icona piccola con tooltip "Precedente all'ultima aggiunta di fonti" su domande (pannello Domande e Studio), evidenziazioni e note con `precedente`. Nessun altro cambiamento a quegli elementi.

### Antigravity · MA1 e QT1
- **Materie** in Impostazioni (scena 3): elenco con il numero di lezioni, campo + per aggiungere, × solo sulle materie senza lezioni. L'editor dei tipi di domanda e il datalist del calendario leggono `GET /subjects`.
- **Consigliato** nel pannello Domande (scena 4): chip in più prima degli altri, separato da una riga sottile, con la ✨; manda `qtype: "consigliato"`. Sotto i chip una riga dice cosa riceverà ogni unità (es. "6 Mirata e 4 Quiz"). I chip di oggi e la ✨ sul tipo più consigliato restano come sono. Il default resta quello di oggi.

---

### Antigravity · AP1, WS1, AU1, PN1 (dalla b3, completi)
- **AP1:** API di sola lettura con la sua openapi.json, servita su 127.0.0.1 (Open WebUI gira sullo stesso Mac). Quattro operazioni: cerca nel testo delle lezioni (SQLite FTS5, filtri materia e date), elenco lezioni, scaletta di una lezione, testo di un'unità. Chiave separata di sola lettura, creata e revocata da Impostazioni (nuova riga nella sezione esistente). Guida breve in docs per collegare Open WebUI.
- **WS1:** interruttore in Impostazioni › Ricerca web "Cerca sul web durante la verifica contestuale", spento di default (scena 5 di RT-fonti-materie.html). Quando è acceso, durante la verifica contestuale (VC1 Verifica) una ricerca SearXNG; le fonti con titolo e link si salvano con la risposta e si vedono in una sezione Fonti nella voce di verifica del pannello Verifiche e domande. Spento o senza SearXNG configurato, la verifica funziona come oggi.
- **AU1** (docs/wireframes-4.2.5/RT-audio-linea.html): nella pagina della lezione, linea verticale di 2 px a destra dell'unità che si ascolta, che avanza contando solo il parlato. Il lettore resta in basso. Solo pagina della lezione.
- **PN1** (docs/wireframes-4.2.5/RT-pannelli.html): cambiano solo contenitore (staccato di 8 px, angoli stondati, ombra, X) e animazioni (entrata e uscita da destra con dissolvenza, dissolvenza al cambio di pannello; dal basso su iPhone). Il contenuto di ogni pannello resta identico.

---

## 4.2.5b3 — recall

13 ott 2026, approvato da Attilio nel thread "Raccolta feature 4.2.5". Tutto a Codex, branch `rt425b3/codex` da claude/rt-4.2.5-beta (v4.2.5b2.2). Niente wireframe: le parti di interfaccia sono piccole e si innestano su elementi che esistono già, descritti qui sotto.
Obiettivo: il numero scelto dall'utente diventa un tetto e non una quota, le varianti degli esercizi riempiono il numero, i voti diventano regole per tipo e materia, e una serie di controlli locali (senza LLM) scarta le risposte insensate dei modelli gratuiti.
Niente migrazioni: regole e voti stanno in file JSON nella cartella di stato, come recall_fewshot.json oggi. Se una servisse davvero: 0019 con down_revision 0018, idempotente.

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

### UI1-UI3 · Calendario, import e trascinamento (aggiunte del 14 ott)
Piccole modifiche di interfaccia, da fare dopo RQ1-RQ6. File: CalendarPopups.tsx, NewLessonDialog.tsx, Layout.tsx e components/shell/newLesson; nessun cambio al backend.
- **UI1 · + nel popup di un'ora del calendario.** Quando l'ora non ha una lezione collegata, accanto all'icona "Collega una lezione" (riga "Nessuna registrazione") c'è un'icona + con tooltip "Importa una lezione per quest'ora". Apre il popup di import con la data di quell'ora e quell'ora già scelta fra le ore del calendario, come se l'utente l'avesse cliccata; a import finito la lezione è collegata (stessi campi `calendar_entry_id` e `calendar_date` di oggi). Il contesto NewLessonContext impara ad aprire il popup con opzioni (data, ora, file iniziali); aperto senza opzioni si comporta come oggi.
- **UI2 · Contrasto dell'ora scelta nel popup di import.** Oggi l'ora scelta si distingue appena dalle altre (`border-primary ring-1 bg-primary/10`, e la barretta colorata è uguale su tutte). Nuovo stile, in tema chiaro e scuro: ora scelta con bordo di 2 px del colore primario, sfondo primario più pieno (circa /20) e barretta primaria; le altre ore con bordo normale e barretta grigia (muted). Il bordo dell'ora scelta deve avere un contrasto di almeno 3:1 con lo sfondo in entrambi i temi (controllarlo con i colori dei token). Le ore già registrate restano come oggi.
- **UI3 · Trascinare file su tutta la pagina.** Quando si trascina sulla finestra di RT un file che l'import accetta (gli stessi tipi del campo del popup: audio, materiali, .zip), compare sopra tutta la pagina un velo con la scritta "Rilascia per importare". Rilasciando, si apre il popup di import con quei file già caricati, che li smista come se fossero stati trascinati nel suo riquadro (audio e materiali, oppure pacchetti .zip; stessa regola e stesso messaggio di oggi se sono mescolati). Il velo non compare per file non accettati, per testo o link trascinati, quando il popup di import è già aperto (lì vale il suo riquadro) e mentre si trascina dentro un editor o un pannello che accetta già file (es. Fonti in Dettagli). Si chiude se il trascinamento esce dalla finestra o con Esc.

### Fuori dalla b3
- Nessun cambiamento alla valutazione del classificatore, al rifornimento automatico (salvo che usa le stesse funzioni) e a Telegram (deprecato).
