# Piano: 8 job in parallelo fissi, trascrizione locale una alla volta

## Obiettivo

Decisione di Attilio (22/10/2026): niente impostazione "Job in parallelo". Il worker esegue sempre
fino a **8 job insieme** (8 lezioni diverse). Con OpenRouter a consumo il collo di bottiglia non è
il provider. Perché sia sicuro, la trascrizione locale (Parakeet ONNX / macparakeet), l'unica parte
pesante per CPU e memoria, va in fila una alla volta. Le chiamate al modello restano in parallelo.

Non cambia: un solo job per lezione alla volta (vincolo `active_lesson` della coda).

## 0. Bug di oggi: sul Mac il worker esegue un job alla volta

Sull'app per Mac il worker gira come servizio launchd (`rt/services/service_manager.py`,
`SERVICES["worker"] = ["worker"]`), senza `--concurrency`; in `rt/cli_jobs.py` il default è 1.
Solo `rt web` in primo piano (`rt/api/launcher.py`) passava il valore. Diagnostica di Attilio:
impostazione 2, "Worker: 1 attivi". Il punto 1 lo risolve.

## 1. Una costante, nessuna impostazione

- `rt/services/jobs.py`, accanto a `DEFAULT_LEASE_SECONDS`: `WORKER_CONCURRENCY = 8`.
- `rt/cli_jobs.py`: `--concurrency` con `default=None`; se non indicato usa `WORKER_CONCURRENCY`.
  Help: "Job eseguiti in parallelo (default 8)". `--concurrency N` resta per test e uso a mano.
- `rt/api/launcher.py`: togli `worker_concurrency()` e il passaggio di `--concurrency` al worker
  (il default del comando basta). Aggiorna i test che lo monkeypatchano
  (`tests/test_parallel_jobs.py`, `tests/test_desktop_window.py`, `tests/test_app_switch.py`).
- `rt/core/config.py`, `WorkerConfig.concurrency`: **resta** nel modello (i `general.yaml` esistenti
  hanno `worker.concurrency: 2` e non devono fallire al caricamento) ma non lo legge più nessuno.
  Description: "Non usato: il worker esegue sempre fino a 8 job (dalla 4.3.3)". Togli il `le=4`
  (`ge=1` basta).
- `rt/services/settings_service.py`: togli `WORKER_CONCURRENCY_RANGE` e `save_worker_concurrency`.
  In `snapshot()` togli la chiave `worker` se non serve più al frontend (vedi punto 3); altrimenti
  lascia solo `running`.
- `rt/api/routers/settings.py`: togli `PUT /api/v1/settings/worker`, `WorkerIn` e il campo
  `concurrency` di `WorkerSettings` (o tutto `WorkerSettings` se sparisce dallo snapshot).
- `rt/services/doctor_service.py` / diagnostica: se mostra "Worker: N attivi" va bene così.
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

- `frontend/src/components/settings/general.tsx`: togli `WorkerSection`, `WorkerFields` e
  `WORKER_CONCURRENCY_OPTIONS`; in `frontend/src/routes/settings.tsx` togli `<WorkerSection />`
  dalla pagina; in `frontend/src/api/settings.ts` togli `useSaveWorker`.
- Nessun testo nuovo, a parte "In attesa che finisca un'altra trascrizione" del punto 2.

## 4. Documentazione

`docs/WEB.md`, sezione "Job in parallelo": il worker esegue fino a 8 job insieme su lezioni diverse,
non è un'impostazione; le trascrizioni locali vanno comunque una alla volta. Togli il riferimento a
Impostazioni > Generali e alla frase su `rt worker` a 1 thread. Aggiorna `docs/API.md` se cita
`/settings/worker`.

## 5. Test

- `tests/test_parallel_jobs.py`: togli `test_worker_concurrency_setting`; aggiungi che `rt worker`
  senza `--concurrency` chiama `run_workers` con 8 e con `--concurrency 1` usa 1 (monkeypatch di
  `run_workers`). Aggiorna `test_launcher_passes_concurrency_to_worker`: il launcher non passa più
  `--concurrency`.
- Test che un `general.yaml` con `worker: {concurrency: 2}` si carica ancora.
- Nuovo test dello slot: due thread entrano in `local_transcription_slot`; il secondo non entra
  finché il primo non esce e riceve `on_wait` una volta. Un terzo con `cancel_token` annullato
  mentre aspetta esce con `RunCancelled`.
- `frontend/e2e/settings.spec.ts`: togli la parte su "Job in parallelo" (`worker-concurrency`).
- Esegui `pytest tests/test_parallel_jobs.py tests/test_desktop_window.py tests/test_app_switch.py`
  e l'e2e delle impostazioni.

## Note

Dopo l'aggiornamento il servizio worker del Mac viene riavviato ("Servizi aggiornati e riavviati"),
quindi gli 8 job valgono subito senza altro da fare.
