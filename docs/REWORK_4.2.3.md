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
