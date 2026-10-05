# RT 4.2.2b1 — Studio, lettura veloce, impostazioni: piano e task

Piano della 4.2.2b1, sul modello di `docs/REWORK_4.2.1.md`. Le modifiche le fanno **Codex (GPT)** e
**Antigravity**, **un giro solo a testa**; **Claude** non implementa: rivede le PR, le unisce nel
branch beta e pubblica la beta.

Wireframe di riferimento (interattivo, Mac e iPhone): `docs/wireframes-4.2.2/RT-4.2.2.html`, da
aprire nel browser. Contiene le schermate Studio, Lettura veloce e Impostazioni; dove questo piano e il
wireframe non coincidono, vale il piano.

## Regole per tutti

- Lingua: interfaccia, commenti, commit e PR in italiano. Stile del codice come il resto del repo.
- Valgono le sezioni **"Regole per tutti"** (tranne i nomi dei branch), **"Stile comune"** e **"Test"**
  di `docs/REWORK_4.2.md`: componenti di `frontend/src/components/ui/`, solo token del tema,
  `text-meta` / `text-body` / `text-heading`, icone `lucide-react`, niente frasi che spiegano
  l'interfaccia.
- **Branch**: ogni agente lavora solo sul suo branch, già creato da `claude/rt-4.2.2-beta`:

  | Agente | Branch | Dove |
  |---|---|---|
  | Codex | `rt422/codex` | Codex nel cloud, repo `atturk/rt` |
  | Antigravity | `rt422/antigravity` | `~/rt-antigravity` |

  Un commit per task (messaggio `<id>: …`), alla fine **una PR verso `claude/rt-4.2.2-beta`**.
  Mai merge su `main` o sul branch beta, niente tag, niente modifiche a `VERSION`.
- **File**: i due agenti non toccano gli stessi file. Elenco dei file per agente nella sezione
  "Divisione dei file". `frontend/src/index.css` è condiviso **per sezioni**: ognuno aggiunge o cambia
  solo i blocchi indicati nei suoi task. Se serve toccare altro, dirlo nella PR.
- **Codice di terzi (clean room)**: Readest è AGPL-3.0: **non se ne copia codice**, nemmeno adattato.
  Il lettore di oleksii.design non è open source: si prende solo il comportamento descritto qui e nel
  wireframe. `web-highlighter` (MIT) si usa come dipendenza npm.
- **Test**: solo quelli delle parti toccate (`npm run lint`, `npm run typecheck`,
  `npx vitest run <file>`, `pytest tests/test_x.py -q`). Ogni task aggiunge i suoi test. Nella PR:
  quali test sono stati eseguiti e con che esito.
- API cambiate: rigenerare `docs/openapi.json` (`scripts/export_openapi.py`) e
  `frontend/src/api/schema.d.ts` (`npm run gen:api`).

## Decisioni (risposte di Attilio, 5 ottobre 2026)

- **TipTap**: no, per ora. L'editor resta CodeMirror (atomic-editor); l'aspetto di "simple editor"
  si ottiene con una barra degli strumenti sopra l'editor (task T1).
- **Evidenziazioni**: si salvano nel database di RT (si ritrovano su Mac e iPhone), si vedono **solo
  nello Studio**, non cambiano il documento né l'export.
- **Studio**: strumenti di evidenziazione **in alto a destra**, insieme a lettura veloce, audio e
  indice. Il titolo si accorcia; un clic apre un popup con titolo intero e dettagli della lezione.
- **Lettura veloce**: una sola unità, quella aperta nello Studio. In alto solo: `← Studio`, titolo
  dell'unità, Giorno/Notte, Contesto (niente selettore di unità). Per le domande si torna allo Studio.
  Tema: all'apertura quello dell'app; Giorno/Notte lo cambia solo dentro la lettura veloce.
  Aspetto e comportamento come il lettore di oleksii.design (dettagli nel task V1).
- **Impostazioni**: riorganizzazione in 7 sezioni come nel wireframe, con menu veri al posto dei
  `<select>` del wireframe. Le preferenze personali (tema, lettura veloce, evidenziatore, scorciatoie,
  velocità audio) si salvano su RT e valgono su tutti i dispositivi.
- **Scorciatoie dell'editor personalizzabili** (richiesta della 4.2.1): nella sezione "Editor e
  scorciatoie".
- **Allineamenti**: si sistemano tutti e cinque (task A1 e A2).

## Divisione dei file

| Agente | File (oltre ai test relativi) |
|---|---|
| **Codex** | `rt/api/routers/settings.py`, nuovo `rt/api/routers/preferences.py`, `rt/services/settings_service.py`, nuovo `rt/services/preferences_service.py`, `rt/api/routers/enrichment.py` (solo impostazioni), `frontend/src/routes/settings.tsx`, `frontend/src/routes/telegram.tsx`, `frontend/src/routes/index.tsx`, `frontend/src/components/settings/*`, `frontend/src/components/TelegramBotPanel.tsx`, `frontend/src/lib/settings.ts`, `frontend/src/lib/theme.ts`, nuovo `frontend/src/lib/preferences.ts`, `frontend/index.html`, `frontend/src/components/lesson/LessonEditor.tsx`, `frontend/src/components/lesson/markdownShortcuts.ts`, `frontend/src/components/lesson/lessonFolding.ts`, nuovo `frontend/src/components/lesson/EditorToolbar.tsx`, `index.css` (blocchi "Sezioni richiudibili" e nuovi blocchi dell'editor), file morti elencati in I1 |
| **Antigravity** | `frontend/src/components/study/*`, `frontend/src/routes/study.tsx`, nuovi `frontend/src/components/study/SpeedReader.tsx`, `speedReader.ts`, `highlights.ts`, nuovo `frontend/src/lib/studyPrefs.ts`, nuovo `frontend/src/api/highlights.ts`, `frontend/src/components/recall/LightweightSession.tsx`, `frontend/src/components/lessons/LessonsView.tsx` (solo `StatusDot`), `frontend/src/components/shell/PageHeader.tsx`, `frontend/package.json` / `package-lock.json`, `rt/db/models.py`, nuova migrazione `rt/db/migrations/versions/0009_study_highlights.py`, nuovo `rt/api/routers/highlights.py`, nuovo `rt/services/highlights_service.py`, `rt/services/lesson_delete_service.py`, `index.css` (nuovi blocchi "Evidenziatore" e "Lettura veloce" in fondo) |

Le preferenze della lettura veloce e dell'evidenziatore le gestisce Antigravity in
`frontend/src/lib/studyPrefs.ts` (salvate nel browser, chiavi e forma dei dati fissate sotto). Al
merge Claude collega `studyPrefs.ts` alle preferenze su RT di P1: per questo chiavi e forma dei dati
vanno rispettate alla lettera.

## Task

| Agente | Task |
|---|---|
| **Codex** — impostazioni ed editor (backend + frontend) | P1, I1, K3, T1, A1 |
| **Antigravity** — Studio e lettura veloce (backend + frontend) | S1, H1, V1, A2 |

Ordine consigliato: Codex P1 → I1 → K3 → T1 → A1; Antigravity A2 → S1 → H1 → V1. Nessun task
aspetta l'altro agente.

### P1 — Preferenze personali salvate su RT (Codex)

- Backend: le preferenze stanno nella tabella `settings` esistente (`rt/db/models.py`, `Setting`),
  con chiave `pref:<nome>`. API nuove (router `preferences.py`, autenticate come le altre):
  `GET /preferences` → oggetto `{nome: valore}` di tutte le preferenze; `PUT /preferences/{nome}` con
  corpo JSON qualsiasi (massimo 16 KB, nome `^[a-z0-9][a-z0-9._-]{0,63}$`, 422 altrimenti);
  `DELETE /preferences/{nome}` torna al predefinito.
- Frontend `frontend/src/lib/preferences.ts`: `usePreference<T>(nome, predefinito)` →
  `[valore, imposta]` con React Query, aggiornamento ottimistico e copia in `localStorage`
  (`rt-pref:<nome>`) per avere il valore subito al caricamento.
- Nomi fissati (usati anche da Antigravity e dalle Impostazioni):
  - `theme`: `'sistema' | 'chiaro' | 'scuro'` (predefinito `'sistema'`). Sostituisce `rt-theme`:
    `lib/theme.ts` e lo script in `index.html` leggono la copia `rt-pref:theme` prima del primo
    disegno; il vecchio `rt-theme` si migra una volta e poi si cancella. "Sistema" segue
    `prefers-color-scheme` anche quando cambia.
  - `audio.rate`: numero (sostituisce `rt-playback-rate`, stessa migrazione).
  - `study.rsvp`, `study.highlighter`: forma nel task V1 e H1.
  - `editor.shortcuts`: forma nel task K3.
- Test: pytest delle API (salva, rilegge, cancella, nome non valido, troppo grande); vitest di
  `preferences.ts` e della migrazione del tema.

### I1 — Impostazioni riorganizzate (Codex)

Wireframe: scheda "Impostazioni". Oggi 8 schede (`routes/settings.tsx`) con doppioni; diventano
**7 sezioni** con URL propri, e i vecchi URL (`/impostazioni/modelli`, `/chiavi`, `/costi`,
`/ricerca-web`, `/decisioni`, `/bot`, `/info`, e `/bot` fuori dalle impostazioni) portano alla sezione giusta.

- **Layout**: su desktop elenco delle sezioni a sinistra (nome, la sezione aperta evidenziata) e
  contenuto a destra, gruppi con titolo in maiuscoletto e righe "etichetta — controllo". Sul telefono
  l'elenco è una pagina (nome + descrizione breve + `›`), ogni sezione si apre a pagina intera con la
  freccia indietro. Menu a tendina con i componenti di `components/ui/` (niente `<select>` nativi
  dove esiste il componente), interruttori per i sì/no.
- **Sezioni e contenuto** (ogni controllo di oggi deve trovare posto; nella PR una tabella "prima →
  dopo" di tutti i controlli):
  1. **Aspetto e lettura**: Tema (Sistema / Chiaro / Scuro, pref `theme`; l'icona del tema
     nell'intestazione sparisce); Sfondo dei gruppi in Lezioni; Studio: colori dell'evidenziatore
     (sola lettura dell'ordine) e "Frecce per cambiare unità" (pref `study.highlighter.arrows`, vedi
     H1); Lettura veloce: velocità, lettera di fuoco, pausa dopo la frase, font per dislessia, suono
     (stessa pref `study.rsvp` di V1); Audio: velocità di riproduzione (pref `audio.rate`).
  2. **Editor e scorciatoie**: task K3.
  3. **Lavorazione delle lezioni**: Trascrizione (motore, base URL, modello, chiave STT: la chiave
     STT solo qui); Scaletta: "Approva da sola dopo" in secondi con "0 = aspetta sempre te";
     Arricchimento: **un solo controllo** Disattivato / Manuale / Automatico (scrive `enrichment.mode`
     e `automatic` coerenti come fa oggi il validatore; la casella "Analizza anche nella pipeline"
     sparisce) più tetto, numero massimo, utilità minima e la ricerca web (SearXNG, con "Prova");
     Job in parallelo.
  4. **Modelli e connessioni**: Modelli per fase (con "Prova"); Connessioni: ogni connessione mostra
     le sue chiavi (salva, prova, elimina con Option come oggi) e i costi dei suoi modelli (le schede
     **Chiavi** e **Costi** spariscono); Nuova connessione; Avanzate: Route di riserva e parametri,
     **Modelli decisionali** (Classificatore e modello decisionale dell'arricchimento nella stessa
     pagina; la credenziale si sceglie da un menu delle chiavi esistenti, non si scrive a mano),
     Istruzioni dei prompt.
  5. **Telegram**: tutto qui, una volta sola: Usa Telegram, bot (avvia/ferma), token e chat del
     gruppo (il token del bot solo qui), topic per materia, archivio dei topic, ultime notifiche.
     Il contenuto di `routes/telegram.tsx` confluisce qui; `/bot` e `/impostazioni/bot` portano qui.
  6. **Accesso da iPhone**: indirizzo e QR di accesso (contenuto attuale di `device-access.tsx`).
  7. **Info e aggiornamenti**: versione, canale, cartelle (la cartella dati solo qui),
     Configurazione guidata, Esci.
- **Configurazione guidata**: "un modello per tutte le fasi" non assegna le fasi che richiedono un
  modello con immagini (`image_description`, `enrichment_image`): restano da scegliere a parte,
  con il passo che lo dice; i commenti "sei fasi" vanno corretti.
- **Codice morto da togliere**: `useLessonViewPrefs`, `useRecallViewPrefs`, `useViewPrefs`
  (`lib/viewPrefs.ts`) e LessonPicker / LessonBrowser / LessonList se non usati da nessuna route
  (verificare prima con una ricerca), con i loro test.
- Nessuna API esistente cambia significato; se ne serve una nuova per le chiavi di una connessione o
  i costi per modello, si aggiunge.
- Test: vitest della navigazione (desktop e telefono), dei redirect dai vecchi URL, del controllo
  unico dell'arricchimento; aggiornare `settings.test.tsx` e l'e2e `settings.spec.ts`.

### K3 — Scorciatoie dell'editor personalizzabili (Codex)

- `markdownShortcuts.ts` espone un **registro dei comandi**: `{id, etichetta, gruppo, predefinita,
  run}` per tutti quelli della 4.2.1 (grassetto, corsivo, barrato, codice, evidenziato, link,
  casella, rientro +/−, elimina paragrafo) e per le sezioni (`lessonFolding.ts`: chiudi/riapri
  sezione, chiudi/riapri tutto). Le predefinite restano quelle di oggi (Obsidian).
- Pref `editor.shortcuts`: `{[id]: string | null}` con le sole differenze dalle predefinite
  (`null` = nessuna scorciatoia). `LessonEditor.tsx` costruisce il keymap dal registro più la pref,
  in un `Compartment`, e lo riconfigura quando la pref cambia, senza ricaricare l'editor.
- Sezione **Editor e scorciatoie** delle Impostazioni: campo di ricerca (per nome o combinazione),
  comandi per gruppo, combinazione mostrata con i simboli del Mac (⌘ ⌥ ⇧ ⌃) o Ctrl/Alt altrove. Clic
  sulla combinazione: "Premi i tasti…", Esc annulla, Backspace toglie la scorciatoia. Se la
  combinazione è già usata da un altro comando, si dice quale e si chiede se scambiarle. Combinazioni
  riservate non assegnabili: `Mod-z`, `Mod-Shift-z`, `Mod-c`, `Mod-v`, `Mod-x`, `Mod-a`, `Mod-f`.
  "Ripristina" per comando e "Ripristina tutte".
- Test: vitest del registro (predefinite = 4.2.1), del keymap con una pref personalizzata (con un
  `EditorView` vero), del conflitto e dello scambio nella sezione delle Impostazioni.

### T1 — Barra degli strumenti dell'editor (Codex)

L'aspetto di "simple editor" di TipTap, sopra l'editor CodeMirror di oggi.

- `EditorToolbar.tsx` sopra il documento in `LessonEditor.tsx`, attaccata in alto mentre si scorre
  (sotto l'intestazione della lezione), senza bordo, icone `lucide-react` con tooltip "Nome (⌘B)"
  che mostra la scorciatoia attuale (K3). Gruppi separati da una linea sottile: Annulla, Ripeti |
  Elenco puntato, Elenco numerato, Casella | Grassetto, Corsivo, Barrato, Codice, Evidenziato, Link
  | Cerca. **Niente pulsanti per i titoli** (i titoli danno struttura a sezioni e unità, come
  deciso nella 4.2.1).
- I pulsanti usano gli stessi comandi del registro di K3; quelli di formattazione appaiono attivi
  quando il cursore è dentro quella formattazione (come il toggle di `Mod-b` della 4.2.1b2).
- In sola lettura (lezione bloccata da un job) la barra non c'è. Sul telefono una riga sola che
  scorre in orizzontale.
- Le regole della 4.2.1 valgono anche qui: niente effetti dentro i timecode bloccati, i blocchi
  immagine e le tabelle.
- Test: vitest della barra (pulsante → testo cambiato, stato attivo, assente in sola lettura).

### A1 — Allineamenti dell'editor (Codex)

- Le frecce delle sezioni (`.cm-foldGutter`) stanno centrate sulla **prima riga** del titolo; oggi
  stanno in alto, sopra la riga (screenshot di Attilio nel PDF del batch; la riga del titolo ha un
  padding che la gutter non considera).
- Sull'iPhone il testo della lezione parte 20 px più a destra del titolo della pagina (16 px contro
  36 px, misurato): il testo va allineato al titolo e la freccia sta nel margine a sinistra, come su
  desktop.
- Test: e2e o vitest che misura il centro della freccia contro il centro della prima riga del titolo
  (tolleranza 2 px) e il bordo sinistro del testo contro quello del titolo (desktop e 390 px).

### S1 — Intestazione dello Studio e frecce (Antigravity)

Wireframe: scheda "Studio ed evidenziatore".

- Il titolo non contiene più "· unità N di M" (la posizione resta nel pulsante dell'indice).
- Il titolo è un pulsante (icona `Info` accanto): apre un popup con titolo intero, Materia, Docente,
  Data, Unità ("16 · stai leggendo la 1"), durata dell'audio se c'è, e "Apri la lezione". Si chiude
  con un clic fuori o Esc. Sul telefono non c'è spazio per il titolo: resta solo l'icona `Info` che
  apre lo stesso popup.
- A destra, in quest'ordine: evidenziatore e gomma (H1), cestino (H1), una linea verticale sottile,
  lettura veloce (V1, icona `Gauge`), audio dell'unità, indice "Unità N di M". Nella fase domande
  restano "Rileggi l'unità" e l'indice come oggi.
- Tasti `←` / `→` (solo nella fase di lettura): unità precedente / successiva, saltando le domande
  (come scegliere dall'indice). Non agiscono con il focus in un campo di testo o con Cmd/Ctrl/Alt
  premuti. Pref `study.highlighter.arrows` (booleano, predefinito `true`, da `studyPrefs.ts`) le
  spegne.
- Test: vitest (titolo senza posizione, popup, frecce avanti/indietro, nessun effetto nei campi di
  testo o nella fase domande).

### H1 — Evidenziatore nello Studio (Antigravity)

- **Backend**: tabella `study_highlights` (migrazione Alembic `0009_study_highlights.py`):
  `id`, `lesson_id` (FK con cancellazione a cascata), `unit_id` (stringa, es. "1.3"), `color`
  (0–4), `source` (JSON: la serializzazione di web-highlighter, `startMeta`/`endMeta`/`text`/`id`),
  `created_at`. API: `GET /lessons/{id}/highlights?unit=` (elenco dell'unità),
  `POST /lessons/{id}/highlights` (`unit_id`, `color`, `source`) → 201,
  `DELETE /lessons/{id}/highlights/{hid}`, `DELETE /lessons/{id}/highlights?unit=` (tutte
  dell'unità). La cancellazione della lezione le cancella (`lesson_delete_service.py`). Non entrano
  in export, import, Telegram.
- **Frontend**: `web-highlighter` (npm, MIT, `^0.8.0`) sul contenitore del testo dell'unità
  (`UnitText`), **senza il popup "delete"**. Strumenti in alto a destra (S1):
  - selettore a due posizioni **evidenziatore / gomma** (stesso stile del selettore Lezioni:
    `bg-muted`, elemento attivo bianco); sotto l'icona dell'evidenziatore una striscia del colore
    attuale;
  - con l'evidenziatore attivo, selezionare testo lo evidenzia subito; un clic sull'evidenziatore
    già attivo **cambia colore**, a giro tra 5: giallo, verde, azzurro, rosa, arancio (token CSS
    nuovi `--hl-1`…`--hl-5` con valori per tema chiaro e scuro, blocco "Evidenziatore" in fondo a
    `index.css`);
  - con la gomma attiva, un clic su un'evidenziazione la toglie;
  - il cestino toglie tutte le evidenziazioni dell'unità, dopo una conferma nel popover ("Togli
    tutte le evidenziazioni di questa unità?" Annulla / Togli).
- Le evidenziazioni si ricaricano all'apertura dell'unità e anche in "Rileggi l'unità". Se il testo
  dell'unità è cambiato e un'evidenziazione non si ritrova più, si salta senza errori.
- Funziona con il tocco sull'iPhone (selezione nativa, poi evidenziazione).
- Pref `study.highlighter` (in `studyPrefs.ts`): `{color: 0..4, arrows: boolean}`; l'ultimo colore
  usato resta.
- Test: pytest delle API e della cancellazione a cascata; vitest degli strumenti (cambio colore a
  giro, gomma, cestino con conferma) con le API finte.

### V1 — Lettura veloce (Antigravity)

Wireframe: scheda "Lettura veloce" (provarla nel browser: suono, pause e zoom sono quelli voluti).
Componente `SpeedReader.tsx` a schermo intero sopra lo Studio, logica pura in `speedReader.ts`
(testabile senza DOM).

- **Apertura**: dal pulsante lettura veloce dell'intestazione dello Studio (S1). Legge **l'unità
  aperta** (il testo di `UnitText`, già sanificato). Chiusura con `← Studio` o `Esc`: si torna allo
  Studio sulla stessa unità, nella stessa fase.
- **In alto**: `← Studio`, titolo dell'unità (nascosto sul telefono), selettore Giorno / Notte,
  pulsante Contesto. Niente selettore di unità.
- **Tema**: all'apertura segue il tema dell'app (chiaro → Giorno, scuro → Notte); Giorno/Notte
  vale solo dentro la lettura veloce e non cambia il tema dell'app. Colori propri (Notte: fondo
  `#121212`, testo `#e9e9e7`, attenuato `#6f6f6c`, fuoco `#e8714a`; Giorno: `#f4f3ef`, `#1d1d1b`,
  `#8f8d87`, `#d4572f`), definiti come token del blocco "Lettura veloce" in `index.css`.
- **Parola**: grande (60 px desktop, 36 px telefono; regolabile), spaziata (`letter-spacing`
  ~0.16em), una lettera di fuoco colorata **sempre nello stesso punto dello schermo**: la parola è
  divisa in prima / lettera di fuoco / dopo, con larghezze fisse ai lati. Posizione della lettera:
  "Prima" 25 %, "Bilanciata" 35 %, "Dopo" 50 % delle lettere (punteggiatura esclusa).
- **Testo intorno**: **solo in pausa**, attenuato: sopra la frase fino alla parola, sotto il resto
  della frase (massimo 12 parole per lato). Mentre legge si vede solo la parola.
- **Due stati di parola**: *normale* e *fine frase* (`.` `!` `?` `…`, anche seguiti da virgolette o
  parentesi). Con "Virgola come pausa piena" acceso anche `,` `;` `:` sono *fine frase*; spento sono
  parole normali. Nessun terzo stato.
  - Tempo base `60000 / parole al minuto`; parole oltre 8 lettere `× (1 + (lettere − 8) × 0.06)`.
  - *Fine frase*: + "Pausa dopo la frase" (predefinita 400 ms); suono più grave; **zoom out**: la
    parola passa da scala 1 a 0.93 e opacità 0.82 con `ease-out` per tutta la durata della parola
    più la pausa.
  - Ripartenza graduale: dopo play le prime 5 parole sono più lente (`× 1 + n × 0.12`, n da 5 a 1).
- **Suono** (Web Audio, nessun file audio): un clic per parola, oscillatore `triangle`. Normale:
  880 Hz × tono, 45 ms, picco di guadagno 0.13. Fine frase: 520 Hz × tono che scende a ×0.82, 110 ms,
  picco 0.22. Inviluppo: attacco 4 ms, discesa esponenziale. L'`AudioContext` si crea al primo play.
- **Rumore di fondo**: bianco, rosa, marrone generati in un buffer di 2 s in loop (Web Audio), volume
  regolabile (predefinito 0.25, con dissolvenza d'ingresso di 0.3 s). Suona durante la lettura;
  quando lo si attiva o si cambia tipo in pausa si sente per 2 s come anteprima.
- **Comandi** (al centro, in basso): "Velocità N parole/min" in carattere monospaziato con
  l'icona delle impostazioni accanto, slider 100–900 a passi di 25; tre pulsanti tondi: indietro di
  N parole (N sotto il pulsante), play/pausa grande con un **anello di avanzamento** dell'unità
  (colore di fuoco), ricomincia. Sotto, piccolo: "parola / totale · tempo rimanente". Su desktop la
  riga dei tasti.
- **Tasti**: `Spazio` avvia/ferma, `←` / `→` frase precedente / successiva, `↑` / `↓` velocità ±25,
  `Home` ricomincia, `Esc` torna allo Studio.
- **Impostazioni** (pannello a destra su desktop, foglio dal basso sul telefono, con "Fatto"): Suono
  (sì/no) e Tono 0.5–2.0×; Font per dislessia (OpenDyslexic, licenza OFL, file del font nel repo
  sotto `frontend/public/fonts/`); Modalità Irlen (sì/no) con sfondo Pesca / Menta / Pergamena;
  Rumore di fondo (sì/no) con Bianco / Rosa / Marrone e volume; Pausa dopo la frase 0–1200 ms;
  Lettera di fuoco Prima / Bilanciata / Dopo; Virgola come pausa piena; Passo indietro −1 / −3 /
  −5 / −10 parole; Dimensione del testo.
- **Contesto**: pulsante in alto a destra che apre un riquadro con il paragrafo della parola,
  parole già lette più chiare e quella corrente evidenziata.
- **Cosa si legge**: le parole dei nodi di testo dell'unità, titolo escluso. Formule, immagini e
  tabelle si saltano (nel Contesto restano visibili).
- Pref `study.rsvp` (in `studyPrefs.ts`): `{wpm, orp: 'prima'|'bilanciata'|'dopo', pauseMs, comma,
  step, size, sound, pitch, dyslexic, irlen: null|'pesca'|'menta'|'pergamena', noise:
  null|'bianco'|'rosa'|'marrone', noiseVolume}`. Giorno/Notte non si salva (segue l'app ogni volta).
- `prefers-reduced-motion`: niente zoom out.
- Test: vitest di `rsvp.ts` (divisione in parole e salto di formule/immagini, stati con e
  senza "virgola", tempi, posizione della lettera di fuoco, frase precedente/successiva, indietro
  di N) e del componente (testo intorno solo in pausa, tasti, tema iniziale dall'app).

### A2 — Allineamenti fuori dall'editor (Antigravity)

- Pagina Lezioni: il pallino di stato (`StatusDot`) centrato sulla **prima riga** del titolo, con
  qualsiasi font e dimensione (oggi è centrato in un box di 20 px, mentre la riga è più alta: si
  vede su Safari). Il contenitore deve avere l'altezza della riga del titolo (es. `h-lh`).
- Linea sotto l'intestazione alla **stessa altezza in tutte le pagine** (misurato: su Mac 52 px,
  ma 56 nella sessione di ripasso; su iPhone 64, 61 nello Studio, 56 nel ripasso): Studio e
  sessione di ripasso (`LightweightSession.tsx`) usano `PageHeader` con le altezze standard
  (`--header-height` su desktop, la stessa delle altre pagine sul telefono).
- Sessione di ripasso: "Esci" diventa la sola freccia indietro (`IconButton` con etichetta "Esci"),
  come nello Studio e nella lezione.
- Test: e2e o vitest che misura l'altezza dell'intestazione nelle pagine Lezioni, Studio, Ripasso
  (desktop e 390 px) e il centro del pallino contro il centro della prima riga (tolleranza 2 px).

## Revisione e merge (Claude)

Come in `docs/REWORK_4.2.md` ("Revisione e merge"): Claude rivede il diff di ogni PR, prova le
parti toccate, fa le correzioni brevi con commit "Revisione: …" e unisce nel branch
`claude/rt-4.2.2-beta`, risolvendo i conflitti. Al merge Claude collega `studyPrefs.ts` alle
preferenze di P1. Gli errori grossi diventano task `R<n>` in fondo, per lo stesso agente.

## Correzioni

- 5 ottobre: Antigravity si è fermato dopo A2 e S1 (H1 lasciato a metà, recuperato dal Mac in
  `rt422/antigravity-wip`). Su richiesta di Attilio H1 e V1 li ha completati Claude, e
  `studyPrefs.ts` usa direttamente le preferenze su RT di P1.

## 4.2.2b2 (feedback del 5 ottobre, fatti da Claude)

- **Formule nell'editor** (`frontend/src/components/lesson/lessonMath.ts`): dal passaggio
  all'editor atomic (4.2.0) il LaTeX fra delimitatori si vedeva in chiaro, perché il rendering
  stava solo in `DocumentView`. Ora un'estensione di CodeMirror lo rende con Temml (lo stesso
  MathML della lettura) e lo rimette in chiaro quando il cursore entra nella formula, come in
  Obsidian. Fuori dai blocchi di codice e dal codice in riga.
- **Popup Nuova lezione**: più largo (560 px) e, con più di un audio, torna la lista con
  l'ordine in cui i file diventano un'unica registrazione: si riordina trascinando una riga o
  con le frecce sulla maniglia (`components/lessons/AudioOrder.tsx`, come in 4.1.1).
- **Niente "Nessuna anteprima disponibile" mentre una fase lavora**: l'API dice ora se la
  lezione non ha ancora un documento (`LessonDocument.pending`) e la pagina mostra le righe
  animate al posto del testo del segnaposto.
- **Righe vuote animate**: un riflesso le attraversa (`.rt-skeleton` e `.rt-unit-pending`),
  fermo con `prefers-reduced-motion`.

## 4.2.2b3 (richiesta del 5 ottobre, fatta da Claude)

Studio e ripasso diventano la stessa cosa, e le domande del pool si possono correggere a mano.

### Studio

- **"Nessuna domanda · genera ora"** al posto di "unità successiva": apre un popup con tipo
  (quiz, mirata, caso clinico, esercizio: le vaste non si attaccano a una singola unità), quante
  e istruzioni aggiuntive, e lancia `POST /recall/generate` con `unit_ids` su quell'unità.
  Finito il job il pulsante diventa "Mettimi alla prova · N domande": il ripasso parte con un
  clic, non da solo. Sotto resta "Unità successiva" per andare avanti senza generare niente.
- **Le domande dell'unità sono la sessione di ripasso vera e propria**: al posto della vecchia
  `QuestionPhase` (scarna) c'è `LightweightSession` nel modo "unità", quindi "Non lo so", voto,
  commento, scarto, rigenerazione e chip per tipo, limitata alle domande di quell'unità.
  I chip mostrano quante domande da porre ci sono per tipo e sono spenti se è zero; si torna al
  testo dall'icona in alto a destra, dalla freccia indietro o da "Termina" (che rimette fra
  quelle da porre la domanda lasciata a metà). Finite le domande, un pulsante porta all'unità
  successiva.

### Sessione di ripasso

- **Il clic sull'alternativa è la risposta** (non c'è più "Rispondi" nel quiz), come nello Studio.
- **Esito giusto**: l'esito, la risposta corretta e la spiegazione li dice ora il server
  (`QuizResult`). Prima si leggevano da `correct_index` della domanda, che `/recall/next` non
  rivela mai: ogni quiz risultava sbagliato e senza spiegazione, mentre il backend registrava
  l'esito giusto.
- **"Salta" e "Prossima"**: "Salta" c'è solo prima di rispondere (la domanda torna fra quelle da
  porre), "Prossima" solo dopo (non lascia niente a metà).

### Pannello Domande

- **"Domande della lezione" contraibile**, con il numero di domande mostrate.
- **Filtro per stato**: Tutte / Da porre / Poste.
- **Riproponi**: un pulsante per tutte quelle già poste e un altro per le sole sbagliate
  (ci stanno anche i "Non lo so", che il backend registra come sbagliate; le "parziali" no).
- **Menu "..." su ogni domanda**: Modifica, Segna come posta / da porre, Elimina.
- **Popup di modifica**: il testo sempre; nei quiz anche le quattro alternative e quale è la
  giusta; dove il tipo lo prevede (quiz, vasta, esercizio) il commento pregenerato dell'IA, a
  mano o riscritto dall'IA ("Rigenera con l'IA", job `recall_comment`). Le regole sono quelle
  della generazione (`GeneratedRecallQuestion`), così una modifica a mano non può produrre una
  domanda che l'IA non avrebbe potuto scrivere. Salvata, la domanda torna fra quelle da porre.

### Backend

- `rt/services/recall_editing.py` e cinque rotte sotto `/lessons/{id}/recall`:
  `POST questions/{qid}/edit`, `POST questions/{qid}/status`, `POST questions/{qid}/comment`
  (202, job), `GET questions/restorable`, `POST questions/restore`.
- Wireframe: `docs/wireframes-4.2.2/RT-4.2.2b3.html`.

## 4.2.2b4 — piano e task (issue del 5 ottobre 2026)

Sei segnalazioni d'uso raccolte da Attilio dopo la b3. Le implementano **Codex (GPT)** e
**Antigravity**, un giro solo a testa; Claude rivede le PR, le unisce in `claude/rt-4.2.2-beta` e
pubblica la beta. Valgono le "Regole per tutti" in cima a questo file, con i branch nuovi:

| Agente | Branch | Dove |
|---|---|---|
| Codex | `rt422b4/codex` | Codex nel cloud, repo `atturk/rt` |
| Antigravity | `rt422b4/antigravity` | `~/rt-antigravity` |

Un commit per task (`B1: …`), alla fine **una sola PR verso `claude/rt-4.2.2-beta`**. Niente merge,
niente tag, `VERSION` non si tocca.

### Divisione dei file

| Agente | File (oltre ai test relativi) |
|---|---|
| **Codex** — import, spazio su disco, impostazioni | `rt/pipeline/setup.py`, `rt/services/pipeline_service.py`, `rt/services/events.py`, `rt/services/worker.py`, `rt/services/audio_service.py`, `rt/api/routers/system.py`, `docs/openapi.json`, `frontend/src/api/schema.d.ts`, `frontend/src/components/settings/info.tsx` |
| **Antigravity** — Studio, ripasso, pannello Domande | `frontend/src/components/study/Study.tsx`, `frontend/src/components/recall/LightweightSession.tsx`, `frontend/src/components/lesson/panels/QuestionsPanel.tsx`, `frontend/e2e/study.spec.ts`, `frontend/e2e/recall-sessions.spec.ts` |

### Task

| Agente | Task |
|---|---|
| **Codex** | B1, B2, B3 |
| **Antigravity** | F1, F2, F3, F4 |

Nessun task aspetta l'altro agente. Ordine consigliato: Codex B1 → B2 → B3;
Antigravity F4 → F2 → F3 → F1.

### B1 — La lezione importata si vede subito (Codex)

**Sintomo**: importato un audio, per tutta la trascrizione la lezione sta in fondo all'elenco nel
gruppo "SENZA DATA" senza materia, e aprendola si legge "Nessuna anteprima disponibile" invece
dello scheletro animato. Appena parte la scaletta tutto si sistema da solo.

**Causa**: `info.yaml` si scrive al punto 7 di `run_setup`, dopo la trascrizione, e `_lesson_summary`
(`rt/services/lesson_service.py:154`) legge data e materia solo da lì; e `JobEventReporter.emit`
(`rt/services/worker.py:87`) attacca il job alla lezione solo su `PhaseCompleted(phase="setup")`,
quindi prima di allora `GET /jobs?lesson_id=N` non dà niente e nella pagina della lezione
`writing = !!doc?.pending && !live && running` resta falso.

**Da fare**:
1. In `rt/pipeline/setup.py`, appena la cartella (o la riga nel database) esiste — subito dopo
   `fs.create_db_lesson` / `fs.makedirs`, punto 4 — scrivere un `info.yaml` provvisorio con
   `data`, `ora`, `materia`, `argomenti`, `docente`, `cartella`, `creato_il`,
   `fase_corrente: metadata_only`, `stato: in_attesa_di_trascrizione` (i metadati sono già tutti
   noti: arrivano dal popup di import). Alla fine il punto 7 riscrive `info.yaml` come fa oggi,
   contenuto incluso: non cambiarlo.
2. **Non rompere la ripresa di un import interrotto**: il controllo
   `elif fs.isfile(existing_info) and not force` (~riga 510) oggi rifiuta una cartella che ha
   `info.yaml`. Con l'1 quel file c'è dal primo secondo, quindi il controllo deve considerare
   "già inizializzata" solo una lezione vera: `info.yaml` provvisorio
   (`stato: in_attesa_di_trascrizione`, nessun `trascritto grezzo.json`/`.md`, nessun lavoro
   protetto) si può sovrascrivere senza `--force`. Il messaggio e il comportamento per le lezioni
   vere restano quelli di oggi (vedi `tests/test_web_dashboard.py:42`).
3. Attaccare il job alla lezione appena la cartella esiste: `run_setup` prende un parametro
   `on_lesson_created: Optional[Callable[[str], None]]`, chiamato una volta dopo il punto 1;
   `_setup` in `rt/services/pipeline_service.py` passa
   `lambda d: ctx.progress("setup", message="Lezione creata", lesson_dir=d)`; `PhaseProgress`
   (`rt/services/events.py`) prende un campo `lesson_dir: Optional[str] = None`; in
   `JobEventReporter.emit` l'`attach_lesson` scatta per qualunque evento che porti un `lesson_dir`
   (il ramo attuale su `PhaseCompleted` resta, è idempotente).
4. Vale per tutti e tre i rami del punto 5 (trascrizione vera, `mock_asr`, `--skip-transcribe`).

**Risultato atteso**: appena l'import parte, la lezione sta nel gruppo della sua data e materia con
lo stato "in corso", e aprendola si vede lo scheletro animato per tutta la trascrizione.

**Test**: `tests/test_setup.py` — `info.yaml` con data e materia esiste subito dopo la creazione
della cartella (anche con `skip_transcribe` e con `mock_asr`); un import interrotto si riprende
senza `--force`; una lezione vera continua a essere rifiutata. Un test del worker (ListReporter o
`DbJobQueue`) che l'`attach_lesson` avviene su `PhaseProgress` con `lesson_dir`, prima della fine
del setup.

### B2 — Niente copie inutili dell'audio (Codex)

Oggi, al punto 6 di `run_setup`, **tutte** le clip originali vengono copiate nella cartella della
lezione, anche quando sono state unite in `audio completo.m4a` (punto 5, AAC 96k mono 48 kHz,
~45 MB/ora). `info.yaml` ha un solo `file_audio`, il file unito, e tutto il codice risolve solo
quello (`rt/services/lesson_service.py:529`, `rt/web/data.py:246`, `rt/pipeline/prepare.py:56`,
`rt/core/audio_clip.py` via `manifest.json`): le clip originali sono peso morto che raddoppia lo
spazio, e nemmeno un backup, perché l'import copia e non sposta.

**Da fare**:
1. Quando c'è stato il merge, copiare **solo** il file unito: il punto 6 copia le clip originali
   soltanto se non c'è `merged_audio`.
2. Import a un file solo: se il file non è già in un formato efficiente (`.m4a`, `.mp3`, `.aac`,
   `.ogg`), transcodificarlo in `<nome>.m4a` con gli stessi parametri del merge
   (`aresample=48000`, mono, `-c:a aac -b:a 96k -movflags +faststart`) e puntare `file_audio` lì,
   invece di copiare un `.wav` da ~345 MB/ora. Senza ffmpeg, o se la conversione non riesce, si
   copia l'originale come oggi (nessun import deve fallire per questo).
3. L'originale sul disco di chi importa non si cancella mai: RT copia, non sposta.

**Test**: import di due clip → nella cartella c'è solo `audio completo.m4a`; import di un `.wav` →
c'è solo il `.m4a` e `info.yaml` lo indica; import di un `.m4a` → file copiato identico; senza
ffmpeg (monkeypatch di `shutil.which`) l'import a un file solo funziona ancora.

### B3 — Sezione "Spazio e cache" nelle impostazioni (Codex)

`rt/services/audio_service.py` scrive in `<cartella dati>/cache/audio/` (copia MP4 degli `.m4a` in
AAC ADTS che i browser rifiutano) e in `<cartella dati>/cache/waveform/` (i livelli del player). La
chiave è `sha256(realpath:size:mtime_ns)[:24]`: ogni modifica di un audio lascia la voce vecchia
per sempre e le lezioni cancellate lasciano le loro. Non c'è scadenza, né conteggio, né modo di
svuotarla. Si rigenera da sola su richiesta, quindi svuotarla è sempre sicuro.

**Da fare**:
1. `GET /api/v1/system/cache` → voci e byte per tipo (`audio`, `waveform`) e totale;
   `DELETE /api/v1/system/cache` → svuota `<dati>/cache` (solo quella cartella, solo i tipi noti,
   niente errore se manca) e restituisce quanto ha liberato. Schemi Pydantic in
   `rt/api/routers/system.py` accanto a `SystemInfo`, con `summary` in italiano come le altre rotte.
   Rigenerare `docs/openapi.json` (`python scripts/export_openapi.py`) e
   `frontend/src/api/schema.d.ts` (`npm run gen:api`).
2. `frontend/src/components/settings/info.tsx`: nuova `CacheSection` nella sezione "Info e
   aggiornamenti", con la dimensione della cache e un pulsante "Svuota la cache" dietro
   `ConfirmDialog` (come `keys.tsx`). Nessuna frase che spiega l'interfaccia: basta la descrizione
   della `Section` che dice che si rigenera da sola.

**Test**: pytest delle due rotte (dimensione dopo aver creato file finti nella cache, svuotamento,
cache assente) e vitest della sezione (mostra la dimensione, chiede conferma, chiama il DELETE).

### F1 — Swipe fra le unità, via "Unità successiva" (Antigravity)

Sul PC le frecce ← → cambiano già unità nella fase di lettura dello Studio (b1, preferenza
`study.highlighter.arrows`). Sul telefono serve l'equivalente col gesto, e allora il pulsante
"Unità successiva" sparisce dal footer.

**Da fare** (nessuna libreria):
- Gestori `pointerdown` / `pointermove` / `pointerup` / `pointercancel` sul contenitore di lettura di
  `Study.tsx` (la colonna dentro `StudyShell`), attivi solo nella fase di lettura, solo con
  `event.pointerType === 'touch'` e solo se `study.highlighter.arrows` è attiva (la stessa
  preferenza delle frecce). `touch-action: pan-y` sul contenitore, così lo scorrimento verticale
  resta al browser.
- Soglia: `|dx| >= 60`, `|dx| > 2·|dy|`, gesto più breve di ~600 ms. Destra→sinistra = unità
  successiva, sinistra→destra = precedente, con gli stessi limiti delle frecce (niente oltre la
  prima e l'ultima unità della lezione). È un semplice cambio di unità: se l'unità ha domande, le
  salta, come fanno le frecce.
- Non rubare il gesto: ignorarlo se parte dentro un elemento che scorre in orizzontale (formule a
  blocco, tabelle, blocchi di codice: `overflow-x: auto`), se c'è una selezione di testo in corso
  (`getSelection()?.toString()`, l'evidenziatore lavora sulle selezioni), se la lettura veloce è
  aperta, o se inizia nei primi 25 px da sinistra (è il "torna indietro" di Safari su iOS).
- Niente animazione di scorrimento: i trattini in alto e il testo che cambia bastano.
- Togliere il pulsante `study-next` dal footer (resta l'indice "Unità N di M" per chi non usa i
  gesti, e il footer di F2).

**Test**: vitest della funzione pura che decide il gesto (estrarla, es. `swipe.ts`), e un e2e in
`frontend/e2e/study.spec.ts` in un contesto `hasTouch` con il touch via CDP, che funziona così
(provato):

```ts
const cdp = await page.context().newCDPSession(page)
const touch = (type: string, x: number, y: number) =>
  cdp.send('Input.dispatchTouchEvent', { type, touchPoints: type === 'touchEnd' ? [] : [{ x, y }] })
```

`page.touchscreen` fa solo tap: con `Input.dispatchTouchEvent` gli eventi arrivano come veri
`pointerType: 'touch'`.

### F2 — Studio: provare e generare affiancati (Antigravity)

Nel footer della fase di lettura di `Study.tsx`:
- con domande sull'unità: **due pulsanti affiancati**, "Mettimi alla prova · N" (`study-quiz`,
  primario) e uno per generarne altre che apre il popup `GenerateUnitQuestions` già esistente
  (`study-generate`);
- senza domande: solo quello per generare, com'è oggi ("Nessuna domanda · genera ora").

Capita di avere una sola domanda su un'unità: da lì nasce la richiesta. Sul telefono i due pulsanti
stanno sulla stessa riga (il secondo può essere solo icona con etichetta accessibile, se il testo
non ci sta).

**Test**: vitest in `Study.test.tsx` — con domande ci sono entrambi i pulsanti e il secondo apre il
popup; senza domande c'è solo quello di generazione e non c'è più `study-next`.

### F3 — Pool vuoto: alternative vere (Antigravity)

Nella sessione di ripasso, quando non c'è niente da porre, la scheda `recall-empty`
(`LightweightSession.tsx`) offre "Prova mista" anche quando il tipo scelto è già mista, e anche
quando le domande da porre sono zero: un pulsante che rimanda a se stesso.

**Da fare**:
- "Prova mista" solo quando serve davvero: tipo diverso da mista **e** `daPorreCount > 0`.
- Con `daPorreCount === 0` e una lezione sola, tre alternative: **"Genera domande"**, che porta a
  `/lezioni/{id}?panel=domande` (il pannello Domande si apre già da quel parametro),
  **"Riproponi le sbagliate (N)"** e **"Riproponi le poste (N)"**, che usano il ripescaggio della
  b3 (`useRestorable`, `useRestoreQuestions` in `frontend/src/api/recall.ts`) e ricominciano la
  sessione senza passare dal pannello. I due pulsanti di ripescaggio non si mostrano quando il
  conteggio è zero.
- Sessione su più lezioni (`isSelection`): nessun pulsante per generare, solo il testo che dice di
  generare le domande dai pannelli delle rispettive lezioni; il ripescaggio resta fuori.
- Nel modo "unità" (ripasso dallo Studio) restano "Torna allo studio" e il pulsante dell'unità
  successiva come oggi, più il ripescaggio se c'è qualcosa da ripescare.

**Test**: vitest in `LightweightSession.test.tsx` per i tre casi (tipo già mista, pool vuoto con una
lezione, selezione su più lezioni) e per il ripescaggio che riparte.

### F4 — Ripescaggio come due icone (Antigravity)

Nel pannello Domande (`QuestionsPanel.tsx`, blocco `questions-restore` della b3) i due pulsanti
larghi impilati "Riproponi le poste (12)" e "Solo quelle sbagliate (1)" diventano **due icone
affiancate** con il conteggio accanto (`IconButton` di `frontend/src/components/ui/icon-button.tsx`,
come le azioni dell'intestazione della lezione): `RotateCcw` per tutte quelle poste, un'icona che
dica "sbagliate" per l'altra. Il senso sta nell'etichetta accessibile, i `data-testid` non cambiano.

**Test**: aggiornare il test del pannello in `QuestionsPanel.test.tsx` e il pezzo di
`recall-sessions.spec.ts` che usa i due pulsanti.
