# Piano: l'audio della lezione si blocca dopo pochi secondi

Base: `claude/rt-4.3.2-beta`. Ramo suggerito: `codex/audio-remux`. PR verso `claude/rt-4.3.2-beta`.

## Sintomo

Nell'app (WKWebView) e nel browser l'audio parte, suona 5-10 secondi e si ferma con
"Il browser non riesce a riprodurre questo audio." Succede su più lezioni.

## Causa (riprodotta)

`rt/services/audio_service.py::playable_audio` converte i `.m4a` in AAC ADTS in un MP4 in
`<dati>/cache/audio/<chiave>.m4a`. `get_audio` in `rt/api/routers/lessons.py` è una funzione
sincrona, quindi FastAPI la esegue nel threadpool: le richieste Range arrivano in parallelo
(nell'`api.log` dell'utente ce ne sono una ventina di fila per la stessa lezione al primo play).

Quando la cache non c'è ancora:

1. tutte le richieste vedono che `target` non esiste e lanciano ognuna un ffmpeg sullo **stesso**
   file temporaneo `target + ".tmp.m4a"` (con `-y`, che lo tronca);
2. la prima che finisce fa `os.replace(temporary, target)` mentre le altre stanno ancora scrivendo
   in quell'inode (e il passaggio `+faststart` lo riapre per nome);
3. le altre falliscono `os.replace` (`FileNotFoundError`) e restituiscono **il file originale ADTS**.

Risultato: il browser riceve i primi byte da un file e i successivi da un altro (stessa URL,
contenuti diversi) e la cache resta corrotta per sempre, perché da lì in poi `os.path.isfile(target)`
la restituisce senza controlli.

Prova in locale (ADTS di 1 ora, 8 thread su `playable_audio`): 7 richieste su 8 ricevono
l'originale, e il file in cache non ha più alcuno stream leggibile (`ffprobe` → `duration N/A`,
"Output file does not contain any stream"), in 4 prove su 4. Con un solo thread il remux è
corretto (3600 s, nessun errore di decodifica).

## Modifiche

### 1. `playable_audio` serializzato per file

In `rt/services/audio_service.py`:

- Aggiungi un dizionario di lock per chiave, protetto da `_lock`:

  ```python
  _remux_locks: Dict[str, threading.Lock] = {}

  def _remux_lock(key: str) -> threading.Lock:
      with _lock:
          return _remux_locks.setdefault(key, threading.Lock())
  ```

- Flusso nuovo:

  ```python
  def playable_audio(path: str) -> str:
      if os.path.splitext(path)[1].lower() != ".m4a" or _is_mp4(path):
          return path
      key = _key(path)
      target = os.path.join(_cache_dir("audio"), key + REMUX_SUFFIX)
      if _valid_remux(target):          # controllo veloce, vedi punto 3
          return target
      with _remux_lock(key), file_lock(target + ".lock", ...):
          if _valid_remux(target):      # un'altra richiesta l'ha appena creato
              return target
          fd, temporary = tempfile.mkstemp(prefix=key + ".", suffix=".tmp.m4a", dir=os.path.dirname(target))
          os.close(fd)
          try:
              subprocess.run([... "-i", path, "-c:a", "copy", "-movflags", "+faststart", temporary], ...)
              if not _probe_ok(temporary):
                  return path
              os.replace(temporary, target)
              return target
          except (OSError, subprocess.SubprocessError):
              return path
          finally:
              if os.path.exists(temporary):
                  os.remove(temporary)
  ```

- Il lock tra processi usa `rt/core/filelock.py::file_lock` (già portabile Mac/Windows): l'API
  è un processo solo, ma non costa nulla e copre un secondo server avviato per errore. Scegli
  `stale_sec` più lungo del timeout di ffmpeg (300 s) e `retries/backoff` che attendono almeno
  quanto un remux; se il lock non si ottiene, restituisci `path` come oggi.
- Il nome del temporaneo è unico (`mkstemp`) e sta nella stessa cartella, così `os.replace` resta
  atomico.

### 2. Le voci corrotte già in cache non vengono più servite

Gli utenti hanno già file rotti in `cache/audio/`. Cambia il nome delle voci con una costante,
per esempio `REMUX_SUFFIX = ".v2.m4a"`, così le vecchie `<chiave>.m4a` non vengono più lette.
`clear_cache()`/`cache_info()` le contano e le cancellano comunque (camminano su tutta la cartella),
quindi non serve una migrazione. In più, al primo remux riuscito di una chiave, rimuovi se esiste la
vecchia `<chiave>.m4a` (best effort, ignora `OSError`).

### 3. Controllo del remux

- `_probe_ok(file)`: `ffprobe` non c'è in `rt/core/media_tools.py` e con `imageio_ffmpeg` non è
  garantito, quindi usa ffmpeg stesso: `ffmpeg -v error -i file -map 0:a:0 -t 1 -f null -` deve
  uscire con 0 e senza stderr. In più il file deve iniziare con `ftyp` (`_is_mp4`) e avere
  dimensione almeno il 90% dell'originale (il remux copia i dati AAC, quindi le dimensioni sono quasi
  uguali: nella prova 29,6 MB contro 30,1 MB). Non confrontare le durate: quella dell'ADTS è una
  stima (3551 s contro i 3600 reali nella prova).
- `_valid_remux(target)`: solo controlli economici, perché gira a ogni richiesta Range:
  `os.path.isfile`, `_is_mp4`, dimensione ≥ 90% dell'originale. Il controllo con ffmpeg si fa solo
  prima di `os.replace`.

### 4. Nessun mix di file per la stessa URL

Con il lock, le richieste che arrivano durante il remux aspettano e ricevono il remux. L'originale
si restituisce solo se il remux fallisce davvero (ffmpeg assente, errore, controllo non superato), e
in quel caso lo ricevono tutte le richieste successive allo stesso modo, perché `target` non esiste.

### 5. Il player recupera da un errore

In `frontend/src/components/lesson/AudioPlayer.tsx`, sull'evento `error` dell'`<audio>`, prova una
sola volta a ricaricare la sorgente con un parametro di cache-busting (`?r=<timestamp>`), riprendendo
da `currentTime`; se fallisce ancora mostra il messaggio di oggi. Il server ignora il parametro.

## Test

In `tests/test_api_lesson_view.py` (accanto a `test_playable_audio_remuxes_adts_once`):

- **Concorrenza**: crea un ADTS breve con ffmpeg (salta il test se ffmpeg manca, come i test
  vicini), lancia 8 thread su `playable_audio` con una `threading.Barrier`; tutti devono restituire
  lo stesso percorso in cache, ffmpeg deve essere chiamato una volta sola (contatore su
  `subprocess.run` incapsulato), e il file deve passare `_probe_ok`.
- **Vecchia voce corrotta**: scrivi byte casuali in `<chiave>.m4a`; `playable_audio` deve creare e
  restituire `<chiave>.v2.m4a` valida e rimuovere la vecchia.
- **Remux non valido**: simula ffmpeg che esce 0 ma scrive un file vuoto; deve restituire
  l'originale e non lasciare nulla in `cache/audio/`.
- **Nessun temporaneo rimasto** dopo successo e dopo errore.
- Frontend: in `AudioPlayer.test.tsx` (o nuovo file), un `error` sull'audio cambia `src` una sola
  volta aggiungendo `r=`; un secondo `error` mostra il messaggio.

Esegui `pytest tests/test_api_lesson_view.py` e i test del frontend del componente.

## Note per il changelog

"L'audio della lezione non si interrompe più dopo pochi secondi al primo ascolto: la copia
riproducibile si prepara una volta sola e le copie rovinate dalle versioni precedenti vengono
rifatte."
