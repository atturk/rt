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

- **Impostazioni**: nella sezione esistente più vicina allo studio (preferenze di studio; se non c'è, crea «Studio») aggiungi «Stati delle unità»: mostra i 4 stati di default (icona, colore, nome; non modificabili né eliminabili) e sotto gli stati personalizzati con «Aggiungi stato».
- Uno stato personalizzato ha: nome (max 24 caratteri), colore (6-8 colori predefiniti a scelta, compatibili con tema chiaro e scuro) e icona da un set base di ~10 icone lucide (es. Circle, Star, Flag, Bookmark, Flame, Eye, HelpCircle, Repeat, Clock, AlertTriangle). Si possono rinominare, cambiare, riordinare, eliminare.
- **Ciclo** (tasto S, clic sull'icona dell'unità): `da-imparare → in-apprendimento → [personalizzati nell'ordine] → appreso → ignorata → da-imparare`.
- **Dati**: impostazione salvata nei settings (lista `{id, nome, colore, icona}`; `id` tipo `c1`, `c2`… stabile, entra nella colonna `status` String(16)). Il backend accetta come stato i 4 di default più gli `id` presenti nei settings; `Literal` → validazione dinamica.
  - Uno stato personalizzato conta come «in apprendimento» per i progressi, il calendario e `initialStudyUnit` (non come appreso).
  - Eliminare uno stato in uso: le unità con quello stato tornano a `in-apprendimento` (chiedi conferma dicendo quante unità sono coinvolte).
  - Export/import di lezioni e collezione: uno stato sconosciuto all'arrivo diventa `in-apprendimento`.
- Ovunque si mostrano icona/etichetta di stato (barra della lettura veloce, barra zen, elenco unità, tooltip come «Da imparare» dell'allegato) usa una sola funzione che risolve default + personalizzati.
- Test: backend (stato valido/invalido, eliminazione con unità in uso, import con stato sconosciuto) e vitest (ciclo con 2 stati personalizzati, impostazioni aggiungi/elimina).

## Prima della PR

- `python -m pytest tests/ -q -n auto --dist loadfile -p no:cacheprovider`
- `cd frontend && npm run -s typecheck && npm run -s lint && npx vitest run`
- e2e toccati: `npx playwright test guide study recall` (o gli spec che hai modificato).
- Ogni file nuovo nella radice del repo va in `.gitattributes` con `export-ignore` (altrimenti il controllo del pacchetto di rilascio fallisce).
