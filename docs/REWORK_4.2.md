# RT 4.2 — rework della web app: piano e task

Piano di lavoro per portare la web app ai wireframe 4.2 (pannelli della lezione, ripasso,
Lezioni, Nuova lezione). Pensato per essere diviso tra più agenti: ogni task ha obiettivo, file,
dipendenze, criteri di accettazione e test. I wireframe sono in `docs/wireframes-4.2/`
(sorgenti `.dc.html`: si leggono come HTML; il canvas originale è privato).

## Regole per tutti

- Lingua: interfaccia, commenti, commit e PR in italiano. Stile del codice come il resto del repo.
- **Niente descrizioni superflue** nell'interfaccia: etichette e dati sì, frasi che spiegano come
  funziona l'interfaccia no (se servono, tooltip o "Altre info"). Icone senza testo dove il wireframe
  le mostra così.
- Telegram è spento di predefinito: non aggiungere UI Telegram.
- Branch: **un branch per task**, creato da `claude/rt-4.2.0-beta-54bz3z` e chiamato
  `rt42/<id-task>-<breve>` (es. `rt42/A1-righe-lezioni`); PR verso `claude/rt-4.2.0-beta-54bz3z`.
  Non lavorare direttamente sul branch di integrazione, non fare merge su `main`, niente tag.
- Prima di aprire la PR: `cd frontend && npx vitest related --run <file toccati>`, `npm run lint`,
  `npm run typecheck`; backend `.venv-dev/bin/pytest` sui test dei moduli toccati; e2e Playwright
  solo delle pagine toccate (`RT_E2E_PORT=8767 npx playwright test e2e/<spec>`; serve `npm run build`).
- Provare a mano con `scripts/dev.sh` (SPA su :5173 con ricarica a caldo, API su :8766, dati finti).
- Un task tocca solo i file elencati; se serve toccarne altri, dirlo nella PR.

## Ripercussioni sul backend

Quasi tutto il rework è frontend. Il backend cambia in questi punti (tutti con task dedicati):

| Tema | Cosa c'è oggi | Cosa serve |
|---|---|---|
| Metadati modificabili (titolo, materia, data, **ora**, docente) | nessuna API; il nome cartella nasce da data, materia, titolo | API di modifica con **rinomina della cartella** (bloccata se un job lavora sulla lezione); campo `ora`; ordinamento per ora nello stesso giorno |
| Ripristina la versione della pipeline | il salvataggio a mano sovrascrive `draft.json` | copia della bozza (testo, titoli, timecode, immagini) alla prima modifica a mano; endpoint di ripristino; le decisioni della revisione restano |
| Domande su una parte / più unità | `RecallGenerate` accetta `unit_ids`, non istruzioni né testo selezionato | campi `instructions` e `selection` passati al recaller; tipi per una parte: quiz, mirata, caso, esercizio |
| 👎 con motivi, "Commenta e rigenera", "Non lo so" | voto up/down/lightning salvato, ma la domanda 👎 **viene ancora riproposta**; few-shot buoni e cattivi mescolati | stato/filtro "scartata"; motivi salvati; few-shot separati (buone / da evitare con motivo); job di rigenerazione da domanda + unità + commento; risposta "non so" |
| Esito delle risposte | quiz: ricavabile; risposte aperte: solo valutazione testuale | esito corretta/parziale/sbagliata dal valutatore; esito dell'ultima risposta nell'API delle domande |
| Nuova lezione con interruttori | `run_pipeline` ha `with_review`; arricchimento automatico solo da configurazione | opzione arricchimento per singola esecuzione; "solo trascrizione" = `ingest_audio` (esiste) |
| Analisi dell'arricchimento | `enrichment.automatic` vero/falso | tre modalità: disattivata, **manuale (predefinita)**, automatica |
| Scaletta "Approva (10)" | approvazione da API; la pipeline aspetta | impostazione secondi; approvazione automatica dal server (D1) |
| Rielaborazione dal vivo come task | eventi di avanzamento con `unit_id` (unità in lavorazione) | stato per unità (fatta / in corso / da fare) leggibile dalla pagina; da verificare se bastano gli eventi |
| Immagini dentro l'editor (incolla/trascina PNG, JPEG, GIF) | immagini solo da PDF o ricerca web | endpoint di caricamento nei media della lezione; export: nello zip i file, nel Markdown solo riferimenti relativi (D2) |
| Sfondo dei gruppi in Lezioni | — | preferenza UI (colori predefinito, grigi, nessuno) |
| Pagine tolte | `/recall`, `/recall/materie`, `/recall/giorno`, `/review`, `/lezioni/:id/revisione`, `/lezioni/:id/rilevanza`, `/lezioni/:id/outline`, `/arricchimento`, `/immagini`, `/importa`, `/lezioni/:id/recall/domande` | solo frontend (redirect); **le API restano** (CLI, mini app, test) |

## Stile comune (vale per entrambi gli agenti)

Due modelli diversi sullo stesso frontend: per non avere stili mischiati si usano solo i pezzi già
presenti nell'app.

- **Componenti**: `frontend/src/components/ui/` (button, icon-button, menu, modal, dialog, input,
  select, slide-toggle, tooltip, badge, alert, card) e, per i pannelli, il contenitore di F0. Se
  manca qualcosa si aggiunge lì, non dentro la pagina.
- **Colori**: solo i token del tema in `frontend/src/index.css` (`bg-muted`, `text-muted-foreground`,
  `text-danger`, `bg-accent`, `border` …). Niente colori esadecimali o `rgba()` nei componenti:
  un colore nuovo diventa una variabile in `index.css` con la sua versione scura.
- **Testo**: `text-meta` (12 px), `text-body` (15 px), `text-heading` (22 px); niente
  `text-[13px]` e simili.
- **Icone**: solo `lucide-react`, 16 px nelle righe e 18 px nell'intestazione; pulsanti a sola icona con
  `IconButton` e il suo tooltip.
- **Misure**: le scale di Tailwind (`gap-2`, `p-3`, `rounded-lg` …); valori tra parentesi quadre
  solo se il wireframe li richiede e non esiste un equivalente.
- **Testi dell'interfaccia** in italiano, brevi, senza righe di spiegazione.
- **Wireframe**: sono il riferimento per contenuto e disposizione; non si copia il loro HTML o i
  loro stili.

## Decisioni (risposte di Attilio, 3 ottobre 2026)

- **D1 — Approvazione automatica della scaletta:** la fa **il server** dopo N secondi (impostazione),
  anche a pagina chiusa o dal telefono; la pagina mostra il conto e "Approva". Scrivere nel campo
  "chiedi modifiche" ferma il conto lato server (endpoint per sospenderlo).
- **D2 — Immagini nel Markdown esportato:** **riferimenti relativi** (`assets/images/…`); lo zip
  contiene i file.
- **D3 — Valutazione delle risposte aperte:** ogni valutazione = elemento pregenerato del tipo +
  commento "personale" del modello sulla risposta, più un campo nuovo **esito**
  (`corretta | parziale | sbagliata`) nella risposta salvata.
  - Mirata: indicatori Correttezza e Completezza (già oggi), nessun materiale pregenerato in più.
  - Vasta: scaletta ideale pregenerata (già oggi) + commento.
  - Esercizio: schema di risoluzione pregenerato (oggi "procedimento"/`pregenerated_material`) + commento.
  - Caso clinico: **niente di pregenerato** (i casi sono troppo vari); solo il commento del modello
    con Correttezza/Completezza.
- **D4 — Preferenze:** sezione temporanea "Preferenze" nella pagina Impostazioni attuale (secondi
  dell'approvazione, sfondo dei gruppi, modalità dell'arricchimento), da riassorbire nel rework delle
  impostazioni.

## Task

Dimensione: **S** ≤ mezza giornata di un agente, **M** ≈ una sessione (S = 1 punto, M = 2).

### Chi fa cosa

Le modifiche le fanno **ChatGPT** e **Antigravity**, divise in parti uguali (20 punti a testa).
**Claude** non implementa: rivede ogni PR (vedi "Revisione").

| Agente | Task | Punti |
|---|---|---|
| **ChatGPT** — fondamenta, editor (CodeMirror), backend più delicato | F0, C1a, C1b, C3, C4, C5, B1, B2, B4, B5, B7 | 20 |
| **Antigravity** — Lezioni, pannelli, sessione di ripasso, backend piccolo | A1–A5, G1–G5, C2, B3, B6, B8, B9 | 20 |

Le dipendenze tra i due sono poche e segnate nei task (es. G4 di Antigravity usa B4 di ChatGPT: si
può fare prima la UI con i pulsanti disattivati).

### Dove lavorano

| Dove | Chi | Uso |
|---|---|---|
| Codex nel cloud, repo `atturk/rt` | ChatGPT | un branch `rt42/<id>-<breve>` e una PR per task |
| `~/rt-antigravity` (worktree) | Antigravity | un branch `rt42/<id>-<breve>` e una PR per task |
| `~/rt-dev` | Claude | branch beta: revisione, correzioni, merge; prove dal vivo di Attilio |

Nuovo task: `git fetch origin && git switch -c rt42/<id>-<breve> origin/claude/rt-4.2.0-beta-54bz3z`.
I wireframe sono nel repo (`docs/wireframes-4.2/*.dc.html`): HTML leggibile come testo.

### Test (agenti e CI)

- **In locale l'agente esegue solo i test toccati**: i file `tests/test_*.py` indicati nel task o
  legati ai moduli cambiati (`pytest tests/test_x.py -q`); per il frontend `npm run lint`,
  `npm run typecheck` e `npx vitest run <file>` dei componenti cambiati. Niente suite intera, niente
  e2e. Nella PR scrive quali test ha eseguito.
- **CI sulle PR verso il beta** (`.github/workflows/pr-beta.yml`): pytest solo se cambiano `rt/`,
  `tests/` o i requirements; lint, typecheck e unit del frontend solo se cambia `frontend/`; e2e
  solo con l'etichetta `e2e` sulla PR. La suite completa (`tests.yml`) resta solo per `main`.
- **e2e**: li lancia Claude a mano sul beta (workflow_dispatch) prima di dire ad Attilio che un
  gruppo è pronto per la prova dal vivo.

### Revisione e merge (Claude)

- Claude rivede il **diff** di ogni PR verso `claude/rt-4.2.0-beta-54bz3z` contro regole, wireframe e
  resto del progetto (niente prove manuali nella web app).
- **Correzioni brevi** (pochi file, nessuna scelta da fare): Claude le fa direttamente sul branch del
  task, con un commit "Revisione: …".
- **Errori grossi** (comportamento sbagliato, struttura da rifare, test mancanti): Claude apre un
  task correttivo nella sezione "Correzioni" in fondo, con id `R<n>`, assegnato all'agente che ha
  fatto il task; la PR resta aperta.
- Rivista e con i controlli della PR verdi, Claude fa il **merge nel branch beta**. Su `main` mai senza l'ok di Attilio.

### Prova dal vivo (Attilio)

La web app la prova Attilio. Claude gli dice quando un gruppo di task è nel branch beta e pronto da
provare, e cosa guardare (pagine, flussi, wireframe di riferimento), con i comandi per avviarla
(`scripts/dev.sh` in `~/rt-dev`).

### Fase 0 — fondamenta (prima di tutto)

**F0 — Contenitore dei pannelli e intestazione della lezione** · ChatGPT · S
- Generalizzare `PanelView` (`frontend/src/lib/lessonPanel.ts`) e `LessonPanel` a: `verifica`,
  `dettagli`, `domande`, `classificatore`, `arricchimento`; un pannello per volta, chiusura con X/Esc.
- Intestazione: freccia indietro a sinistra, niente materia/data in alto; icone Domande (cervello),
  Studio, Arricchimento, Verifica, Dettagli, Esporta. Materia · data · docente e unità · durata
  sotto il titolo.
- Ogni pannello nuovo parte come componente vuoto in `frontend/src/components/lesson/panels/`
  (uno per file), così i task successivi toccano file diversi.
- Wireframe: tutte le tavole della lezione. Test: e2e `lesson-view`, `lesson-page`.

### Fase 1 — in parallelo dopo F0

**A1 — Lezioni: righe senza icone e gruppi con sfondo** · Antigravity · S
- `frontend/src/components/lessons/LessonsView.tsx`: togliere le icone Info/Recall/Studio/Apri dalle
  righe (si apre con un clic sulla riga). Il popup Info sparisce: quelle informazioni stanno nel
  pannello Dettagli della lezione.
- Ogni gruppo in un riquadro con sfondo leggero a rotazione (4 colori: `rgba(21,95,82,.06)`, `rgba(59,111,160,.07)`,
  `rgba(184,134,11,.08)`, `rgba(150,80,110,.06)`), angoli 12 px, 12 px tra i gruppi.
- Wireframe: `Dashboard.dc.html`, `Telefono-Dashboard.dc.html`. Test: `src/routes/lessons.test.tsx`,
  e2e `lessons-view`.

**A2 — Lezioni su telefono: raggruppa e ordina a un tocco** · Antigravity · S
- Su schermo stretto, due pulsanti che a ogni tocco passano al valore successivo: raggruppa
  Data → Materia → Docente; ordina Recenti → Vecchie → A–Z. Su PC resta il gruppo di icone + menu Ordina.
- Wireframe: `Telefono-Dashboard.dc.html`. Test: unit della pagina Lezioni.

**A3 — Nuova lezione: interruttori e Avvia a icona** · Antigravity · S (frontend; l'interruttore
Arricchimento resta disattivato finché non c'è B6)
- `frontend/src/components/lessons/NewLessonDialog.tsx`: campo **Ora**; frase "Dopo l'importazione: …"
  in alto che cambia con gli interruttori; riga con Avvia (icona play) a sinistra e tre icone a stato a
  destra: Solo trascrizione (documento), Revisione (scudo), Arricchimento (immagine); niente Annulla
  (X in alto). Solo trascrizione = job `ingest_audio`; Revisione = `with_review`.
- Wireframe: `Nuova-Lezione.dc.html`. Test: unit del dialogo, e2e `new-lesson`.

**A4 — Studio: vai a un'unità** · Antigravity · S
- `frontend/src/components/study/Study.tsx`: pulsante "Unità N di M ▾" che apre l'indice per sezione
  (unità lette segnate) e porta all'unità scelta.
- Wireframe: `Studio-Indice.dc.html`, `Telefono-Studio-Indice.dc.html`. Test: e2e `study`.

**G1 — Pannello Dettagli** · Antigravity · M (i campi dei metadati salvano davvero solo dopo B1)
- `panels/DetailsPanel.tsx` al posto di `LessonPanel` vista dettagli + `PhasePanel`:
  campi titolo, materia, data e ora, docente; avviso "Documento da ricreare › Ricrea" solo quando serve;
  riepilogo; Fasi compatte con menu ⋯ (Riesegui, Riesegui con opzioni… in linea sotto la fase con unità e
  istruzioni aggiuntive, Segna come valida — sostituisce il tasto Option), "Pipeline completa" con
  casella "con la revisione"; Job chiusi; in fondo "Ripristina la versione della pipeline…" (dopo B2)
  ed "Elimina la lezione…" (stessa conferma scritta "confermo" del vecchio popup Info, tolto in A1:
  recuperare `DeleteLesson` da `LessonsView.tsx` nella storia git; riusare o togliere `lessonInfo`).
- Wireframe: `Dettagli*.dc.html`, `Telefono-Dettagli.dc.html`. Test: `PhasePanel.test.tsx` (da
  spostare), e2e `lesson-view`.

**G2 — Pannello Classificatore** · Antigravity · M
- Port di `frontend/src/routes/relevance.tsx` in `panels/ClassifierPanel.tsx`: stato + "Classifica le
  nuove"/"Riclassifica tutte", filtri, unità con etichetta modificabile e score, "corretta da te ·
  ripristina", sezioni per casi/esercizi (`SectionLabelsCard`). Si apre dal fondo del pannello Domande.
- Le etichette/score accanto ai titoli nel testo sono **C3** (editor), non qui.
- Wireframe: `Classificatore.dc.html`, `Telefono-Classificatore.dc.html`. Test: `relevance.test.tsx`
  (da adattare).

**G3 — Pannello Arricchimento** · Antigravity · M
- Port di `frontend/src/routes/images.tsx` in `panels/EnrichmentPanel.tsx`: in cima galleria dei media
  della lezione (immagini, infografiche, visualizzazioni; clic → punto del testo), Aggiungi e Cerca sul
  web a icona; sotto le idee (Analizza a icona, Genera/Ignora, ignorate a un clic).
- Wireframe: `Arricchimento.dc.html`, `Telefono-Arricchimento.dc.html`. Test: e2e
  `recall-images-bot` (parte immagini).

**G4 — Sessione di ripasso leggera** · Antigravity · M
- Nuova pagina al posto di `/lezioni/:id/recall` e `/recall/selezione/:ids` (stessa UI): tipo (resta
  l'ultimo usato), una domanda alla volta, risposta (scelte/testo/voce), esito, 👍, 👎, Commenta, Salta,
  Non lo so, Termina, Prossima. Le API di sessione esistono (`frontend/src/api/recall.ts`); 👎 con
  motivi, Commenta e Non lo so diventano attivi con B4.
- Wireframe: `Sessione.dc.html`, `Telefono-Sessione.dc.html`, `Telefono-Pollice-Giu.dc.html`,
  `Telefono-Commenta.dc.html`. Test: e2e `recall-sessions`, `recall-images-bot` (recall).

**G5 — Pannello Domande** · Antigravity · M (generazione con istruzioni dopo B3)
- `panels/QuestionsPanel.tsx`: "Ripassa" (→ G4), conteggi per tipo che filtrano l'elenco, "Genera altre
  domande" (tipo, quante, istruzioni), elenco con menu ⋯ (elimina), in fondo unità per il recaller e
  link al Classificatore. Variante "Domande unità 1.2 e 1.3" quando arriva da una selezione: domande
  di quelle unità con l'unità su ogni riga (senza se l'unità è una sola), "Nuove domande su …" con
  tipo Quiz/Mirata/Caso/Esercizio e istruzioni aggiuntive.
- Wireframe: `Domande.dc.html`, `Domande-Parte.dc.html`, `Telefono-Domande.dc.html`.

### Fase 2 — editor e Verifica

**C1 — Pannello Verifica** · ChatGPT · L (spezzato in C1a, C1b: M + M)
- C1a: pannello con stati (mai verificata, in corso, N da decidere, tutte decise + "Riprendi la
  pipeline"), scheda dell'issue (Accetta, Mantieni, Modifica, Annulla l'ultima; **niente scorciatoie**),
  elenco Da decidere/Decise; prima di Accetta su un'unità modificata si salva la modifica.
- C1b: nell'editor passaggio evidenziato + altre issue sottolineate, clic → issue; issue con testo
  cambiato ("Chiudi l'issue" / "Verifica di nuovo l'unità"); telefono: foglio con "Nel testo" e
  "Correzione proposta". Togliere `/lezioni/:id/revisione` e `/review` (redirect).
- Wireframe: `Main.dc.html`, `Verifica-Stati.dc.html`, `Telefono-Verifica.dc.html`.

**C2 — Menu contestuale → Domande su questa parte** · Antigravity · S
- "Domande su questa parte" apre il pannello Domande sulle unità della selezione (anche più unità) e
  passa il testo selezionato; niente "Studia questa parte".

**C3 — Classificatore nell'editor** · ChatGPT · S
- Con il pannello Classificatore aperto: etichetta (unità non didattiche) e score (solo numero,
  colorato) accanto al timecode; testo delle non didattiche più chiaro. A pannello chiuso niente.

**C4 — Rielaborazione dal vivo e scaletta** · ChatGPT · M (dopo B9)
- Stato "scaletta da approvare" nella pagina della lezione (riquadro giallo con "Approva (N)", il
  timer si ferma scrivendo una richiesta di modifiche, "Rigenera con queste modifiche"); dopo
  l'approvazione le unità come task (fatta/in corso/da fare) con il testo che compare; finita la
  rielaborazione la lezione completa, classificazione in background con lucchetto (testo in sola
  lettura finché c'è un job). Togliere `/lezioni/:id/outline`.
- Wireframe: `Scaletta.dc.html`, `Rielaborazione.dc.html`, `Rielaborata.dc.html` e telefono.

**C5 — Immagini nell'editor** · ChatGPT · M (dopo B7)
- Incolla/trascina PNG, JPEG, GIF nel testo → caricamento nei media della lezione e riferimento nel
  Markdown.

### Backend

- **B1 — Metadati e ora** · ChatGPT · M: API di modifica (titolo, materia, data, ora, docente) con rinomina
  della cartella e blocco con job attivo; `ora` nei metadati; ordinamento per ora a parità di giorno.
- **B2 — Ripristina la versione della pipeline** · ChatGPT · M: copia alla prima modifica a mano, endpoint di
  ripristino con conteggio unità modificate.
- **B3 — Generazione con istruzioni e selezione** · Antigravity · S: `instructions` e `selection` in
  `RecallGenerate` fino al recaller; tipi per una parte. 
- **B4 — Voti, scarto, commenta e rigenera, non lo so** · ChatGPT · M: stato scartata e filtro nella scelta e nei
  conteggi; motivi; few-shot separati; job di rigenerazione; risposta "non so".
- **B5 — Esito delle risposte** · ChatGPT · M (D3): campo `outcome` (`corretta|parziale|sbagliata`,
  facoltativo) in `RecallAnswer` e negli schemi `RecallEval*Result`; prompt dei valutatori in
  `rt/llm/prompts.py` aggiornati per restituirlo; quiz: ricavato da risposta e `correct_index`;
  "Non lo so" → `sbagliata`; l'API delle domande espone l'esito dell'ultima risposta. Caso clinico:
  la generazione non produce più `pregenerated_material` e `recall_special.evaluate` non lo passa al
  prompt (resta per gli esercizi come schema di risoluzione). Test: `tests/test_recall.py`,
  `tests/test_recall_special.py`, `tests/test_recall_session.py`.
- **B6 — Arricchimento: modalità e opzione all'avvio** · Antigravity · S: disattivata/manuale/automatica
  (predefinita manuale); opzione per singola esecuzione della pipeline. 
- **B7 — Media caricati dall'editor** · ChatGPT · M (D2): endpoint di caricamento PNG/JPEG/GIF nei media
  della lezione; il Markdown usa riferimenti relativi `assets/images/…`; lo zip esportato contiene i file.
- **B8 — Preferenze** · Antigravity · S (D4): sezione temporanea "Preferenze" nelle Impostazioni attuali
  (API + UI): secondi dell'approvazione, sfondo dei gruppi (niente / grigi / colori), modalità
  dell'arricchimento (salvata da B6).
- **B9 — Approvazione automatica della scaletta** · Antigravity · S (D1): il server approva da solo dopo i
  secondi delle Preferenze; endpoint per sospendere il conto quando l'utente scrive una richiesta di
  modifiche; lo stato della scaletta espone la scadenza per il conto nella pagina.

### Fase 3 — pulizia (quando i sostituti ci sono)

**A5 — Pagine tolte e redirect** · Antigravity · S
- Redirect da `/recall`, `/recall/materie/:m`, `/recall/giorno/:d`, `/review`, `/arricchimento`,
  `/immagini`, `/importa`, `/lezioni/:id/recall/domande` alle nuove posizioni; togliere i componenti
  non più usati e i relativi test/e2e (tenendo le API).

## Ordine: due giri per agente

Ogni agente fa i task di un giro **sullo stesso branch, un commit per task** (messaggio
`<id>: …`), con push dopo ogni commit; alla fine del giro apre **una PR** verso il beta. Claude
rivede la PR commit per commit e la unisce.

| Giro | ChatGPT (Codex) — branch `rt42/codex-1`, `rt42/codex-2` | Antigravity — branch `rt42/A1-lezioni-gruppi`, `rt42/antigravity-2` |
|---|---|---|
| 1 | F0, B1, B2, B4, B5 | A1, A2, A3, A4, B3, B6, B8, B9 |
| 2 (dopo il merge di entrambi i giri 1) | C1a, C1b, C3, B7, C5, C4 | G1, G2, G3, G5, C2, G4, A5 |

## Come passare un task a un altro agente

Messaggio tipo: «Lavora sul repo `atturk/rt`. Leggi `docs/REWORK_4.2.md` (regole, task) e il
wireframe indicato in `docs/wireframes-4.2/`. Fai il task **<id>**: crea il branch
`rt42/<id>-<breve>` da `claude/rt-4.2.0-beta-54bz3z`, tocca solo i file del task, esegui i test
indicati e apri una PR verso `claude/rt-4.2.0-beta-54bz3z` con descrizione in italiano. Non fare
merge: la PR la rivede Claude.»

Per un task correttivo `R<n>`: stesso messaggio, con «Fai la correzione **R<n>** sul branch della
PR indicata».

## Note per il giro 2 (dalla revisione del giro 1)

- **API già pronte** da usare nei pannelli: `PATCH /lessons/{id}/metadata` (B1: titolo, materia, data,
  ora, docente; 409 con job attivo o documento in modifica), `GET …/document/pipeline-version` e
  `POST …/document/restore-pipeline` (B2), `POST …/recall/vote` con `reasons` e `comment`,
  `POST …/recall/regenerate`, `dont_know` in `POST …/recall/answer`, `outcome` nelle domande (B4,
  B5), `instructions`/`selection`/`count` in `POST …/recall/generate` (B3), `with_enrichment` nei
  job (B6), `PUT /settings/preferences` (B8), `expires_at`/`timer_seconds`/`timer_suspended` nella
  scaletta e `POST …/outline/suspend` (B9).
- **G1**: il vecchio `DetailsPanel` di F0 è solo il contenuto di prima spostato; va rifatto come da
  wireframe. "Elimina la lezione…" torna qui (vedi task).
- **G5**: il pulsante Domande dell'intestazione apre già il pannello (oggi vuoto); la pagina Recall
  non ha più un link dall'intestazione.
- **C4**: dopo "Rigenera con queste modifiche" la nuova scaletta deve ripartire con il conto
  alla rovescia: alla fine del job di revisione della scaletta chiamare
  `outline_service.start_outline_timer`. Il timer gira nel processo del worker; se il worker
  riparte, l'approvazione scatta alla prima lettura della scaletta (`get_outline_review`).
- **Stile**: colori solo dalle variabili del tema (per i gruppi `--group-1..4`, `--group-gray`),
  testo con `text-meta`/`text-body`/`text-heading`.

## Correzioni

Task correttivi aperti dalla revisione (formato: `R<n> — task di origine — agente — cosa correggere`).

- **R1 — G4 — Antigravity — sessione di ripasso con i componenti comuni.** _Fatta (#52)._
  `frontend/src/components/recall/LightweightSession.tsx`: i due fogli "Domanda scartata" e
  "Commenta la domanda" sono `div` fissi con `bg-black/40` → usare `components/ui/modal` (o
  `dialog`) con focus, Esc e chiusura come gli altri; chip del tipo, motivi dello scarto e opzioni
  del quiz sono `<button>` con classi scritte a mano → `Button`/`buttonVariants` o un componente
  in `components/ui/` (stesso per i filtri di `ClassifierPanel` e `QuestionsPanel`); testi
  `text-xs` → `text-meta`. "Rileggi l'unità" deve aprire la lezione sull'unità (`#unit-<id>`).
  Dopo "Invia e rigenera" mostrare l'avanzamento del job di rigenerazione invece di passare
  subito alla prossima. Test: `LightweightSession.test.tsx`, e2e `recall-images-bot`.
- **R2 — G5/A5 — Antigravity — unità per il recaller.** _Fatta (#52)._ A5 ha tolto `UnitSelector` ma nessun
  pannello lo sostituisce: "Unità per il recaller … Scegli" porta al Classificatore, che non
  permette di sceglierle. Rimettere la scelta (elenco con caselle, "solo rilevanti"/"tutte",
  salvata con l'API `…/recall/units`) nel pannello Domande o nel Classificatore, come da
  `Domande.dc.html`. "Ultimo ripasso" con la data. Test: unit del pannello scelto.
- **R3 — G3 — Antigravity — galleria dell'Arricchimento.** _Fatta (#52)._ Il clic su un'immagine usa
  `macro_ids[0]` (id della macro-sezione) come id dell'unità e cerca `[data-unit-id]` nel DOM,
  che nell'editor CodeMirror può non essere renderizzato: portare nel punto del testo con
  l'editor (riferimento dell'immagine nel Markdown o unità vera). Gli elementi pronti
  (infografiche, visualizzazioni) mostrano solo un'icona: anteprima vera. Le idee già generate
  non devono riproporre "Genera". Test: `EnrichmentPanel.test.tsx`.
