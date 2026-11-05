# Piano 4.3.8b3 (correzioni di Attilio sulla beta 2)

Base: `claude/rt-4.3.8` (= v4.3.8b2). Branch di lavoro: `agy/4.3.8b3-fix`.
Una voce per commit. **Non modificare il testo delle pagine `docs/guida/*.md`**: le riscrive Attilio. Puoi solo aggiungere file nuovi richiesti qui sotto.

## 1. Guida nel menu «Aiuto» della barra dei menu (Mac e Windows)

- In `rt/window.py` `_menu()`: togli «Guida di RT» dal menu RT e aggiungi un menu di primo livello **«Aiuto»** (ultimo a destra, dopo Vista).
- Contenuto di «Aiuto»:
  - prima voce «Cerca nella guida…» → apre `/guida?cerca=1` con il campo di ricerca già a fuoco (in `routes/guide.tsx` leggi il parametro e fai `focus()`);
  - poi un sottomenu per ogni pagina della guida (titolo `# …` della pagina), con dentro una voce per ogni sezione `## …`; cliccando apre `/guida/<pagina>#<ancora>` (stessa `slugify` del frontend: NFD, senza accenti, minuscolo, non alfanumerici → `-`).
  - L'elenco si costruisce all'avvio leggendo i file markdown della guida (ordine dal file della voce 2). Verifica che `docs/guida/` sia dentro il .dmg e l'.exe; se non c'è, aggiungilo al packaging (`packaging/`).
- macOS: imposta quel menu come Help menu dell'app (`NSApplication.sharedApplication().setHelpMenu_(...)` nel punto dove oggi c'è `_macos_menu`), così macOS aggiunge da solo il campo «Cerca» in cima (come le altre app) e ⌘? lo apre. Il titolo deve restare «Aiuto».
- Windows: lo stesso menu «Aiuto» nella barra della finestra (senza campo di ricerca nativo: c'è «Cerca nella guida…»).
- Test: un test Python che costruisce il menu e controlla «Aiuto» con «Cerca nella guida…» e una voce per pagina; la smoke macOS (`rt/_window_smoke.py`) controlla che il menu «Aiuto» esista.

## 2. Guida modificabile da Attilio, con immagini

- **Un solo file per ordine e titoli delle pagine**: `docs/guida/indice.yml`, lista di `file:` (senza `.md`) nell'ordine voluto. Lo usano: il frontend (`lib/guideDocs.ts`, al posto di `PAGE_ORDER`), `scripts/build_docs_site.py` (genera la `nav` di mkdocs al posto di quella scritta a mano in `mkdocs.yml`) e il menu «Aiuto» della voce 1. Una pagina `.md` non elencata non compare (niente più pagine «in coda»). Test che fallisce se `indice.yml` cita un file che non esiste.
- **Immagini**: cartella `docs/guida/immagini/`. Sintassi markdown standard `![testo alternativo](immagini/nome.png)` su una riga a sé.
  - `GuideMarkdown.tsx`: rende `<img>` (larghezza max 100%, bordo leggero, `loading="lazy"`, `alt` dal testo), con le immagini incluse a build time da Vite (`import.meta.glob('../../../docs/guida/immagini/*', { eager: true, query: '?url', import: 'default' })`), così funzionano offline. Immagine mancante: mostra il testo alternativo in corsivo, niente errore.
  - Sito: `build_docs_site.py` copia anche `immagini/`.
  - Formati: png, jpg, webp, gif. Test vitest con un'immagine finta.
- Aggiungi `docs/guida/COME-MODIFICARE.md` (non è una pagina della guida, non va in `indice.yml`): come aggiungere/rinominare/riordinare pagine (`indice.yml`), sezioni (`## Titolo`, l'ancora nasce dal titolo), immagini (cartella + sintassi), riquadri `> [!NOTE]` / `> [!TIP]` / `> [!WARNING]`, link fra pagine `[testo](/guida/pagina#ancora)`. Massimo una pagina, per una persona non tecnica, con un esempio per ogni cosa.

## 3. Bottone «Indietro» della guida bloccato

- In `/guida` «Indietro» non esce dalla guida (resta lì, soprattutto quando la guida è aperta dal menu con `load_url`). Correggi: torna alla pagina da cui si è entrati; se non c'è (aperta dal menu, dalle Impostazioni o come prima pagina), va a `/` (Lezioni). Navigando fra pagine e ancore della guida «Indietro» non deve tornare alla pagina precedente della guida ma uscire. Test e2e o vitest per i due casi.

## 4. Niente bottone «?» dentro l'app: guida solo da Impostazioni e dal menu

- Togli il «?» da `PageHeader` (e la prop `help`), e i piccoli `HelpLink` contestuali nelle finestre (`HelpLink.tsx` e i suoi usi); elimina il componente se resta inutilizzato.
- F1 resta (apre `/guida`); ⌘? su Mac lo gestisce il menu «Aiuto».
- In Impostazioni aggiungi la sezione **«Guida»** (in fondo all'elenco, vicino a Informazioni): cliccandola si apre direttamente la pagina `/guida` (non un pannello con dentro un bottone).
- Aggiorna i test che cercano il «?».

## 5. Togli «Genera domande» dal ripasso vuoto

- `components/recall/LightweightSession.tsx`, blocco «Una lezione sola, zero da porre: Genera domande» (link bianco a `/lezioni/<id>?panel=domande`): eliminalo. Resta il bottone «Genera» con il numero e i tipi, che funziona. Aggiorna `LightweightSession.test.tsx` (il test 4.2.2b4 F3 deve verificare che il link non c'è più).

## 6. Stati di studio personalizzati

Oggi gli stati sono fissi (`da-imparare`, `in-apprendimento`, `appreso`, `ignorata`: `rt/services/study_progress_service.py`, `frontend/src/components/study/studyProgress.ts`).

- **Impostazioni**: nella sezione esistente più vicina allo studio (preferenze di studio; se non c'è, crea «Studio») aggiungi «Stati delle unità»: un unico elenco ordinabile (trascina o frecce su/giù) con i 4 stati di default e quelli personalizzati mescolati; i default non si possono eliminare né modificare (nome, colore, icona), ma si possono spostare; «Aggiungi stato» aggiunge in fondo.
- Uno stato personalizzato ha: nome (max 24 caratteri), colore (6-8 colori predefiniti a scelta, compatibili con tema chiaro e scuro) e icona da un set base di ~10 icone lucide (es. Circle, Star, Flag, Bookmark, Flame, Eye, HelpCircle, Repeat, Clock, AlertTriangle). Si possono rinominare, cambiare, riordinare, eliminare.
- **Ciclo** (tasto S, clic sull'icona dell'unità): segue l'ordine dell'elenco nelle Impostazioni e ricomincia dal primo. Ordine di partenza: `da-imparare → in-apprendimento → appreso → ignorata`, i nuovi stati in fondo. Le unità nuove partono sempre da `da-imparare`, qualunque sia l'ordine.
- **Dati**: impostazione salvata nei settings (lista `{id, nome, colore, icona}`; `id` tipo `c1`, `c2`… stabile, entra nella colonna `status` String(16)) più l'ordine completo (lista di id, default compresi; se manca un default lo si rimette nella posizione di partenza). Il backend accetta come stato i 4 di default più gli `id` presenti nei settings; `Literal` → validazione dinamica.
  - Uno stato personalizzato conta come «in apprendimento» per i progressi, il calendario e `initialStudyUnit` (non come appreso).
  - Eliminare uno stato in uso: le unità con quello stato tornano a `in-apprendimento` (chiedi conferma dicendo quante unità sono coinvolte).
  - Export/import di lezioni e collezione: uno stato sconosciuto all'arrivo diventa `in-apprendimento`.
- Ovunque si mostrano icona/etichetta di stato (barra della lettura veloce, barra zen, elenco unità, tooltip come «Da imparare» dell'allegato) usa una sola funzione che risolve default + personalizzati.
- Test: backend (stato valido/invalido, eliminazione con unità in uso, import con stato sconosciuto) e vitest (ciclo con 2 stati personalizzati messi fra i default, riordino, impostazioni aggiungi/elimina, default non eliminabili).

## 7. Player audio a scomparsa in Studio

- In Studio (anche nella barra della lettura veloce e in zen, se c'è spazio) un bottone con icona cuffie apre/chiude un player compatto: riusa `components/lesson/AudioPlayer.tsx` e `useLessonAudio` (stesso audio, stessa posizione, stessa velocità di `lib/playbackRate`, stessi skip ±5 s della pagina lezioni). Lezione senza audio: niente bottone.
- Quando il player è aperto, ← e → spostano l'audio di 5 s e **non** cambiano unità; chiuso il player, le frecce tornano a cambiare unità come oggi. Lo spazio non cambia comportamento.
- Aperto/chiuso si ricorda per sessione (non serve salvarlo).
- Test vitest: frecce con player aperto → seek, nessun cambio unità; chiuso → cambio unità.

## 8. Valutazione delle risposte (mirate e vaste): attinenza e domanda di approfondimento

- **Tre parametri** per mirate e vaste, in percentuale: **Correttezza**, **Completezza**, **Attinenza**. Nell'interfaccia stanno in una riga a parte (tre etichette) sopra il commento, non più dentro il testo. Salvali come campi della risposta (`RecallAnswer`: `correttezza`, `completezza`, `attinenza`, opzionali), non solo nella stringa `evaluation`; le vecchie risposte senza campi si mostrano come oggi.
- **Nuovo criterio** (prompt `RECALL_EVAL_MIRATA_SYSTEM_PROMPT` e `RECALL_EVAL_VASTA_SYSTEM_PROMPT` in `rt/llm/prompts.py`): l'LLM è un professore. Correttezza e completezza si valutano sulla correttezza generale della risposta (anche con conoscenze proprie, non solo l'unità). Attinenza = quanto la risposta corrisponde a ciò che c'è nell'unità (una risposta può essere corretta ma non attinente, perché l'unità tratta l'argomento da un'altra prospettiva o in modo diverso). L'esito (`outcome`) dipende da correttezza e completezza, non dall'attinenza. Per le vaste resta il confronto con la scaletta ideale dentro il commento.
- **Domanda di approfondimento** (al massimo una): il risultato ha un campo opzionale `domanda_followup`. Il professore la propone solo se la risposta va nella direzione giusta ma serve chiarire o completare (parzialmente corretta, corretta ma non attinente, corretta e attinente ma incompleta); mai se è sbagliata o «Non lo so», mai se è già completa.
  - Flusso: domanda → risposta → valutazione 1 (+ eventuale domanda di approfondimento) → risposta 2 (stessi controlli della risposta: testo, voce, «Non lo so») → valutazione 2 → fine. La valutazione 2 non può proporre un'altra domanda.
  - Contesto della valutazione 2: domanda, risposta 1, valutazione 1 (parametri e commento), domanda di approfondimento, risposta 2, più lo stesso riferimento (unità o scaletta).
  - L'esito che vale per il ripasso è quello della valutazione 2 (se c'è), altrimenti quello della 1. Salva tutto nella stessa `RecallAnswer` (`followup_question`, `followup_answer`, `followup_evaluation`, parametri della 2); voti 👍/👎 e ⚡ si applicano alla valutazione finale.
  - L'utente può saltare l'approfondimento («Salta»): vale l'esito della valutazione 1.
  - Le domande personalizzate (`recall_special`) e i quiz non cambiano.
- Mock (`force_mock`): valutazione 1 con domanda di approfondimento fissa quando la risposta non è «Non lo so», così e2e e test possono provare il flusso.
- Test: backend (parametri salvati, followup proposto/non proposto, contesto della 2 contiene domanda+risposta 1, esito finale = 2, «Salta»), vitest (riga dei tre parametri, flusso approfondimento), un e2e sul ripasso con mock.

## Prima della PR

- `python -m pytest tests/ -q -n auto --dist loadfile -p no:cacheprovider`
- `cd frontend && npm run -s typecheck && npm run -s lint && npx vitest run`
- e2e toccati: `npx playwright test guide study recall` (o gli spec che hai modificato).
- Ogni file nuovo nella radice del repo va in `.gitattributes` con `export-ignore` (altrimenti il controllo del pacchetto di rilascio fallisce).
