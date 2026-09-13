# Task 72 — Dopo il build, verifica se il demone Telegram è già attivo e proponi di avviarlo

Indipendente dagli altri task attivi. Nel progetto RT (/Users/attilioturco/Desktop/trt),
implementa direttamente, senza produrre un piano preliminare.

## Contesto

Oggi `rt telegram-daemon` va avviato manualmente dall'utente, in un terminale a parte, e non
esiste alcun meccanismo per sapere se è già in esecuzione (verificato: nessun PID file, nessun
lock, nessuna funzione di rilevamento in tutto `rt/`). L'utente vuole che, al termine del build
(sia dentro `rt run` sia con `rt build` standalone), lo script verifichi in modo affidabile se il
demone è già attivo e, se non lo è, chieda "Vuoi avviare il demone Telegram ora? [Y/n]" — se
l'utente conferma, lo avvia automaticamente in una NUOVA finestra di Terminal (macOS, va bene
usare `osascript`/AppleScript o `open -a Terminal`, il progetto è già esclusivamente per macOS,
vedi le decisioni precedenti su Option+Backspace testato solo su Terminal.app).

## Modifica

### 1. Rilevamento robusto "il demone è già attivo"

- In `rt/telegram/daemon.py` (o un nuovo modulo dedicato, es. `rt/telegram/daemon_status.py`),
  aggiungi un meccanismo a PID file: all'avvio di `cmd_telegram_daemon`/dentro la funzione che
  costruisce l'`Application` (riga ~1066, `Application.builder().token(cfg.bot_token).build()`),
  scrivi un file PID (es. in una posizione stabile fuori da una singola lezione, dato che il
  demone non è per-lezione — valuta `~/.rt/telegram_daemon.pid` o analogo, crea la directory se
  serve) con il PID del processo corrente, e rimuovilo (o marcalo) alla chiusura pulita
  (registra un handler per la chiusura, es. `atexit`, o rimuovilo nel blocco `finally` attorno al
  loop del demone).
- Aggiungi una funzione, es. `is_daemon_running() -> bool`, che legge quel PID file (se esiste) e
  verifica che il processo sia REALMENTE vivo (non solo che il file esista — un crash improvviso
  potrebbe lasciare un PID file orfano): usa `os.kill(pid, 0)` per testare l'esistenza del
  processo senza inviare segnali reali (gestisci `ProcessLookupError`/`PermissionError` come
  "non in esecuzione"/"non verificabile", rispettivamente — non dare per scontato che un errore
  generico significhi "in esecuzione").

### 2. Prompt a fine build

- In `rt/cli.py::cmd_build` (dopo `notify_build_completed`, righe ~343-352) e nell'equivalente
  punto dentro `cmd_run` (righe ~573-587, dopo la notifica) — verifica se sono davvero due call
  site distinti con la stessa struttura o se andrebbe estratta una funzione condivisa, invece di
  duplicare la logica in due punti: se `is_daemon_running()` è `False`, chiedi
  `questionary.confirm("Vuoi avviare il demone Telegram ora?", default=True).ask()` (default Y
  come richiesto). Se l'utente conferma, avvia il demone in una NUOVA finestra Terminal.app: es.
  `subprocess.run(["osascript", "-e", f'tell application "Terminal" to do script "{comando}"'])`
  dove `{comando}` è il comando shell per rilanciare `rt telegram-daemon` con lo stesso ambiente
  (verifica come ottenere il percorso assoluto dell'eseguibile `rt` corrente, es. `sys.argv[0]`
  risolto ad assoluto, o il wrapper `bin/rt` del progetto — non assumere che `rt` sia nel PATH
  della nuova sessione di Terminal aperta).
- Se il prompt non è eseguibile (non-TTY, es. CI/script/`--mock` automatizzato): salta
  silenziosamente questo passo, comportamento identico a oggi (nessun prompt, nessun demone
  avviato in automatico) — verifica `sys.stdin.isatty()` prima di proporre la domanda.
- Se il demone risulta GIÀ attivo: non fare nulla, nessun messaggio invadente (comportamento
  silenzioso, l'utente non deve essere disturbato se ha già il bot acceso).

## Test

- Test che verifica `is_daemon_running()`: `False` se nessun PID file esiste; `False` se il PID
  file esiste ma il processo referenziato non è vivo (mocka `os.kill` per sollevare
  `ProcessLookupError`); `True` se il PID file esiste e il processo è vivo (mocka `os.kill` senza
  eccezioni).
- Test che verifica che, a demone NON attivo e in ambiente TTY, dopo `rt build`/`rt run` venga
  proposta la domanda di conferma, e che rispondendo "sì" venga invocato il comando per aprire una
  nuova finestra Terminal (mocka `subprocess.run`/`osascript`, verifica gli argomenti passati,
  NON aprire realmente una finestra durante i test).
- Test che verifica che, a demone GIÀ attivo, la domanda non venga proposta affatto.
- Test che verifica che in ambiente non-TTY la domanda non venga MAI proposta.

Esegui `python3 -m pytest tests/ -q` e correggi finché l'intera suite passa.

## Vincoli

Verifica il bug di portabilità ricorrente sulle annotazioni `typing` per qualunque riga toccata
(vedi `.agents/00-README.md`). Soluzione specifica per macOS (Terminal.app/`osascript`), coerente
con lo scope attuale del progetto — non serve portabilità Linux/Windows.

## Verifica finale

1. `python3 -m pytest tests/ -q`.
2. Test manuale: senza demone attivo, esegui `rt build --force <lezione>`, verifica che compaia
   la domanda e che rispondendo "sì" si apra una nuova finestra Terminal con `rt telegram-daemon`
   in esecuzione. Ripeti con il demone già attivo: nessuna domanda.
