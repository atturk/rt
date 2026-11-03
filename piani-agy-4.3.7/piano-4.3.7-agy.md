# Piano 4.3.7: correzioni dal QA del frontend 4.3.6 (agy)

Le tredici voci di questo piano vengono dalla QA notturna del 2-3 novembre sulla 4.3.6, fatta su desktop e su iPhone emulato. Il report completo è in `piani-agy-4.3.7/report-qa-4.3.6.md`; gli screenshot citati sono sul Mac in `~/rt-stuff/qa-436/shots/`.

- **Base:** `claude/rt-4.3.7` (main 4.3.6 più il commit «Archivio e alleggerimento audio ignorano le lezioni senza info.yaml»).
- **Branch di lavoro:** `agy/4.3.7`, un commit per voce, una sola PR verso la base.
- **Interfaccia:** testi in italiano e minimalismo. Si usano pulsanti a icona con suggerimento, senza righe che spiegano l'interfaccia: solo etichette e dati. Sul telefono il suggerimento non c'è, quindi **non aggiungere testo esplicativo**: dove serve, metti un'etichetta breve sotto l'icona solo nei punti indicati.
- **Test:** ogni voce ha i suoi, nel file indicato o in uno nuovo accanto.

**Già fatto, non rifare:** robustezza di `audio_compaction.all_lessons_list` e `archive_service.usage_index` alle lezioni senza `info.yaml` (già sulla base, con test).
**Escluso di proposito, non fare:**
- la CI di release (riuso dei test della PR): la segue il thread della release;
- le icone della barra dello Studio: restano come sono;
- cancellare le lezioni 75-78 dal database: lo fa Claude via API, dopo l'export.

---

## 1. [URGENTE] La riparazione del LaTeX rompe le ancore della verifica

**Problema.** In 4.3.6, `sanitize_object_encoding` (`rt/core/encoding.py:169`) applica `repair_latex_escapes` a **ogni stringa** dei JSON letti, comprese le `quote` delle ancore (`Anchor` in `rt/core/models.py:128`). Se la citazione contiene una sequenza che la riparazione cambia, la lunghezza della `quote` non è più `end - start`. Il validatore `validate_span` allora fallisce:
- `load_ledger(strict=True)`, chiamata da `migrate_review_anchors` (`rt/pipeline/review_migration.py`), solleva l'errore. Risultato: `GET /lessons/30/study-notes` → 500, e lo Studio dice «Nessuna lezione pronta per lo Studio: serve la rielaborazione»;
- `load_ledger` non strict restituisce **un ledger vuoto**: le decisioni spariscono dalla vista senza avviso.

Riprodotto sui dati veri: lezione 30, `review_decisions.json` decisione 12 e `science_issues.json`, quote di 2734 caratteri che dopo la sanitizzazione ne ha 2732. Oggi è l'unica lezione colpita, ma succede a ogni citazione con quelle sequenze.

**Cosa fare.**
1. La riparazione del LaTeX vale **solo per il testo prodotto dal modello** quando arriva (risposta del rewrite, delle domande, della verifica), non quando si rileggono file già salvati. Separa le due funzioni: `sanitize_object_encoding` torna a fare solo `fix_mojibake`; una nuova `sanitize_llm_output` (o un parametro esplicito `repair_latex=True`) la usano solo i punti in cui oggi la riparazione serve per le risposte nuove. Trovali con `git log -S repair_latex_escapes` (voce 4 della 4.3.6b2).
2. Per i file già salvati con `quote` incoerenti, in `Anchor.validate_span` non sollevare errore: se `quote` non corrisponde a `end - start`, segna l'ancora come da ricalcolare (`start`/`end` ricavati cercando la `quote` nel testo dell'unità, come fa già la migrazione delle ancore) e scrivi un avviso in api.log. Un'ancora rotta non deve mai invalidare l'intero ledger.
3. `load_ledger` non strict non deve più restituire un ledger vuoto quando fallisce la validazione di una sola decisione: scarta solo quella decisione e scrivi l'avviso nel log.

**Test** (`tests/test_ledger_anchor_repair.py`):
- un ledger con una quote che contiene `\theta`/`\frac` e un TAB si carica identico, con la stessa lunghezza;
- una decisione con ancora incoerente non svuota il ledger: le altre restano;
- la risposta finta di un rewrite con `\trm{RTPL}` viene ancora riparata (stesso comportamento della 4.3.6);
- la lezione di prova con ancora rotta risponde 200 su `/lessons/{id}/study-notes`.

## 2. [URGENTE] Lezioni fantasma da cartelle temporanee

**Problema.** Nel DB vero del Mac di prova ci sono 4 lezioni create il 2/11 tra le 08:37 e le 11:24 UTC in cartelle sotto `/private/var/folders/…/T/` (`tmp2fizm4fm`, `tmp6emfp320/lesson_4`, `…/out/[2026-09-05] BIOCHIMICA`, `…/cli/out/[2026-09-05] BIOCHIMICA`). Due non hanno `info.yaml`. Nell'elenco compaiono come «Senza data: tmp2fizm4fm, lesson_4», e le materie BIOCHIMICA e MATERIA INESISTENTE finiscono in Impostazioni → Materie e nel menu Materia. pytest non c'entra (`tests/conftest.py` isola dati e DB): le ha registrate un comando eseguito su cartelle temporanee con la cartella dati vera (`ensure_indexed` / `sync_lesson` in `rt/services/lesson_service.py`).

**Cosa fare.**
1. In `ensure_indexed`, non indicizzare un percorso che sta sotto `tempfile.gettempdir()` (realpath, anche `/private/var/folders/…/T`), a meno che anche la cartella dati di RT (`paths.data_dir()`) sia lì sotto (CI e test). Scrivi una riga in api.log col percorso ignorato.
2. `GET /lessons` (e il conteggio delle materie) non deve mostrare le lezioni `storage=folder` la cui cartella non ha `info.yaml`. Non cancellarle: semplicemente non compaiono.
3. In `rt doctor` / `diagnostica.txt` aggiungi una riga «Lezioni con cartella mancante o senza info.yaml: N» con i percorsi.

**Test:** `ensure_indexed` su una cartella in `tmp_path` con la cartella dati altrove la ignora; con la cartella dati sotto la stessa temp la indicizza; l'elenco nasconde una lezione folder senza `info.yaml`.

## 3. [URGENTE] Domande già fatte su unità con segnalazioni aperte

**Problema.** La 4.3.6 salta le unità con segnalazioni aperte solo quando **genera** domande nuove (`rt/pipeline/recall.py:652`). Le domande già presenti restano nella sessione: nella lezione 68 «Ripassa» parte da un quiz dell'unità 1.2 (con segnalazione aperta), e tra le domande da porre c'è il quiz dell'unità 1.1 la cui risposta giusta è proprio la definizione contestata.

**Cosa fare.**
- In `next_question` / `pick_pending_question` (`rt/services/recall_service.py`) escludi dalla scelta le domande delle unità con segnalazioni ancora da decidere (`get_pending_issues`). Le domande non si cancellano: tornano disponibili quando le segnalazioni dell'unità sono decise.
- Nel pannello Domande (`frontend/src/components/lesson/panels/`), sulle domande di queste unità metti lo stesso contrassegno già usato nello Studio per le unità con segnalazioni aperte, e escludile dal conteggio «da porre».
- Se tutte le domande rimaste sono di unità con segnalazioni aperte, la sessione finisce con il messaggio già usato quando non ci sono domande, più «N domande in attesa della Verifica» e il link «Apri Verifica».

**Test** (`tests/test_recall_pending_issues.py`, già esistente): una domanda di un'unità con segnalazione aperta non viene scelta; dopo la decisione viene scelta.

## 4. [URGENTE] Dopo «Solo trascrizione» non si capisce come continuare

**Problema.** Nuova lezione con «Solo trascrizione»: il job finisce in 1 s e la pagina mostra:
- «Fonti nuove non ancora usate: demo_lecture.m4a · Aggiorna» (`frontend/src/components/lesson/LessonUpdateBar.tsx:204`): l'audio appena trascritto risulta una fonte nuova;
- «Questa lezione non è ancora pronta. Avvia l'elaborazione o riprova se si è interrotta.», ma un pulsante Avvia non c'è;
- «Aggiorna» porta a «Estendi» e «Ricostruisci»; Ricostruisci avvisa che «le unità cambiate perdono decisioni e stato di studio», su una lezione che di unità non ne ha ancora.

Screenshot: `d-nuova-lezione-5-creata.png`, `d-l79-aggiorna-0.png`, `d-l79-ricostruisci-0.png`.

**Cosa fare.**
- Se la lezione ha la trascrizione ma non la scaletta (`phases.outline` MISSING, `phases.prepare` VALID), la barra mostra **un solo pulsante «Continua»** (icona play, suggerimento «Scaletta e rielaborazione»). Avvia lo stesso job della pipeline completa dalla scaletta in poi: `POST /lessons/{id}/update` con `mode: rebuild`, che oggi funziona (12 s su 6 s di audio).
- Le fonti già trascritte in quella lezione non contano come «fonti nuove non ancora usate» finché non esiste una scaletta.
- Il testo «Questa lezione non è ancora pronta…» non deve citare un pulsante che non c'è: in questo stato diventa «Trascrizione pronta.».
- In questo stato non serve l'avviso di Ricostruisci (perdita di decisioni e studio): mostralo solo se la lezione ha unità.

**Test** (`LessonUpdateBar.test.tsx`, `lessons.test.tsx`): con prepare VALID e outline MISSING si vede «Continua» e non «Estendi»; il clic chiama `/update` con `rebuild`; nessuna «fonte nuova» per l'audio trascritto.

## 5. [URGENTE iPhone] Barra della pagina Lezioni e «Nuova lezione» dal telefono

**Problema.** Su iPhone il titolo «Lezioni» si vede come «L…» (`h1` largo 40 px per un testo di 71 px): i pulsanti Data, Recenti, cerca, fissa e seleziona occupano tutta la riga. Inoltre la barra in basso (`frontend/src/components/Layout.tsx:180`) non ha «Nuova lezione», che esiste solo nella barra laterale desktop (`Layout.tsx:158`, `!phone`). Dal telefono si arriva a creare una lezione solo dal «+» del popup di uno slot del calendario.

Già provato e scartato: `max-md:min-w-32` sul titolo in `PageHeader.tsx` manda a capo la barra di tutte le altre pagine.

**Cosa fare.**
- Solo nella pagina Lezioni e solo su telefono (`useIsPhone`), «Data» e «Recenti» diventano pulsanti a sola icona (stessa icona, `aria-label` e suggerimento invariati).
- Nella stessa barra, su telefono, aggiungi un pulsante «+» (`IconButton label="Nuova lezione"`, variant solid come sul desktop) che chiama `openNewLesson()`.
- Verifica a 375 px e 393 px che il titolo «Lezioni» sia intero e che nulla vada a capo.

**Test:** `LessonsView.test.tsx` con telefono simulato: il titolo non è troncato (nessun `…` nel testo accessibile), c'è il pulsante «Nuova lezione» e apre il popup.

## 6. [URGENTE iPhone] Popup dello slot del calendario

**Problema.** Toccando uno slot si apre un popup con 6 pulsanti di stato a sola icona: **il sesto è tagliato dal bordo** del popup. La data è ISO «2026-11-02». Screenshot `i-cal-1-tap.png`; componente `frontend/src/components/calendar/CalendarPopups.tsx`.

**Cosa fare.**
- Su telefono il popup è largo quanto lo schermo meno 16 px per lato, e la fila dei 6 stati si distribuisce su tutta la larghezza senza tagli. Se proprio non ci sta, va su due righe.
- Sotto ogni icona di stato, solo su telefono, la sua etichetta breve (la stessa del suggerimento) in `text-[11px]`.
- La data nel formato degli altri popup: «lun 2 nov · 09:30–11:30».

**Test:** `Calendar.test.tsx` con telefono simulato: i 6 pulsanti sono tutti visibili dentro il popup (nessun `right` oltre il bordo); la data non contiene `2026-`.

## 7. [MEDIO] Errori tecnici mostrati all'utente

**Problema.** Gli errori salvati nelle lezioni e nei job arrivano grezzi nella pagina della lezione:
- lezione 74: «SetupError: Trascrizione macparakeet-cli JSON fallita per 'finto-audio.mp3' (codice uscita: 1). Dettagli errore:», con i dettagli vuoti;
- lezione 15: «…il modello openai/gpt-6-luna ha dato errore (network_error): ('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))…».

**Cosa fare.** Nel backend, dove l'errore della lezione o del job viene esposto (`error` in `GET /lessons/{id}` e nei job), aggiungi un campo `error_message` leggibile e mantieni `error` così com'è per i Dettagli. Mappa almeno questi casi:
- `network_error` / `RemoteDisconnected` / `Connection aborted` → «Connessione al modello interrotta.»;
- `SetupError … macparakeet … fallita` → «Non riesco a leggere l'audio «<nome file>».»;
- `timeout` → «Il modello non ha risposto in tempo.»;
- tutto il resto → il testo di oggi senza il prefisso con il nome della classe (`SetupError: `).

Poi segue la frase che c'è già, se c'è («Le unità completate sono salvate: Riprova rifà solo quelle mancanti.»). Il frontend mostra `error_message`; il testo tecnico resta in Dettagli → Fasi.

**Test:** una funzione pura `human_error(text) -> str` con un caso per riga sopra (`tests/test_human_error.py`); la pagina della lezione mostra il testo leggibile.

## 8. [MEDIO] Pannello Verifica su iPhone

**Problema** (`i-l68-Verifica_con_LLM.png`):
- su telefono il blocco «Nel testo» (`ReviewPanel.tsx:244`) mostra `item.context?.unit_content`, cioè **tutto il paragrafo** dell'unità, invece della frase contestata: occupa lo schermo e l'errore non si trova;
- nel log del frontend, 2 volte: `Measure loop restarted more than 5 times` su `/lezioni/68?panel=verifica&issue=sci_000003`.

**Cosa fare.**
- «Nel testo» mostra `issue.anchor.quote`, con un'ellissi e al massimo 80 caratteri di `prefix`/`suffix` intorno, e la citazione evidenziata. Senza ancora si usa `issue.claim`, come oggi.
- Trova il componente virtualizzato che rimisura in loop e stabilizzalo (dimensione stimata o misura una sola volta per elemento). Il warning non deve più comparire aprendo una segnalazione su telefono.

**Test:** `ReviewPanel.test.tsx`: su telefono «Nel testo» contiene la quote e non tutto il paragrafo.

## 9. [MEDIO] Dettagli su iPhone: nomi delle fonti troncati

**Problema** (`i-l68-Dettagli.png`): «Registrazione …» e «Radioterapia_2….» sono troncati mentre a destra restano più di 100 px liberi; la colonna delle icone è larga; «Argomenti» ha l'etichetta a sinistra e il valore a destra, mentre tutti gli altri campi hanno l'etichetta sopra.

**Cosa fare.** Su telefono la riga della fonte dà al nome tutto lo spazio rimasto (`flex-1 min-w-0`), con fino a 2 righe (`line-clamp-2`); durata e pagine vanno sotto il nome, in piccolo. «Argomenti» prende l'impaginazione degli altri campi.

## 10. [MEDIO] «N lezioni mancanti» senza materia

**Problema** (`d-lista-mancanti.png`, `MissingLessonsButton.tsx`): il popup elenca «Lun 2/11 09:30–11:30» senza la materia.
**Cosa fare.** Ogni riga: «MATERIA · lun 2/11 · 09:30–11:30», con il pallino del colore della materia come nel calendario.

## 11. [MINORE] Aggiornamento fermo a «99%»

**Problema.** Dopo il download restano ~30 s su «Scarico RT 4.3.6 (99%)…» (`frontend/src/components/settings/update.tsx:40`, `UpdatePopup.tsx:70`), mentre il backend verifica ed estrae il pacchetto.
**Cosa fare.** Se il backend espone già la fase (verifica/estrazione), mostrala come «Verifico il pacchetto…»; altrimenti aggiungi la fase allo stato di `/system/update` e mostrala. Il messaggio non deve restare fermo al 99% per più di 2 s.

## 12. [MINORE] Scroll orizzontale sulla pagina della lezione con finestra stretta

**Problema.** Sotto i 768 px con un puntatore che ha hover (la finestra dell'app ristretta sul Mac), la pagina della lezione scorre in orizzontale di 60 px. La colonna `absolute … w-[76px]` con `[@media(hover:hover)]` (dentro `ARTICLE`, `routes/lessons.tsx` ~390) compare anche sotto `md`, mentre il padding che le fa posto, `md:[@media(hover:hover)]:px-[76px]`, vale solo da `md` in su.
**Cosa fare.** Mostra la colonna solo con `md:[@media(hover:hover)]`, come il padding. Prova a 700 px con hover: `scrollWidth == clientWidth`.

## 13. [MINORI] Testi e rumore

Un commit unico, una riga del corpo della PR per punto:
1. **Avviso del duplicato** (`rt/api/routers/jobs.py:125`, `NewLessonDialog.tsx:1176`): «Questa registrazione è già nella lezione «<titolo, o materia se manca>» del <data leggibile, es. 1 settembre 2026>». Niente nome della cartella né data ISO.
2. **Eventi del job:** `rt/pipeline/setup.py:705` «[2/9] MACPARAKEET TRANSCRIPTION (ASR Timecoded)...» → non va negli eventi visibili (solo nel log del worker); `JobLive.tsx:28` «Stream chiuso» → togli la riga (lo stato del job c'è già).
3. **Popup Nuova lezione** (`NewLessonDialog.tsx`):
   - l'avviso «… è già nell'elenco: l'ho aggiunto una volta sola» sparisce alla modifica successiva;
   - un file di 0 byte si rifiuta subito alla scelta («File vuoto: <nome>.»), non dopo Avvia, e non si mostra «1 KB»;
   - il campo Materia è largo abbastanza per «PATOLOGIA GENERALE 2».
4. **Maiuscole delle materie:** dove la materia si mostra in forma «Capitalizzata» (es. «Pgss · 29 ott», «Qa prova notte»), le parole di sole maiuscole lunghe al massimo 4 lettere restano maiuscole («PGSS», «QA prova notte»).
5. **404 / 409 a ogni apertura di una lezione senza scaletta:** il frontend non chiede `/lessons/{id}/outline` se `phases.outline` è MISSING, e non chiede l'arricchimento se non c'è il rewrite. Niente errori in console aprendo le lezioni 74 e 79.
6. **Accessibilità:** la pagina Recall ha due `<main>` annidati: quello interno diventa `<section>` o `<div>`.
7. **Esporta → «Includi lo stato di studio»** (`LessonsView.tsx:446`, `routes/lessons.tsx:517`): la voce mostra sempre la sua casella, spuntata o no, allineata alle altre voci del menu.

---

## Prima della PR

- Python: `python -m pytest tests/ -q -n auto --dist loadfile`.
- Frontend: `cd frontend && npm run lint && npm run typecheck && npm test`.
- Se cambi un modello delle API: `python scripts/export_openapi.py` e `npm run gen:api`.
- Non toccare VERSION né CHANGELOG.
