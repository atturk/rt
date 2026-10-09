# RT 4.2.4 — piano e task

Piano della 4.2.4, sul modello di `docs/REWORK_4.2.3.md`. Quadro complessivo approvato da Attilio
il 9 ottobre 2026 (thread "Raccolta feature 4.2.4b1"):

| Beta | Area | Contenuto |
|---|---|---|
| **b1** | Classificatore e Studio | K1-K3, Z1, L1, L2, CH1 (questa sezione) |
| **b2** | Verifica | backend della verifica rifatto, pannello nuovo, documento finale automatico, VC2, VC1 |
| **b3** | Domande personalizzate | DP1 base ed editor in Impostazioni |

**Claude** non implementa: scrive il piano e i prompt, rivede le PR, prova le parti toccate, le unisce
nel branch beta e pubblica la beta. Le beta successive aggiungono sezioni in fondo a questo file.

Wireframe interattivi, da aprire nel browser, in `docs/wireframes-4.2.4/`. Dove piano e wireframe non
coincidono vale il piano.

## 4.2.4b1 — classificatore e Studio

Lavora **solo Codex**, con **due PR in parallelo** su file diversi, un giro solo:

| PR | Branch | Task |
|---|---|---|
| Classificatore | `rt424b1/classificatore` | K1 → K2 → K3 |
| Studio | `rt424b1/studio` | Z1 → L1 → L2 → CH1 |

Wireframe: `RT-pannello-classificatore.html` (K2, K3), `RT-modalita-zen.html` (Z1),
`RT-linguetta-lezioni.html` (L1), `RT-cambio-lezione-pagina.html` (L2).

### Regole

- Valgono le **"Regole per tutti"** in cima a `docs/REWORK_4.2.2.md` (lingua, componenti di
  `frontend/src/components/ui/`, solo token del tema, `text-meta` / `text-body`, icone `lucide-react`,
  niente frasi che spiegano l'interfaccia) e le sezioni "Stile comune" e "Test" di `docs/REWORK_4.2.md`.
- **Branch**: già creati da `claude/rt-4.2.4-beta`. Un commit per task (messaggio `<id>: …`), alla fine
  **una sola PR per branch verso `claude/rt-4.2.4-beta`**. Mai merge su `main` o sul branch beta,
  niente tag, `VERSION` non si tocca.
- **File divisi fra le due PR.** La PR Classificatore non tocca `components/study/`, `routes/study.tsx`,
  `routes/lessons.tsx`, `lib/zen.tsx`, `components/shell/Layout.tsx`, `.github/`, `scripts/check_release.py`,
  `rt/core/version.py`, `components/settings/info.tsx`, `rt/api/routers/system.py`. La PR Studio non
  tocca `rt/services/` (tranne quanto serve a CH1), `rt/pipeline/`, `rt/core/config.py`,
  `components/lesson/panels/`, `components/settings/` (tranne `info.tsx`), `components/recall/`.
  File in comune, ognuno solo per la sua parte: `frontend/src/index.css` (Classificatore aggiunge
  blocchi nuovi `.rt-cls-*`; Studio rinomina e aggiunge i blocchi zen), `rt/api/schemas.py`,
  `docs/openapi.json`, `frontend/src/api/schema.d.ts` (si rigenerano; in caso di conflitto Claude li
  rigenera al merge).
- **Tooltip**: solo il componente `Tooltip` / `IconButton` dell'app, mai `title` nativi.
- **Lezioni e configurazioni esistenti** devono continuare a funzionare senza perdere dati: file vecchi
  (`unit_relevance*.json`, `unit_question_types.json`, `section_labels.json`, config con il blocco `jev:`
  e `enrichment:` di oggi) si leggono e si migrano da soli.
- **Test prima della PR**, tutti: pytest completo, `npm run lint`, `npm run typecheck`,
  `npx vitest run`, `npm run build`, poi gli e2e di **entrambi** i gruppi (`RT_E2E_GROUP=recall-images` e
  `RT_E2E_GROUP=other`) dopo la build. Le preferenze stanno sul server: un e2e che ne cambia una la
  rimette com'era. Rigenera `docs/openapi.json` (`python scripts/export_openapi.py`) e
  `frontend/src/api/schema.d.ts` (`npm run gen:api`) dopo i cambi all'API. Nella PR: quali test e con
  che esito.

### Decisioni (Attilio, 8 e 9 ottobre 2026)

- **Classificatore**: correggere le incoerenze I1-I6 e le inefficienze C1, C2, C5, C6 e D1-D3 della code
  review; C3 scartata (il tipo consigliato del recaller non si tocca), C4 superata dalle domande
  personalizzate della b3. Impostazioni con un modello condiviso e un interruttore per job. Pannello a
  griglia come dal wireframe.
- **Zen**: decisioni dell'8 ottobre scritte nella scheda 4 del wireframe (tasti italiani D, E, G, ⇧E, S,
  Z; nessuna scorciatoia sposta il testo; barra solo col mouse in cima; Irlen condiviso con la lettura
  veloce; niente audio, niente ripasso in zen).
- **Linguetta (L1)**: approvata con le proposte del wireframe: la lezione nuova si apre dalla prima
  unità andando avanti e dall'ultima andando indietro; il mouse sopra la linguetta ferma il timer;
  le lezioni non pronte si saltano.
- **Pagina lezione (L2)**: approvata con le proposte del wireframe, compresi i commenti: al passaggio
  del mouse compaiono tutti e quattro i bottoni, semitrasparenti tranne quello sotto il mouse; su iPhone
  sempre linguetta fissa a metà schermo; contano tutte le lezioni.
- **Changelog**: `CHANGELOG.md` nel repo, testo della release su GitHub, mostrato in Impostazioni › Info.

### Task

| Id | PR | Cosa |
|---|---|---|
| K1 | Classificatore | Classificazione caricata una volta, meno chiamate, cache di prefiltro e deriva |
| K2 | Classificatore | Impostazioni › Modelli › Classificatore unica, con migrazione |
| K3 | Classificatore | Pannello Classificatore a griglia e bottone in Dettagli |
| Z1 | Studio | Modalità zen |
| L1 | Studio | Linguetta per cambiare lezione nello Studio |
| L2 | Studio | Cambio lezione dalla pagina lezione |
| CH1 | Studio | Changelog |

### K1 — Classificazione caricata una volta, meno chiamate

Code review del 9 ottobre (punti C1-C6, D1-D3, I1-I6, riassunti nei task). Moduli: `rt/services/unit_relevance.py`, `rt/services/question_types.py`,
`rt/services/section_labels.py`, `rt/pipeline/recall_special.py`, `rt/services/recall_context.py`,
`rt/services/enrichment_service.py`, `rt/pipeline/review.py`.

1. **Letture da disco (D1-D3).**
   - `lesson_context(lesson_dir)` (`recall_context.py:41`) si calcola una volta: cache per
     `(lesson_dir, mtime di info.yaml, mtime di outline.json)`. `_unit_hash` (rilevanza) e
     `_section_hash` (casi/esercizi) la usano invece di rileggere i file per ogni unità.
   - Una funzione `included_ids(lesson_dir, units, *, view)` carica `unit_relevance*.json` e la
     configurazione **una volta** e restituisce l'insieme delle unità incluse. La usano al posto del
     ciclo su `included()`: `review.py:616-617`, `review_service.py:347`, `list_units`. `included()`
     resta per i chiamanti singoli e delega alla nuova funzione.
   - `recall_special.available()` e `groups()` calcolano `sections()` e `labels()` una volta e se le
     passano (oggi `labels` richiama `sections`, e `available` chiama `groups` e poi di nuovo `labels` e
     `sections`). `section_labels.labels()` e `view()` accettano `sections` già calcolate.
   - Test: un test che conta le aperture di `info.yaml`/`outline.json` (mock di `open` o contatore) per
     `list_units` su una lezione di 10 unità: una lettura, non dieci.
2. **Rilevanza e tipo consigliato in una sola chiamata (C1).** Quando per una subunità vanno rifatte
   entrambe, si fa **una** `call_jev` con le due domande (`QUESTION_NAMES["relevance"]` e
   `tipo_consigliato`); se ne serve una sola, si chiede solo quella. Lo stato mandato al modello è
   quello della rilevanza (`jev_mapping.state_for("relevance", …)`), così la rilevanza **non** cambia
   impronta e non si riclassifica; il tipo consigliato cambia ingresso, quindi la sua `_config_hash`
   aggiunge un numero di versione (`QT_VERSION = 2`) e si riclassifica una volta. Le impronte e i file
   restano separati (`unit_relevance*.json`, `unit_question_types.json`): cambiare i criteri di una non
   rifà l'altra. Il punto naturale è `rewrite.py:118-129`, dove oggi si chiamano `unit_relevance.refresh`
   e poi `question_types.refresh`: diventano una funzione `classify_units(lesson_dir, ctx)` in un modulo
   nuovo `rt/services/classifier.py`, che decide per ogni subunità cosa chiedere.
3. **Solo subunità didattiche (C2, C5).** Il tipo consigliato si calcola solo sulle subunità con
   rilevanza effettiva `didactic` (con la rilevanza spenta o in osservazione: tutte, come oggi).
   `enrichment_service.analyze` salta le subunità non didattiche con la stessa regola. Le altre restano
   senza valore ("saltata" nel pannello di K3) e si possono classificare a mano da lì.
4. **Cache di prefiltro e deriva (C6).** File nuovo `unit_prefilter.json` (aggiungerlo a
   `rt/core/lesson_paths.py`), una riga per unità: `text_hash` (titolo + testo + contesto della lezione),
   `config_hash` (modello, mappatura `prefilter_decision`, soglie), `task_a` (verdetto ed esito),
   `task_b` (punteggio ed eventuale issue), `at`, `error`. `run_jev_task_a` / `run_jev_task_b`
   (`review.py:199`, `:241`) leggono la riga se è fresca e chiamano il modello solo se manca o è vecchia;
   dopo la chiamata la scrivono (sotto il lock della lezione, come `unit_relevance._save`). Una funzione
   `refresh_prefilter(lesson_dir, unit_ids=None, force=False)` li esegue fuori dalla revisione: la usa il
   job di K3. Il Task A continua a **non** vedere il trascritto grezzo (`review.py:205`); le due domande
   restano due chiamate.
5. **Test**: unit per `classify_units` (una chiamata con due domande quando servono entrambe, una sola
   quando ne serve una, nessuna quando tutto è fresco), per il filtro didattico di tipo consigliato e
   arricchimento, per la cache di `unit_prefilter.json` (seconda revisione forzata senza chiamate se il
   testo non cambia; chiamata se cambia). I test esistenti (`test_unit_relevance.py`,
   `test_question_types.py`, `test_recall_special.py`, `test_jev_prefilter.py`, `test_enrichment.py`)
   restano verdi, aggiornati solo dove cambia il numero di chiamate.

### K2 — Impostazioni › Modelli › Classificatore unica

Oggi tre modelli e tre interruttori per lo stesso servizio (I2, I3): `jev.relevance_model` +
`jev.relevance_mode` accendono insieme rilevanza, tipo consigliato e casi/esercizi; `jev.model` +
`jev.enabled` + `jev.shadow` il prefiltro e la deriva; `enrichment.decision_model` + `enrichment.mode`
l'arricchimento e il giudice delle immagini. Vedi `rt/core/config.py` (`JevConfig` :311,
`EnrichmentConfig` :349).

1. **Config.** Blocco nuovo `classifier:` in `config/general.yaml`, modello `ClassifierConfig` in
   `rt/core/config.py`:
   ```yaml
   classifier:
     model: typesafe/jev-1.13      # condiviso
     credential: openrouter
     base_url: null
     timeout_seconds: 30
     jobs:
       relevance:      {mode: observe}    # off | manual | observe | pipeline
       question_types: {mode: pipeline}   # off | manual | pipeline
       section_labels: {mode: pipeline}   # off | manual | pipeline
       prefilter:      {mode: off}        # off | manual | observe | pipeline
       drift:          {mode: off}        # off | manual | observe | pipeline
       enrichment:     {mode: manual}     # off | manual | pipeline
       images:         {mode: manual}     # off | manual (il giudice si usa solo nel job "Aggiungi immagini")
   ```
   Ogni job può avere `model`, `credential`, `base_url` propri che sostituiscono quelli condivisi.
   - `off`: il job non gira e non si vede nel pannello di K3 (riga spenta).
   - `manual`: gira solo dal pannello (o dal job dedicato), mai in pipeline.
   - `observe`: gira in pipeline e salva il risultato, ma non filtra né salta nulla (l'"ombra" di oggi).
   - `pipeline`: gira in pipeline e conta (rilevanza = filtro attivo; prefiltro = salta la revisione;
     deriva = apre l'issue; arricchimento = automatico a fine pipeline).
   - Soglie, prompt e mappature (`relevance_decision`, `prefilter_decision`, soglie di Task A/B,
     `relevance_threshold`, `utility_threshold`) restano dove sono: il playground non cambia.
2. **Un solo punto di lettura.** Funzione `classifier_job(cfg, name) -> ClassifierJob` (mode, model,
   credential, base_url, timeout) in `rt/core/config.py` o `rt/services/classifier.py`. Tutti i
   chiamanti la usano al posto di `cfg.jev.relevance_model`, `relevance_mode`, `jev.enabled`,
   `jev.shadow`, `jev.model`, `enrichment.decision_model`, `enrichment.mode`: `unit_relevance.mode()`,
   `question_types.enabled()`, `section_labels.mode()`, `_review_unit` (:333/:344), 
   `enrichment_service.decision()`, `pipeline_service.py:298-309`, `job_handlers.py:173`, il giudice
   delle immagini. Tipo consigliato e casi/esercizi **non dipendono più** dalla rilevanza (I2). La
   flag CLI `--shadow-jev` resta e forza `observe` per prefiltro e deriva.
3. **Migrazione.** Se `classifier:` manca, un validatore `before` di `RTConfig` lo ricava dalla config
   vecchia, senza scriverla:
   - `model` = `jev.relevance_model` o, se vuoto, `jev.model`; `credential`, `base_url`, `timeout` da
     `jev`. Se `enrichment.decision_model` è diverso dal modello condiviso, va come `model` del job
     `enrichment` (e `images`), con le sue credenziali.
   - `relevance`: `disabled` → `off` (anche con `relevance_model` vuoto), `shadow` → `observe`,
     `active` → `pipeline`. `question_types` e `section_labels`: `pipeline` se la rilevanza non era
     spenta, altrimenti `off`.
   - `prefilter` e `drift`: `jev.enabled` falso → `off`; vero con `jev.shadow` → `observe`; vero senza →
     `pipeline`.
   - `enrichment`: `disabled` → `off`, `manual` → `manual`, `automatic` → `pipeline`.
   Al primo salvataggio dalle Impostazioni si scrive il blocco `classifier:` e si tolgono le chiavi vecchie
   da `jev:` (`enabled`, `shadow`, `model`, `credential`, `base_url`, `timeout_seconds`, `relevance_mode`,
   `relevance_model`) e da `enrichment:` (`decision_*`, `mode`, `automatic`). Aggiornare
   `config.example/general.yaml`.
4. **API.** `GET/PUT /settings/classifier` (nuovo router o in `settings.py`): modello condiviso e
   l'elenco dei job con mode e modello facoltativo. Il PUT chiede la prova di connessione (`probe`) come
   oggi `PUT /settings/decision-model` quando cambia il modello. `GET/PUT /settings/decision-model`
   resta per il playground ma non scrive più modelli e interruttori; `GET/PUT /settings/enrichment`
   non scrive più `mode` e `decision_*`.
5. **Interfaccia** (`components/settings/`, scheda "Impostazioni" del wireframe): sezione
   **Classificatore** in Modelli, al posto di modello e Select di `jev-playground.tsx:234-245` e dei campi
   decisionali di `enrichment.tsx`. In cima modello, connessione e timeout condivisi; sotto una riga per
   job con nome, una frase corta su cosa decide, il Select della modalità (solo le modalità valide per
   quel job) e un'icona ⋯ per il modello proprio. Il playground (domande e mappature) resta sotto, con il
   selettore di fase che oggi ha. Testi: "Spento", "Manuale", "In osservazione", "In pipeline".
6. **Test**: unit sulla migrazione (ogni combinazione della config vecchia sopra, più config già
   nuova), su `classifier_job` (modello del job che sostituisce il condiviso), sul fatto che spegnere la
   rilevanza non spegne più tipo consigliato e casi/esercizi; API; vitest della sezione; i test esistenti
   delle impostazioni (`test_decision_model_settings.py`, `test_enrichment_settings.py`,
   `test_config_split.py`, `jev-playground.test.tsx`, `enrichment.test.tsx`) aggiornati.

### K3 — Pannello Classificatore a griglia

Wireframe `RT-pannello-classificatore.html`, scheda "Lezione". Oggi: `ClassifierPanel.tsx` (lista
unità con Select) + `SectionLabelsCard` (`components/recall/SectionLabels.tsx`).

1. **API unica** (alimentata dallo snapshot di K1): `GET /lessons/{id}/classifier` restituisce
   - le unità nell'ordine della lezione, raggruppate per sezione (`id`, `title`, `section_id`, per le
     subunità);
   - per ogni job (`relevance`, `question_types`, `exercises`, `cases`, `prefilter`, `drift`,
     `enrichment`) `mode`, stato (fatto / parziale / da rifare / mai / spento), ultima esecuzione,
     numero di errori e le **celle**: `unit_id` (o `section_id` per esercizi e casi), `value`, `source`
     (`classifier` | `manual`), `state` (`fresh` | `stale` | `missing` | `error` | `skipped`),
     `confidence` e le opzioni possibili.
   - Rilevanza: la **vista risolta** quando esiste, altrimenti la bozza (I4).
   Correzioni: `PUT /lessons/{id}/classifier/{job}/{cell_id}` con `{value}` (`null` = torna al valore
   del classificatore) per rilevanza, tipo consigliato (nuovo, I5), esercizi e casi; le route di oggi
   (`/relevance/{unit_id}`, `/sections/{section_id}`) restano e delegano. Il tipo consigliato a mano ha
   la precedenza nel recall (`question_types.suggestions` / `recall_service.py:87-100`).
   Esecuzione: `POST /lessons/{id}/classifier/{job}/run` con `{force, unit_ids?}` (job in coda come
   oggi `unit_relevance`); `POST /lessons/{id}/classifier/run` per tutti i job attivi.
2. **Pannello** (`ClassifierPanel.tsx` riscritto, `SectionLabelsCard` tolto dal pannello):
   - In cima una riga di stato e due icone: classifica le cambiate, riclassifica tutte (con conferma).
   - Un blocco per job, nell'ordine Rilevanza, Tipo di domanda, Esercizi, Casi clinici, Prefiltro
     errori, Deriva dal trascritto, Arricchimento. Nome, stato e due icone (classifica le cambiate,
     riclassifica tutte). I job `off` non si mostrano; i `manual` sì.
   - La griglia: un rettangolo per subunità (per Esercizi e Casi uno che copre tutte le subunità
     dell'unità), colonne allineate fra i job, colore per valore. Puntino in alto a destra = corretta a
     mano; tratteggio = da classificare; bordo rosso = errore; vuoto tratteggiato = saltata.
   - Tooltip col componente dell'app: unità, titolo e valore. L'hover evidenzia la stessa subunità in
     tutti i job.
   - Clic: scheda dal basso (sul telefono e sul computer, come nel wireframe) con il valore da scegliere,
     "Torna al classificatore", "Riclassifica questa", "Vai all'unità" (`/lezioni/ID#unit-X`), ‹ › per la
     subunità vicina.
   - Prefiltro, Deriva e Arricchimento si eseguono da qui con `refresh_prefilter` (K1) e
     `enrichment_service.analyze`: revisione e arricchimento poi riusano il risultato.
   - I testi della card vecchia (I1) e il titolo schiacciato (I6) spariscono con la card.
3. **Dettagli**: in `DetailsPanel.tsx`, sotto lo stato, un bottone grande **Classificatore** (icona Tags,
   nome, "N unità da rivedere" = errori + da classificare + da rifare) che apre il pannello
   (`?panel=classificatore`). Stesso stile dei bottoni del wireframe di VC1
   (`RT-verifica-chiedi.html`, scheda 2): nella b2 accanto arriverà "Verifiche e domande".
4. `UnitStrip` (pannelli Verifica e Domande) resta in questa beta e apre il pannello nuovo; si toglie dal
   pannello Verifica nella b2. `lessonClassifier.ts` (etichette nell'editor) non cambia.
5. **Test**: pytest dell'API (celle, vista risolta, correzione del tipo consigliato usata dal recall,
   run per job), vitest del pannello (blocchi, tooltip, scheda, correzione), e2e nel gruppo `other`
   (apri dal bottone in Dettagli, correggi una cella, il puntino compare, torna al classificatore).

### Z1 — Modalità zen

Wireframe `RT-modalita-zen.html` (quattro schede; la quarta ha la tabella dei tasti e le decisioni).
File: `components/study/Study.tsx`, `lib/zen.tsx`, `components/shell/Layout.tsx`, `index.css`,
`lib/studyPrefs.ts`.

1. **Nomi.** Oggi `zen` vuol dire "lettura veloce": `useZen`/`ZenState` in `lib/zen.tsx`, `data-zen`
   in `Layout.tsx:107` e `StudyShell` (:587), CSS `[data-zen]` in `index.css:645-667`. Rinominarli in
   `rsvp` (`useRsvpLayout`, `data-rsvp`, `[data-rsvp]`) senza cambiare comportamento, poi aggiungere la
   zen vera con `data-zen`. Gli e2e e i vitest della lettura veloce si aggiornano solo nei selettori.
2. **Entrare e uscire**: IconButton (lucide `Focus`, tooltip "Modalità zen · Z") come **primo**
   elemento di `headerActions` (Study.tsx:299), tra ⓘ e `HighlightTools`; tasto Z; Esc chiude le
   impostazioni, poi esce. Stato in `StudyFlow`, che resta acceso cambiando unità e lezione (anche con
   L1). Entrando l'audio dell'unità si ferma.
3. **Cosa sparisce**: rail e tab bar (come fa oggi la lettura veloce, `inert` + `aria-hidden`), indice,
   contesto, barrette, audio, footer "Mettimi alla prova". Resta il testo a tutta altezza.
4. **Barra in alto**: nascosta; scende solo quando il mouse entra nei primi 40 px della finestra (barra
   alta 52), resta giù finché il mouse è sopra o un suo menu è aperto, risale 2 s dopo che il mouse è
   uscito; lo scroll non la tocca; scende anche col fuoco da tastiera. Contiene a sinistra il nome
   dell'unità attenuato, a destra Impostazioni (solo Irlen, la stessa preferenza `study.rsvp.irlen` della
   lettura veloce) ed Esci. Solo con `@media (hover: none)`: tocco sul bordo alto la fa scendere, tocco
   nel testo la richiude. Impostazioni dal basso sotto i 768 px.
5. **Tasti** (stesso gestore di Study.tsx:164-190, stesse esclusioni: campi, modificatori, popup aperti):
   - `D`: come "Mettimi alla prova" (ripasso classico, o popup Genera senza domande); "Torna allo
     Studio" riporta in zen. Vale anche fuori da zen.
   - `E`: attiva/toglie l'evidenziatore; `G`: attiva/toglie la gomma; `⇧E`: colore successivo (accende
     l'evidenziatore se era spento). `HighlightMode` diventa `'evidenzia' | 'gomma' | null`. Valgono
     anche fuori da zen.
   - `S`, `←`/`→` come oggi; `Z` entra ed esce.
   - Avvisi a icone **solo in zen** e solo per S (icona dello stato nuovo), E/⇧E (evidenziatore col
     colore, barrato se tolto), G (gomma, barrata se tolta); testo uguale in `aria-live`.
6. **Posizione**: nessuna scorciatoia e nessun cambio di modalità sposta il testo (S, E, ⇧E, G, la
   barra, entrare e uscire da zen, tornare dal ripasso). Solo il cambio di unità riparte dall'inizio.
   Salvare e rimettere lo `scrollTop` del contenitore di lettura dove serve.
7. Bordo laterale all'inizio e alla fine come nello Studio classico. Dalla zen non si apre la lettura
   veloce (bottone assente). iPhone: zen senza tasti, tocco sul bordo alto.
8. **Test**: vitest dei tasti (D, E, G, ⇧E, Z, Esc), dello stato che resta cambiando unità, dello scroll
   che non cambia con S/E/G; e2e nel gruppo `other`: entra con Z, la barra scende col mouse in cima e
   risale dopo 2 s, Esc esce, iPhone a 390 px con tocco sul bordo.

### L1 — Linguetta per cambiare lezione nello Studio

Wireframe `RT-linguetta-lezioni.html`. Oggi `StudyLessonPage` passa **una** lezione a `StudyFlow`
(`routes/study.tsx:21`), quindi `next-lesson` di `studyNavigation` non scatta mai: il cambio di lezione
passa dalla route.

1. **Vicini**: funzione pura `lessonNeighbors(lessons, id, {readyOnly})` in `lib/lessonNeighbors.ts`, con
   `useLessons()`. Ordine: data, ora, titolo (stesso criterio di `sortLessons`, `lib/lessonView.ts:94`);
   lezioni senza data in fondo. Restituisce `{sameDay: {prev, next}, sameSubject: {prev, next}}`; stesso
   giorno = stessa `data`, stessa materia = stessa `materia`. Con `readyOnly` si saltano le lezioni con
   `phases.rewrite !== 'VALID'` (nello Studio sì, in L2 no).
2. **Componente condiviso** `LessonJumpButtons` (in `components/lesson/` o `components/shared/`): i due
   bottoni (Calendar + freccia, Tag + freccia), tooltip "Lezione dopo dello stesso giorno: <titolo>" e
   simili, bottone spento con il motivo se manca la lezione, barra del tempo facoltativa. E
   `LessonJumpTab`: la linguetta fissa a metà altezza sul lato, che lo contiene.
3. **Quando**: in `navigateReading` (Study.tsx:119-134), su `'left-edge'`/`'right-edge'`, oltre al bordo
   si apre la linguetta sul lato con 5 s di barra; ripremendo la stessa freccia i 5 s ripartono; la
   freccia opposta o qualsiasi cambio di unità la chiude; il mouse sopra ferma il timer (riparte da 5 s
   quando esce). Solo Studio classico, non in zen né in lettura veloce. Swipe sul telefono uguale.
4. **Clic**: `navigate('/studio/lezione/' + id, {state: {enter: 'first' | 'last'}})`: avanti dalla prima
   unità, indietro dall'ultima. `StudyFlow` legge lo stato (come fa oggi `enterLast`). Se la zen era
   accesa resta accesa (stato nella route o in un contesto).
5. **Test**: unit di `lessonNeighbors` (stesso giorno, materia, non pronte, nessun vicino, senza data);
   vitest: → sull'ultima unità mostra la linguetta, ← la chiude, dopo 5 s sparisce; e2e: il clic apre la
   lezione giusta sulla prima unità, e indietro sull'ultima.

### L2 — Cambio lezione dalla pagina lezione

Wireframe `RT-cambio-lezione-pagina.html` (vista Computer e iPhone). File: `routes/lessons.tsx` (box del
titolo :254-257), i componenti di L1.

1. **Computer, mouse** (solo `@media (hover: hover)`): il box del titolo diventa `relative` con due fasce
   invisibili ai lati, fuori dalla colonna di lettura (circa 76 px). Entrando in una fascia compaiono
   **tutti e quattro** i bottoni (due per lato), al 40% di opacità tranne quello sotto il mouse; uscito
   il mouse da fasce e bottoni spariscono dopo 150 ms. Con il pannello laterale aperto la fascia destra
   resta a sinistra del pannello.
2. **Computer, tastiera**: ← → mostrano i bottoni di quel lato per 5 s con la barra; ripremendo, i 5 s
   ripartono. Il gestore sul documento esce subito se: modificatori, `defaultPrevented`, bersaglio dentro
   `.cm-editor`, `input`, `textarea`, `select`, `[contenteditable]`, `[role=slider|menu|listbox|dialog]`
   (il player audio usa le frecce, `AudioPlayer.tsx:36-49`), selezione non vuota, dialogo aperto.
   CodeMirror tiene le sue frecce senza modifiche.
3. **Titolo fuori vista**: `IntersectionObserver` sul box; se non si vede, frecce e swipe mostrano
   `LessonJumpTab` fissa a metà altezza della finestra, sopra editor e player (z-index sotto solo a menu e
   tooltip).
4. **iPhone**: swipe orizzontale sull'articolo con la soglia dello Studio (`swipe.ts`: |dx| ≥ 60 px,
   |dx| > 2·|dy|, < 600 ms), ignorando gesti dentro tabelle o formule che scorrono, con selezione attiva,
   o nei primi 25 px dal bordo sinistro. Mostra `LessonJumpTab` del lato per 5 s, **sempre** fissa a metà
   schermo a qualunque scroll, con `env(safe-area-inset-*)`; non apre direttamente la lezione.
5. **Lezioni**: tutte, anche non rielaborate (`readyOnly: false`). **Clic**: `navigate('/lezioni/' + id)`
   mantenendo `?panel=`; la pagina riparte dall'alto.
6. **Test**: e2e con il cursore nell'editor (le frecce muovono il cursore, i bottoni non compaiono),
   fuori dall'editor (compaiono per 5 s), hover su una fascia (quattro bottoni, opacità), swipe a 390 px
   con `page.context().newCDPSession(page)` + `Input.dispatchTouchEvent` in un contesto `hasTouch` (con
   la pagina scorsa a metà: la linguetta è dentro la finestra).

### CH1 — Changelog

1. **File** `CHANGELOG.md` nella radice: una sezione per versione, la più nuova in cima,
   intestazione `## 4.2.4b1 — 2026-10-xx`, sotto elenchi brevi in italiano divisi in "Novità",
   "Correzioni", "Cambiamenti". Prima sezione: la 4.2.4b1 (scritta da Codex con i task di questa beta,
   Claude la rivede). Sotto, una riga che rimanda alle release di GitHub per le versioni precedenti.
2. **Release** (`.github/workflows/release.yml`, `scripts/check_release.py`):
   - `check_release.py` aggiunge `CHANGELOG.md` a `REQUIRED`/`ALLOWED_ROOT_FILES`, verifica che esista la
     sezione della versione e la estrae in `dist/release-notes.md`; senza sezione si ferma con un errore
     chiaro. Aggiornare `tests/test_release_archive.py`.
   - Nel passo `softprops/action-gh-release` (:85-96) `generate_release_notes: true` diventa
     `body_path: dist/release-notes.md`.
3. **Aggiornamento**: `rt -u` oggi copia solo `rt`, `bin`, `config.example`, `docs` e `VERSION`
   (`rt/core/version.py`, `_is_managed_code` :261-265, copia a :503-544): aggiungere `CHANGELOG.md`,
   copiato insieme a `VERSION`, con un test.
4. **App**: `GET /api/v1/system/changelog` (`rt/api/routers/system.py`, autenticato) restituisce le
   sezioni lette dal `CHANGELOG.md` installato: `[{version, date, groups: [{title, items}]}]` (vuoto se
   il file manca). In Impostazioni › Info (`components/settings/info.tsx`), sotto le righe di sistema,
   una sezione **Novità**: la versione installata aperta, le precedenti chiuse (`<details>`), testo
   semplice (niente renderer Markdown). Test: pytest del parser e dell'API, vitest della sezione.
5. Regola da qui in poi: ogni PR verso un branch beta aggiunge le sue righe alla sezione della versione
   in corso. Scriverla in `docs/DEVELOPMENT.md`.

### Revisione e merge (Claude)

Claude rivede le due PR, prova le parti toccate (anche nel browser), unisce prima Classificatore e poi
Studio in `claude/rt-4.2.4-beta`, rigenera openapi e tipi se servono, porta `VERSION` a `4.2.4b1`, fa
girare la suite completa in locale e pubblica la v4.2.4b1 con release.yml, seguendo il run fino alla
fine.
