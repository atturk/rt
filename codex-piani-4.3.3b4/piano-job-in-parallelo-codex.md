# Piano 0 · Job in parallelo: 8 fissi, trascrizione locale una alla volta

Versione per la 4.3.3b4. Sostituisce `codex-piani-job-paralleli/piano-job-in-parallelo-codex.md` (ramo
`claude/project-thread-krk5ox`). Scelta di Attilio del 22/10/2026: niente impostazione, il worker esegue
sempre fino a **8** lezioni insieme. Le chiamate al modello restano tutte in parallelo. In fila va solo
la trascrizione locale (Parakeet ONNX, macparakeet), l'unica parte pesante per CPU e memoria.

Non cambia: un solo job per lezione alla volta (vincolo `active_lesson` della coda).

## 0. Il worker del Mac ignora il valore (da fare per primo)

Sull'app per Mac il worker gira come servizio launchd (`rt/services/service_manager.py`,
`SERVICES["worker"] = ["worker"]`), senza `--concurrency`. In `rt/cli_jobs.py` il default di
`--concurrency` è 1, quindi il worker esegue sempre un job alla volta. Solo `rt web` in primo piano
(`rt/api/launcher.py`) passa il valore. La diagnostica di Attilio lo conferma: "Worker: 1 attivi".

Correzione:
- `rt/cli_jobs.py`: `--concurrency` con `default=None`. Se manca, usa `worker_concurrency()`.
  Help: "default: 8". L'opzione resta per chi lancia `rt worker` a mano.
- Il servizio launchd già installato la prende senza riscrivere il plist, appena il worker riparte
  (chiudere RT dal menu e riaprirlo).

## 1. Un'unica costante, 8

- `rt/services/settings_service.py`: `WORKER_CONCURRENCY = 8`. Togli `WORKER_CONCURRENCY_RANGE` e
  `save_worker_concurrency`.
- `rt/api/launcher.py`, `worker_concurrency()`: restituisce `WORKER_CONCURRENCY`, senza leggere la
  configurazione.
- `rt/core/config.py`, `WorkerConfig.concurrency`: le configurazioni esistenti hanno ancora
  `worker.concurrency: 2`. Non devono dare errore né valere qualcosa. Accetta e ignora la chiave
  (campo deprecato senza limiti stretti oppure `extra="ignore"`, come è più semplice nel modello).
- API (`rt/api/routers/settings.py`): togli l'endpoint che salva il valore e `WorkerIn`. Nello
  snapshot, `worker` tiene solo `running` (il numero di worker attivi usato dalla diagnostica). Se
  qualcosa nel frontend legge ancora `concurrency`, rimuovilo.
- Rigenera `docs/openapi.json` e `frontend/src/api/schema.d.ts` con lo script del repo.

## 2. Trascrizione locale: uno slot per processo

Nuovo file `rt/core/stt_slot.py`:

```python
"""Una trascrizione locale alla volta per processo: il motore usa già tutti i core e tiene
l'audio decodificato in memoria (circa 700 MB per due ore di lezione)."""
import threading
from contextlib import contextmanager

_slot = threading.Semaphore(1)

@contextmanager
def local_transcription_slot(on_wait=None, cancel_token=None):
    if not _slot.acquire(blocking=False):
        if on_wait:
            on_wait("In attesa che finisca un'altra trascrizione")
        while not _slot.acquire(timeout=1.0):
            if cancel_token is not None:
                cancel_token.raise_if_cancelled()   # RunCancelled, rt/services/context.py
    try:
        yield
    finally:
        _slot.release()
```

Avvolgi **solo** i punti dei job, non `transcribe_onnx` in sé. La risposta vocale di Telegram
(`rt/core/recall_stt.py`) è breve e non deve aspettare una lezione intera.

- `rt/pipeline/setup.py`, circa riga 715: `transcribe_onnx(...)` dentro
  `with local_transcription_slot(...)`.
- `rt/pipeline/setup.py`, circa riga 728: `_run_transcribe_with_spinner(cmd_json, ...)`, stesso
  trattamento.
- `rt/pipeline/source_update.py`, `_transcribe`: i rami `transcribe_onnx` e macparakeet, stesso
  trattamento. Il ramo `custom` (trascrizione via API) e il ramo mock **non** passano dallo slot.

Per `on_wait` usa il reporter di avanzamento già disponibile in quel punto:
`ctx.progress('prepare', message=...)` in `source_update`, `on_progress` in `setup.py`. Così nella
barra del job si legge "In attesa che finisca un'altra trascrizione".

## 3. Interfaccia

`frontend/src/components/settings/general.tsx`: togli il selettore "Job in parallelo", con la sua
etichetta e il salvataggio. Non aggiungere testi al suo posto. Se il gruppo "Job" resta vuoto,
toglilo. Aggiorna i test unitari della sezione.

## 4. Documentazione

`docs/WEB.md`, sezione "Job in parallelo": il worker esegue fino a 8 lezioni insieme, una sola
fase alla volta per lezione. Le trascrizioni locali vanno comunque una alla volta. Togli la frase
sull'impostazione e su `worker.concurrency`, e la voce "job in parallelo" dall'elenco delle
impostazioni (circa riga 143). `rt worker --concurrency N` resta per l'uso a mano.

## 5. Test

- `tests/test_parallel_jobs.py`: `worker_concurrency()` restituisce 8 anche con
  `worker.concurrency: 2` nella configurazione, e la configurazione si carica senza errori.
- `rt worker` senza `--concurrency` chiama `run_workers` con 8 (monkeypatch di `run_workers`); con
  `--concurrency 1` usa 1.
- Slot: due thread entrano in `local_transcription_slot`. Il secondo entra solo quando il primo
  esce, e riceve `on_wait` una volta. Un terzo, con `cancel_token` annullato mentre aspetta, esce
  con l'eccezione di annullamento.
- `frontend/e2e/settings.spec.ts`: il test "lavorazione" sceglie "Job in parallelo" = 3 (circa
  riga 99). Togli quella parte e verifica che il selettore non ci sia più.
- Esegui `pytest tests/test_parallel_jobs.py tests/test_desktop_window.py tests/test_app_switch.py`,
  poi `settings.spec.ts` e `telegram.spec.ts`, che girano in serie sullo stesso server.
