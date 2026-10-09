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
  - *Testo cambiato* (`phases.review === 'STALE'`): titolo "Il testo è cambiato dopo la verifica",
    sotto in `text-meta` "Le correzioni fatte a mano non rifanno la verifica."; pulsante principale
    **"Aggiorna il documento"** = `run_pipeline` con `with_review: true`, senza `force`. Motivo: dalla
    4.2.3b3.2 (fix urgente in `review.py`) lo stato resta STALE anche dopo le sole correzioni a mano
    nell'editor, ma `run_review` le riconosce, tiene issue e decisioni e salta al build; rifà la
    review solo se la rielaborazione, i segmenti o le unità sono davvero cambiati. Non usare
    `force` qui e non scrivere "verifica di nuovo". Il pulsante in fondo "Verifica di nuovo tutta la
    lezione" (`force: true`) resta disponibile come oggi.
  - *Completa e decisa* (`VALID`, nessuna da decidere): "Tutte decise" con il riepilogo di oggi e il
    pulsante principale **"Ricostruisci il documento"** = `run_phase` build. Se il build è già `VALID`
    il pulsante è disattivato con il testo "Documento aggiornato".
  - *Completa con issue da decidere*: com'è oggi ("N da decidere su M").
- "Ricostruisci il documento" usa lo stesso dialogo di conferma del build di `DetailsPanel.tsx` quando
  `phase_report` del build ha avvisi (estrarlo in un componente comune), altrimenti parte subito.
- "Riprendi la pipeline" sparisce dal pannello. Il badge "Pipeline in attesa" resta: una pipeline in
  attesa riparte già da sola quando si decide l'ultima issue (`resume_waiting_jobs`).
- Il pulsante in fondo "Verifica (di nuovo) tutta la lezione" resta in tutti gli stati tranne *Mai
  verificata*, dove è già il pulsante principale.

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

## 4.2.3 stabile — rifiniture dopo la b4

Riscontri di Attilio della mattina del 7 ottobre 2026 (thread "Bug breaking"), provando la v4.2.3b4,
discussi uno per uno e confermati sui wireframe. Lavora **solo Codex (GPT)**, un giro solo. Dopo la
revisione esce direttamente come **4.2.3 stabile** (eventuali correzioni dopo con la quarta cifra,
4.2.3.1 e così via).

Wireframe di riferimento (interattivi), da aprire nel browser:

- `docs/wireframes-4.2.3/RT-4.2.3-correzione.html` — card della revisione con correzione proposta (C1).
- `docs/wireframes-4.2.3/RT-4.2.3-lezioni.html` — righe di Lezioni: anello, scudo, icone cliccabili,
  domande (N1, N2). Selettore "Proposta / Oggi" e "Computer / iPhone".
- `docs/wireframes-4.2.3/RT-4.2.3-revisore.html` — unità al revisore in fondo al pannello Verifica (N3).
  Vale il pannello di sinistra ("Proposta", la striscia), non l'alternativa.

Dove piano e wireframe non coincidono, vale il piano.

### Regole

Come per la b4 (sezione "Regole" della 4.2.3b4), con queste differenze:

- **Branch**: `rt423s/codex`, già creato da `claude/rt-4.2.3-beta` (v4.2.3b4 più i fix urgenti
  4.2.3b3.1 e 4.2.3b3.2). Un commit per task (messaggio `<id>: …`), alla fine **una sola PR verso
  `claude/rt-4.2.3-beta`**. Mai merge su `main` o sul branch beta, niente tag, `VERSION` non si tocca.
- Il fix urgente in `rt/pipeline/review.py` e `rt/pipeline/ledger.py` (test
  `tests/test_review_restart_decisions.py`) non si tocca.
- Tutti i test prima della PR, come nella b4 (pytest completo, lint, typecheck, vitest, build, e2e di
  entrambi i gruppi dopo la build).

### Decisioni (Attilio, 7 ottobre 2026)

- I suggerimenti (delay group della b3) vanno bene: devono essere **gli stessi su tutte le icone**,
  niente più suggerimenti nativi del browser.
- Studio: il **triplo clic** non deve evidenziare un paragrafo intero per sbaglio; il **clic destro**
  su un'evidenziazione la toglie; una **scorciatoia** passa da evidenziatore a gomma e viceversa.
- Tornando dallo Studio alla lezione, l'unità **non** va segnata (si arriva solo lì).
- "Consigliato" **non è un'opzione a parte**: le opzioni sono solo i tipi di domanda, e il tipo
  consigliato ha accanto una stellina. Vale per il popup dell'unità, il pannello Domande e la
  schermata "domande finite".
- La barra di formattazione dell'editor si può **nascondere** dalle Impostazioni.
- Da Impostazioni e da Job si torna **alla pagina esatta** da cui si è arrivati (freccia indietro, o
  di nuovo clic sull'icona).
- Colori dello studio più distinguibili (appresa, in apprendimento, ignorata), uguali nell'anello e
  nelle barrette dello Studio.
- Righe di Lezioni: anello grande come lo scudo e senza numeri (i numeri nel suggerimento), via
  "N apprese" dal sottotitolo, scudo della verifica giallo o verde, icone cliccabili, "N domande" nel
  sottotitolo, via il puntino giallo "Da verificare".
- Card della correzione proposta: Accetta e Mantieni solo icone, modifica col doppio clic sul box,
  ripristino del testo proposto. Confermate anche le regole di contorno (sotto, C1).
- In fondo al pannello Verifica si vede quante unità vanno al revisore, con una striscia di tacche; lo
  stesso elemento va in fondo al pannello Domande al posto della riga di testo di oggi.

### Task

| Id | Cosa |
|---|---|
| T1 | Suggerimenti uguali su tutte le icone |
| E1 | Evidenziatore dello Studio: niente triplo clic, clic destro toglie, scorciatoia E |
| E2 | Ritorno dallo Studio alla lezione senza segnare l'unità |
| E3 | Barra di formattazione dell'editor nascondibile |
| P1 | Tipo consigliato come stellina accanto al tipo |
| A1 | Indietro da Impostazioni e Job verso la pagina di partenza |
| K1 | Colori dello studio |
| N1 | Righe di Lezioni: anello, scudo, icone cliccabili, sottotitolo |
| C1 | Card della correzione proposta |
| N3 | Unità al revisore e al recaller in fondo ai pannelli |

Ordine: T1 → E1 → E2 → E3 → P1 → A1 → K1 → N1 → C1 → N3. N1 usa i colori di K1; C1 e N3 usano il
`Tooltip` come lo lascia T1.

### T1 — Suggerimenti uguali su tutte le icone

File: tutti i componenti con pulsanti a icona o icone con `title=` (per esempio `HighlightTools` in
`frontend/src/components/study/Study.tsx`: evidenziatore e gomma hanno `title`, e il browser mostra il
suo suggerimento grigio invece di quello di RT), `frontend/src/components/ui/tooltip.tsx`,
`frontend/src/components/ui/icon-button.tsx`.

- Ogni elemento cliccabile che mostra solo un'icona usa il `Tooltip` di RT (o `IconButton`, che lo
  usa già), con lo stesso ritardo condiviso della b3. Nessun `title=` su pulsanti, link e icone: va
  tolto, e il testo passa al `Tooltip` (il nome accessibile resta in `aria-label`).
- Restano i `title` che non sono suggerimenti di icone (titoli di `Modal`, `PageHeader`, ecc.) e quelli
  su testo troncato, se servono per leggere il testo intero.
- Il suggerimento dell'evidenziatore: "Evidenziatore giallo · clic: colore successivo · E"; della gomma:
  "Gomma · clic su un'evidenziazione per toglierla · E" (la scorciatoia arriva con E1).
- Nessuna modifica al comportamento del `Tooltip` stesso.

Test: un vitest che fallisce se un componente in `frontend/src/components` mette `title=` su un
`<button>` o su un `<a>`/`Link` (controllo sul sorgente o sul DOM renderizzato delle schermate
principali, a scelta); vitest di `HighlightTools`: al passaggio del mouse compare il suggerimento di RT
(`role="tooltip"`).

### E1 — Evidenziatore dello Studio

File: `frontend/src/components/study/highlights.ts`, `Study.tsx` (`HighlightTools` e il gestore dei
tasti della fase di lettura).

- **Triplo clic**: in modalità evidenziatore un triplo clic non deve creare un'evidenziazione di tutto
  il paragrafo. Sul contenitore del testo, un `mousedown` con `event.detail >= 3` fa
  `preventDefault()` (niente selezione del paragrafo), e in ogni caso una selezione nata da un triplo
  clic non si evidenzia. Il doppio clic su una parola continua a evidenziarla.
- **Clic destro**: in entrambe le modalità, il clic destro (`contextmenu`) su un'evidenziazione la
  toglie come fa la gomma (stessa chiamata `highlightsApi.remove`) e non apre il menu del browser. Il
  clic destro fuori dalle evidenziazioni resta quello del browser. Su iPhone non cambia nulla.
- **Scorciatoia E**: nella fase di lettura (stesse condizioni del tasto S: non nei campi di testo, non
  con Cmd/Ctrl/Alt, non in lettura veloce) il tasto E passa da evidenziatore a gomma e viceversa. Il
  colore resta quello scelto.

Test: vitest — `contextmenu` su un'evidenziazione la toglie e chiama l'API; E alterna le due modalità
(e non fa nulla dentro un input); `mousedown` con `detail: 3` è annullato. E2e — clic destro su
un'evidenziazione salvata la toglie e al ricaricamento non torna.

### E2 — Ritorno dallo Studio senza segnare l'unità

File: `Study.tsx` (link "Esci" di S1), `frontend/src/components/lesson/LessonEditor.tsx` (effetto su
`#unit-`, `setLinkedUnit`), `frontend/src/components/lesson/DocumentView.tsx`.

- Oggi `/lezioni/{id}#unit-{unità}` porta l'unità in vista **e** la segna (`setLinkedUnit`). Dallo
  Studio deve solo portarla in vista. La freccia "Esci" passa uno stato del router (per esempio
  `state: { fromStudy: true }`) e l'editor, con quello stato, fa solo lo scroll senza `setLinkedUnit`.
- Gli altri link "Vai all'unità" (Classificatore, Rilevanza, ecc.) continuano a segnare l'unità.

Test: aggiornare l'e2e di S1 — dopo "Esci" l'unità è in vista ma non segnata; un e2e esistente di
"Vai all'unità" continua a vederla segnata.

### E3 — Barra di formattazione nascondibile

File: `frontend/src/components/lesson/EditorToolbar.tsx`, `LessonEditor.tsx`, la sezione "Editor e
scorciatoie" delle Impostazioni (`frontend/src/lib/settings.ts` e il componente della sezione), le
preferenze lato server dell'editor.

- Nuova preferenza "Barra di formattazione" (Sì/No, predefinito Sì) nella sezione **Editor e
  scorciatoie**, salvata sul server come le altre preferenze dell'editor.
- Con "No" la barra (annulla/ripeti, elenchi, grassetto, corsivo, barrato, codice, evidenzia, link,
  cerca) non si mostra; le scorciatoie da tastiera continuano a funzionare.

Test: vitest della sezione (cambia e salva la preferenza); e2e — con "No" la barra non c'è nella
lezione e Cmd/Ctrl+B mette comunque il grassetto; alla fine il test rimette la preferenza com'era.

### P1 — Tipo consigliato come stellina

File: `Study.tsx` (`GenerateUnitQuestions`, `UNIT_TYPES`), `frontend/src/components/lesson/panels/QuestionsPanel.tsx`
(`TYPES`, select "Tipo"), `frontend/src/components/recall/EmptyGeneration.tsx`,
`frontend/src/lib/questionTypes.ts`.

- **Opzioni = solo i tipi.** Sparisce "Consigliato" (popup) e "Consigliato per ogni unità" (pannello).
  Il tipo consigliato ha accanto una stellina (`Sparkles` di lucide, colore d'accento, 14 px) e il
  suggerimento "Consigliato da Jev"; quando il popup o il pannello si aprono è già selezionato.
- **Nomi uguali dappertutto**: le etichette vengono da `QUESTION_TYPE_LABELS` (oggi il pannello dice
  "Caso" e il popup "Caso clinico"). Nel popup dell'unità e nella fine delle domande di un'unità
  niente "Vasta" (come oggi); nel pannello Domande della lezione "Vasta" c'è.
- **Popup dell'unità** (Studio, "Genera domande · unità"): chip dei tipi, stellina su `suggested_qtype`
  dell'unità.
- **Pannello Domande** ("Genera altre domande"): il select diventa una fila di chip come nel popup.
  La stellina va sul tipo consigliato per **più unità** fra quelle selezionate per il recaller, e il suo
  suggerimento dice "Consigliato per N unità su M". Generando, il tipo scelto vale per tutte le unità.
  Il qtype `consigliato` resta nell'API (per compatibilità), ma l'interfaccia non lo usa più.
- **Fine delle domande** (`EmptyGeneration`): una sola riga "Quante · chip dei tipi con la stellina ·
  Genera", al posto di "Genera consigliato" e "Genera personalizzato". Il tipo consigliato è già
  selezionato; la sessione riprende da sola come oggi.
- Senza Jev configurato (`suggestions` falso) non c'è stellina e il primo tipo selezionato è Quiz.

Test: aggiornare i vitest di Q2 (popup, pannello, fine domande): nessuna opzione "Consigliato", la
stellina sul tipo giusto, il tipo consigliato preselezionato, nel pannello il conteggio "N unità su M".
Aggiornare gli e2e di Q2.

### A1 — Indietro da Impostazioni e Job

File: `frontend/src/components/Layout.tsx` (sezioni `JOBS` e `SETTINGS`), le pagine
`frontend/src/routes/settings.tsx` e `frontend/src/routes/jobs.tsx`.

- Quando si entra in Impostazioni (`/impostazioni…`, `/bot…`) o in Job (`/job…`, `/importa…`) da
  un'altra pagina, RT si ricorda l'indirizzo completo di partenza (percorso, query e `#`, per esempio
  `/lezioni/15?panel=verifica#unit-2.4` o `/studio/lezione/15`).
- Nell'intestazione di Impostazioni e di Job compare la freccia indietro (come nello Studio, con il
  suggerimento "Indietro") che riporta lì. Anche un secondo clic sull'icona Impostazioni (o Job) nella
  barra laterale, e nella barra in basso dell'iPhone, riporta lì.
- Spostarsi fra le sezioni delle Impostazioni non cambia l'indirizzo di partenza. Se si è arrivati
  direttamente (link aperto da fuori, ricarica), la freccia porta a Lezioni.
- Passando da Impostazioni a Job (o viceversa) vale sempre la prima pagina fuori da entrambe.

Test: vitest della logica dell'indirizzo di partenza; e2e — dalla lezione con il pannello Verifica
aperto si va in Impostazioni, si cambia sezione, freccia indietro → di nuovo la lezione con il
pannello aperto; lo stesso con il secondo clic sull'icona; da Job allo stesso modo.

### K1 — Colori dello studio

File: `frontend/src/index.css`, `Study.tsx` (barrette, riga ~601, e pulsante dello stato),
`frontend/src/components/lessons/LessonsView.tsx` (`StudyRing`),
`frontend/src/components/lessons/SelectionDetails.tsx`. Wireframe: **lezioni**.

- Nuovi token in `index.css`, chiaro e scuro: `--study-learned`, `--study-learning`,
  `--study-ignored`, `--study-track` (valori del wireframe: chiaro `#13896b`, `#e8a317`, `#d4382a`,
  `#e6e6e6`; scuro `#5cc79f`, `#f5c242`, `#ff6b5b`, `#333333`), con le classi Tailwind
  corrispondenti. Il tema Irlen, se ridefinisce i colori, li ridefinisce anche qui.
- Usano questi token: le barrette dello Studio (oggi `bg-success`, `bg-warning`, `bg-danger`),
  l'anello di Lezioni, le icone del pulsante dello stato nello Studio, i pallini dei Dettagli della
  selezione. `success`, `warning` e `danger` restano per tutto il resto.
- Anello: fra un arco e l'altro un piccolo stacco (circa 3 unità su 100 di `pathLength`), come nel
  wireframe.

Test: vitest di `StudyRing` (archi presenti con i nuovi colori); aggiornare i test che controllano le
classi delle barrette.

### N1 — Righe di Lezioni

File: `LessonsView.tsx` (`LessonRow`, `StudyRing`, `StatusDot`), `frontend/src/lib/lessonsPage.ts`
(`lessonSubtitle`, `lessonStatus`). Wireframe: **lezioni** (Proposta, Computer e iPhone).

- **Anello**: 19 px come lo scudo, tratto di circa 2,6 px; **niente numero** accanto (via "1/11").
  Suggerimento RT: "N apprese · N da apprendere · N ignorate" (singolare "appresa", "ignorata"), dove
  "da apprendere" = unità − apprese − ignorate. Il nome accessibile è lo stesso testo.
- **Sottotitolo**: via "N apprese"; si aggiunge "N domande" (da `recall_questions`, solo se > 0) dopo
  "N unità".
- **Scudo della verifica** (`ShieldCheck` di lucide, 19 px): verde (`--study-learned`) se
  `phases.review === 'VALID'` e `pending_issues === 0`; giallo (`--study-learning`) in tutti gli altri
  casi con la rielaborazione fatta; nessuno scudo se `phases.rewrite !== 'VALID'`. Suggerimento:
  "Verifica fatta", "Verifica da fare" o "Verifica da fare · N issue da decidere".
- **Posizione**: a destra della riga; su computer anello e scudo in riga, sull'iPhone (`max-md`) uno
  sopra l'altro. Ogni icona ha il suo posto fisso anche quando manca (posto vuoto), così gli scudi
  restano in colonna. Area da toccare 34 px su computer, 40 px sull'iPhone.
- **Clic**: anello → `/studio/lezione/{id}`; scudo → `/lezioni/{id}?panel=verifica`; il resto della
  riga apre la lezione come oggi. Oggi tutta la riga è un `Link`: non si mettono link dentro un link.
  Il titolo diventa il link e copre la riga con un `::after` assoluto; anello e scudo sono link
  separati sopra (`position: relative; z-index: 1`). Con la selezione attiva le icone non ci sono
  (come oggi l'anello).
- **Puntino**: lo stato "da verificare" non ha più il puntino giallo (lo dice lo scudo): si disegna come
  "pronta". `lessonStatus` e i conteggi che lo usano restano com'erano.

Test: vitest di `lessonSubtitle` (domande sì, apprese no) e della riga (scudo verde/giallo/assente,
link giusti, nessun `<a>` dentro un `<a>`); e2e — clic sull'anello apre lo Studio, clic sullo scudo apre
la lezione con il pannello Verifica, clic sul titolo apre la lezione; a 390 px anello e scudo in
colonna e il titolo non si sovrappone.

### C1 — Card della correzione proposta

File: `frontend/src/components/lesson/panels/ReviewPanel.tsx` (`IssueCard`) e il suo test. Wireframe:
**correzione**.

Vale per le issue con correzione proposta (`!paragraphIssue(issue)`). Le issue di paragrafo restano
come oggi.

- **Accetta** e **Mantieni** diventano pulsanti a sola icona (`Check`, accento come oggi; `X`,
  contorno) con il `Tooltip`: "Accetta la correzione" e "Mantieni il testo attuale". Il pulsante
  "Modifica" sparisce. Sull'iPhone restano grandi (48 px di altezza come oggi).
- **Modifica**: doppio clic sul box "Correzione proposta" (sull'iPhone basta un tocco). Il box diventa
  bianco con il bordo d'accento e il testo si modifica lì dentro (textarea che cresce col testo, il
  cursore dove si è cliccato o alla fine). Passando sul box (solo con il mouse) compare "Doppio clic per
  modificare".
- In modifica, a destra di "Correzione proposta", fuori dal box, compare un piccolo pulsante a icona
  (`RotateCcw`) "Ripristina la correzione proposta", attivo solo se il testo è cambiato.
- **Applicare**: clic fuori dal box o su ✓ (o Cmd/Ctrl+Invio) → decisione `edited` con il testo scritto.
  Il suggerimento di ✓ in modifica con testo cambiato diventa "Applica la tua correzione".
- **Regole confermate**: uscire dal box senza aver cambiato nulla non decide niente (il box torna
  com'era); Esc annulla la modifica senza decidere; ✕ durante la modifica vale "Mantieni" e scarta il
  testo scritto; il testo vuoto non si applica.
- Lo stato `editing` del pannello (oggi passato a `IssueCard`) si adatta: niente più form separato per
  queste issue.

Test: vitest — doppio clic apre la modifica; clic fuori con testo cambiato manda `edited` con quel
testo; clic fuori senza cambi non manda nulla; Esc annulla; ✕ in modifica manda `rejected`; il
ripristino rimette il testo proposto; i due pulsanti hanno solo l'icona e il nome accessibile. E2e —
modifica col doppio clic e clic fuori: l'issue passa fra le decise come "modificata" e il testo nel
documento è quello scritto.

### N3 — Unità al revisore e al recaller

File: `rt/services/unit_relevance.py` (`list_units`), `rt/api/schemas.py` e il router di
`/lessons/{id}/relevance` in `rt/api/routers/lessons.py` (schema `UnitRelevanceOverview`), `ReviewPanel.tsx`, `QuestionsPanel.tsx` (footer di oggi, righe ~645-670), un
componente condiviso nuovo (per esempio `frontend/src/components/lesson/panels/UnitStrip.tsx`).
Wireframe: **revisore** (pannello "Proposta").

- **Regola** (già nel codice, non cambia): al revisore vanno le unità per cui
  `unit_relevance.included(lesson_dir, unit)` è vero, cioè le didattiche col classificatore attivo,
  tutte col classificatore spento, e quelle non classificate o cambiate dopo la classificazione.
- **API**: ogni riga di `GET /lessons/{id}/relevance` aggiunge `review_included: bool`, calcolato con
  `included()` (così l'interfaccia non rifà la regola). Rigenerare openapi e `schema.d.ts`.
- **Elemento** in fondo al pannello Verifica (sotto "Verifica di nuovo tutta la lezione", con il bordo
  in alto come il footer del pannello Domande):
  - una **striscia** con una tacca per unità, in ordine: piena (accento) se va al revisore, vuota (solo
    contorno) se è esclusa, a righe se non è ancora classificata o è cambiata (`stale` o senza
    `prediction`) ma va comunque. Passando su una tacca: "2.4 Emogasanalisi · va al revisore" /
    "· esclusa" / "· non classificata, va al revisore".
  - accanto il numero "15/18" (incluse/totale), senza altro testo.
  - passando sulla striscia (fuori dalle tacche) il suggerimento con la regola in una riga: "Al revisore
    vanno le unità didattiche secondo il classificatore" (+ ", più quelle non ancora classificate" se
    ce ne sono); col classificatore spento "Classificatore spento: al revisore vanno tutte le unità".
  - a destra un pulsante a icona etichette (`Tag`) che apre il classificatore (come oggi "Rivedi le
    etichette"), con un puntino verde se il classificatore è aggiornato e giallo se va rifatto
    (stesso stato che il footer del pannello Domande mostra oggi come testo); suggerimento "Rivedi le
    etichette · classificatore aggiornato / da aggiornare". Col classificatore spento non c'è.
  - un clic sulla striscia apre anche lui il classificatore.
- **Pannello Domande**: lo stesso componente al posto delle due righe di oggi ("Unità per il recaller:
  18 di 18 (solo rilevanti) · Scegli" e "Classificatore: … · Rivedi le etichette"). Qui la tacca è piena
  se l'unità è selezionata per il recaller; un clic sulla striscia apre il popup "Unità per il recaller"
  (oggi "Scegli"); il suggerimento della striscia dice "Al recaller vanno le unità rilevanti" oppure
  "Scelta personalizzata"; l'icona etichette come sopra.
- Su iPhone niente suggerimenti al passaggio: il clic fa quello che fa su computer.

Test: pytest — `review_included` coincide con `included()` (classificatore spento, attivo, unità stale);
vitest del componente (tacche piene/vuote/a righe, conteggio, puntino, clic); vitest dei due pannelli
(il footer di testo di oggi non c'è più). E2e — nel pannello Verifica di una lezione con il
classificatore attivo il numero e le tacche corrispondono, e il clic sull'icona apre il classificatore.

### Revisione, merge e stabile (Claude)

Claude rivede il diff, prova le parti toccate, fa le correzioni brevi con commit "Revisione: …", unisce
in `claude/rt-4.2.3-beta`, imposta VERSION `4.2.3`, lancia **tutti** i test in locale (pytest,
frontend, build, entrambi i gruppi e2e). Poi apre la PR da `claude/rt-4.2.3-beta` verso `main` (la PR
#63 con i fix urgenti va unita prima, o chiusa se è già tutto nella beta), e dopo il merge di Attilio
lancia `release.yml` su `main` e segue il run fino alla fine.

## 4.2.3.2b1 — rework della verifica

Audit del 9 ottobre 2026 (thread "Rework verifica 4.2.3.2", lista completa con le cause in
`/mnt/project-files/rt-4.2.3/audit-verifica-4.2.3.2.md`), approvato da Attilio. Lavora **solo Codex**,
un giro solo. Esce come beta **4.2.3.2b1** (beta del fix 4.2.3.2 della stabile 4.2.3).

Wireframe interattivo del pannello, da aprire nel browser: `docs/wireframes-4.2.3/RT-4.2.3.2-verifica.html`
(tre schede: "Issue per unità", "Unità verificate", "Menu contestuale"). Dove piano e wireframe non
coincidono vale il piano.

### Regole

- **Branch**: `rt4232/codex`, già creato da `claude/rt-4.2.3.2-beta` (v4.2.3 più questo piano). Un commit per task (messaggio `<id>: …`),
  alla fine **una sola PR verso `claude/rt-4.2.3.2-beta`**. Mai merge su `main` o sul branch beta,
  niente tag, `VERSION` non si tocca.
- In parallelo esce la stabile 4.2.3.1 (PR #68: tooltip che restano nella finestra, pannello laterale
  sopra la barra dell'editor, popup info dello Studio, versioni tipo 4.2.3.2b1). Non toccare quei punti:
  `frontend/src/components/ui/tooltip.tsx`, lo z-index di `LessonPanel.tsx`, il popup info di
  `Study.tsx`, `rt/core/version.py`. Claude porta la 4.2.3.1 nel branch beta prima del merge.
- Ogni bug ha un test che fallisce sul codice di oggi e passa col fix (i casi sono scritti nei task).
- Le lezioni esistenti devono continuare a funzionare: file vecchi (issue con id `sci_` numerati per
  posizione, `document_edits.json` senza date, checkpoint senza registro) si leggono senza errori e
  senza perdere decisioni.
- Prima della PR si lanciano **tutti** i test: pytest completo, `npm run lint`, `npm run typecheck`,
  `npx vitest run`, `npm run build`, poi gli e2e di **entrambi** i gruppi (`RT_E2E_GROUP=recall-images` e
  `RT_E2E_GROUP=other`) dopo la build. Le preferenze stanno sul server: un e2e che ne cambia una la
  rimette com'era. Rigenera `docs/openapi.json` (`python scripts/export_openapi.py`) e
  `frontend/src/api/schema.d.ts` (`npm run gen:api`) dopo i cambi all'API.
- Testi dell'interfaccia in italiano, nello stile dei pannelli di oggi.

### Decisioni (Attilio, 8 e 9 ottobre 2026)

- Una decisione presa deve **sempre** arrivare nel testo, o essere rifiutata con un motivo chiaro: mai
  una decisione registrata che non cambia nulla.
- Un'unità già verificata sul testo di adesso **non si verifica di nuovo** per sbaglio: serve una scelta
  esplicita ("Verifica di nuovo", con conferma). Vale per la singola unità e per tutta la lezione.
- Le decisioni restano agganciate alle issue ritrovate quando un'unità si verifica di nuovo.
- Il pannello mostra anche le unità verificate **senza** issue (oggi non lasciano traccia).
- Menu contestuale: "Domande su questa parte" diventa "Domande sull'unità X" (o "sulle unità X–Y");
  "Verifica questa parte" resta visibile ma spenta con "In arrivo" (la verifica contestuale del solo
  testo selezionato è per la 4.2.4).
- Ordinamenti di oggi (cronologico, tipo e gravità) restano; in più il raggruppamento per unità.

### Task

| Id | Cosa |
|---|---|
| V1 | Decisioni applicate anche alle unità modificate a mano |
| V2 | Sostituzione: fine frase corretta (decimali) |
| V3 | Decisioni controllate sul testo che si vede; ordine di applicazione fisso |
| V4 | Suggerimenti non letterali: niente "Accetta" a vuoto |
| V5 | Id delle issue stabili, niente più rinumerazione |
| V6 | Registro delle unità verificate |
| V7 | Niente ri-verifica delle unità già verificate, salvo forzatura |
| V8 | Pannello Verifica e menu contestuale |
| V9 | Elenco issue senza letture ripetute |
| V10 | Rifiniture: stato dopo una review saltata, avviso di decisione non applicata |

Ordine: V1 → V2 → V3 → V4 → V5 → V6 → V7 → V9 → V10 → V8 (il pannello usa le API dei task prima).

### V1 — Decisioni applicate anche alle unità modificate a mano

Oggi: se un'unità è stata modificata a mano nell'anteprima (in `document_edits.json` ha `edited: true`),
`apply_decisions_to_draft` (`rt/pipeline/ledger.py`) la salta per intero, anche per le decisioni prese
**dopo** la modifica. Accetti, la decisione si salva, il testo non cambia.

- `plan_document_edit` / `save_document_edit` (`rt/services/document_edit_service.py`): quando il
  testo di un'unità cambia, la voce dell'unità prende anche `edited_at` (stesso formato di
  `ReviewDecision.timestamp`, `datetime.now().isoformat()`); se l'unità era già modificata e il testo
  non cambia, `edited_at` resta quello di prima.
- `apply_decisions_to_draft`: per un'unità modificata si applicano le decisioni con timestamp **dopo**
  `edited_at` (quelle prima sono già nel testo scritto a mano). Per le voci vecchie senza `edited_at` vale
  la data di modifica di `document_edits.json`. Serve passare a `apply_decisions_to_draft` le date
  invece del solo insieme degli id (aggiorna `load_resolved_draft`, `build.py` e gli altri chiamanti).
- `orphan_issue_ids` e `_only_manual_edits` (`rt/pipeline/review.py`) continuano a funzionare.

Test (pytest): lezione sintetica (come `_synthetic_lesson` in `tests/test_document_edit.py`) con
l'unità 1.1 "Gli acidi grassi saturi hanno doppi legami. Sono lipidi."; issue su "hanno doppi
legami" → "non hanno doppi legami"; modifica a mano di "Sono lipidi." in "Sono lipidi semplici." con
`save_document_edit`; poi la decisione `accepted` dal canale web: l'anteprima
(`render_lesson_documents`) contiene "non hanno doppi legami" **e** "lipidi semplici". Più: decisione
presa prima della modifica non applicata due volte; file senza `edited_at` letto con la data del file.

### V2 — Sostituzione: fine frase corretta

Oggi in `apply_decisions_to_draft`, se la correzione finisce con "." la sostituzione si allarga dal
claim fino al primo "." del testo; il punto di "7.4" conta come fine frase e il testo si rompe:
"…7,35-7,45, mantenuto dai tamponi.4 circa, mantenuto dai tamponi."

- Fine frase = `.`, `!` o `?` seguito da spazio, a capo o fine testo, nello stesso paragrafo (mai oltre
  un a capo). Se non c'è una frase intera riconoscibile si sostituisce solo il claim.
- Togli la logica di sostituzione da `apply_decisions_to_draft` in una funzione piccola e testata da sola.

Test (pytest): unità "Il pH normale del sangue è 7.4 circa, mantenuto dai tamponi. Altro testo qui.",
claim "Il pH normale del sangue è 7.4 circa", correzione "Il pH normale del sangue arterioso è
7,35-7,45, mantenuto dai tamponi." → risultato "Il pH normale del sangue arterioso è 7,35-7,45,
mantenuto dai tamponi. Altro testo qui."; più casi con "es." a metà frase, claim in fondo al testo senza
punto, frase su due paragrafi.

### V3 — Decisioni controllate sul testo che si vede

Oggi `_validated_text` (`rt/services/review_service.py`) controlla il claim nella bozza **grezza**,
mentre il testo mostrato ha già dentro le decisioni prese. Due issue sulla stessa frase: la seconda
risulta accettata ma non entra mai. Inoltre il testo di partenza per modificare un'issue di paragrafo
(`issue_context`, `unit_content`) viene dalla bozza grezza, e la decisione "modificata" sostituisce
l'intera unità cancellando le correzioni già accettate.

- Una funzione unica che dà il testo risolto di un'unità (quello che il documento mostra adesso) e che
  usano `_validated_text`, `issue_context` e `orphan_issue_ids`.
- `accepted`/`edited` su un'issue puntuale il cui claim non è più nel testo risolto → `ReviewDecisionError`
  con un codice proprio (per esempio `claim_changed`) e il messaggio "Il testo è già cambiato: modificalo
  a mano o chiudi l'issue". L'API lo restituisce come errore 409/422 con quel codice.
- `apply_decisions_to_draft` applica prima le decisioni di paragrafo (ASR, deriva) e poi quelle puntuali,
  ognuna nell'ordine del ledger; la modifica di paragrafo parte dal testo risolto (quindi contiene già
  le correzioni puntuali prese prima).

Test (pytest): unità "La CO2 si lega all'emoglobina formando carbossiemoglobina nei globuli rossi.",
issue A su "formando carbossiemoglobina" e B su "all'emoglobina formando carbossiemoglobina nei globuli
rossi"; accetti A, poi B → B rifiutata con `claim_changed` e il ledger ha solo A. Issue di paragrafo
modificata dopo un'accettazione puntuale nella stessa unità: il testo finale contiene entrambe.

### V4 — Suggerimenti non letterali

Oggi `sanitize_suggested_fix` restituisce `None` per i suggerimenti discorsivi ("Precisare che…",
"Verificare…"); "Accetta" salva lo stesso una decisione senza testo e il documento resta uguale.

- `GET /lessons/{id}/issues`: ogni voce dice se la correzione si applica così com'è (per esempio
  `fix_text`: il testo che entrerebbe nel documento, `null` se il suggerimento non è letterale).
- Backend: `accepted` su un'issue puntuale senza testo applicabile → `ReviewDecisionError`
  ("È un suggerimento, non una correzione: scrivi tu il testo"). L'auto-accept della CLI le lascia da
  decidere.
- Card dell'issue: con `fix_text` nullo il box si intitola "Suggerimento" (non "Correzione proposta"),
  mostra il suggerimento, ✓ Accetta non c'è; il doppio clic (un tocco su iPhone) apre la modifica a
  partire dal **claim**, e ✓ applica come `edited`. ✕ Mantieni resta.

Test: pytest (accettazione rifiutata, auto-accept che salta), vitest della card (titolo, niente
Accetta, modifica che parte dal claim).

### V5 — Id delle issue stabili

Oggi `_run_review` rinumera tutte le issue per posizione (`sci_000001`…) dopo ogni unità e alla fine;
`run_review_unit` mette le issue dell'unità rifatta in fondo al file. Verificare di nuovo un'unità e poi
"Completa la verifica" cambia gli id e `_drop_moved_decisions` toglie **tutte** le decisioni (riprodotto:
3 decisioni → 0).

- Un'issue tiene il suo id per sempre. Le issue nuove prendono il numero dopo il più alto mai usato
  (nel file delle issue **e** nel ledger, così un id con decisioni passate non si riusa).
- Quando un'unità si verifica di nuovo (singola, completamento, forzatura) le issue ritrovate (stessa
  chiave `_issue_key`: tipo, segmento, claim) riprendono il loro id e la decisione resta; le issue non
  ritrovate escono dal file e le loro decisioni dal ledger. Una sola funzione per questo, usata da
  `_run_review` e `run_review_unit`. Vale anche per le issue ERR_ASR_ST aggiunte a fine review.
- Il file delle issue resta ordinato per unità nell'ordine della bozza (l'ordine non dà più gli id).
- `run_review_unit` non porta la fase a PARTIAL quando la verifica era completa: se dopo il giro tutte
  le unità risultano verificate sul testo di adesso, la fase resta (o torna) VALID.
- Niente più `purge_decisions_by_prefix(…, "sci_")` sull'intera lezione in `_run_review`.
  `_drop_moved_decisions` resta solo per i file vecchi.

Test (pytest, con `_validated_review_issues` sostituito da un finto revisore che dà un'issue per unità):
lezione a tre unità verificata, tutte le issue decise; `run_review_unit` sulla 1.1; fase ancora VALID;
`run_review` normale → nessuna chiamata al modello e le tre decisioni ci sono ancora. Forzatura su una
lezione con issue decise: le issue ritrovate tengono id e decisione. Issue nuova in un'unità rifatta: id
nuovo mai usato prima. Adatta `tests/test_review_restart_decisions.py` e
`tests/test_force_review_ledger_purge.py` alle nuove regole (le decisioni sulle issue ritrovate restano),
senza togliere i casi che proteggono dalle decisioni attaccate all'issue sbagliata.

### V6 — Registro delle unità verificate

Oggi il checkpoint sa solo quali unità sono state fatte e la loro impronta (`unit_hashes`): niente data,
modello, numero di issue, e le unità verificate senza issue non lasciano traccia.

- Nuovo file della lezione `review_units.json` (non è un input di nessuna fase, non cambia impronte):
  per unità `reviewed_at`, `model` (il modello che ha risposto davvero, come nel log del worker; se il
  client non lo espone, il primario configurato del job `review`), `issues` (trovate in quel giro),
  `text_hash` (come `_unit_hashes`), `result` (`ok`, `issues`, `skipped_by_prefilter`, `failed` con il
  messaggio). Lo scrivono `_run_review` dopo ogni unità e `run_review_unit`.
- API `GET /lessons/{id}/review/units`: una riga per ogni unità della bozza, nell'ordine della lezione,
  con `unit_id`, `title`, `state` (`ok` verificata senza issue, `issues` con issue, `changed` testo
  cambiato dopo la verifica, `never` mai verificata, `excluded` esclusa dal revisore, `failed`),
  `reviewed_at`, `model`, `issues_total`, `issues_pending`. Per le lezioni vecchie senza registro le
  unità in `completed_items` con impronta uguale valgono verificate (data e modello vuoti).

Test (pytest): registro scritto da review completa e singola; stati `ok`, `issues`, `changed` (dopo una
modifica a mano), `never`, `excluded`, `failed`; lezione vecchia senza registro.

### V7 — Niente ri-verifica delle unità già verificate

Oggi "Verifica di nuovo tutta la lezione" forza la review e cancella tutte le decisioni senza chiedere;
se la bozza cambia per una via diversa dalla modifica a mano (per esempio una rielaborazione di
un'unità) la fase diventa STALE e "Aggiorna il documento" rifà **tutte** le unità e cancella tutte le
decisioni, pagando di nuovo il modello sull'intera lezione.

- `run_review` senza forzatura verifica solo le unità mai verificate, fallite o il cui testo è cambiato
  per la pipeline; le altre tengono issue e decisioni. Le unità cambiate solo a mano non si rifanno da
  sole (come oggi `_only_manual_edits`), ma il registro le mostra `changed`.
- Con forzatura si rifanno tutte, con le regole di V5 (issue ritrovate tengono id e decisione).
- `review_unit` (API con `unit`/`units`): un'unità già verificata sul testo di adesso si salta con
  `status: "skipped"` e motivo "già verificata", a meno di `force: true`. Il risultato del job dice per
  ogni unità quante issue ha trovato.

Test (pytest, finto revisore che conta le chiamate): lezione verificata, una unità riscritta → `run_review`
chiama il modello solo per quella e le decisioni delle altre restano; `review_unit` su unità già
verificata senza forzatura → nessuna chiamata; con forzatura → una chiamata.

### V9 — Elenco issue senza letture ripetute

Oggi `GET /lessons/{id}/issues` chiama `issue_context` per ogni issue, e ognuna rilegge `segments.json` e
`draft.json` (50 issue = 100 letture). Carica segmenti, bozza e testo risolto una volta per richiesta e
passali a `issue_context`. Test (pytest): con 30 issue i caricamenti di segmenti e bozza avvengono una
volta (monkeypatch dei loader che conta).

### V10 — Rifiniture

- In `_run_review`, quando la review si salta (fase valida, o modifiche solo a mano), lo stato successivo
  (`HUMAN_REVIEW_REQUIRED` / `READY_TO_BUILD`) si calcola dal ledger, non da `issue.status == "pending"`
  (campo che non cambia mai).
- `build_warnings`: nuovo avviso `decision_not_applied` per le decisioni `accepted`/`edited` la cui
  correzione non è nel testo risolto (dopo V1-V4 non dovrebbe succedere, ma se succede si vede prima
  del documento finale).

Test (pytest) per entrambi.

### V8 — Pannello Verifica e menu contestuale

Come il wireframe `docs/wireframes-4.2.3/RT-4.2.3.2-verifica.html`.

- **Riassunto** sotto lo stato: "N unità verificate su M · K senza problemi".
- **Per unità**: interruttore accanto al menu dell'ordine (scelta salvata come l'ordine). Acceso, le
  issue di "Da decidere" e "Decise" stanno sotto l'intestazione della loro unità (numero, titolo, un
  puntino per issue colorato per gravità, "2 da decidere · 1 decisa"), che si chiude e si apre con un
  clic. Con "Tipo e gravità" i gruppi si ordinano per la issue più grave, con "Cronologico" seguono la
  lezione; dentro il gruppo vale l'ordine scelto.
- **Terza sezione "Unità"** accanto a "Da decidere" e "Decise", dai dati di V6: una riga per unità con
  lo stato a sinistra (verde ok, ambra con issue e conto, vuoto mai verificata, a righe testo cambiato,
  grigio esclusa, rosso fallita) e sotto il titolo data e modello. Unità mai verificate, cambiate o
  fallite: pulsante "Verifica". Unità verificate sul testo di adesso: solo ⋯ con "Verifica di nuovo",
  che chiede conferma ("Le decisioni prese restano agganciate alle issue ritrovate"). Mentre il job
  gira la riga dice "Verifico…" e alla fine diventa verde o ambra. Clic sulla riga: porta all'unità nel
  testo. Clic sul conto: apre "Da decidere" filtrato su quell'unità (filtro visibile e togliibile).
- **"Verifica di nuovo tutta la lezione"**: apre una conferma con due scelte: "Verifica le unità
  cambiate o mai verificate" (predefinita, disattivata se non ce ne sono) e "Forza tutte le unità" (dice
  quante decisioni potrebbero sparire se le issue non si ritrovano). Mai più forzatura con un clic.
- **Errori delle decisioni**: `claim_changed` e il suggerimento non letterale (V3, V4) si mostrano
  nella card come gli errori di oggi; con `claim_changed` la card passa allo stato "Testo cambiato".
- **Menu contestuale** (`DocumentMenu.tsx`): "Domande su questa parte" diventa "Domande sull'unità 1.2"
  (o "sulle unità 1.2–1.3"); "Verifica questa parte" resta visibile e spenta con "In arrivo", come
  "Leggi da qui"; via la riga "Questa parte: …" e l'avviso `PartReviewStatus` in cima al documento.
- Su iPhone il pannello resta quello di oggi con le stesse aggiunte (la sezione Unità è una lista a
  tutta larghezza).

Test: vitest del pannello (riassunto, raggruppamento e ordine dei gruppi, sezione Unità con i sei
stati, conferme, filtro per unità, errori delle decisioni) e del menu (etichette, voce spenta). E2e
(mock): verifica di un'unità dalla sezione Unità, la riga passa da "Verifico…" a verde/ambra; "Verifica
di nuovo tutta la lezione" con la scelta predefinita non lancia nessun giro se tutto è già verificato;
accettazione di una correzione su un'unità modificata a mano nell'editor → il testo dell'editor cambia.

### Revisione, merge e beta (Claude)

Claude rivede il diff, prova le parti toccate, fa le correzioni brevi con commit "Revisione: …", unisce
in `claude/rt-4.2.3.2-beta` (che a quel punto contiene anche la 4.2.3.1), imposta VERSION `4.2.3.2b1`,
lancia tutti i test in locale e pubblica la beta con `release.yml`, seguendo il run fino alla fine.
