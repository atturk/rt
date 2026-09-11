# Task 04 — TUI review terminale con `rich`

Indipendente — nessun file condiviso con gli altri task in `.agents/` (tocca solo
rt/pipeline/issue_review.py).

Nel progetto RT (/Users/attilioturco/Desktop/trt), migliora il rendering della schermata di
review interattiva da terminale (rt/pipeline/issue_review.py) usando la libreria `rich`
(già presente in requirements.txt come rich>=13.0, ma oggi mai importata in questo file).
Implementa direttamente, senza produrre un piano preliminare.

CONTESTO: la funzione `run_interactive_review` costruisce oggi la schermata manualmente come
una lista di stringhe (`block_lines`), e la ridisegna "in place" con sequenze ANSI scritte a
mano (`sys.stdout.write(f"\x1b[{prev_line_count}A\x1b[0J")` per risalire il cursore e pulire).
L'input a tasto singolo (accetta/rifiuta/modifica/play/pausa/indietro/salta/esci) passa da
`read_single_key` in rt/core/keyboard.py, un'implementazione raw-mode custom via
termios/tty.setcbreak scritta apposta per leggere un carattere alla volta senza bufferizzazione,
necessaria per gestire input in tempo reale mentre l'audio riproduce in background.

1. NON toccare rt/core/keyboard.py, né `read_single_key`/`raw_mode`, né la logica di decisione
   (record_decision, revert_last_decision, il dispatch sui tasti A/R/M/P/O/B/S/Q), né la
   riproduzione audio (play_clip_background, cut_clip), né `start_review_via_telegram`/
   `send_current_issue` (il percorso Telegram, che resta invariato). Tocca SOLO il modo in cui
   viene renderizzata a schermo l'informazione dentro `run_interactive_review` per il percorso
   terminale.

2. Sostituisci la costruzione manuale di `block_lines`/`full_block` e il redraw via escape ANSI
   con un `rich.live.Live` che avvolge l'intero blocco `with raw_mode() as is_raw: ...`:
   ```python
   from rich.console import Console
   from rich.live import Live
   from rich.panel import Panel

   console = Console()
   with raw_mode() as is_raw, Live(console=console, auto_refresh=False, transient=False) as live:
       while idx < total_count:
           ...
           panel_content = _build_asr_panel(...)  # o _build_science_panel(...) a seconda del tipo issue
           live.update(panel_content, refresh=True)
           raw_key = read_single_key(already_raw=is_raw)
           ...
   ```
   Scrivi due funzioni helper `_build_asr_panel(...)` e `_build_science_panel(...)` (o una sola
   parametrica) che producono un `rich.panel.Panel`/`rich.text.Text` con le stesse informazioni
   mostrate oggi: unità didattica, timecode, testo ASR originale/proposta + motivazione + contesto
   (per le issue ASR), oppure claim/critica/correzione suggerita + contesto (per le issue di
   scienza), più l'ultima azione compiuta (approvato/rifiutato/modificato) come riga finale del
   pannello invece che come `print()` separato interleaved con il redraw manuale.

3. Attorno alle chiamate a `edit_text_in_editor(...)` (che lanciano `$EDITOR` in modo bloccante
   a schermo intero), ferma e riavvia il Live per non corrompere il terminale:
   ```python
   live.stop()
   edited_res = edit_text_in_editor(initial_editor_content)
   live.start()
   ```

4. Rimuovi tutto il bookkeeping di `prev_line_count` e le `sys.stdout.write` con escape ANSI
   di cursore, ormai sostituiti da `Live`.

5. Esegui la test suite (pytest tests/test_issue_review.py -q e l'intera suite). I test esistenti
   simulano le pressioni di tasti patchando `builtins.input` (perché `read_single_key` ricade su
   `input()` quando stdin non è un TTY, come sotto pytest) e asseriscono solo sullo stato del
   ledger o su specifiche stringhe di warning — non asseriscono sul contenuto renderizzato del
   blocco/pannello, quindi dovrebbero continuare a passare senza modifiche; se qualche test fallisse
   per output catturato via capsys che confronta testo esatto della vecchia UI ANSI, aggiornalo
   di conseguenza.
