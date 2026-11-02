# Correzioni alla revisione di 4.3.6b2 (agy)

Lavora sul branch `agy/4.3.6b2` che hai già. Valgono le regole di `TASK-agy.md` (regola 0 compresa).
Un commit per punto, messaggio «4.3.6b2: fix N. <titolo>». Poi esegui i test (Python e frontend) e apri la PR come scritto in `TASK-agy.md`, se non è già aperta.

## fix 1. Rielaborazione per macro-unità: un client per thread

In `rt/pipeline/rewrite.py`, `process_macro_group` usa `macro_client = client if client is not None else LLMClient(...)`. Ma `client` esiste sempre (riga ~282), quindi tutti i thread condividono lo stesso `LLMClient`. `LLMClient` tiene stato per istanza (`last_usage`, `last_context_model`, `last_max_tokens`), letto subito dopo la chiamata per `context_for_usage`: con più thread si leggono i numeri di un'altra macro-unità.

- Crea sempre `LLMClient(force_mock=force_mock)` dentro `process_macro_group`, come fa `examine` in `rt/pipeline/review.py`. Se il client principale ha impostazioni da copiare (budget mock e simili), copiale.
- `ctx.progress(...)` e `ctx.emit(...)` vengono chiamati dai thread: chiamali dentro `write_lock`, così il reporter non riceve eventi in parallelo.
- Test: con `parallel_macros=2` e un client finto che registra l'identità dell'istanza, due macro-unità usano due client diversi.

## fix 2. Riparazione LaTeX: non rompere le formule su più righe

In `rt/core/encoding.py` (`_CONTROL_IN_MATH`) e in `frontend/src/lib/math.ts` (`repairLatexEscapes`) un `\n` o `\r` seguito da una lettera diventa un comando LaTeX. Dentro `$$…$$` o `\[…\]` un a capo vero seguito da testo è normale (`$$\na = b\n$$`, `$$\ni = 1\n$$`, righe di `aligned`): diventa `\na` e la formula si rompe. Anche la pulizia finale in `math.ts` toglie tutti i caratteri di controllo, a capo compresi.

- `\t`, `\x08`, `\x0c` seguiti da lettera: ripara come ora.
- `\n` e `\r`: ripara solo se seguiti dal resto di un comando noto. Per `\n`: `abla`, `eq`, `ot`, `otin`, `eg`, `ewline`, `leq`, `geq`, `mid`, `exists`, `parallel`, `subseteq`, `cong`, `sim`, sempre seguito da un carattere che non è una lettera. Per `\r`: `ho`, `ight`, `angle`, `ceil`, `floor`, `m{`, alle stesse condizioni. Stessa lista in Python e in TypeScript.
- Nella pulizia finale lascia `\n` e `\r` nelle formule display (in Python lo fai già; in `math.ts` no).
- Test in entrambi: `$$\na = b\n$$` resta invariato; un `\n` seguito da `abla` diventa `\nabla`; un `\r` seguito da `ho` diventa `\rho`.

## fix 3. Test delle etichette di sezione dipendente dall'ordine

`tests/test_recall_special.py::test_classifier_reads_whole_sections_once_and_keeps_user_corrections` fallisce: ora le sezioni si classificano in parallelo, mentre il test dà le risposte con `side_effect=[...]` in ordine fisso. Il codice è corretto: rendi il test indipendente dall'ordine, con un `side_effect` che sceglie la risposta guardando gli id delle unità nello `state` (`[1.1]` → sezione 1, `[2.1]` → sezione 2, `[3.1]` → sezione 3). Controlla gli altri test che usano liste di risposte con chiamate ora parallele (recall, classificatore, etichette).

## fix 4. Registrazione già caricata: un solo controllo

In `rt/api/routers/jobs.py` il blocco che calcola lo sha e solleva 409 `audio_duplicate` è copiato due volte (`_mixed` e `_go`). Mettilo in una funzione `_check_duplicate_audio(path, consenti_duplicato)` e chiamala nei due punti. In `_check_audio_file` intercetta anche `FileNotFoundError` e `subprocess.TimeoutExpired` (ffprobe o ffmpeg mancanti o lenti): in quel caso **non** rifiutare il file, lascia proseguire.
