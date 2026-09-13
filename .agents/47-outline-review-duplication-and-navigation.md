# Task 47 — Outline review: le card si duplicano in navigazione (grave) + naviga con frecce sinistra/destra per collassare/espandere

Indipendente dagli altri task attivi. Nel progetto RT (/Users/attilioturco/Desktop/trt),
implementa direttamente, senza produrre un piano preliminare.

## Contesto

Test reale su una lezione completa: durante la schermata "📋 OUTLINE REVIEW"
(`rt/pipeline/outline_review.py`), muoversi tra le macro-unità (UP/DOWN), con le frecce
sinistra/destra, o espandere/collassare con Spazio produce **una nuova card stampata ogni
volta senza cancellare le precedenti** — il log incollato dall'utente mostra decine di pannelli
`╭─── 📋 OUTLINE REVIEW ───╮` impilati uno sotto l'altro invece che un singolo pannello che si
aggiorna in place. Descritto dall'utente come "grave errore di navigazione" e riprodotto
specificamente su UP/DOWN, navigazione orizzontale, ed espandi/collassa — quindi succede a ogni
singolo tasto premuto nel loop, non solo in un caso isolato.

**Causa**: `_confirm_via_terminal` (`rt/pipeline/outline_review.py`, righe 147-252) NON usa
`rich.Live` (a differenza di `issue_review.py` e del carosello di `rt/pipeline/configure.py`,
Task 43) — usa invece un pattern manuale in loop (righe 206-213):
```python
panel = Panel(tree, title="📋 OUTLINE REVIEW", ...)
console.clear()
console.print(panel)
```
Se `console.clear()` non si comporta come atteso in questo contesto (per qualunque motivo — va
verificato empiricamente in un vero terminale interattivo, non assunto a priori), il risultato è
esattamente l'accumulo di pannelli osservato. Indipendentemente dalla causa esatta di
`console.clear()`, il fix strutturalmente più robusto e coerente col resto del codebase è
migrare questo loop allo stesso pattern `rich.Live` già usato con successo in
`issue_review.py::run_interactive_review` e nel carosello di `configure.py` (Task 43) — un
singolo oggetto `Live` che si aggiorna con `live.update(panel, refresh=True)` invece di
`clear()+print()` ripetuti, eliminando la classe di bug indipendentemente dalla causa
sottostante.

**Richiesta aggiuntiva dell'utente sulla navigazione**: oggi Spazio/Invio è l'UNICO modo per
espandere/collassare la macro-unità selezionata (riga 224: `elif key in ("", " ") or choice in
("enter", "\r", "\n"):`). L'utente vuole che LA FRECCIA DESTRA espanda (se la macro selezionata è
collassata) e LA FRECCIA SINISTRA collassi (se è espansa) — IN AGGIUNTA al toggle esistente con
Spazio/Invio, non in sua sostituzione. Verifica cosa fanno oggi LEFT/RIGHT in questo loop (non
sembrano gestiti affatto nel codice attuale — righe 218-223 gestiscono solo UP/DOWN — quindi
premere le frecce orizzontali oggi probabilmente non fa nulla di specifico, cade nel ramo finale
implicito che non gestisce quel tasto, ma comunque ridisegna la card ad ogni iterazione del
loop, il che è coerente con la duplicazione osservata "anche con le frecce").

## Modifica

### 1. Migra a `rich.Live`

Sostituisci il loop `while True: ... console.clear(); console.print(panel); key =
read_single_key(...)` con lo stesso schema di `issue_review.py`:
```python
with raw_mode() as is_raw:
    with Live(console=console, auto_refresh=False, transient=False) as live:
        while True:
            ...
            panel = Panel(...)
            live.update(panel, refresh=True)
            key = read_single_key(already_raw=is_raw)
            ...
```
Il blocco `with raw_mode() as is_raw:` esiste già (riga 185) — annidaci dentro un `with Live(...)
as live:` e sostituisci `console.clear(); console.print(panel)` con `live.update(panel,
refresh=True)`. Import necessario: `from rich.live import Live` (verifica se già importato in
cima al file).

Attenzione al ramo "M=Modifica" (righe 234-251), che chiama `questionary.text(...).ask()` o
`input(...)` per chiedere il feedback di revisione — sono prompt interattivi normali che
scrivono sullo schermo mentre `Live` è attivo: fai `live.stop()` prima di quel prompt e
`live.start()` dopo (stesso pattern usato altrove), altrimenti il prompt si sovrapporrebbe al
rendering di `Live`. **Applica anche qui la stessa precauzione del Task 46** (se presente):
valuta se serve un `console.clear()` prima di `live.start()` dopo il prompt di feedback, per lo
stesso motivo architetturale descritto nel Task 46 (evitare che `Live` riprenda da una posizione
del cursore sporca dopo output normale stampato mentre era fermo).

### 2. Naviga con LEFT/RIGHT oltre a Spazio/Invio

Nel blocco di gestione tasti (righe 218-230 circa), aggiungi:
```python
elif key == "RIGHT":
    if all_macros:
        target_id = all_macros[selected_index]
        expanded_macros.add(target_id)  # espande, idempotente se già espansa
elif key == "LEFT":
    if all_macros:
        target_id = all_macros[selected_index]
        expanded_macros.discard(target_id)  # collassa, idempotente se già collassata
```
Mantieni invariato il toggle esistente con Spazio/Invio (righe 224-230) — deve continuare a
funzionare esattamente come oggi, in aggiunta alle frecce, non al posto loro.

## Test

- Test che verifica che il loop usi `Live`/`live.update` invece di `console.clear()`+
  `console.print()` ripetuti (es. mockando `Live` e verificando che `update` venga chiamato,
  oppure verificando che `console.clear` non venga più chiamato nel loop principale — solo,
  eventualmente, attorno al prompt di feedback).
- Test su LEFT/RIGHT: con una macro-unità collassata selezionata, simula `key == "RIGHT"` e
  verifica che venga aggiunta a `expanded_macros`; con una espansa, simula `key == "LEFT"` e
  verifica che venga rimossa. Verifica anche l'idempotenza (RIGHT su una già espansa non deve
  sollevare errori né toglierla).
- Verifica che il toggle Spazio/Invio esistente (test già presenti, se ce ne sono in
  `tests/test_outline_review.py` o simile) continui a passare invariato.

Esegui `python3 -m pytest tests/ -q` e correggi finché l'intera suite passa.

## Vincoli

Verifica il bug di portabilità ricorrente sulle annotazioni `typing` per qualunque riga toccata
(vedi `.agents/00-README.md`). Leggi la nota su come isolare l'ambiente di test da `config/`
reale prima di qualunque verifica funzionale diretta.

Non toccare `build_outline_tree` (righe 36-145): la logica di costruzione dell'albero è
corretta, il problema è solo nel loop di rendering/input attorno ad essa.

## Verifica finale

1. `python3 -m pytest tests/ -q`.
2. Test manuale interattivo REALE in un vero terminale: lancia una outline review (anche con
   `--mock`), naviga con UP/DOWN/LEFT/RIGHT e Spazio, verifica visivamente che la card si
   aggiorni in place senza mai duplicarsi, e che LEFT/RIGHT collassino/espandano come atteso.
   Documenta esplicitamente il risultato di questa verifica manuale nel riepilogo finale.
