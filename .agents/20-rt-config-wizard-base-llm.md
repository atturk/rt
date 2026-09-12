# Task 20 — `rt config`: scheletro del comando + sezione provider LLM

Dipende solo dallo stato attuale del repo (task 01-18 già completati). Indipendente dal task
19 (migrazione macparakeet) — non lo tocca. È il primo di 3 task che costruiscono insieme il
comando `rt config` (20 = scheletro + provider LLM, 21 = sezione Telegram, 22 = STT/pricing/
rifinitura); esegui in ordine numerico perché 21 e 22 estendono la stessa funzione creata qui.
Nel progetto RT (/Users/attilioturco/Desktop/trt), implementa direttamente, senza produrre un
piano preliminare.

## Contesto

RT oggi si configura editando a mano `config/general.yaml`, i file `config/rt/<job>.yaml` e
`.env` (vedi `docs/CONFIGURATION_REFERENCE.md`). Vogliamo un comando interattivo `rt config`
che guidi l'utente nella configurazione iniziale (o in una modifica successiva — deve essere
rieseguibile senza distruggere ciò che non viene toccato in quella sessione) usando
`questionary` (già dipendenza del progetto, usato in `rt/pipeline/setup.py::_prompt_materia_select`
— non introdurre una libreria TUI diversa, `questionary` copre già select/checkbox/password/
autocomplete/confirm).

Decisioni prese con l'utente:
- `rt config` NON prende una cartella lezione come argomento: opera sulla configurazione
  globale del progetto (`config/`, `.env`), con la stessa logica di risoluzione già usata da
  `load_config()`/`load_env_file()` in `rt/core/config.py`: se `config/` (o `.env`) esiste già
  nella cwd corrente, modifica quelli; altrimenti se esistono nella project root reale
  (`_default_project_root()`), modifica quelli; altrimenti (primo avvio, niente `config/`
  ancora) creali nella project root reale copiando prima `config.example/` → `config/` (stessa
  logica già usata da `install.sh`), poi applica le risposte del wizard sopra quella base.
- Il flusso è composto da sezioni sequenziali, ciascuna con un messaggio di intestazione chiaro
  e la possibilità di saltarla (default "no" su "vuoi configurare X ora?" per le sezioni
  opzionali, vedi task 22). Ogni sezione pre-compila i valori di default con quanto già presente
  in config (se il comando viene rilanciato per modificare una sola cosa, non deve chiedere di
  nuovo da zero tutto quello che è già impostato — mostra il valore attuale come default del
  prompt `questionary`, così basta premere invio per confermarlo).
- Nessun segreto (API key, bot token) va mai scritto in `config/*.yaml`: solo in `.env`, con lo
  stesso meccanismo di `credentials:` + `env_var` già esistente in `RTConfig`/
  `CredentialRegistry` (vedi `rt/llm/credentials.py`, `rt/core/config.py::RTConfig`).

## 1. Scheletro del comando

Nuovo modulo `rt/pipeline/configure.py` (o `rt/cli_config.py` — scegli tu la posizione più
coerente con l'organizzazione esistente, es. `rt/pipeline/setup.py` sta in `rt/pipeline/`
quindi `rt/pipeline/configure.py` è probabilmente la scelta più naturale) con una funzione
principale `run_config_wizard(interactive: bool = True) -> None` (o simile) e un
`configure_config_parser(parser)` seguendo lo stesso pattern di
`rt/pipeline/setup.py::configure_setup_parser`.

Nuovo subparser in `rt/cli.py`:
```
rt config
```
Nessun argomento posizionale. Aggiungi `cmd_config(args)` e registra il subparser nello stesso
punto in cui sono registrati gli altri (`p_set = subparsers.add_parser("setup", ...)` eccetera).
Aggiorna il docstring in cima a `rt/cli.py` (elenco comandi) per includere `rt config`.

Il comando deve funzionare anche a `config/` completamente assente (primo avvio): non chiamare
`_ensure_config_ready` (che fallirebbe proprio perché `config/` non esiste ancora — è
esattamente il caso che `rt config` deve risolvere).

Struttura generale della funzione principale (le sezioni Telegram/STT/pricing verranno aggiunte
nei task 21-22, per ora struttura il codice in modo che aggiungere una sezione sia un blocco
sequenziale indipendente, es. una funzione privata per sezione):

```python
def run_config_wizard():
    print(intestazione di benvenuto)
    config_dir, env_path = _resolve_or_bootstrap_config_paths()   # crea config/ da config.example/ se assente
    _configure_llm_provider_section(config_dir, env_path)         # questo task
    # _configure_telegram_section(...)   # task 21
    # _configure_stt_and_pricing_section(...)  # task 22
    print(riepilogo finale di cosa è stato scritto/lasciato invariato)
```

## 2. Sezione provider LLM (`_configure_llm_provider_section`)

Obiettivo: configurare in modo semplice UN provider/modello condiviso da tutti i job LLM (il
caso comune — la personalizzazione fine per singolo job resta possibile editando a mano i
singoli `config/rt/<job>.yaml`/`config/telegram/<job>.yaml`, già documentata in
`docs/CONFIGURATION_REFERENCE.md`, non serve replicarla nel wizard).

Passi con `questionary`:

1. **Provider**: `questionary.select("Provider LLM principale:", choices=["deepseek",
   "openrouter", "google", "openai_compatible"])`. Se `openai_compatible` non è nella lista dei
   provider già gestiti da `KNOWN_PROVIDER_DEFAULT_BASE_URLS` (`rt/core/config.py`), va bene.

2. **Base URL**: pre-compila con `KNOWN_PROVIDER_DEFAULT_BASE_URLS[provider]` se il provider è
   `deepseek`/`openrouter`/`google` (permetti comunque di modificarlo, es. per un proxy
   personale); per `openai_compatible` richiedi un valore esplicito (obbligatorio, come impone
   già `RouteConfig.model_post_init` — non permettere di proseguire con base_url vuoto per
   questo provider).

3. **API key**: `questionary.password("API key per <provider>:")` (input mascherato). Deriva un
   nome di variabile d'ambiente leggibile, es. `f"{provider.upper()}_API_KEY"` (per `google`
   valuta se serve gestire `google_1`/`google_2` — per la configurazione "semplice" di questo
   wizard basta una singola credenziale `google_1`, la seconda chiave dual-key resta una
   personalizzazione avanzata da fare a mano). Scrivi/aggiorna questa riga in `.env` (leggi il
   file esistente riga per riga, sostituisci la riga se la chiave esiste già, altrimenti
   aggiungila in fondo — non troncare/riscrivere l'intero file perdendo altre righe esistenti,
   es. `RT_TELEGRAM_BOT_TOKEN` già presente). Registra la credenziale in
   `config/general.yaml` sotto `credentials:` con `name`, `provider`, `env_var` (stesso formato
   di `config.example/general.yaml`) — se una credenziale con lo stesso `name` esiste già,
   aggiornala invece di duplicarla.

4. **Modello**: prova a recuperare la lista modelli reale interrogando
   `GET {base_url}/models` con header `Authorization: Bearer {api_key}` (endpoint standard
   OpenAI-compatible, supportato da DeepSeek/OpenRouter/molti server `openai_compatible`; Google
   Gemini via l'endpoint OpenAI-compat dichiarato in `KNOWN_PROVIDER_DEFAULT_BASE_URLS["google"]`
   dovrebbe rispondere allo stesso modo — verificalo con una chiamata reale se hai una chiave di
   test disponibile, altrimenti gestiscilo comunque col fallback sotto). Usa `requests` (già
   dipendenza), timeout breve (es. 8s), **non bloccare mai il wizard** se la richiesta fallisce
   per qualsiasi motivo (timeout, 404, 401, JSON malformato, endpoint che richiede un altro
   schema di risposta): in caso di fallimento stampa un avviso chiaro ("non è stato possibile
   recuperare la lista modelli automaticamente, inseriscilo manualmente") e passa a un prompt di
   testo libero (`questionary.text`). Se la richiesta ha successo, estrai gli ID modello dalla
   risposta (tipicamente `data[].id` nello schema OpenAI `/models`) e proponili con
   `questionary.select` (o `questionary.autocomplete` se la lista è lunga, es. > 15 elementi),
   con una voce "✍️ Inserisci manualmente" in fondo alla lista per chi vuole un modello non
   elencato.

5. **Applicazione a tutti i job**: usa `find_job_yaml_paths(config_dir)` (già in
   `rt/core/config.py`) per trovare tutti i file `<job>.yaml` esistenti in `config/` (creati
   dalla copia di `config.example/` se è il primo avvio) e, per ciascuno, aggiorna SOLO le
   chiavi `primary.provider`, `primary.model`, `primary.base_url`, `primary.credential` (nome
   della credenziale appena registrata) — preserva invariati tutti gli altri campi già presenti
   nel file (`thinking`, `reasoning_effort`, `max_tokens`, `timeout_seconds`, `round_robin`,
   `fallback`, ecc.), leggendo lo YAML con `yaml.safe_load`, modificando solo quelle chiavi nella
   struttura Python, e riscrivendo con `yaml.safe_dump` (attenzione a preservare tipi/valori
   `null` come nell'originale, es. `max_thinking_tokens: null`).

6. Alla fine di questa sezione, stampa un riepilogo (quali job sono stati aggiornati, quale
   provider/modello/credenziale è stato impostato).

## Vincoli generali

- Nessuna chiamata di rete bloccante senza timeout. Nessuna eccezione non gestita deve poter
  interrompere il wizard con uno stacktrace grezzo: qualunque errore di I/O/rete va catturato e
  mostrato come messaggio chiaro, con possibilità di riprovare o saltare il passo.
- Scrittura file sempre atomica dove già esiste un pattern nel codebase (vedi
  `_atomic_write_text`/pattern `tmp + os.replace` usato altrove, es. in
  `rt/core/segments.py::save_segments_json`) per `config/general.yaml` e i file `<job>.yaml`.
  Per `.env` (file di poche righe, riscritto raramente) è accettabile una riscrittura diretta
  purché si preservi il contenuto esistente non toccato.
- Verifica sempre che ogni annotazione `Optional[...]`/`List[...]`/`Dict[...]` da `typing`
  aggiunta in un nuovo file/funzione sia esplicitamente importata (bug di portabilità ricorrente
  documentato in `.agents/00-README.md` — non fidarti del fatto che i test passino, girano su
  Python 3.14 che maschera il problema su versioni precedenti).

## Test

Nuovo file `tests/test_configure_wizard.py`. Il wizard è interattivo (usa `questionary`), quindi
i test devono mockare gli input (`questionary.select`/`text`/`password`, tipicamente via
`monkeypatch` sull'oggetto ritornato o mockando il modulo `questionary` — segui il pattern già
usato per testare altri flussi interattivi nel repo, es. `tests/test_setup.py` se mocka prompt
simili) e mockare `requests.get` per il recupero modelli (sia il caso di successo con una
risposta JSON realistica in stile OpenAI `/models`, sia il caso di fallimento/timeout, per
verificare che il fallback a testo libero funzioni senza sollevare eccezioni).

Copri almeno:
- Primo avvio (nessun `config/` esistente): il wizard crea `config/` da `config.example/` e
  applica le risposte.
- Riesecuzione con `config/` già esistente e valori personalizzati: i valori non toccati dal
  wizard in questa sessione restano invariati (es. `max_tokens` di un job non viene resettato).
- Scrittura `.env`: una chiave già presente viene sostituita in-place, non duplicata; altre
  righe esistenti (es. `RT_TELEGRAM_BOT_TOKEN` se presente) restano intatte.
- Fallback modello manuale quando la richiesta HTTP fallisce.

Esegui `python3 -m pytest tests/ -q` e correggi finché l'intera suite passa (non solo il nuovo
file).

## Verifica finale

1. `python3 -m pytest tests/ -q`.
2. Test manuale in una copia temporanea del repo senza `config/` (es. `/tmp/rt-config-test`,
   clonata da questo repo): esegui `./bin/rt config`, rispondi alle domande della sezione
   provider LLM con valori di prova, verifica che `config/general.yaml` e i file
   `config/rt/*.yaml`/`config/telegram/*.yaml` risultanti abbiano `provider`/`model`/
   `base_url`/`credential` coerenti con le risposte date, e che `.env` contenga la riga della
   API key. Pulisci la cartella temporanea alla fine.
3. Riesegui `./bin/rt config` una seconda volta sulla stessa cartella temporanea e verifica che
   i valori già impostati vengano proposti come default (non richiesti da zero).
