# Piano 4.3.8b3: guida, aiuto, primo avvio, pronto al lancio (agy)

Base: `claude/rt-4.3.8` (= 4.3.8b1). Branch: `agy/4.3.8b3`. Un commit per voce: «4.3.8b3: <n>. <titolo>».
Regole generali: testi in italiano semplice per studenti; nessun nuovo servizio esterno; nessuna dipendenza Python nuova nell'app (per il sito vale solo nella CI); niente monetizzazione (RT Cloud resta nascosto).

## 1. Guida in Markdown (`docs/guida/`)

Pagine brevi, una per argomento, con titoli `##` usati come ancore:
`index.md` (cos'è RT, primi passi), `installazione.md` (Mac: «Apri comunque» in Impostazioni di Sistema → Privacy e sicurezza, e in alternativa `xattr -dr com.apple.quarantine /Applications/RT.app`; Windows: SmartScreen «Ulteriori informazioni → Esegui comunque»), `chiavi-e-costi.md`, `nuova-lezione.md`, `fonti.md` (tipi di fonte e affidabilità alta/normale/bassa), `verifica.md`, `studio.md` (strumenti E/G/V/C con selezione, lettura veloce, zen, stato S, scorciatoie), `ripasso.md`, `calendario.md`, `file-di-rt.md` (.rt, .rtdb, .rtcal), `iphone-e-agenti.md` (accesso da iPhone, API di sola lettura, prompt per gli agenti), `backup-e-aggiornamenti.md` (voce 5), `problemi.md` (domande frequenti, dove sono i registri), `privacy.md` (lascia solo il titolo e «Testo in arrivo»: lo scrive Claude).
Descrivi solo funzioni che esistono nel codice di questa branch; dove serve controlla i testi reali dell'interfaccia.

## 2. Guida dentro l'app, offline, con ricerca

- Rotta `/guida` e `/guida/:pagina`: il frontend include i file di `docs/guida/*.md` a build time (`import.meta.glob(..., { query: '?raw', eager: true })`) e li mostra con il renderer Markdown già usato nell'app. Nessuna rete.
- Barra di ricerca in cima: ricerca semplice su titoli e paragrafi (minuscole, senza accenti), risultati con link all'ancora.
- Collegamenti: pulsante «?» nell'intestazione (tooltip «Guida · F1»), tasto F1 e ⌘? / Ctrl+? aprono `/guida`. Nei punti complessi un piccolo «?» porta all'ancora giusta: Nuova lezione, Dettagli → Fonti (affidabilità), Verifica, Impostazioni → Accesso da iPhone, Esporta/Importa.
- Menu dell'app desktop (`rt/window.py`, `_menu`): nuova voce «Guida di RT» che apre `/guida` nella finestra. Se pywebview permette la scorciatoia nel menu, usa ⌘?; altrimenti basta la scorciatoia gestita dal frontend.
- Test: vitest per rotta, ricerca e F1; test Python per la voce di menu.

## 3. Sito pubblico su GitHub Pages

- Workflow `.github/workflows/pages.yml`, solo su push a `main` che toccano `docs/guida/**` o `docs/sito/**`, più `workflow_dispatch`. Usa MkDocs (installato solo nel job) con tema semplice, lingua italiana, ricerca integrata, sorgente `docs/guida/`.
- Landing `docs/sito/index.md` (o la home di MkDocs): cosa fa RT in 5 righe, schermate (lascia segnaposto `docs/sito/img/` vuoto con README), link a Scarica (ultima release), Guida, Privacy, codice su GitHub, licenza AGPL, e «Sostieni RT» solo se `DONAZIONI_URL` (vedi voce 7) non è vuoto.
- Non attivare Pages dalle impostazioni del repo: lo fa Attilio.

## 4. Primo avvio con lezione di esempio e stima dei costi

- Quando non c'è nessuna lezione, la pagina Lezioni mostra un riquadro di benvenuto: «Prova con una lezione di esempio» (importa un `.rt` incluso nell'app, già elaborato: costo zero) e «Crea la tua prima lezione».
- La lezione di esempio: crea `rt/assets/esempio/lezione-esempio.rt` con uno script `scripts/make_sample_lesson.py` che parte dai dati di prova già nei test (golden) e produce trascrizione, rielaborato, verifica e qualche domanda. Contenuto inventato, nessun audio vero (o pochi secondi di silenzio), sotto 1 MB. Materia «ESEMPIO»; si può cancellare come le altre.
- Stima dei costi: funzione in `rt/llm/pricing.py` che, dati i modelli configurati, stima il costo di una lezione di 90 minuti con token tipici (costanti documentate nel codice). Mostrala nel benvenuto e in Impostazioni → Modelli come «circa X € a lezione (stima)». Se un modello non ha prezzo noto, scrivi «stima non disponibile».
- Il riquadro sparisce dopo la prima lezione vera o con «Non mostrare più».
- Test: API della stima, importazione dell'esempio, riquadro in vitest.

## 5. Backup leggero prima degli aggiornamenti, ultimi 5, ripristino

- Prima di installare un aggiornamento (app Mac/Windows in `rt/core/app_update.py` e `rt -u` in `rt/core/version.py`) crea un backup leggero: database SQLite (copia consistente, come fa già `backup_service`) + i file di testo delle lezioni (md, json, yaml). Niente audio, immagini, PDF né media.
- Cartella: `<cartella dati>/backups/prima-aggiornamento/rt-<versione-attuale>-<data-ora>.zip`. Tieni solo gli ultimi 5 (cancella i più vecchi dopo un backup riuscito).
- Se il backup fallisce, l'aggiornamento non parte e l'utente vede il motivo.
- Ripristino: voce di menu desktop «Ripristina dati prima di un aggiornamento…» e comando `rt restore --pre-update [nome]`. Mostra la lista (versione, data), chiede conferma con «Annulla» predefinito, mette da parte i dati attuali come fa già l'import della collezione e ripristina database e testi. I media restano quelli attuali.
- La guida spiega che il ripristino riporta i dati, non il programma: per tornare alla versione precedente si reinstalla l'installer dalla pagina delle release.
- Test: creazione, rotazione a 5, fallimento che blocca l'aggiornamento, ripristino.

## 6. Messaggio dopo «Genera le domande» su un'unità con segnalazioni aperte

Oggi, se l'unità ha segnalazioni aperte, le domande vengono generate ma restano bloccate e non succede niente di visibile. Mostra: «Domande pronte: compariranno quando avrai deciso le segnalazioni della Verifica», con link alla Verifica dell'unità. Test vitest.

## 7. Donazioni (spente finché non c'è il link)

Costante `DONAZIONI_URL = ""` in un solo posto (backend, esposta in `/system/info`). Se non è vuota: link «Sostieni RT» in Informazioni su RT e nella landing. Se è vuota non compare nulla. Test per entrambi i casi.

## Prima della PR

- Python: `python -m pytest tests/ -q -n auto --dist loadfile`.
- Frontend: `cd frontend && npm run lint && npm run typecheck && npm test`.
- e2e se tocchi la pagina Lezioni o lo Studio: `npx playwright test` sulle spec interessate.
- Se cambi un modello delle API: `python scripts/export_openapi.py` e `npm run gen:api`.
- Non toccare VERSION né CHANGELOG.
