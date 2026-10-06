# RT 4.2.3 — piano e task

Piano della 4.2.3, sul modello di `docs/REWORK_4.2.2.md`. **Claude** non implementa: rivede la PR,
la unisce nel branch beta e pubblica la beta. Le beta successive aggiungono sezioni in fondo a
questo file.

## 4.2.3b1 — stato di studio, lettura veloce zen, dettagli della selezione

Richieste di Attilio del 5 ottobre 2026 (thread "4.2.3b1"), tutte approvate sul wireframe.
Per la b1 lavora **solo Codex (GPT)**, un giro solo.

Wireframe di riferimento (interattivo, Mac e iPhone): `docs/wireframes-4.2.3/RT-4.2.3b1.html`, da
aprire nel browser. Schede: Studio, Lezioni, Lettura veloce zen, Dettagli selezione, iPhone. Dove
questo piano e il wireframe non coincidono, vale il piano.

### Regole

- Valgono le **"Regole per tutti"** in cima a `docs/REWORK_4.2.2.md` (lingua, componenti di
  `frontend/src/components/ui/`, solo token del tema, `text-meta` / `text-body`, icone
  `lucide-react`, niente frasi che spiegano l'interfaccia, test delle sole parti toccate, rigenerare
  `docs/openapi.json` con `python scripts/export_openapi.py` e `frontend/src/api/schema.d.ts` con
  `npm run gen:api` quando cambia l'API) e le sezioni "Stile comune" e "Test" di
  `docs/REWORK_4.2.md`.
- **Branch**: `rt423/codex`, già creato da `claude/rt-4.2.3-beta`. Un commit per task
  (messaggio `<id>: …`), alla fine **una sola PR verso `claude/rt-4.2.3-beta`**. Mai merge su `main`
  o sul branch beta, niente tag, `VERSION` non si tocca.
- Lavorando da solo, Codex può toccare tutti i file che servono; quelli previsti sono elencati per
  task.
- Le preferenze personali stanno su RT (`/api/v1/preferences/{name}`, `frontend/src/lib/preferences.ts`):
  un test e2e che ne cambia una la rimette com'era alla fine; chi dipende da una preferenza la imposta
  lui con `page.request.put`. Gli e2e si verificano lanciando il gruppo intero, non lo spec da solo.

### Decisioni (Attilio, 5 ottobre 2026)

- Lo **stato di un'unità** è uno di tre: *da imparare* (predefinito), *in apprendimento*, *appreso*.
  Lo cambia solo l'utente, mai RT in automatico. Si salva **nel database di RT** (Mac e iPhone vedono
  lo stesso stato), non nel browser.
- RT ricorda anche **quando** si è studiato: l'ultima volta che ogni unità è stata aperta nello Studio
  e quando ne è cambiato lo stato.
- Nell'elenco delle lezioni l'avanzamento è un **anello** a destra della riga (variante A del
  wireframe).
- Le **barrette** dello Studio si colorano per stato e si possono cliccare.
- Lo Studio si apre sulla **prima unità non appresa**; se sono tutte apprese, dalla prima.
- **Export**: lo zip può includere lo stato di studio (casella, scelta ricordata); il Markdown no.
- **Lettura veloce**: diventa una modalità "zen" dentro lo Studio, con l'aspetto dell'app. Resta in
  alto l'indice "Unità N di M".
- **Dettagli** delle lezioni selezionate: approvati come nel wireframe.

### Task

| Id | Cosa |
|---|---|
| U1 | Stato di studio nel database e nell'API |
| U2 | Studio: pulsante dello stato, barrette, indice, apertura sulla prima unità non appresa |
| U3 | Lezioni: anello dell'avanzamento e ordinamenti per studio |
| U4 | Stato di studio nello zip (export e import) |
| D1 | Dettagli delle lezioni selezionate |
| V2 | Lettura veloce zen |

Ordine: U1 → U2 → U3 → U4 → D1 → V2. U2, U3, U4 e D1 usano i campi di U1.

### U1 — Stato di studio nel database e nell'API

**Modello** (`rt/db/models.py`, nuova migrazione `rt/db/migrations/versions/0010_study_units.py`):
tabella `study_units`, una riga per unità toccata almeno una volta:

| Colonna | Tipo | Note |
|---|---|---|
| `lesson_id` | int, FK `lessons.id` `ondelete=CASCADE` | chiave primaria composta con `unit_id` |
| `unit_id` | str(64) | id dell'unità, es. `1.3` (come `study_highlights`) |
| `status` | str(16) | `da-imparare` \| `in-apprendimento` \| `appreso` |
| `status_at` | datetime, null | ultimo cambio di stato |
| `last_read_at` | datetime, null | ultima apertura dell'unità nello Studio |

Nessuna riga = *da imparare*, mai letta. Verificare che `rt/services/lesson_delete_service.py`
(come per `study_highlights`) e il backup non lascino righe orfane.

**Servizio** nuovo `rt/services/study_progress_service.py` sul modello di
`rt/services/highlights_service.py`: leggere gli stati di una lezione, impostare lo stato di
un'unità, segnare una lettura, riassunto per lezione. Il riassunto conta **solo le unità che esistono
ancora** nella scaletta attuale (se la lezione viene rielaborata e un'unità sparisce, la sua riga si
ignora; non si cancella).

**API** (router nuovo `rt/api/routers/study_progress.py` o dentro quello delle evidenziazioni, tag
`studio`):

- `PUT /api/v1/lessons/{lesson_id}/study/units/{unit_id}` con `{"status": "appreso"}`: imposta lo
  stato e `status_at`. Risponde con lo stato aggiornato.
- `POST /api/v1/lessons/{lesson_id}/study/units/{unit_id}/read`: imposta `last_read_at` a ora. 204.
- `GET /api/v1/lessons/{lesson_id}/study` (esistente, `schemas.StudyUnit`): ogni unità guadagna
  `status`, `status_at`, `last_read_at`.
- `LessonSummary` (elenco delle lezioni) guadagna `study_learned` (unità apprese),
  `study_learning` (in apprendimento) e `study_last_at` (la più recente fra `last_read_at` e
  `status_at` delle sue unità, null se mai studiata). Il calcolo va fatto con **una sola query** per
  tutto l'elenco, non una per lezione.

Test: pytest del servizio e delle rotte (stato predefinito, cambio, lettura, unità sparite dalla
scaletta non contate, cancellazione della lezione), migrazione su e giù.

### U2 — Studio: stato dell'unità

File: `frontend/src/components/study/Study.tsx`, nuovo `frontend/src/api/studyProgress.ts`,
`frontend/e2e/study.spec.ts`. Wireframe: scheda **Studio**.

- **Pulsante dello stato** nell'intestazione, subito a sinistra di quello della lettura veloce (anche
  su iPhone). Un clic cicla *da imparare → in apprendimento → appreso → da imparare*. Tre icone, nessun
  testo: cerchio tratteggiato (`CircleDashed`, colore `text-muted-foreground`), mezzo pieno
  (`Contrast`, colore warning, arancione), pieno con spunta (`CircleCheck` riempito,
  colore success); se un nome non esiste nella versione di `lucide-react` installata, l'icona equivalente più vicina. Etichetta accessibile e tooltip col nome dello stato ("Stato dell'unità: appreso").
  Il cambio è ottimistico; se il salvataggio fallisce si torna allo stato di prima con l'errore.
- **Tasto `S`** cicla lo stato, con le stesse esclusioni delle frecce ← → (solo in lettura, non nei
  campi di testo, non con ⌘/Ctrl/Alt, non in lettura veloce).
- **Barrette** (`Dots`): colore per stato, *da imparare* neutro come le barrette non ancora lette di
  oggi (`bg-muted`, nel tema scuro chiaro), *in apprendimento* warning, *appreso* success. L'unità
  aperta non si riconosce più dal colore: la sua barretta è **più alta** (circa 7 px contro 3). Le
  barrette diventano pulsanti: clic = `goToUnit(i)`, `title` col titolo dell'unità e lo stato, area di
  clic più alta della barretta (almeno 12 px), non devono avere più `aria-hidden` (etichetta "Unità N:
  titolo, stato").
- **Indice "Unità N di M"** (`UnitIndexMenu`): al posto di "letta" a destra, l'icona dello stato
  prima del titolo e la data dell'ultimo cambio di stato ("oggi", "ieri", "3 ott") a destra;
  l'unità aperta resta "qui".
- **Apertura**: lo Studio si apre sulla **prima unità non appresa** nell'ordine delle unità; se sono
  tutte apprese, sulla prima. Vale per ogni lezione quando lo Studio passa alla lezione successiva.
  Il flusso con `onlyUnits` (Domande su questa parte) non cambia.
- **Lettura**: quando un'unità resta aperta in lettura almeno 3 secondi, si chiama
  `POST …/read` (una volta per apertura; chi scorre veloce con le frecce non segna niente).
- Le query di `['lessons']` e dello studio si aggiornano dopo un cambio di stato.

Test: vitest per la scelta dell'unità iniziale e il ciclo degli stati; e2e in `study.spec.ts`:
cambia stato col pulsante e con `S`, ricarica e lo ritrova, la barretta prende il colore, il clic
su una barretta cambia unità, la riapertura parte dalla prima non appresa.

### U3 — Lezioni: anello e ordinamenti

File: `frontend/src/components/lessons/LessonsView.tsx`, `frontend/src/lib/lessonsPage.ts`,
`frontend/e2e/lessons-view.spec.ts`. Wireframe: scheda **Lezioni**, variante A.

- **Anello** a destra di ogni riga, allineato in colonna: SVG di 22 px, arco success per le apprese,
  arco warning subito dopo per quelle in apprendimento, fondo `bg-muted`; a sinistra dell'anello
  "7/18" in `text-meta`, cifre tabulari. Una lezione mai studiata (`study_learned` e
  `study_learning` a zero) non mostra niente. In modalità selezione l'anello non c'è.
  `aria-label` "7 unità apprese su 18, 2 in apprendimento".
- **Sottotitolo**: dopo "18 unità" si aggiunge " · 7 apprese" quando sono più di zero.
- **Ordina**: tre voci nuove dopo quelle di oggi, in `SORT_OPTIONS`, `SORT_CYCLE` e
  `PHONE_SORT_LABELS`:

  | Chiave | Menu | iPhone | Regola |
  |---|---|---|---|
  | `studio-recente` | Studiate di recente | Studio | `study_last_at` decrescente; mai studiate in fondo, fra loro per data |
  | `piu-avanti` | Più avanti nello studio | Avanti | apprese/totale decrescente; a pari, più unità in apprendimento prima |
  | `piu-indietro` | Più indietro nello studio | Indietro | apprese/totale crescente; a pari, meno unità in apprendimento prima |

  L'ordine vale dentro ogni gruppo, come quelli di oggi. Lezioni senza unità (`unit_count` nullo o
  zero) contano 0 %.

Test: vitest degli ordinamenti in `lessonsPage`; e2e: l'anello compare dopo aver segnato un'unità e
l'ordinamento "Più avanti nello studio" mette prima quella lezione.

### U4 — Stato di studio nello zip

File: `rt/storage/export.py`, `rt/services/lesson_import_service.py`, `rt/api/routers/lessons.py`,
`rt/api/schemas.py`, `rt/services/api_jobs.py`, `frontend/src/routes/lessons.tsx` (menu export della
lezione), `frontend/src/components/lessons/LessonsView.tsx` (`SelectionBar`).

- Lo zip completo (`scope=all`) può portare lo stato di studio nel manifesto `rt-export.json`, come
  chiave in più `"study": [{"unit_id", "status", "status_at", "last_read_at"}, …]`. Niente file nuovi
  nell'archivio: così uno zip con lo stato si importa anche in un RT che non lo conosce (la chiave in
  più si ignora).
- Export di una lezione: parametro `study: bool = false` di `GET /lessons/{id}/export`; export di
  gruppo: campo `study: bool = false` di `LessonExportRequest`, passato fino a `_export_zip_into` per
  ogni lezione.
- **Import**: se il manifesto ha `study`, dopo aver creato la lezione si scrivono le righe di
  `study_units`. Valori non validi si saltano senza far fallire l'import.
- **Interfaccia**: preferenza nuova `export.study` (booleano, predefinito `true`).
  - Nel menu export della pagina lezione, sotto "Tutti i dati (zip)", una voce con spunta "Includi lo
    stato di studio" che cambia la preferenza; il link zip aggiunge `&study=1` quando è attiva.
  - Nella barra della selezione il pulsante zip apre un piccolo menu con la casella "Includi lo stato
    di studio" e il pulsante "Scarica zip" (wireframe, scheda Dettagli selezione, clic sull'icona zip).
- Il Markdown non cambia. Le evidenziazioni restano fuori dallo zip.

Test: pytest export con e senza `study`, import che ripristina gli stati, import di uno zip vecchio
senza la chiave.

### D1 — Dettagli delle lezioni selezionate

File: `frontend/src/components/lessons/LessonsView.tsx` (`SelectionBar`), `frontend/src/lib/lessonsPage.ts`,
eventuale nuovo `frontend/src/components/lessons/SelectionDetails.tsx`. Wireframe: scheda
**Dettagli selezione**.

- Nella barra della selezione, subito dopo "Seleziona tutto", un `IconButton` "Dettagli della
  selezione" (`Info`), non disponibile senza lezioni selezionate. Apre un `Modal` "N lezioni
  selezionate" (o "1 lezione selezionata").
- In alto sei riquadri: **Audio** (durata totale, sotto "dal … al …" con le date della prima e
  dell'ultima lezione), **Unità** (totale, sotto "N apprese · M in apprendimento"), **Domande** (nel
  pool, sotto "N da fare"), **Costo** (totale, sotto il costo per ora di audio), **Ultimo studio**
  (data relativa, sotto la lezione e l'unità se note, altrimenti solo la lezione), **Stato** (quante
  pronte, sotto quante da verificare / con errore). Valori mancanti: "—".
- Sotto, la barra dello studio sommata (success / warning / neutro) con la legenda in percentuali.
- Poi una tabella con una riga per lezione: Lezione, Audio, Studio ("7/18"), Domande, Costo;
  ordinabile cliccando l'intestazione (predefinito: costo decrescente). Su iPhone la tabella scorre
  in orizzontale dentro il popup.
- In fondo, una riga "Materie" e una "Docenti" con i conteggi.
- Tutti i numeri vengono dai campi già presenti in `LessonSummary` più quelli di U1: nessuna API nuova.
  I calcoli stanno in una funzione pura in `lessonsPage.ts`, con test vitest.

### V2 — Lettura veloce zen

File: `frontend/src/components/study/SpeedReader.tsx`, `frontend/src/components/study/Study.tsx`,
`frontend/src/components/Layout.tsx`, `frontend/src/index.css` (blocco "Lettura veloce"),
`frontend/e2e/study.spec.ts`. Wireframe: scheda **Lettura veloce zen** (provare i due pulsanti) e
scheda **iPhone**.

Oggi `SpeedReader` è un overlay `fixed inset-0` con colori suoi (`--o-*`), Giorno/Notte e una barra
in alto sua. Diventa una modalità della pagina dello Studio:

- **Entrata**: il pulsante della lettura veloce porta in modalità zen con una dissolvenza (circa
  300 ms; nessuna animazione con `prefers-reduced-motion`): il testo dell'unità sfuma e al centro
  compare la parola. **Uscita** col pulsante libro o `Esc`, con la dissolvenza inversa.
- **Cosa sparisce** in zen: la barra laterale dell'app (Mac) e la barra in basso (iPhone), con una
  dissolvenza; nell'intestazione dello Studio freccia indietro, popup dei dettagli, evidenziatore,
  cestino, pulsante dello stato, audio; il footer ("Mettimi alla prova", "genera"); le barrette.
  Per nascondere la navigazione, `Layout` espone un modo semplice (per esempio un contesto o un
  attributo `data-zen` sulla radice che il CSS usa); niente manipolazioni del DOM dall'esterno.
- **Cosa resta** in alto: il titolo dell'unità attenuato, **libro** (`BookOpen`, al posto del
  tachimetro, "Torna allo Studio"), **impostazioni** (`SlidersHorizontal`, apre il pannello),
  **contesto** (`TextQuote` o simile, attiva/disattiva il testo intorno) e l'indice **"Unità N di M"**.
  Scegliere un'altra unità dall'indice resta in zen e fa ripartire la lettura veloce su quella unità.
- **Via**: Giorno/Notte (la lettura veloce segue il tema dell'app), la pillola "← Studio", la barra
  in alto propria del lettore, "Mettimi alla prova".
- **Aspetto come l'app**: la parola usa `var(--font-sans)` come il testo dello Studio, senza la
  spaziatura larga di oggi; la lettera di fuoco resta colorata. Niente monospazio nei testi
  (velocità, conteggio parole, tempo). Pulsanti indietro / ricomincia rotondi col bordo dei token
  dell'app, play più grande con lo stile del pulsante primario (`bg-accent text-accent-foreground`).
  Slider e interruttori come quelli delle Impostazioni (riusare i componenti di
  `frontend/src/components/settings/` o `ui/` se ci sono). Le variabili `--o-*` si tolgono, tranne quelle
  che servono ai colori Irlen.
- **Pannello impostazioni**: stesse voci di oggi, come popover ancorato al pulsante (Mac) o foglio dal
  basso (iPhone), con lo stile dei menu dell'app; "Fatto" lo chiude.
- **Modalità Irlen**: il colore scelto copre **tutta la finestra**, intestazione compresa (con la
  navigazione nascosta non resta nessuna parte bianca); su iPhone anche il `theme-color` della barra
  di stato. Uscendo dalla lettura veloce tornano i colori normali.
- Tutto il resto non cambia: tasti (spazio, ← →, ↑ ↓, Home, Esc), suono, rumore di fondo, contesto,
  preferenze `study.rsvp`.

Test: aggiornare gli e2e della lettura veloce in `study.spec.ts` (non ci sono più Giorno/Notte né
"← Studio"); nuovo e2e: entrando in zen la navigazione non è visibile, il pulsante libro e `Esc`
tornano allo Studio e la navigazione ricompare; con Irlen attivo lo sfondo dell'intestazione ha il
colore Irlen.

### Revisione e merge (Claude)

Come per la 4.2.2: Claude rivede il diff, prova le parti toccate, fa le correzioni brevi con commit
"Revisione: …", unisce in `claude/rt-4.2.3-beta`, lancia **tutti** gli e2e (entrambi i gruppi) prima
di pubblicare e pubblica la beta con `release.yml` (VERSION `4.2.3b1`).

### Revisione (6 ottobre 2026)

PR #62 di Codex unita in `claude/rt-4.2.3-beta`. Correzioni di Claude:

- l'elenco delle lezioni apriva la scaletta di ogni lezione a ogni richiesta per contare le unità
  studiate: ora solo quelle con righe in `study_units`;
- nel tema scuro la lettera di fuoco della lettura veloce (colore `--link`) era quasi bianca: ora usa
  `--rsvp-focus` (success nel tema scuro, verde scuro con Irlen);
- `e2e/new-lesson.spec.ts` falliva quando avanzamento e "Scaletta da approvare" erano visibili
  insieme.

## 4.2.3b2 — Ignorata, lettura veloce con formule ed evidenziazioni, suoni, suggerimenti

> Nota: il nome della sezione resta "4.2.3b2" perché il prompt di Codex la cita così, ma questo lotto
> esce come **4.2.3b3**: la v4.2.3b2 è stata usata per il fix urgente del QR dell'iPhone.

Richieste di Attilio del 6 ottobre 2026 (thread "4.2.3b1"), discusse una per una e approvate sul
wireframe. Lavora **solo Codex (GPT)**, un giro solo.

Wireframe di riferimento (interattivo): `docs/wireframes-4.2.3/RT-4.2.3b2.html`, da aprire nel browser.
Schede: Lettura veloce (provare "Parola dopo", la barra laterale delle impostazioni e il pulsante
Ripassa), Studio (provare il pulsante dello stato e i suggerimenti passando sulle icone), Ripasso
(provare "Prossima" e "Fine"), Lezioni. Dove piano e wireframe non coincidono, vale il piano. Il
wireframe della b1 resta valido per tutto quello che qui non cambia.

### Regole

Come per la b1 (sezione "Regole" sopra), con queste differenze:

- **Branch**: `rt423b2/codex`, già creato da `claude/rt-4.2.3-beta`. Un commit per task
  (messaggio `<id>: …`), alla fine **una sola PR verso `claude/rt-4.2.3-beta`**. Mai merge su `main`
  o sul branch beta, niente tag, `VERSION` non si tocca.
- Prima di aprire la PR si lanciano **tutti** i test, non solo quelli delle parti toccate: pytest
  completo, `npm run lint`, `npm run typecheck`, `npx vitest run`, e gli e2e di **entrambi** i gruppi
  (`RT_E2E_GROUP=recall-images` e `RT_E2E_GROUP=other`). Nella b1 la release è caduta due volte su e2e
  che nessuno aveva lanciato.

### Decisioni (Attilio, 6 ottobre 2026)

- Nuovo stato dell'unità **Ignorata**: per le parti senza informazioni utili. È una scelta solo
  dell'utente, come le evidenziazioni, distinta dalla rilevanza calcolata dal classificatore.
- I suggerimenti del pulsante dello stato dicono solo lo stato ("Da imparare", "In apprendimento",
  "Appresa", "Ignorata").
- In Lezioni il sottotitolo mostra solo le apprese, **non** le ignorate. Le ignorate si vedono
  dall'arco rosso dell'anello.
- Lettura veloce: le formule si leggono (oggi si saltano), le evidenziazioni si vedono con una fascia
  uniforme, le impostazioni diventano una barra laterale senza "Fatto", i pulsanti sono quattro e
  uguali, il clic si sceglie fra tre suoni con **Legno** predefinito.
- Dopo l'ultima domanda del ripasso il pulsante è **"Fine"**.
- Suggerimenti solo al passaggio del mouse, con il comportamento "delay group".
- La selezione del testo nel tema scuro deve leggersi.

### Task

| Id | Cosa |
|---|---|
| G1 | Stato "Ignorata" (database, API, Studio, Lezioni, ripasso) |
| G2 | Studio: icona "Apri la lezione" |
| G3 | Ripasso: "Prossima" diventa "Fine" |
| G4 | Suggerimenti con delay group |
| G5 | Tema scuro: selezione del testo e pulsanti premuti |
| L1 | Lettura veloce: impostazioni in una barra laterale |
| L2 | Lettura veloce: formule |
| L3 | Lettura veloce: evidenziazioni |
| L4 | Lettura veloce: tre suoni del clic, Legno predefinito |
| L5 | Lettura veloce: quattro pulsanti, Ripassa |

Ordine: G1 → G2 → G3 → G4 → G5 → L1 → L2 → L3 → L4 → L5. L2, L3 e L4 aggiungono voci alla barra
laterale di L1.

### G1 — Stato "Ignorata"

File: `rt/services/study_progress_service.py`, `rt/api/schemas.py`, `rt/api/routers/study_progress.py`,
`rt/services/recall_service.py` (e dove si sceglie la selezione predefinita delle unità per generare,
`rt/services/recall_units.py`), `frontend/src/api/studyProgress.ts`,
`frontend/src/components/study/studyProgress.ts`, `frontend/src/components/study/Study.tsx`,
`frontend/src/components/lessons/LessonsView.tsx`, `frontend/src/lib/lessonsPage.ts`. Wireframe:
schede **Studio** e **Lezioni**.

- **Valori**: `ignorata` si aggiunge a `STATUSES` e ai `Literal` dello schema. Nessuna migrazione: la
  colonna `status` è già `String(16)`. L'export zip e l'import la accettano come gli altri stati.
- **Ciclo** (pulsante e tasto `S`): da imparare → in apprendimento → appresa → **ignorata** → da
  imparare.
- **Icona**: `CircleX` (lucide) in `text-danger`. **Barretta**: `bg-danger`.
- **Etichette**: `STATUS_LABELS` diventa al femminile e con la maiuscola, cioè "Da imparare", "In
  apprendimento", "Appresa", "Ignorata"; il valore salvato resta `appreso`. Il **suggerimento** del
  pulsante è solo l'etichetta (oggi "Stato dell'unità: …"). L'`aria-label` resta descrittivo, "Stato:
  appresa". Le stesse etichette nell'indice delle unità.
- **Apertura dello Studio**: `initialStudyUnit` salta le apprese **e** le ignorate; se sono tutte
  apprese o ignorate si parte dalla prima. Un'unità ignorata resta raggiungibile dalla barretta,
  dall'indice e dalle frecce.
- **Ripasso e generazione**: le domande delle unità ignorate non escono nella sessione sulla lezione
  intera (Mista e per tipo, web e Telegram: `pick_pending_question` senza `unit_id`). Restano nel pool
  e tornano se l'unità cambia stato. Con `unit_id` esplicito (ripasso dell'unità) l'unità si usa
  anche se ignorata. Le unità ignorate sono escluse anche dalla selezione predefinita per generare
  domande sulla lezione intera; se l'utente le sceglie a mano si usano.
- **Lezioni**:
  - `LessonSummary` guadagna `study_ignored`, calcolato nella stessa query di U1.
  - **Anello**: tutte le unità sul giro, arco success per le apprese, warning per quelle in
    apprendimento, **danger per le ignorate** in fondo al giro. Il numero è apprese su unità da
    studiare (`unit_count - study_ignored`): 18 unità, 2 ignorate, 7 apprese → "7/16".
    `aria-label` "7 unità apprese su 16, 3 in apprendimento, 2 ignorate".
  - L'anello compare anche se ci sono solo ignorate.
  - **Sottotitolo**: invariato, solo " · N apprese". Niente "ignorate".
  - Gli ordinamenti "Più avanti / Più indietro nello studio" e i Dettagli della selezione (D1) usano
    lo stesso conto (apprese / unità non ignorate). In D1 la barra dello studio aggiunge il segmento
    danger con la legenda "ignorate".

Test: pytest (stato `ignorata` accettato, `study_ignored` nel riassunto, domande delle ignorate escluse
dalla sessione sulla lezione e incluse con `unit_id`, export/import); vitest (ciclo a quattro,
apertura che salta le ignorate, ordinamenti e conti con le ignorate); e2e in `study.spec.ts` (il ciclo
arriva a "Ignorata", la barretta è rossa, la riapertura la salta) e in `lessons-view.spec.ts`
(l'anello mostra "N/M" senza le ignorate).

### G2 — Studio: "Apri la lezione"

File: `frontend/src/components/study/Study.tsx`. Wireframe: scheda **Studio** (icona tratteggiata).

- `IconLink` "Apri la lezione" (`FileText` o simile) nell'intestazione dello Studio, subito dopo il
  pulsante dei dettagli; sul telefono nello stesso gruppo di icone. Non c'è in modalità zen.
- Porta a `/lezioni/{id}#unit-{unitId}` dell'unità aperta: la pagina della lezione la porta in vista e
  la segna come fa già per "Vai all'unità" (`DocumentView.tsx`, `LessonEditor.tsx`).
- Il link "Apri la lezione ›" nel popup dei dettagli resta e usa lo stesso indirizzo.

Test: e2e, il clic porta alla pagina della lezione con l'unità segnata.

### G3 — Ripasso: "Prossima" diventa "Fine"

File: `rt/api/schemas.py` (`RecallQuestion`), `rt/api/routers/recall.py`, `rt/services/recall_service.py`,
`frontend/src/components/recall/LightweightSession.tsx`. Wireframe: scheda **Ripasso**.

- `POST /lessons/{id}/recall/next` risponde anche con `remaining`: quante domande pendenti restano
  **dopo** quella restituita, con gli stessi filtri (tipo o Mista, `unit_id`, unità ignorate escluse
  come in G1).
- In `LightweightSession`, dopo aver risposto a una domanda con `remaining == 0`, il pulsante
  "Prossima" si chiama **"Fine"** e mostra subito la schermata finale di oggi (per l'unità: "Hai finito
  le domande di questa unità" con "Riproponi le poste", "Torna allo studio", "Unità successiva"; per
  la lezione intera il suo messaggio), senza chiamare `next`.
- Se si cambia tipo con i chip, vale il `remaining` della nuova domanda.

Test: pytest di `remaining`; vitest di `LightweightSession` (all'ultima domanda compare "Fine" e il clic
mostra la schermata finale senza chiamare `next`).

### G4 — Suggerimenti con delay group

File: `frontend/src/components/ui/tooltip.tsx` (e i suoi test). Wireframe: scheda **Studio**, dove i
suggerimenti funzionano già così.

Oggi il suggerimento si apre anche a ogni focus (`onFocus: show`) e si chiude solo al blur. Così resta
aperto dopo un clic (Chrome dà il focus al pulsante), quando si torna alla finestra e quando un popup
restituisce il focus al pulsante. Nuovo comportamento, unico per tutta l'app:

- si apre al passaggio del mouse dopo **600 ms**;
- se un altro suggerimento è aperto, o se ne è chiuso uno da meno di **300 ms**, si apre **subito**
  (stato condiviso a livello di modulo, niente librerie);
- un clic (`pointerdown`) sul pulsante lo chiude e non si riapre finché il puntatore non esce e rientra;
- col focus si apre solo se il focus è visibile (`:focus-visible`, cioè navigando con Tab), mai al
  clic né quando il focus torna da solo; si chiude al blur e con `Esc` (già così);
- sui dispositivi senza hover (`(hover: none)`, telefono) non si apre mai.

L'API del componente (`content`, `side`, `describe`, `disabled`, render-prop) non cambia.

Test: vitest con i timer finti (600 ms, apertura immediata entro 300 ms, chiusura al clic, niente
apertura al focus non visibile).

### G5 — Tema scuro: selezione del testo e pulsanti premuti

File: `frontend/src/index.css`, `frontend/src/components/ui/icon-button.tsx`,
`frontend/src/components/lessons/LessonsView.tsx`. Wireframe: scheda **Studio**, riquadro sotto.

- **Selezione**: oggi `::selection` ha sfondo `--accent` (verde chiarissimo) e testo `--acc` (verde
  scuro) anche nel tema scuro. Safari rende trasparente uno sfondo di selezione opaco, quindi nel tema
  scuro il verde chiaro diventa quasi nero e il testo verde scuro sparisce. Nel tema scuro si usa uno
  sfondo già traslucido, `color-mix(in oklch, var(--success) 35%, transparent)`, con il testo
  `var(--fg)`. Il tema chiaro non cambia. La stessa coppia di colori vale per `::highlight(rt-generate)`
  e per `--atomic-editor-selection-bg` nel tema scuro.
- **Pulsanti a icona premuti** (`active` nella variante ghost): oggi `bg-muted`, nel tema scuro quasi
  uguale allo sfondo e identico all'hover. Diventano `bg-accent text-accent-foreground` nel tema
  chiaro e `bg-success-soft text-success` nel tema scuro, diversi dall'hover. Si vede per esempio su
  "Seleziona" in Lezioni e sull'evidenziatore dello Studio.
- In selezione, la riga spuntata di Lezioni ha uno sfondo tenue (`bg-accent/40` o il token più vicino).

Test: e2e leggero, nel tema scuro il colore calcolato di `::selection` non è più `--accent`; il
pulsante "Seleziona" premuto ha uno sfondo diverso da quello della pagina.

### L1 — Impostazioni in una barra laterale

File: `frontend/src/components/study/SpeedReader.tsx` (`SettingsPanel`), `frontend/src/index.css`.
Wireframe: scheda **Lettura veloce**, icona delle impostazioni.

- **Mac**: al posto del popover, una barra laterale a destra larga 340 px, dall'intestazione al fondo
  della finestra, che entra scorrendo (circa 250 ms, niente animazione con `prefers-reduced-motion`).
  Mentre è aperta la parola, i pulsanti e lo slider della velocità si centrano nello spazio rimasto a
  sinistra, così le modifiche si vedono subito.
- **Niente "Fatto"**. Si chiude con la X in alto a destra della barra, con `Esc` o di nuovo con
  l'icona delle impostazioni, che resta visibile e premuta. Il clic fuori non la chiude: la parola
  resta visibile e si può leggere con la barra aperta. Alla chiusura il salvataggio parte subito,
  senza aspettare i 400 ms.
- **Sezioni**, con il titolo piccolo maiuscolo come nel wireframe:
  - **Lettura**: pausa dopo la frase, virgola come pausa piena, pausa sulle formule (L2), lettera di
    fuoco, passo indietro;
  - **Aspetto**: dimensione del testo, font per dislessia, modalità Irlen, evidenziazioni (L3);
  - **Suono**: suono sì/no, tipo di clic (L4), tono, rumore di fondo.
- **iPhone**: resta il foglio dal basso, senza "Fatto": si chiude toccando fuori o con `Esc`.

Test: aggiornare gli e2e della lettura veloce (niente "Fatto"; la X e `Esc` chiudono; una modifica
fatta e chiusa subito è salvata su RT).

### L2 — Formule nella lettura veloce

File: `frontend/src/components/study/rsvp.ts` (e `rsvp.test.ts`), `SpeedReader.tsx`,
`frontend/src/lib/studyPrefs.ts`. Wireframe: scheda **Lettura veloce**, "Parola dopo".

- Oggi `readUnitWords` salta `.katex` e nel Contesto mette "[formula]". Ora ogni formula diventa un
  elemento del flusso: `Word` guadagna un campo opzionale `math: { html: string; tex: string; complex: boolean }`.
  - `html` è l'HTML della formula già resa da KaTeX nel testo, da clonare.
  - `tex` è il sorgente, da `annotation[encoding="application/x-tex"]`.
- La formula si mostra al posto della parola, centrata, senza lettera di fuoco, con la stessa
  dimensione del testo. Se non sta in larghezza si rimpicciolisce (`transform: scale` calcolato)
  fino a entrare. Nel Contesto c'è la formula resa, non "[formula]".
- **Semplice o complessa**, dal sorgente:
  - **atomi**: ogni lettera, cifra o simbolo vale 1; ogni comando `\nome` vale 1, tranne quelli di
    struttura e quelli di formattazione e spaziatura (`\left`, `\right`, `\,`, `\;`, `\quad`,
    `\text`, `\mathrm`, `\mathbf`, `\operatorname`, `\displaystyle`), che valgono 0. Graffe, `^`,
    `_` e spazi valgono 0;
  - **strutture**: `\frac`, `\dfrac`, `\tfrac`, `\sum`, `\prod`, `\int`, `\oint`, `\sqrt`, `\lim`,
    `\begin{…}` (una per ambiente);
  - **semplice** = nessuna struttura e al massimo 6 atomi. Non conta se è scritta con `$` o `$$`.
- **Durata**, preferenza nuova in `study.rsvp`: `formulaPause: 'adattiva' | 'standard' | 'personalizzata'`
  (predefinito `adattiva`) e `formulaMs` (predefinito 2000, da 500 a 5000 a passi di 250).
  - semplice, o modalità `standard`: come una parola;
  - complessa in `adattiva`: `60000 / wpm × (1 + 0,25 × atomi + 1,5 × strutture)`;
  - complessa in `personalizzata`: `formulaMs`;
  - se la formula chiude la frase si aggiunge la pausa di fine frase, come per le parole.
- **Suono**: una formula complessa (in `adattiva` o `personalizzata`) suona con il clic grave di fine
  frase; una semplice con quello normale.
- **Impostazioni** (sezione Lettura): "Pausa sulle formule" con tre segmenti Adattiva · Standard ·
  Personalizzata; con Personalizzata compare lo slider "Formule complesse · 2,0 s".
- Esempi a 300 parole/min (pausa parola 200 ms), da usare nei test:

  | Sorgente | Atomi | Strutture | Tipo | Durata adattiva |
  |---|---|---|---|---|
  | `z` | 1 | 0 | semplice | 200 ms |
  | `Ca^{2+}` | 4 | 0 | semplice | 200 ms |
  | `x_{\max}` | 2 | 0 | semplice | 200 ms |
  | `\sum_{i=1}^{6} x_i` | 6 | 1 | complessa | 800 ms |
  | `z = \frac{x - x_{\min}}{x_{\max} - x_{\min}}` | 11 | 1 | complessa | 1050 ms |

Test: vitest della classificazione e delle durate (la tabella), di `readUnitWords` con una formula in
linea e una a blocco; e2e: una formula in un'unità del fixture compare nella lettura veloce.

### L3 — Evidenziazioni nella lettura veloce

File: `rsvp.ts`, `SpeedReader.tsx`, `frontend/src/index.css`, `frontend/src/lib/studyPrefs.ts`.
Wireframe: scheda **Lettura veloce**, le parole "matematicamente tale obiettivo,".

- `readUnitWords` segna `hl: true` sulle parole che stanno dentro un `.rt-hl`. Le parole vanno
  rilette quando le evidenziazioni cambiano mentre la lettura veloce è aperta: oggi si calcolano solo
  quando cambia `source`.
- La parola evidenziata ha **una sola fascia** di sfondo, indipendente dal colore scelto nello Studio:
  token `--rsvp-hl` / `--rsvp-hl-fg` accanto a `--rsvp-focus` in `index.css`.
  - Tema chiaro: `--hl-1` (giallo) con il testo normale.
  - Tema scuro: `#6b5a12` con testo bianco.
  - Irlen: `color-mix(in oklch, var(--fg) 16%, transparent)` con il testo normale.
  - La lettera di fuoco resta colorata dentro la fascia, con contrasto sufficiente in tutti e cinque
    i casi (chiaro, scuro, pesca, menta, pergamena).
- Nel Contesto le parole evidenziate hanno la stessa fascia.
- Preferenze nuove in `study.rsvp`, sezione Aspetto:
  - `highlights` (predefinito `true`): "Mostra le evidenziazioni".
  - `slowHighlights` (predefinito `false`): "Rallenta sulle evidenziate", che allunga di 1,3 volte la
    durata delle parole evidenziate.

Test: vitest di `readUnitWords` con `.rt-hl` e della durata con `slowHighlights`; e2e: una parola
evidenziata nello Studio ha la fascia nella lettura veloce.

### L4 — Tre suoni del clic, Legno predefinito

File: `SpeedReader.tsx` (`createSound`), `frontend/src/lib/studyPrefs.ts`. Si ascoltano tutti
nell'artifact "Suoni della lettura veloce" (link nel thread).

- Preferenza nuova `clickSound: 'legno' | 'tick' | 'classico'` in `study.rsvp`, predefinito
  **`legno`** (vale anche per chi ha già `study.rsvp` salvato senza questa chiave). Nelle impostazioni,
  sezione Suono, "Tipo di clic" con tre segmenti Legno · Tick morbido · Classico, visibile quando il
  suono è attivo.
- Tutto con Web Audio, niente file né librerie. `p` è il tono (`pitch`), `t` l'istante; "grave" è il
  suono di fine frase e delle formule complesse. Inviluppo: da 0,0001 al picco in *attacco*, poi
  esponenziale a 0,0001 in *decadimento*.

  | Suono | Normale | Grave |
  |---|---|---|
  | **Classico** (quello di oggi) | triangolare 880·p Hz, picco 0,13, attacco 4 ms, decadimento 45 ms | triangolare 520·p Hz che scende a 0,82×, picco 0,22, attacco 4 ms, decadimento 110 ms |
  | **Tick morbido** | sinusoide 1000·p → 940·p Hz, picco 0,2, attacco 4 ms, decadimento 35 ms, filtro passa-basso 2600 Hz | sinusoide 620·p → 480·p Hz, picco 0,3, attacco 6 ms, decadimento 120 ms, stesso filtro |
  | **Legno** | rumore bianco con filtro passa-banda 2200·p Hz Q 5, picco 0,3, attacco 1 ms, decadimento 12 ms; più sinusoide 760·p → 700·p Hz, picco 0,14, attacco 2 ms, decadimento 30 ms | rumore con passa-banda 900·p Hz Q 3, picco 0,35, decadimento 30 ms; più sinusoide 380·p → 330·p Hz, picco 0,32, attacco 3 ms, decadimento 110 ms |

- Il buffer di rumore (0,2 s) si crea una volta sola, come quelli del rumore di fondo.

Test: vitest della preferenza (predefinito `legno`, anche se la chiave manca); un test di
`createSound` con un `AudioContext` finto che controlla quali nodi crea per ciascun suono.

### L5 — Quattro pulsanti uguali, Ripassa

File: `SpeedReader.tsx`, `Study.tsx`. Wireframe: scheda **Lettura veloce**, pulsante "Unità con 7
domande" per vedere i due casi.

- I pulsanti sotto la parola diventano quattro, **tutti tondi e della stessa grandezza** (56 px; 48 px
  sul telefono): indietro di N parole, play/pausa (resta con lo stile primario), ricomincia,
  **Ripassa**. Sotto ciascuno un'etichetta corta in `text-meta`: "−5", "Play"/"Pausa", "Ricomincia",
  "Ripassa"/"Genera".
- **Ripassa**:
  - se l'unità ha domande (`units[].questions > 0` dello Studio), icona `MessageCircleQuestion` e
    suggerimento "Ripassa l'unità · N domande". Esce dalla lettura veloce e apre il ripasso
    dell'unità, la stessa pagina di "Mettimi alla prova";
  - se non ne ha, icona `Sparkles` e suggerimento "Genera domande su questa unità". Apre il popup
    "Genera domande" già esistente sull'unità; generate le domande, il pulsante diventa Ripassa.
- I tasti della lettura veloce non cambiano; Ripassa non ha tasto.

Test: e2e, con domande Ripassa porta al ripasso dell'unità; senza domande apre il popup Genera.

### Revisione e merge (Claude)

Come per la b1: Claude rivede il diff, prova le parti toccate, fa le correzioni brevi con commit
"Revisione: …", unisce in `claude/rt-4.2.3-beta`, lancia **tutti** i test in locale (pytest, frontend,
entrambi i gruppi e2e) prima di pubblicare, pubblica la beta con `release.yml` (VERSION `4.2.3b3`; la PR di Codex parte da prima del fix urgente, quindi in revisione si porta dentro `claude/rt-4.2.3-beta`)
e segue il run fino alla fine.

## 4.2.3b4 — Studio verso la lezione, fine delle unità, revisione, tipo consigliato, parole lunghe

Richieste di Attilio della sera del 6 ottobre 2026 (thread "Piano 4.2.3"), discusse una per una.
Lavora **solo Codex (GPT)**, un giro solo. Esce come **4.2.3b4**.

Wireframe di riferimento (interattivo): `docs/wireframes-4.2.3/RT-4.2.3b4.html`, da aprire nel browser.
Schede: Studio (provare la freccia "Esci" e le frecce ← → alla prima e all'ultima unità), Revisione
(provare gli stati del pannello e le icone delle issue d'unità), Domande finite (provare "Genera
consigliato" e "Genera personalizzato"), Lettura veloce iPhone (provare le parole lunghe). Dove piano e
wireframe non coincidono, vale il piano.

### Regole

Come per la b2 (sezione "Regole" della 4.2.3b2), con queste differenze:

- **Branch**: `rt423b4/codex`, già creato da `claude/rt-4.2.3-beta` (contiene il fix urgente
  4.2.3b3.1 delle decisioni della revisione). Un commit per task (messaggio `<id>: …`), alla fine
  **una sola PR verso `claude/rt-4.2.3-beta`**. Mai merge su `main` o sul branch beta, niente tag,
  `VERSION` non si tocca.
- Prima di aprire la PR si lanciano **tutti** i test: pytest completo, `npm run lint`,
  `npm run typecheck`, `npx vitest run`, `npm run build`, e gli e2e di **entrambi** i gruppi
  (`RT_E2E_GROUP=recall-images` e `RT_E2E_GROUP=other`). Gli e2e usano la build: lanciarli dopo
  `npm run build`, altrimenti provano l'interfaccia vecchia.
- Il fix urgente di `rt/pipeline/review.py` e `rt/pipeline/ledger.py` (4.2.3b3.1, test
  `tests/test_review_restart_decisions.py`) non si tocca: R1 lavora solo sul pannello e sull'API.

### Decisioni (Attilio, 6 ottobre 2026)

- Nello Studio la freccia **"Esci"** porta alla lezione, sull'unità aperta; l'icona "Apri la lezione"
  accanto al titolo (G2 della b3) si toglie, perché con i titoli lunghi finisce nascosta.
- Alla fine delle unità **non c'è più la pagina "Hai finito lo Studio"**: si resta sull'ultima unità e
  un effetto sul bordo dello schermo fa capire che le unità sono finite. Lo stesso prima della prima.
- La revisione si fa **una volta sola**: a revisione completa e decisa il pulsante è "Ricostruisci il
  documento" (solo il build). "Riprendi la pipeline" sparisce dal pannello.
- Le issue che riguardano **tutta l'unità** (qualità ASR, deriva della rielaborazione) non
  sottolineano più l'unità intera: diventano un'icona accanto al timestamp, solo in revisione.
- **Tipo consigliato**: Jev legge il testo di ogni unità e consiglia quiz, mirata, caso clinico o
  esercizio. Nei popup di generazione è un'alternativa alla scelta manuale; quando le domande finiscono
  ci sono "Genera consigliato" e "Genera personalizzato", con il numero di domande.
- **Lettura veloce**: una parola troppo lunga per lo schermo si rimpicciolisce quanto basta; se
  dovesse scendere sotto il 70 % si divide in due (o più) pezzi con il trattino.

### Task

| Id | Cosa |
|---|---|
| S1 | Studio: "Esci" porta alla lezione, via l'icona "Apri la lezione" |
| S2 | Studio: niente pagina finale, effetto sul bordo alla prima e all'ultima unità |
| R1 | Revisione: pannello con unità verificate e "Ricostruisci il documento" |
| R2 | Revisione: issue di tutta l'unità come icona accanto al timestamp |
| Q1 | Tipo di domanda consigliato (Jev, cache, API) |
| Q2 | Tipo consigliato nell'interfaccia: popup, pannello, fine delle domande |
| L6 | Lettura veloce: parole lunghe rimpicciolite o divise |

Ordine: S1 → S2 → R1 → R2 → Q1 → Q2 → L6. Q2 usa i campi di Q1.

### S1 — "Esci" porta alla lezione

File: `frontend/src/components/study/Study.tsx`, `frontend/src/routes/study.tsx`. Wireframe: scheda
**Studio**.

- Oggi `back` è `{ to: '/', label: 'Esci' }` (pagina Lezioni). Dentro `StudyFlow`, quando ci sono
  lezione e unità, la freccia porta a `/lezioni/{id}#unit-{unitId}` dell'unità aperta (lo stesso
  indirizzo `lessonUrl` di G2), così l'editor si apre su quell'unità e la segna come fa già G2. Con lo
  Studio su più lezioni vale la lezione dell'unità aperta. Il suggerimento resta "Esci". Durante il
  caricamento e in caso di errore (prima che ci sia un'unità) resta la lezione senza `#unit-`.
- Con `?unita=` (domande su una parte) non cambia nulla: porta già a `/lezioni/{id}`; aggiungere
  `#unit-` della prima unità della parte.
- Togliere l'`IconLink` "Apri la lezione" accanto al titolo (`titleButton`). Il link "Apri la lezione"
  nel popup dei dettagli resta.

Test: e2e — "Esci" dallo Studio aperto sull'unità 2 porta alla lezione con l'unità 2 in vista e
segnata, anche a 390 px; l'icona accanto al titolo non c'è più. Aggiornare l'e2e di G2.

### S2 — Fine delle unità con un effetto sul bordo

File: `Study.tsx`, `frontend/src/index.css`. Wireframe: scheda **Studio** (pulsanti "← prima unità" e
"ultima unità →").

- Freccia →, tasto → e swipe verso sinistra **sull'ultima unità dell'ultima lezione**: non si chiama
  più `advance()` che porta a `finished`; si resta sull'unità e parte l'effetto sul bordo **destro**.
  Freccia ←, tasto ← e swipe verso destra sulla **prima unità della prima lezione**: effetto sul bordo
  **sinistro** (oggi non succede nulla). Con lo Studio su più lezioni, il passaggio da una lezione alla
  successiva resta com'è: l'effetto vale solo ai due estremi.
- Effetto: una fascia di 28 px sul bordo dell'area di lettura (sotto l'intestazione, a tutta altezza,
  `pointer-events: none`), sfumatura da `color-mix(in oklch, var(--success) 45%, transparent)` a
  trasparente verso l'interno, che compare e svanisce in 450 ms; insieme il testo dell'unità si sposta
  di 12 px verso il bordo e torna (300 ms, ease-out), come il rimbalzo di fine lista. Premendo di
  nuovo l'animazione riparte. Con `prefers-reduced-motion: reduce` niente spostamento del testo, solo
  la fascia (opacità massima 0,6, 300 ms).
- Per chi usa lo screen reader: una regione `aria-live="polite"` dice "Ultima unità" o "Prima unità".
- La pagina "Hai finito lo Studio della lezione / di queste lezioni" non si raggiunge più dalla
  lettura. Resta solo per `onlyUnits` ("Hai finito le domande su questa parte"), che nasce dalle
  domande.
- Nella schermata di fine domande in modo unità (`LightweightSession`, `unit.onDone`), sull'ultima unità
  dell'ultima lezione il pulsante "Unità successiva" non compare (resta "Torna allo studio").

Test: vitest della funzione che decide fra cambio unità ed effetto (prima/ultima/in mezzo, più
lezioni); e2e — ultima unità + → resta sull'ultima (titolo invariato, nessun `study-done`) e la fascia
destra compare; prima unità + ← mostra la fascia sinistra; swipe simulato a 390 px (vedi la nota
sullo swipe con CDP nella memoria del progetto: `Input.dispatchTouchEvent` in un contesto `hasTouch`).

### R1 — Pannello della revisione

File: `frontend/src/components/lesson/panels/ReviewPanel.tsx`, `rt/api/schemas.py`,
`rt/api/routers/lessons.py` (o dove si costruisce `LessonDetail`), eventualmente un componente
condiviso per il dialogo di conferma del build oggi in `DetailsPanel.tsx`. Wireframe: scheda
**Revisione**.

Oggi `done = l.phases.review === 'VALID' || items.length > 0`: una revisione a metà sembra finita
("Tutte decise") e "Riprendi la pipeline" lancia `run_pipeline` con la review, che riprende le unità
mancanti o, se il testo è cambiato, rifà tutta la review.

- **API**: `LessonDetail` aggiunge `review_progress: { reviewed: int, total: int } | null` (unità nel
  checkpoint della fase review, cioè `completed_items` del manifest, e unità della bozza; `null` se
  la review non è mai partita). Rigenerare openapi e `schema.d.ts`.
- **Stati del pannello** (titolo con `role="status"` come oggi):
  - *In corso*: com'è oggi (avanzamento, issue trovate, Interrompi).
  - *Mai verificata*: com'è oggi, con "Verifica tutta la lezione".
  - *A metà* (`phases.review === 'PARTIAL'`): titolo "Verificate N unità su M"; elenco delle issue come
    oggi; pulsante principale **"Completa la verifica"** = `run_phase` review senza `force` (riprende
    dalle unità mancanti).
  - *Testo cambiato* (`phases.review === 'STALE'`): titolo "Il testo è cambiato dopo la verifica";
    pulsante principale **"Verifica di nuovo tutta la lezione"** (`force: true`), secondario
    "Ricostruisci il documento".
  - *Completa e decisa* (`VALID`, nessuna da decidere): "Tutte decise" con il riepilogo di oggi e il
    pulsante principale **"Ricostruisci il documento"** = `run_phase` build. Se il build è già `VALID`
    il pulsante è disattivato con il testo "Documento aggiornato".
  - *Completa con issue da decidere*: com'è oggi ("N da decidere su M").
- "Ricostruisci il documento" usa lo stesso dialogo di conferma del build di `DetailsPanel.tsx` quando
  `phase_report` del build ha avvisi (estrarlo in un componente comune), altrimenti parte subito.
- "Riprendi la pipeline" sparisce dal pannello. Il badge "Pipeline in attesa" resta: una pipeline in
  attesa riparte già da sola quando si decide l'ultima issue (`resume_waiting_jobs`).
- Il pulsante in fondo "Verifica (di nuovo) tutta la lezione" resta, tranne quando è già il pulsante
  principale.

Test: vitest del pannello per ogni stato (testo, pulsante principale, payload del job); pytest di
`review_progress` (mai partita, a metà, completa); e2e — dopo aver deciso tutte le issue il pulsante è
"Ricostruisci il documento" e avvia un job `run_phase` build, non `run_pipeline`.

### R2 — Issue di tutta l'unità come icona

File: `frontend/src/components/lesson/lessonReview.ts`, `frontend/src/components/lesson/reviewIssues.ts`,
`frontend/src/index.css`, dove l'editor ascolta `ISSUE_EVENT` e scorre all'issue selezionata.
Wireframe: scheda **Revisione**.

- Per le issue con `paragraphIssue(issue)` (oggi `ERR_ASR_ST`, `ERR_ASR_LLM`, `ERR_REWRITE_DRIFT`) niente
  `Decoration.mark` sul testo dell'unità: al suo posto un `Decoration.widget` alla fine della riga del
  timestamp dell'unità (la riga dopo il titolo), un'icona per issue non decisa, nell'ordine delle
  issue. Le sottolineature a puntini restano per le issue con una frase precisa.
- Icona `AudioLines` per le issue ASR, `GitCompareArrows` per la deriva della rielaborazione, 16 px,
  dentro un pulsantino tondo di 24 px; colore `text-warning`; se l'issue è quella selezionata, sfondo
  e colore della selezione (`rt-issue-selected`). `aria-label` e suggerimento = etichetta del tipo
  (`issueLabels`, es. "Qualità ASR · statistica").
- Clic sull'icona = stesso evento di oggi (`ISSUE_EVENT` con l'id): la sidebar seleziona l'issue.
  Selezionando un'issue d'unità dalla sidebar l'editor scorre fino al suo timestamp.
- Le icone esistono solo quando l'editor ha le issue della revisione (vista Verifica), come oggi le
  sottolineature; fuori dalla revisione non si vedono. Le issue decise non hanno icona.

Test: vitest di `lessonReview` (issue d'unità → widget e nessun mark; issue di frase → mark); e2e —
in Verifica un'issue ASR d'unità mostra l'icona accanto al timestamp, nessuna sottolineatura sul
testo, il clic la seleziona nella sidebar.

### Q1 — Tipo di domanda consigliato

File nuovi: `rt/services/question_types.py`, test `tests/test_question_types.py`. File toccati:
`rt/pipeline/rewrite.py` (dopo `unit_relevance.refresh`), `rt/core/lesson_paths.py`,
`rt/services/recall_service.py` / `rt/services/job_handlers.py` (generazione "consigliato"),
`rt/api/schemas.py` e i router dello Studio e del recall, `rt/core/config.py`.

- Modello: come `rt/services/section_labels.py` (stessa chiamata `jev_client.call_jev` con il modello,
  la credenziale e l'endpoint della rilevanza, stesse regole di "attivo": `relevance_model`
  configurato e `relevance_mode` diverso da `disabled`), ma **per unità della bozza** (2.1, 2.2: le
  unità dello Studio), con una sola domanda di tipo choice, `tipo_consigliato`:
  - istruzioni: "Valuta un'unità di una lezione universitaria riscritta e scegli il tipo di domanda
    più adatto per verificare se lo studente l'ha capita."
  - `quiz`: "Il contenuto è fatto soprattutto di fatti, definizioni, valori o classificazioni da
    riconoscere: si verifica bene con domande a risposta multipla."
  - `mirata`: "Il contenuto spiega un meccanismo, un perché o un collegamento fra concetti: si
    verifica bene con una domanda aperta precisa, a cui rispondere in poche righe."
  - `caso`: "Il contenuto riguarda pazienti, quadri clinici, diagnosi, parametri o terapie: si
    verifica bene presentando un caso clinico da interpretare."
  - `esercizio`: "Il contenuto contiene calcoli, formule da applicare o procedimenti risolutivi: si
    verifica bene con un esercizio da svolgere."
- **Coerenza con casi ed esercizi**: oggi casi ed esercizi nascono solo dalle sezioni che
  `section_labels` riconosce (`POSITIVE`). Se Jev consiglia `caso` o `esercizio` per un'unità la cui
  sezione non è positiva per quel tipo, il consiglio diventa il più probabile fra `quiz` e `mirata`.
  Verificare in `rt/pipeline/recall_special.py` che con `unit_ids` la generazione di quell'unità
  produca davvero domande del tipo consigliato; il consiglio deve essere sempre un tipo generabile.
- Cache `unit_question_types.json` nella cartella della lezione (aggiungerla a
  `rt/core/lesson_paths.py` accanto a `unit_relevance.json`): per unità `type`, `confidence`,
  `probabilities`, `text_hash`, `config_hash`, `at`. Si ricalcola solo se cambia il testo dell'unità o
  la configurazione, come `section_labels.refresh`. Mock deterministico (per esempio dal contenuto:
  formule → esercizio, parole cliniche → caso, altrimenti alternanza quiz/mirata) per test ed e2e.
- **Quando**: nella pipeline subito dopo `unit_relevance.refresh` in `run_rewrite`; un errore di Jev
  non fa fallire la rielaborazione (fail-open: unità senza consiglio, notice di avviso). Per le
  lezioni vecchie senza cache, il calcolo avviene nel job di generazione quando si chiede
  "consigliato" (vedi sotto).
- **API**:
  - le unità dello Studio (`StudyUnit` e la risposta di `GET /lessons/{id}/study`) aggiungono
    `suggested_qtype: Optional[Literal["quiz","mirata","caso","esercizio"]]`;
  - la risposta aggiunge `suggestions: bool` (Jev attivo: si possono chiedere consigli);
  - `RecallGenerate.qtype` accetta anche `"consigliato"`: il job calcola i consigli mancanti delle unità
    coinvolte (quelle di `unit_ids`, o quelle selezionate per il recall se mancano), raggruppa le unità
    per tipo consigliato e genera ogni gruppo con il suo tipo. `count` si divide fra i gruppi in
    proporzione al numero di unità, almeno 1 per gruppo, senza superare `count`. Unità senza consiglio
    (Jev in errore) → `quiz`. Il messaggio finale del job dice i tipi generati ("3 mirate, 2 quiz").
  - Rigenerare openapi e `schema.d.ts`.

Test: pytest — choice con le quattro opzioni e le istruzioni; cache non ricalcolata a testo invariato,
ricalcolata se cambia; coerenza con `section_labels` (caso senza sezione positiva → quiz o mirata);
fail-open; job "consigliato" con unità di due tipi e divisione di `count`; `suggested_qtype` nella
risposta dello Studio.

### Q2 — Tipo consigliato nell'interfaccia

File: `Study.tsx` (`GenerateUnitQuestions`), `frontend/src/components/lesson/panels/QuestionsPanel.tsx`
("Genera altre domande"), `frontend/src/components/recall/LightweightSession.tsx` (blocco
`recall-empty`). Wireframe: scheda **Domande finite**.

- Tutto quello che segue compare solo se `suggestions` è vero; senza Jev resta la scelta manuale di
  oggi.
- **Popup "Genera domande · unità"**: prima dei tipi un chip **"Consigliato · Mirata"** (icona
  `Sparkles` 14 px, nome del tipo consigliato; solo "Consigliato" se l'unità non ha ancora il
  consiglio), selezionato all'apertura. Scegliendo un altro chip si torna alla scelta manuale.
- **Pannello Domande, "Genera altre domande"**: nella select Tipo una prima voce "Consigliato per
  ogni unità", selezionata all'apertura.
- **Domande finite** (la scheda `recall-empty` quando le domande sono finite, in modo unità e nel
  ripasso di una lezione sola; mai nel ripasso di più lezioni, dove resta il testo di oggi): sopra i
  pulsanti di oggi una riga
  `Quante [3]  ·  [✦ Genera consigliato · Mirata]  ·  [Tipo ▾] [Genera personalizzato]`:
  - "Quante": `Input` numerico 1–20, predefinito 3 in modo unità e 10 nel ripasso della lezione;
  - "Genera consigliato · Mirata": pulsante principale (in modo lezione: "Genera consigliato");
  - select del tipo (quiz, mirata, caso clinico, esercizio; vasta solo nel ripasso della lezione) e
    pulsante "Genera personalizzato";
  - durante il job la riga diventa "Genero le domande…" con l'avanzamento; finito il job la sessione
    riprende da sola con le domande nuove (come dopo "Riproponi"); in caso di errore un `Alert`.
  - Su iPhone la riga va a capo: Quante e Genera consigliato sulla prima, tipo e personalizzato sulla
    seconda, pulsanti a tutta larghezza.
- "Riproponi le sbagliate", "Riproponi le poste", "Torna allo studio" e "Unità successiva" restano
  sotto, come oggi.

Test: vitest dei tre punti (chip/voce consigliata presente e selezionata con `suggestions`, assente
senza; payload `qtype: "consigliato"` con `count`); e2e — finite le domande di un'unità, "Genera
consigliato" con Quante 2 avvia il job e la sessione riprende con le domande nuove.

### L6 — Lettura veloce: parole lunghe

File: `frontend/src/components/study/SpeedReader.tsx`, `frontend/src/components/study/rsvp.ts`,
`frontend/src/index.css`. Wireframe: scheda **Lettura veloce iPhone**.

Oggi la parola è divisa in `.pre | .orp | .post`; `.pre` e `.post` sono larghi 6,2em (4,6em sotto
768 px) con `overflow: visible`, così la lettera di fuoco resta al centro, ma un `.post` più lungo
esce dallo schermo (sull'iPhone "un'impostazione": la "u" è la lettera di fuoco e "n'impostazione"
supera il bordo).

- **Spazio**: per lato `(larghezza dell'area di lettura / 2) − (larghezza della lettera di fuoco / 2)
  − 16 px`.
- **Misura**: con `CanvasRenderingContext2D.measureText`, usando il font calcolato di `.rt-rsvp-word`
  (famiglia, peso, dimensione reale, anche OpenDyslexic), la larghezza in px di pre, lettera di fuoco e
  post di ogni parola. Si calcola per tutta l'unità all'apertura e di nuovo quando cambiano dimensione
  del testo, font o larghezza dell'area (`ResizeObserver`, rotazione del telefono); mai a ogni parola
  mostrata.
- **Scala**: `scale = min(1, spazio / max(pre, post))`. Se `scale ≥ 0,7` la parola si mostra con
  `font-size` moltiplicato per `scale` (variabile CSS sulla sola parola): pre e post sono in `em`, quindi
  la lettera di fuoco resta al centro.
- **Divisione**: se `scale < 0,7` la parola si divide in pezzi, ognuno mostrato come una parola a sé con
  la sua lettera di fuoco e la sua scala (ogni pezzo almeno 0,7). Tutti i pezzi tranne l'ultimo
  finiscono con "-", tranne quando il taglio cade dopo un apostrofo o un trattino già presenti. Punti
  di taglio ammessi: dopo un apostrofo o un trattino; prima di una consonante fra due vocali
  ("imposta|zione"); fra due consonanti uguali ("at|tività"); mai pezzi sotto 3 caratteri. Fra i punti
  per cui entrambi i pezzi stanno almeno a 0,7 si sceglie il più vicino alla metà della parola; se il
  secondo pezzo non sta ancora, si ripete su di lui (parole lunghissime: tre pezzi). Esempio
  sull'iPhone a dimensione 60: "un'impostazione" → "un'imposta-" (scala 0,87) e "zione". Il wireframe
  usa esattamente questa regola con la misura vera del canvas.
- **Tempi e conteggi**: ogni pezzo ha il tempo di `wordDelay` sul proprio testo; la pausa di fine frase
  e la virgola solo sull'ultimo pezzo; il clic grave solo sull'ultimo. Il Contesto, l'avanzamento
  ("13 / 338 parole") e i salti (−5, frase precedente) restano sulle parole originali: un pezzo punta
  alla sua parola. Le evidenziazioni (`hl`) valgono per tutti i pezzi.
- Le formule non cambiano: hanno già la loro scala (`RsvpFormula`).

Test: vitest della funzione di adattamento con una misura finta (larghezza fissa per carattere):
parola corta → scala 1; parola un po' lunga → scala fra 0,7 e 1; "un'impostazione" con lo spazio
dell'iPhone → "un'imposta-" e "zione"; un taglio dopo l'apostrofo non aggiunge il trattino; tre
pezzi per una parola lunghissima; pausa di fine frase solo sull'ultimo pezzo. E2e a 390 px: la parola
"un'impostazione" (aggiungerla alla fixture se serve) non esce dalla finestra (`boundingBox` dentro
`viewport`).

### Revisione e merge (Claude)

Come per la b3: Claude rivede il diff, prova le parti toccate, fa le correzioni brevi con commit
"Revisione: …", unisce in `claude/rt-4.2.3-beta`, imposta VERSION `4.2.3b4`, lancia **tutti** i test in
locale (pytest, frontend, build, entrambi i gruppi e2e) prima di pubblicare, pubblica la beta con
`release.yml` e segue il run fino alla fine.
