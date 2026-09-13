# Task 64 (PILOTA) — Migra `outline_review.py` da `rich.Live` a Textual

Questo è il PRIMO di 5 task (64-68) che migrano le schermate interattive da terminale di RT dal
motore attuale (`rich.Live` + parsing manuale delle sequenze ANSI in `rt/core/keyboard.py`) a
Textual. **Fermati dopo questo task e attendi conferma esplicita in chat prima di iniziare il
Task 65**: è il file più piccolo e meno rischioso delle 4 schermate coinvolte, usato apposta per
validare l'approccio prima di investire sugli altri 3 (più grandi e più delicati). Nel progetto RT
(/Users/attilioturco/Desktop/trt), implementa direttamente questo singolo task, senza produrre un
piano preliminare — ma NON procedere oltre da solo.

## Contesto e motivazione (perché questa migrazione, non un altro fix)

Tre problemi distinti segnalati dall'utente su più cicli di test reali condividono la stessa causa
di fondo — pilotare il terminale a mano invece di usare un framework pensato per farlo:

1. **Duplicazione visiva delle card**: nonostante il fix del Task 46 (`console.clear()` prima di
   ogni `live.start()`) sia presente in ogni punto in cui un'istanza di `Live` viene fermata e
   riavviata, il bug persiste — ipotesi: `rich.Live` non azzera il proprio conteggio interno di
   righe quando la STESSA istanza viene riusata dopo `stop()`.
2. **Cancellazione di parole intere (Option+Backspace)** nei prompt: la sequenza ANSI esatta varia
   fra terminali, perché il parsing in `rt/core/keyboard.py` è scritto a mano byte per byte.
3. **Tema chiaro/scuro**: nessuno stile è mai stato centralizzato, perché non esiste un concetto di
   "tema" nell'attuale accoppiata rich+questionary.

Textual (stessa softwarehouse di Rich, costruito sopra Rich) risolve tutti e tre strutturalmente:
ridisegna l'intero schermo per frame (niente bookkeeping manuale di righe → niente duplicazione),
gestisce l'input da tastiera con un proprio sistema di keybinding (niente parsing ANSI a mano →
niente fragilità di portabilità), e ha un sistema di temi chiaro/scuro nativo (`App.dark`,
variabili CSS).

**Perimetro della migrazione (tutti e 5 i task)**: le 4 schermate che oggi usano `rich.Live` per un
carosello/loop di navigazione a tasti — `rt/pipeline/outline_review.py` (QUESTO task, 265 righe,
`Live` a riga 186), `rt/pipeline/issue_review.py` (Task 65, `Live` a riga 451), `rt/pipeline/
configure.py` (Task 66, `Live` a riga 963, sezione ruoli-fase del wizard), `rt/pipeline/
recall_session.py` (Task 67, `Live` a riga 605, pulizia domande "stale"). Il modulo `rt/core/
keyboard.py` (parsing ANSI manuale) diventa orfano una volta completati i 4 task e va rimosso nel
Task 68. **I 49 prompt lineari `questionary` (testo/scelta singola/conferma) SPARSI nel resto del
wizard NON fanno parte di questo perimetro**: restano su `questionary`, che non ha mai avuto questi
bug — migrarli sarebbe un costo aggiuntivo enorme senza un problema reale da risolvere. Se una
schermata mescola un carosello Textual con un prompt questionary intermedio (es. testo libero per
il feedback), avvolgi la chiamata a `questionary` in `App.suspend()` (context manager di Textual
che restituisce temporaneamente il controllo del terminale a un processo esterno, poi lo
recupera) invece di riscrivere quel prompt come widget Textual.

## Modifica per questo file

Riscrivi `_confirm_via_terminal` (righe 147-266) sostituendo il blocco `with raw_mode() as is_raw:
with Live(...) as live: while True: ...` (righe 185-265) con una vera Textual `App`. Comportamento
da preservare ESATTAMENTE (nessuna regressione funzionale, solo il motore di rendering/input
cambia):

- L'albero outline (oggi `rich.tree.Tree` via `build_outline_tree`, righe 36-144) — Textual può
  ospitare direttamente un `rich.tree.Tree` dentro un widget `Static`/`Tree`-like, oppure
  ricostruire l'equivalente con il widget `Tree` nativo di Textual (valuta quale richiede meno
  riscrittura logica: `build_outline_tree` calcola già tutta la struttura diff/espansione, non
  serve reinventarla, solo cambiarne il "contenitore" di rendering).
- Navigazione: UP/DOWN (anche `k`/`j`/`w`/`s`) sposta `selected_index`; RIGHT espande il macro
  selezionato; LEFT lo collassa; ENTER/SPAZIO fa toggle espandi/collassa — stesso comportamento
  di oggi (righe 218-238), ma via `App.BINDINGS`/gestori di evento Textual invece di
  `read_single_key`.
- `A`/`approva`: chiude la app e ritorna (equivalente a `return` dopo "✔ Outline approvata.").
- `M`/`modifiche`: oggi fa `live.stop()`, chiede il feedback con `questionary.text(...)` (o
  `input()` di fallback), poi richiama `run_outline_revision` e infine `console.clear(); live.
  start()` per riprendere il carosello con l'outline aggiornata (righe 243-265) — questo è
  ESATTAMENTE il punto più sospetto per il bug di duplicazione (`live.start()` chiamato una
  seconda volta sulla stessa istanza). Nella versione Textual, sostituisci `live.stop()`/
  `live.start()` con `App.suspend()` attorno alla chiamata a `questionary.text(...)` (o mantieni un
  `input()` di fallback identico se preferisci non introdurre una dipendenza da terminale
  interattivo durante il suspend), poi aggiorna i dati interni della `App` (nuovo `outline`,
  reset `selected_index`, macro espansi) e lascia che Textual ridisegni da zero — NON serve
  nessuna `console.clear()` manuale, è gestita dal framework.
- Il fallback non-TTY (righe 150-173, usato da script/test/CI dove `sys.stdin.isatty()` è False)
  resta INVARIATO: non ha nulla a che fare con `Live`/Textual, non toccarlo.

## Test

- Verifica che i test esistenti che coprono `outline_review.py` (cerca in `tests/` con `grep -rl
  outline_review tests/`) passino ancora — probabilmente mockano `read_single_key`/`Live`
  direttamente: se lo fanno, questi mock non hanno più senso con Textual e vanno riscritti per
  guidare l'interazione tramite l'API di test di Textual (`App.run_test()`, che permette di
  simulare pressioni di tasti con `pilot.press(...)` e ispezionare lo stato/i widget risultanti —
  è il modo standard per testare una `App` Textual senza un terminale reale).
- Aggiungi/adatta test che verificano: navigazione UP/DOWN cambia `selected_index`; RIGHT/LEFT
  espande/collassa; ENTER fa il toggle; A approva e termina; M raccoglie un feedback e richiama
  `run_outline_revision`, poi torna al carosello con l'outline aggiornata SENZA duplicare
  l'output (questo è il test che conta di più: prova a ripetere il ciclo M→feedback→outline
  aggiornata più volte in sequenza nello stesso test e verifica che lo stato finale sia coerente,
  non un proxy indiretto della vecchia asserzione su `console.clear()`).
- Il fallback non-TTY deve restare coperto dagli stessi test di oggi, senza modifiche.

Esegui `python3 -m pytest tests/ -q` e correggi finché l'intera suite passa.

## Vincoli

- Aggiungi `textual` a `requirements.txt` (o dove sono dichiarate le dipendenze del progetto —
  verifica il file esatto, es. `pyproject.toml`/`requirements.txt`), pinnando una versione stabile
  recente.
- Verifica il bug di portabilità ricorrente sulle annotazioni `typing` per qualunque riga toccata
  (vedi `.agents/00-README.md`).
- Non toccare `rt/core/keyboard.py` in questo task (verrà rimosso solo nel Task 68, dopo che
  TUTTI e 4 gli usi sono stati migrati) — `issue_review.py`, `configure.py` e `recall_session.py`
  lo usano ancora finché i Task 65-67 non sono completati.
- Non introdurre CSS/temi Textual completi in questo task: usa lo stile di default di Textual
  (già ragionevolmente leggibile su sfondo scuro e chiaro) — la palette/tema personalizzato, se
  servirà, sarà oggetto di un task a parte dopo che tutte e 4 le schermate sono migrate.

## Verifica finale

1. `python3 -m pytest tests/ -q`.
2. Lancia `rt run` su una lezione mock fino alla fase di outline review, verifica manualmente:
   nessuna duplicazione visiva a schermo dopo un ciclo di modifica (M → feedback → outline
   rigenerata → ritorno al carosello), navigazione fluida con frecce, approvazione funzionante.
3. Riferisci in chat, con la stessa onestà con cui vengono segnalati problemi negli altri task,
   SE il bug di duplicazione è davvero sparito con Textual o se osservi ancora qualcosa di simile
   — è l'ipotesi centrale di questa intera migrazione, va confermata o smentita con questo pilota
   prima di investire sugli altri 3 file.
