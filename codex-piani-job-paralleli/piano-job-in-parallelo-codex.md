# Piano: più job in parallelo (limite da 4 a 16) con trascrizione locale una alla volta

## Obiettivo

Oggi "Job in parallelo" (Impostazioni > Generali) va da 1 a 4. Con OpenRouter a consumo il collo di
bottiglia non è il provider: è il tetto fisso. Alziamo il tetto a 16 e, perché sia sicuro, mettiamo
in fila **solo** la trascrizione locale (Parakeet ONNX / macparakeet), che è l'unica parte pesante
per CPU e memoria. Le chiamate al modello restano tutte in parallelo.

Non cambia: un solo job per lezione alla volta (vincolo `active_lesson` della coda). Il default resta 2.

## 1. Un'unica costante per il tetto

- `rt/core/config.py`, `WorkerConfig.concurrency`: `le=4` -> `le=16`.
- `rt/services/settings_service.py`: `WORKER_CONCURRENCY_RANGE = (1, 16)`.
- `rt/api/routers/settings.py`: `WorkerIn.concurrency` `le=4` -> `le=16`; nella description di
  `WorkerSettings.concurrency` "1-4" -> "1-16".
- `rt/api/launcher.py`, `worker_concurrency()`: `min(4, ...)` -> `min(WORKER_CONCURRENCY_RANGE[1], ...)`
  importando la costante da `settings_service` (niente numeri duplicati).
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

Avvolgi **solo** i punti dei job, non `transcribe_onnx` in sé (la risposta vocale di Telegram in
`rt/core/recall_stt.py` è breve e non deve aspettare una lezione intera):

- `rt/pipeline/setup.py` ~riga 715: `transcribe_onnx(...)` dentro `with local_transcription_slot(...)`.
- `rt/pipeline/setup.py` ~riga 728: `_run_transcribe_with_spinner(cmd_json, ...)` idem.
- `rt/pipeline/source_update.py` `_transcribe`: i rami `transcribe_onnx` e macparakeet, idem.
  Il ramo `custom` (trascrizione via API) **non** passa dallo slot. Il ramo mock neanche.

Per `on_wait` usa il reporter di avanzamento già disponibile in quel punto (in `source_update`
`ctx.progress('prepare', message=...)`, in `setup.py` `on_progress`), così nella barra del job si
legge "In attesa che finisca un'altra trascrizione" invece di un job fermo senza motivo.

## 3. Interfaccia

`frontend/src/components/settings/general.tsx`: `WORKER_CONCURRENCY_OPTIONS = [1, 2, 3, 4]` ->
`[1, 2, 3, 4, 6, 8, 12, 16]`. Nessun altro testo.

## 4. Documentazione

`docs/WEB.md`, sezione "Job in parallelo": "da 1 a 4" -> "da 1 a 16"; aggiungi una frase: le
trascrizioni locali vanno comunque una alla volta, gli altri job (revisione, rielaborazione,
immagini, domande) girano insieme.

## 5. Test

- `tests/test_parallel_jobs.py::test_worker_concurrency_setting`: valori non validi `(0, 5)` ->
  `(0, 17)`; aggiungi che `16` è accettato e `worker_concurrency()` restituisce 16.
- Nuovo test in `tests/test_parallel_jobs.py`: due thread entrano in `local_transcription_slot`;
  il secondo non entra finché il primo non esce e riceve `on_wait` una volta. Un terzo con
  `cancel_token` annullato mentre aspetta esce con l'eccezione di annullamento.
- `frontend/e2e/settings.spec.ts`: se seleziona un valore, verifica che 8 sia selezionabile.
- Esegui `pytest tests/test_parallel_jobs.py tests/test_desktop_window.py tests/test_app_switch.py`
  e l'e2e delle impostazioni.

## Fuori da questo piano

Applicare il valore senza riavviare RT (oggi vale dal prossimo avvio). Si può fare dopo.
