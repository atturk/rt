# RT 4.2.1b1 — modifiche minori: piano e task

Piano delle modifiche della 4.2.1b1, sul modello di `docs/REWORK_4.2.md`. Le modifiche le fanno
**Codex (GPT)** e **Antigravity**, **un giro solo a testa**; **Claude** non implementa: rivede le PR,
le unisce nel branch beta e pubblica la beta.

## Regole per tutti

- Lingua: interfaccia, commenti, commit e PR in italiano. Stile del codice come il resto del repo.
- Valgono le sezioni **"Regole per tutti"** (tranne i nomi dei branch) e **"Stile comune"** di
  `docs/REWORK_4.2.md`: componenti di `frontend/src/components/ui/`, solo token del tema, `text-meta` /
  `text-body` / `text-heading`, icone `lucide-react`, niente frasi che spiegano l'interfaccia.
- **Branch**: ogni agente lavora solo sul suo branch, già creato da `claude/rt-4.2.1-beta`:

  | Agente | Branch | Dove |
  |---|---|---|
  | Codex | `rt421/codex` | Codex nel cloud, repo `atturk/rt` |
  | Antigravity | `rt421/antigravity` | `~/rt-antigravity` |

  Un commit per task (messaggio `<id>: …`), alla fine **una PR verso `claude/rt-4.2.1-beta`**.
  Mai merge su `main` o sul branch beta, niente tag, niente modifiche a `VERSION`.
- **File**: ogni task dice quali file tocca. I due agenti non toccano gli stessi file, tranne
  `frontend/src/components/lessons/LessonsView.tsx`, diviso per parti (vedi i task). Se serve
  toccare altro, dirlo nella PR.
- **Test**: solo quelli delle parti toccate (sezione "Test" di `docs/REWORK_4.2.md`): `npm run lint`,
  `npm run typecheck`, `npx vitest run <file>` dei componenti cambiati; `pytest tests/test_x.py -q`
  dei moduli backend cambiati. Ogni task aggiunge i suoi test. Nella PR: quali test sono stati
  eseguiti e con che esito.
- API cambiate: rigenerare `docs/openapi.json` (`scripts/export_openapi.py`) e
  `frontend/src/api/schema.d.ts` (`npm run gen:api`).

## Decisioni (risposte di Attilio, 4 ottobre 2026)

- **Audio**: resta **intero** (`audio completo.m4a` anche da più registrazioni). Nessun task.
- **Titolo duplicato nel Markdown**: falso allarme. Il titolo H1 `# [data] MATERIA - Titolo` non si
  scrive più dal commit 3700cca (29 settembre); lo hanno solo i documenti costruiti prima, e
  l'editor lo ignora. Nessun task.
- **Export e import di più lezioni**: l'export diventa un job con avanzamento; l'import accetta anche
  lo ZIP di più lezioni prodotto da "Scarica zip". Formati di file personalizzati: in una versione
  successiva.
- **Raggruppamento per mese**: nel selettore del desktop, un secondo clic su "Per data" alterna
  giorno e mese; sul telefono il pulsante unico gira su data, mese, materia, docente.
- **Scorciatoie**: quelle predefinite di Obsidian, più simile è meglio.
- **Sezioni richiudibili**: nell'editor, sotto i titoli, come in Obsidian.

## Task

| Agente | Task |
|---|---|
| **Codex** — export, import, selezione (backend + frontend) | E1, E2, L1 |
| **Antigravity** — editor e righe della pagina Lezioni (solo frontend) | K1, K2, L2, L3 |

Ordine consigliato: Codex E1 → E2 → L1; Antigravity L3 → L2 → K1 → K2. Nessun task aspetta l'altro
agente.

### E1 — Export di più lezioni come job con avanzamento (Codex)

Oggi "Scarica Markdown" e "Scarica zip" della barra di selezione sono link a `GET /lesson-exports`:
il server prepara tutto lo ZIP prima di rispondere e per minuti non si vede niente.

- Backend: job nuovo `export_lessons` sul modello di `telegram_topic_export_job`
  (`rt/services/api_jobs.py`: `exports_root()`, `job_export_path()`, `sweep_stale_exports()`).
  Payload: `ids`, `format` (`markdown` | `zip`), `name`. Avanzamento **per lezione** (`n su N`, nome
  della lezione nel messaggio), annullabile tra una lezione e l'altra (`ctx.check_cancelled()`). Il
  contenuto resta quello di `export_many_to_tempfile` (`rt/storage/export.py`): va diviso in modo
  che chiami un callback di avanzamento, senza duplicare la logica.
- API: `POST /lesson-exports` → 202 con `job_id` (stessi parametri di oggi nel corpo);
  `GET /lesson-exports/{job_id}/file` scarica lo ZIP finito (404 se il job non è finito o non è
  un export). `GET /lesson-exports` resta com'è (CLI e compatibilità).
- Frontend (`SelectionBar` in `LessonsView.tsx` e `frontend/src/api/`): i due pulsanti avviano il
  job; l'avanzamento si vede con i componenti dei job già presenti (`JobProgress` /
  indicatore dei job); a job finito il download parte da solo, e resta un link per riscaricarlo.
  Gli errori (nessuna lezione con documento finale, ecc.) come oggi.
- Test: pytest del job e delle due API (avanzamento, file, 404); vitest della barra.

### E2 — Import di più lezioni e finestra che non si chiude (Codex)

Problemi visti da Attilio: lo ZIP di più lezioni prodotto da "Scarica zip" non si importa (bisogna
estrarlo a mano); dopo un import la finestra resta aperta con lo stesso file e il pulsante
"Importa" attivo, così si può reimportare all'infinito (i duplicati vengono rifiutati, ma la finestra
non dice bene cosa è successo).

- Backend (`rt/api/routers/jobs.py`, `import_lesson_zips_job`, `rt/services/lesson_import_service.py`):
  un archivio che contiene **solo file `.zip`** (lo ZIP di gruppo di E1/`export_many_to_tempfile`) si
  espande nei suoi archivi di lezione, ognuno importato come oggi (stessi controlli, una riga di
  esito per lezione). Il limite di 20 archivi vale per i file caricati, non per le lezioni contenute
  in uno ZIP di gruppo. L'avanzamento del job dice quale lezione sta importando (`n su N`).
- Frontend (`NewLessonDialog.tsx`): a job finito il pulsante "Importa" lascia il posto a "Chiudi" e i
  file scelti non si possono reimportare (per un altro import si scelgono di nuovo). Riepilogo
  in cima all'esito: "N importate, M già presenti, K rifiutate"; le lezioni già presenti
  (`duplicate_lesson`) si distinguono dagli altri rifiuti. Con una sola lezione importata si va
  alla lezione come oggi.
- Test: pytest dell'import di uno ZIP di gruppo (anche con una lezione già presente); vitest della
  finestra (dopo il job niente "Importa", c'è "Chiudi", riepilogo corretto).

### L1 — Seleziona tutto (Codex)

- Nella barra di selezione (`SelectionBar`, parte bassa di `LessonsView.tsx`) un comando "Seleziona
  tutto" che seleziona tutte le lezioni **visibili** (con la ricerca attiva, solo quelle trovate) e,
  se sono già tutte selezionate, diventa "Deseleziona tutto". Icona con tooltip, come gli altri
  comandi della barra.
- Test: vitest (seleziona, deseleziona, rispetto della ricerca).

### L2 — Raggruppamento per mese (Antigravity)

`groupLessons` (`frontend/src/lib/lessonView.ts`) sa già raggruppare per mese (`'mese'`); la pagina
Lezioni (`frontend/src/lib/lessonsPage.ts`, `LessonsHeaderActions` in `LessonsView.tsx`) offre solo
data, materia, docente.

- `LessonsGrouping` diventa `'data' | 'mese' | 'materia' | 'docente'`; le preferenze salvate
  vecchie restano valide.
- Desktop: il selettore resta a tre icone. Con "Per data" attivo, un altro clic sulla stessa icona
  passa a "Per mese" e viceversa; tooltip ed `aria-label` dicono lo stato attuale ("Per data",
  "Per mese"); l'icona del mese è diversa da quella del giorno (oggi `Calendar` per il giorno; per il mese es. `CalendarRange`).
  Clic su materia o docente e poi di nuovo sul calendario: si torna all'ultima scelta tra giorno e
  mese.
- Telefono: il pulsante unico gira su data → mese → materia → docente.
- Etichette dei gruppi per mese: quelle di `monthLabel` già esistenti. Il sottotitolo delle righe
  nel raggruppamento per mese mostra anche la data.
- Test: vitest di `lessonsPage` e del selettore (doppio clic, telefono, preferenza salvata).

### L3 — Dettagli della lezione sotto il titolo (Antigravity)

Oggi nella pagina Lezioni, su desktop, materia, docente e unità stanno sulla stessa riga del titolo
(dopo " · "); sul telefono già sotto.

- `LessonRow` in `LessonsView.tsx`: il sottotitolo va **sempre sotto il titolo**, anche su desktop
  (togliere il separatore " · " e le classi `max-md:`), `text-meta text-muted-foreground`. Il
  pallino di stato resta allineato al titolo.
- Test: vitest della riga se esiste; e2e `lessons-view.spec.ts` solo se controlla la disposizione.

### K1 — Scorciatoie Markdown nell'editor (Antigravity)

L'editor è `frontend/src/components/lesson/LessonEditor.tsx` su `@atomic-editor/editor`, che ha
solo le scorciatoie di base di CodeMirror (annulla, cerca, liste, Tab): niente grassetto o corsivo.

- Estensione nuova accanto alle altre (`frontend/src/components/lesson/markdownShortcuts.ts`),
  aggiunta in `extensions` di `LessonEditor.tsx`, con `Prec.high` sopra le scorciatoie di base.
- Scorciatoie predefinite di Obsidian (`Mod` = ⌘ su Mac, Ctrl altrove). Dove Obsidian e
  CodeMirror usano lo stesso tasto per cose diverse, vince Obsidian.
  - `Mod-b` grassetto `**`, `Mod-i` corsivo `*`: con testo selezionato lo avvolgono, se è già
    avvolto lo tolgono, senza selezione inseriscono la coppia con il cursore in mezzo (senza
    selezione e dentro una parola, come Obsidian, agiscono sulla parola).
  - `Mod-k` link: avvolge la selezione in `[testo]()` con il cursore tra le parentesi tonde;
    se la selezione è un URL, `[](url)` con il cursore tra le quadre.
  - `Mod-Enter` spunta o toglie la spunta di `- [ ]` / `- [x]` (sulla riga di un elenco senza
    casella la aggiunge).
  - `Mod-]` / `Mod-[` rientra / riduce il rientro delle righe selezionate (anche fuori dagli elenchi).
  - `Mod-d` elimina il paragrafo (la riga, o le righe della selezione), al posto di "seleziona
    l'occorrenza successiva" di CodeMirror.
  - Già presenti da CodeMirror e da tenere: `Mod-z` / `Mod-Shift-z` annulla e ripeti, `Mod-f`
    cerca, `Alt-↑` / `Alt-↓` sposta la riga, `Shift-Alt-↑` / `Shift-Alt-↓` duplica la riga,
    `Mod-a`, Invio che continua gli elenchi, Tab e Shift-Tab negli elenchi.
  - Senza scorciatoia predefinita in Obsidian, aggiunte come comodità: `Mod-Shift-x` barrato `~~`,
    `Mod-Shift-c` codice in linea `` ` ``, `Mod-Shift-h` evidenziato `==` solo se l'anteprima di RT
    lo mostra (altrimenti si salta e si dice nella PR).
  - Non si usano: `Mod-e` (in Obsidian cambia vista), `Mod-/` (commenti `%%`, che l'anteprima di RT
    non conosce), `Mod-1…6` per i livelli dei titoli (i titoli nell'editor di RT danno struttura a
    sezioni e unità: cambiarli da tastiera è troppo facile da sbagliare).
- **Non rompere l'anteprima di RT**: le scorciatoie non devono agire dentro i timecode bloccati
  (`timecodeLock`), i blocchi immagine e le tabelle; con la lezione in sola lettura non fanno
  niente. Verificare che l'anteprima in linea di atomic-editor mostri il risultato.
- Test: `markdownShortcuts.test.ts` con un `EditorView` vero (come `timecodeLock.test.ts`):
  avvolgi, togli, senza selezione, dentro un timecode bloccato (niente modifica), sola lettura.

### K2 — Sezioni richiudibili nell'editor (Antigravity)

- Come in Obsidian: accanto a ogni titolo (`##`, `###`, …) una freccia che compare al passaggio
  del mouse (sempre visibile sul telefono) e chiude o riapre tutto fino al titolo successivo dello
  stesso livello o superiore. Il folding dei titoli c'è già in `@codemirror/lang-markdown`
  (`foldService` / `foldNodeProp`); si usano `codeFolding` e `foldGutter` o un widget sul titolo
  di `@codemirror/language`, con lo stile dell'app (token del tema, icona `lucide-react` se è un
  widget).
- Come in Obsidian, la freccia si vede al passaggio del mouse e una sezione chiusa mostra `…` alla
  fine del titolo; clic sul titolo o sulla freccia la riapre. Scorciatoie (Obsidian non ne ha di
  predefinite): quelle di `foldKeymap` di CodeMirror, `Mod-Alt-[` chiude e `Mod-Alt-]` riapre la
  sezione del cursore, `Ctrl-Alt-[` chiude tutto e `Ctrl-Alt-]` riapre tutto.
- Le sezioni chiuse **si riaprono da sole** quando l'app porta il cursore o lo scorrimento dentro
  (salto a un'unità, a un problema della revisione, a un timecode, ricerca), cioè dove
  `LessonEditor.tsx` usa `EditorView.scrollIntoView`.
- Il testo salvato non cambia: chiudere una sezione non modifica il Markdown né fa partire il
  salvataggio. Lo stato chiuso/aperto non si salva.
- Test: vitest con un `EditorView` vero: chiudi e riapri, il documento non cambia, il salto a una
  posizione dentro una sezione chiusa la riapre.

## Revisione e merge (Claude)

Come in `docs/REWORK_4.2.md` ("Revisione e merge"): Claude rivede il diff di ogni PR, prova le
parti toccate, fa le correzioni brevi con commit "Revisione: …" e unisce nel branch
`claude/rt-4.2.1-beta`, risolvendo i conflitti. Gli errori grossi diventano task `R<n>` in fondo,
per lo stesso agente.

## Correzioni

(vuoto)
