Questo documento è già il piano di implementazione completo e concordato: procedi direttamente alle modifiche, senza produrre un piano separato da approvare prima.

# TASK: Timeout di inattività (idle read timeout) per lo streaming SSE, indipendente dal deadline totale

## Contesto

Durante un test e2e reale su `review_science`, un modello dietro `openrouter/free` (`nvidia/nemotron-3.5-lightning:free` — probabilmente un classificatore di safety, non un modello conversazionale generico) ha risposto con soli 17 caratteri di testo (`"User Safety: safe"`, non JSON, non recuperabile) e poi è rimasto **muto sulla connessione** senza chiuderla né inviare `finish_reason`. Il monitor a terminale ha mostrato lo stato `[3/4] Streaming response` bloccato per oltre 53 secondi (fino a un massimo teorico di ~300s, il `timeout_seconds` configurato per il job).

### Causa esatta (verificata leggendo il codice, non ipotizzata)

In `rt/llm/client.py:344-356`:
```python
if deadline is not None:
    rem_sec = deadline - time.monotonic()
    if rem_sec <= 0:
        attempt_exception = TimeoutFailure(...)
        break
    req_timeout = max(0.1, rem_sec)
else:
    req_timeout = None
```
`req_timeout` viene passato a `requests.post(..., timeout=req_timeout, stream=True)` (riga 363, dentro il ramo streaming). In `requests`/`urllib3`, quel valore agisce come **read timeout a livello di socket**: scatta solo se non arriva *nessun byte* per l'intera durata del timeout configurato. Siccome `req_timeout` qui è calcolato come "tempo rimanente fino al deadline complessivo di 300s" (quasi l'intero budget, specialmente a inizio richiesta), un modello che tace dopo pochi caratteri blocca `for line_raw in response.iter_lines(...)` (riga 401) per quasi l'intero tempo rimanente prima che il socket stesso sollevi un `ReadTimeout` — classificato correttamente come `TimeoutFailure` (già gestito dal retry same-route esistente), ma con uno spreco di tempo enorme e del tutto evitabile.

## Decisione presa

Introdurre un **timeout di inattività breve e fisso** (default 45.0s), applicato **esclusivamente al ramo streaming**, disaccoppiato dal deadline wall-clock complessivo di 300s. Se il modello non invia alcun nuovo byte per più di questa soglia, la lettura fallisce prima (invece di aspettare fino a ~300s), rientrando nel meccanismo di classificazione/retry `TimeoutFailure` già esistente e invariato.

**Esplicitamente escluso da questo task** (discusso e scartato per rischio di falsi positivi): nessun controllo euristico sulla "forma" del contenuto accumulato (es. "il primo carattere deve essere `{`"). Il fix è puramente un controllo di vitalità della connessione (nessun byte in arrivo), non un controllo sul contenuto.

## Modifiche

### 1. `rt/core/config.py` — nuovo campo in `LLMRetryConfig`
```python
class LLMRetryConfig(BaseModel):
    max_timeout_retries: int = Field(default=1, description="Numero massimo di retry dopo timeout sullo stesso provider")
    timeout_backoff_seconds: float = Field(default=2.0, description="Secondi di attesa (backoff) tra un tentativo e il successivo")
    idle_read_timeout_seconds: float = Field(default=45.0, description="Timeout massimo (in secondi) di inattività sul socket durante lo streaming SSE: se nessun byte arriva entro questa soglia, la lettura fallisce con TimeoutFailure indipendentemente dal deadline wall-clock complessivo del job")
```

### 2. `rt/llm/client.py` — `call_structured()`

**Nuovo parametro opzionale** nella signature (vicino a `max_timeout_retries`/`timeout_backoff_seconds`, riga ~94):
```python
        max_timeout_retries: Optional[int] = None,
        timeout_backoff_seconds: Optional[float] = None,
        idle_read_timeout_seconds: Optional[float] = None
```

**Risoluzione del valore effettivo**, esattamente nello stesso stile delle altre impostazioni di retry già risolte alle righe 210-214:
```python
        cfg_retry = getattr(self.config, "retry", None)
        default_max_timeout_retries = getattr(cfg_retry, "max_timeout_retries", 1) if cfg_retry else 1
        default_backoff_sec = getattr(cfg_retry, "timeout_backoff_seconds", 2.0) if cfg_retry else 2.0
        default_idle_read_timeout = getattr(cfg_retry, "idle_read_timeout_seconds", 45.0) if cfg_retry else 45.0
        route_max_timeout_retries = max_timeout_retries if max_timeout_retries is not None else default_max_timeout_retries
        effective_backoff_sec = timeout_backoff_seconds if timeout_backoff_seconds is not None else default_backoff_sec
        effective_idle_read_timeout = idle_read_timeout_seconds if idle_read_timeout_seconds is not None else default_idle_read_timeout
```

**Punto di applicazione** — righe 344-356. Il fix si applica SOLO al valore di timeout usato per la richiesta in streaming; il ramo non-streaming (riga 531, usa la stessa variabile `req_timeout` oggi) deve continuare a comportarsi come oggi (attesa dell'intera risposta, nessun idle-timeout ridotto — semantica diversa, non è "attesa tra chunk" ma "attesa di un'unica risposta completa"). Serve quindi una seconda variabile dedicata allo streaming:
```python
                    if deadline is not None:
                        rem_sec = deadline - time.monotonic()
                        if rem_sec <= 0:
                            attempt_exception = TimeoutFailure(
                                f"Deadline wall-clock superata prima dell'invio della richiesta "
                                f"({time.time() - t_attempt_start:.2f}s >= {timeout_seconds}s)",
                                provider=provider_name,
                                model=model_name
                            )
                            break
                        req_timeout = max(0.1, rem_sec)
                        stream_req_timeout = max(0.1, min(rem_sec, effective_idle_read_timeout))
                    else:
                        req_timeout = None
                        stream_req_timeout = None
```

Poi, nel blocco `post_kwargs` del ramo streaming (riga ~363, dentro `if use_stream:`), usare `stream_req_timeout` al posto di `req_timeout`:
```python
                            post_kwargs = {
                                "headers": headers,
                                "json": payload,
                                "timeout": stream_req_timeout,
                                "stream": True,
                            }
```
Il ramo non-streaming (riga ~531, dentro l'`else:` di `if use_stream:`) **non va toccato**: deve continuare a usare `req_timeout` (invariato).

## Edge case e invarianti da rispettare

1. Quando `rem_sec` è già più piccolo di `effective_idle_read_timeout` (siamo vicini alla scadenza del deadline complessivo), `min(rem_sec, effective_idle_read_timeout)` deve restituire semplicemente `rem_sec` — cioè il comportamento per le richieste vicine a fine deadline resta identico a oggi, invariato.
2. Il controllo periodico già esistente del deadline wall-clock complessivo DURANTE l'iterazione dei chunk (dentro il `for line_raw in response.iter_lines(...)`, i vari `if deadline is not None and now_mono >= deadline: raise TimeoutFailure(...)`) resta invariato: continua a proteggere contro uno stream che continua a mandare byte lentamente ma supera comunque il tempo totale di 300s. Il nuovo `stream_req_timeout` copre un caso complementare e diverso: l'assenza totale di nuovi byte per un intervallo prolungato.
3. Nessuna modifica a `classify_failure`, a `rt/llm/router.py`, né al blocco di decisione retry in `client.py`: il `ReadTimeout` risultante deve continuare a essere classificato come `TimeoutFailure` e gestito dal meccanismo di retry same-route già esistente, senza alcuna modifica.
4. Il ramo non-streaming (`use_stream=False`) non deve essere in alcun modo affetto da questa modifica: stessa variabile `req_timeout` di oggi, stesso comportamento.
5. Nessun controllo euristico sul contenuto (fuori scope, deciso esplicitamente).
6. `idle_read_timeout_seconds` è opzionale con default `45.0`: non è richiesta alcuna modifica a `rt.config.yaml`/`rt.config.yaml.example` per il funzionamento base (il default si applica automaticamente), ma il campo deve essere leggibile/sovrascrivibile da lì se l'utente lo desidera in futuro (arriva gratis definendo il campo su `LLMRetryConfig`, che è già letto dalla sezione `retry:` del file YAML).

## Test di accettazione (`pytest tests/`)

In un file nuovo o esteso (es. `tests/test_llm_timeout_retry.py`, dove già esistono test sul timeout):

1. **Idle timeout scatta prima del deadline totale**: simulare un mock di `requests.post` per il ramo streaming il cui `iter_lines` restituisce un generatore che produce un primo chunk valido e poi, tramite un side_effect che solleva `requests.exceptions.ReadTimeout` a metà iterazione (simulando lo scadere del socket read timeout), verificare che la richiesta fallisca con `TimeoutFailure` (non un'eccezione generica) MOLTO prima del `timeout_seconds` complessivo configurato (es. usando un job con `timeout_seconds=300` ma verificando che il fallimento avvenga per via del meccanismo di retry timeout esistente, senza dover realmente attendere 300s nel test — il test deve verificare la CHIAMATA a `requests.post` con il valore di `timeout` passato, non il tempo reale trascorso).
2. **Verifica diretta del valore di `stream_req_timeout` passato a `requests.post`**: con `timeout_seconds=300` sul job e `idle_read_timeout_seconds` di default (45.0) o esplicitamente passato a `call_structured`, catturare il kwarg `timeout` ricevuto da `requests.post` nel ramo streaming e verificare che sia `<= 45.0` (e non vicino a 300), anche a inizio richiesta quando `rem_sec` sarebbe quasi 300.
3. **Non regressione sul ramo non-streaming**: con `stream=False`, verificare che il kwarg `timeout` passato a `requests.post` rifletta ancora il comportamento pieno basato su `rem_sec` (non ridotto a `idle_read_timeout_seconds`).
4. **Non regressione quando `rem_sec` è già piccolo**: con un job quasi a fine deadline (simulare `t_attempt_monotonic` vicino al deadline), verificare che `stream_req_timeout` coincida con `rem_sec` e non con `idle_read_timeout_seconds` (il `min()` deve scegliere correttamente il più piccolo dei due in entrambe le direzioni).
5. Rieseguire l'intera suite (`python3 -m pytest tests/ -q`) e confermare zero regressioni sui test esistenti (165 attuali + i nuovi).

## Output atteso
Diff completo sui file toccati + output di `python3 -m pytest tests/ -q` con il conteggio finale. Nessun walkthrough testuale dettagliato necessario.
