# Task 69 — In fase di build, sposta (non copia) la cartella lezione in `lessons_root`

Indipendente dagli altri task attivi. Nel progetto RT (/Users/attilioturco/Desktop/trt),
implementa direttamente, senza produrre un piano preliminare.

## Contesto

Test reale sul MacBook Air: l'utente configura `lessons_root` (es.
`/Users/attilioturco/Desktop/Medicinali/ANNO 3/S1/_RT Lezioni`) aspettandosi che le lezioni
finiscano lì, ma la cartella lezione viene sempre creata accanto al file audio sorgente (o nella
cwd) e **non viene mai spostata automaticamente** in `lessons_root` — verificato leggendo il
codice, non un fix precedente rotto: `rt/pipeline/setup.py::run_setup` (righe 394-412) determina
la cartella di destinazione da `dest_dir`/`audio_dir`/cwd, MAI da `lessons_root`; `rt/pipeline/
build.py` non contiene alcun riferimento a `lessons_root` né alcuna `shutil.move`/`shutil.copy`.
`lessons_root` oggi è usato SOLO da `rt/core/lesson_index.py::scan_lessons` per indicizzare le
lezioni ai fini di `/list`/`/recall` via Telegram (nessun'altra funzione lo legge). L'utente ha
verificato con `rt build --force` su una lezione reale: la cartella resta dov'era, non si sposta.

**Comportamento richiesto**: la cartella lezione deve continuare a essere CREATA accanto al file
audio sorgente (comportamento attuale di `run_setup`, corretto, non toccarlo) — ma alla fine della
fase di **build**, se `lessons_root` è configurato in `general.yaml`, la cartella deve essere
**spostata** (mai copiata: non deve restare un duplicato nella posizione originale) dentro
`lessons_root`.

## Punto di innesto: `rt/pipeline/build.py::run_build`

C'è già un precedente diretto da riusare come modello: il blocco `rename_folder` (righe 366-385)
sposta già la cartella con `os.rename` (nella STESSA directory padre, cambiando solo il nome) e
aggiorna `current_dir`/`yaml_path`/`named_filepath` di conseguenza, gestendo la collisione (stampa
un avviso e NON sovrascrive se la destinazione esiste già). Aggiungi un blocco analogo SUBITO DOPO
(quindi `current_dir` riflette già l'eventuale rename), PRIMA del passo 7 (registrazione
fingerprint, riga 387-396, che usa `current_dir`):

- Leggi `lessons_root = load_config().telegram.lessons_root` (verifica l'import esatto, es.
  `from rt.core.config import load_config`, già usato altrove nel progetto con questo pattern).
- Se `lessons_root` è vuoto/`None`, non fare nulla (comportamento identico a oggi).
- Se `lessons_root` è configurato:
  - Calcola `dest_path = os.path.join(lessons_root, os.path.basename(current_dir))`.
  - Se `os.path.abspath(current_dir)` è GIÀ dentro `os.path.abspath(lessons_root)` (stesso
    genitore), non fare nulla (evita spostamenti inutili/loop su rebuild ripetute di una lezione
    già in `lessons_root`).
  - Se `dest_path` esiste già (ed è diverso da `current_dir`): stampa un avviso analogo a quello
    del blocco rename (NON sovrascrivere, NON spostare, la lezione resta dov'è) — stessa filosofia
    del controllo di collisione già presente per il rename.
  - Altrimenti: crea `lessons_root` se non esiste (`os.makedirs(lessons_root, exist_ok=True)`),
    poi `shutil.move(current_dir, dest_path)` (usa `shutil.move`, non `os.rename`: deve funzionare
    anche se `lessons_root` è su un filesystem/volume diverso, cosa che `os.rename` non garantisce).
    Aggiorna `current_dir = dest_path` e ricalcola `yaml_path`/`named_filepath` come fa già il
    blocco rename. Stampa una riga di conferma, es. `📦 Cartella spostata in: '{dest_path}'`.

## Punti da verificare con attenzione (non assumere, controllare nel codice)

1. **Notifica Telegram di build completata**: `cmd_build`/`cmd_run` in `rt/cli.py` (righe ~343-352
   e ~573-587) calcolano `final_dir = res.get("lesson_dir") or args.lesson_dir` DOPO la chiamata a
   `run_build`, e lo passano a `notify_build_completed`. Verifica che il dizionario ritornato da
   `run_build` (chiave `"lesson_dir"`, riga ~425) rifletta correttamente `current_dir` DOPO lo
   spostamento (dovrebbe già funzionare automaticamente se implementi il punto sopra
   correttamente, dato che il return finale usa `current_dir` — ma verificalo esplicitamente con
   un test, non fidarti che "dovrebbe funzionare").
2. **Percorso già "corrotto" da un salvataggio precedente**: `rt/telegram/last_lesson.py` traccia
   l'ultima lezione con build completata per topic. Verifica che venga aggiornato con il percorso
   POST-spostamento (dovrebbe, se riceve `final_dir` già corretto dal punto 1).
3. **Caso SKIP (idempotenza)**: se la fase build è già `VALID` e non è forzata, `run_build`
   ritorna PRIMA di qualunque logica (righe 306-320, "SKIP"), quindi una lezione già completata ma
   MAI spostata (es. costruita prima che questa funzionalità esistesse) non verrebbe spostata da
   un semplice `rt build` senza `--force`. Valuta se applicare il controllo "sposta se non è già
   in lessons_root" ANCHE nel percorso SKIP (prima di ritornare), dato che è un'operazione
   filesystem economica e idempotente — se lo fai, applica la stessa identica logica di
   collisione/verifica del blocco principale, non duplicarla: estraila in una funzione helper
   privata (es. `_move_to_lessons_root_if_configured(current_dir) -> str`) richiamata da ENTRAMBI
   i punti di ritorno.
4. **Riferimenti assoluti interni**: verifica se `info.yaml`, `manifest.json` o altri file di stato
   dentro la cartella lezione memorizzano il percorso ASSOLUTO della cartella stessa (non il
   percorso del file audio originale, che resta altrove e non viene toccato — quello è corretto
   che rimanga invariato). Se esiste un simile self-reference, aggiornalo dopo lo spostamento,
   altrimenti diventerebbe stale.
5. **Nessuno stato Telegram pendente riferisce ancora il percorso vecchio**: la fase di build
   avviene PRIMA che l'utente possa avviare `/recall`/`/list` su questa lezione (nessuna sessione
   Telegram attiva per una lezione appena buildata), quindi non dovrebbe esserci stato pendente da
   invalidare — ma verifica che `notify_build_completed` non registri già qualcosa in
   `rt/telegram/registry.py` con il percorso vecchio PRIMA che tu applichi lo spostamento; se lo fa
   (leggi `notify_build_completed` per certezza), sposta la cartella PRIMA di chiamare quella
   funzione (in `cli.py`, non dentro `run_build`, se necessario) invece che dopo.

## Test

- Test che verifica che, con `lessons_root` configurato e diverso dalla directory corrente della
  lezione, dopo `run_build` la cartella si trovi in `lessons_root/<nome_cartella>` e NON più nella
  posizione originale (verifica `os.path.isdir` su entrambi i percorsi).
- Test che verifica che, SENZA `lessons_root` configurato (`None`/vuoto), il comportamento resti
  identico a oggi (nessuno spostamento).
- Test che verifica la combinazione `rename_folder=True` + `lessons_root` configurato: la cartella
  finale deve avere il nome RINOMINATO e trovarsi dentro `lessons_root` (entrambe le operazioni
  applicate in sequenza corretta).
- Test di collisione: se in `lessons_root` esiste già una cartella con lo stesso nome finale,
  verifica che NON venga sovrascritta/spostata (la lezione resta dov'è, con un avviso stampato).
- Test che verifica che una lezione GIÀ dentro `lessons_root` non venga ulteriormente "spostata su
  se stessa" da una rebuild successiva (`rt build --force` ripetuto).
- Test che verifica che il dizionario ritornato da `run_build` (`"lesson_dir"`) rifletta il
  percorso POST-spostamento.

Esegui `python3 -m pytest tests/ -q` e correggi finché l'intera suite passa.

## Vincoli

Verifica il bug di portabilità ricorrente sulle annotazioni `typing` per qualunque riga toccata
(vedi `.agents/00-README.md`).

Non toccare `run_setup`/la logica di creazione iniziale della cartella (righe 394-412 di
`setup.py`): deve continuare a creare la cartella accanto all'audio sorgente, invariato — solo la
fase di BUILD sposta la cartella alla fine.

## Verifica finale

1. `python3 -m pytest tests/ -q`.
2. Test manuale end-to-end: `rt run <audio>.m4a --mock` con `lessons_root` configurato diverso
   dalla directory dell'audio, verifica che al termine la cartella lezione si trovi in
   `lessons_root`, non accanto all'audio. Poi `rt build --force <percorso_in_lessons_root>` e
   verifica che non si sposti ulteriormente né si duplichi.
