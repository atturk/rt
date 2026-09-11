# Task 02 — cli.py: `--with-review` granulare, rimozione conferma outline via Telegram

Indipendente — eseguibile in parallelo con 01, 03, 04. Piccola sovrapposizione prevista con 03
su `rt/cli.py`/`rt/telegram/notify.py` (funzioni diverse, non righe adiacenti) e su
`rt/core/config.py` (campi diversi di `TelegramRuntimeConfig`) — si ricompone bene al merge.

Nel progetto RT (/Users/attilioturco/Desktop/trt), implementa direttamente due cambi correlati
in rt/cli.py e rt/pipeline/outline_review.py, senza produrre un piano preliminare:

PARTE 1 — `--with-review` granulare (oggi è un flag booleano che avvia sempre sia ASR sia
scienza insieme; deve diventare selettivo).

1. In rt/cli.py, il subparser `run` (`p_run.add_argument("--with-review", action="store_true",
   dest="with_review", ...)`): cambia in
   ```python
   p_run.add_argument(
       "--with-review", nargs="?", const="all", choices=["all", "asr", "science"], default=None,
       dest="with_review",
       help="Include anche la review nella run: senza valore o 'all' = ASR+scientifica, "
            "'asr' = solo ASR, 'science' = solo scientifica. Default: nessuna (passi separati). "
            "Nota: se usato senza valore esplicito, va messo DOPO l'input posizionale "
            "(es. 'rt run cartella --with-review', non 'rt run --with-review cartella')."
   )
   ```
2. Aggiungi un helper module-level (vicino a normalize_review_cli_args):
   ```python
   def _normalize_with_review(value) -> Tuple[bool, bool]:
       """Ritorna (run_asr, run_sci). True/'all' -> entrambi; 'asr'/'science' -> solo quello;
       None/False -> nessuno. Il ramo True copre i chiamanti che costruiscono un Namespace
       manualmente con with_review=True (bypassando argparse), per compatibilità coi test."""
       if value in (True, "all"):
           return True, True
       if value == "asr":
           return True, False
       if value == "science":
           return False, True
       return False, False
   ```
3. In cmd_run: sostituisci `with_review = getattr(args, "with_review", False)` con
   `run_asr, run_sci = _normalize_with_review(getattr(args, "with_review", None))`.
   - La chiamata a `_ensure_config_ready([...])` (oggi include sempre "review_asr",
     "review_science") diventa condizionale:
     ```python
     required = ["outline", "rewrite"]
     if run_asr:
         required.append("review_asr")
     if run_sci:
         required.append("review_science")
     if not mock_mode:
         _ensure_config_ready(required)
     ```
   - `total_steps` (calcolato due volte, per input audio e per input cartella) diventa
     `(6 if is_audio_input else 4) + int(run_asr) + int(run_sci)` invece dei valori binari
     hardcoded 8/6 e 6/4.
   - Il blocco `if with_review: ...` che oggi lancia sempre prima ASR poi sempre scienza va
     diviso in due blocchi indipendenti che usano il numero di step corrente in modo dinamico:
     ```python
     next_step = step_offset + 4
     if run_asr:
         asr_res = run_review_asr(lesson_dir, force=force, force_mock=mock_mode)
         asr_details = (...)  # stessa logica di formattazione già presente
         _print_phase_action("review-asr", asr_res, step=next_step, total_steps=total_steps,
                              description="Ambiguità fonetiche e Confidence Gating", details=asr_details)
         auto_accept_val = "all" if getattr(args, "auto_accept", False) else None
         if not run_interactive_review(lesson_dir, "asr", channel=channel, auto_accept=auto_accept_val):
             print(f"\n⏸  In attesa che la revisione ASR venga completata (Telegram, oppure esegui "
                   f"'rt review-asr \"{lesson_dir}\"' da terminale). Esegui poi 'rt build \"{lesson_dir}\"' per finalizzare.")
             return
         next_step += 1

     if run_sci:
         sci_res = run_review_science(lesson_dir, force=force, force_mock=mock_mode)
         sci_details = (...)  # stessa logica di formattazione già presente
         _print_phase_action("review-science", sci_res, step=next_step, total_steps=total_steps,
                              description="Critic indipendente su docente e allucinazioni", details=sci_details)
         auto_accept_val = "all" if getattr(args, "auto_accept", False) else None
         if not run_interactive_review(lesson_dir, "science", channel=channel, auto_accept=auto_accept_val):
             print(f"\n⏸  In attesa che la revisione scientifica venga completata (Telegram, oppure esegui "
                   f"'rt review-science \"{lesson_dir}\"' da terminale). Esegui poi 'rt build \"{lesson_dir}\"' per finalizzare.")
             return
         next_step += 1

     build_step_num = next_step
     ```
     (nota: `auto_accept_val` va calcolato in entrambi i blocchi indipendentemente, dato che ora
     possono girare da soli). Mantieni identica la logica di formattazione di `asr_details`/
     `sci_details` già presente nel codice attuale (basata su `asr_res.get("skipped")` ecc.).

PARTE 2 — rimozione della conferma outline via Telegram (resta solo terminale; la review
ASR/scienza via Telegram NON va toccata, resta invariata).

4. In rt/pipeline/outline_review.py:
   - `confirm_or_revise_outline(lesson_dir, channel: str, force=False, force_mock=False)`:
     rimuovi il parametro `channel` e la diramazione `if channel == "telegram": ... else: ...`
     (righe ~15-31) — chiama sempre e solo `_confirm_via_terminal(lesson_dir, force_mock)`.
   - Elimina `_confirm_via_telegram` (righe ~75-159) e `_warn_if_daemon_inactive` (righe ~58-72,
     usata solo da quella funzione).
   - Lascia `_confirm_via_terminal` esattamente come oggi (il polish con `questionary` è
     un task separato, non toccarlo qui).

5. In rt/cli.py:
   - `cmd_outline`: rimuovi la risoluzione di `channel` (il blocco `channel = getattr(args,
     "channel", None); if not channel: ...`) e chiama
     `confirm_or_revise_outline(args.lesson_dir, force=force, force_mock=args.mock)`.
   - Il subparser `p_out`: rimuovi l'argomento `--channel` (righe ~687-688).
   - `cmd_run`: rimuovi il blocco che risolve `channel` PRIMA di chiamare
     `confirm_or_revise_outline` e passa channel a quella funzione — chiama invece
     `confirm_or_revise_outline(lesson_dir, force=force, force_mock=mock_mode)` senza channel.
     ATTENZIONE: `channel` resta necessario più sotto in cmd_run per `run_interactive_review`
     (review ASR/scienza) — quindi la risoluzione di `channel` (`channel = getattr(args,
     "channel", None); if not channel: channel = load_config().telegram.default_channel`) va
     SPOSTATA (non eliminata) a un punto della funzione precedente al suo primo uso reale, che
     ora è il blocco review della PARTE 1 sopra (non più necessaria prima della chiamata a
     confirm_or_revise_outline).

6. In rt/telegram/formatting.py: elimina `build_outline_decision_keyboard` (confermato: il suo
   unico chiamante era `_confirm_via_telegram`, appena eliminata). NON toccare
   `render_outline_summary_text` — è condivisa con `_confirm_via_terminal` e resta.

7. Elimina interamente il file rt/telegram/pending.py (esiste solo per supportare il flusso di
   conferma outline via Telegram appena rimosso — nessun altro modulo lo importa).

8. In rt/core/models.py: elimina `TelegramPendingStatus` e `TelegramPendingState` (i cui unici
   consumatori erano rt/telegram/pending.py, appena eliminato, e i test eliminati al punto 11).

9. In rt/telegram/daemon.py: elimina il codice diventato irraggiungibile perché nessuna sessione
   di tipo "outline_confirmation" potrà più essere creata:
   - `_handle_outline_callback` (l'intera funzione).
   - Il branch che dispatcha ai prefissi di callback `"rtappr"`/`"rtedit"` dentro
     `handle_callback`.
   - Il ramo che gestisce `kind == "outline_feedback"` dentro `handle_text`.
   - Il case `kind == "outline_confirmation"` dentro `handle_quit` (fallo confluire nel ramo
     `else` generico esistente).
   NON toccare nient'altro in daemon.py (in particolare non toccare i comandi /recall, /quit
   generici, o la gestione delle issue ASR/scienza via Telegram).

10. In rt/core/config.py: `TelegramRuntimeConfig.poll_interval_seconds` diventa morto (unico
    lettore era il flusso appena rimosso) — rimuovi il campo. NON toccare altri campi di
    TelegramRuntimeConfig.

11. Test:
    - Elimina interamente tests/test_telegram_pending.py (testa un modulo che non esiste più).
    - In tests/test_outline_review.py: elimina tutti i test del percorso Telegram (quelli che
      chiamano `_confirm_via_telegram` o passano `channel="telegram"` a
      `confirm_or_revise_outline`, o testano `TelegramPendingState`/il polling). I test del
      percorso terminale restanti vanno aggiornati solo per la rimozione del parametro
      `channel` dalla firma di `confirm_or_revise_outline` (NON serve toccare il modo in cui
      simulano l'input, quello è un task separato).
    - Cerca in tutta la test suite altri riferimenti a `channel="telegram"` passati a
      `confirm_or_revise_outline`, a `_confirm_via_telegram`, `_warn_if_daemon_inactive`,
      `poll_interval_seconds`, `TelegramPendingStatus`/`TelegramPendingState`, o ai callback
      `rtappr`/`rtedit`, e rimuovili o aggiornali di conseguenza.

12. Esegui la test suite (pytest tests/ -q) e assicurati che passi.
