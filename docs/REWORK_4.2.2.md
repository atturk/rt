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
