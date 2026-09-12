# Task 36 — `rt config`: bug puntuali trovati in un giro di test reale su MacBook Air

Indipendente dal Task 35. Dipende in parte dal Task 37 (che introduce un `default_base`
alternativo per Google) solo per il punto 4 sotto — se lavori sui due task nello stesso giro,
fai comunque prima questo (36), poi 37 e 38, per isolare i commit per causa. Nel progetto RT
(/Users/attilioturco/Desktop/trt), implementa direttamente, senza produrre un piano preliminare.

## Contesto

Un giro di test empirico end-to-end di `rt config` su un MacBook Air reale (installazione da
zero) ha trovato 5 bug puntuali indipendenti in `rt/pipeline/configure.py`. Sono elencati con
riferimenti di riga esatti — leggi comunque il contesto attorno a ciascuno prima di modificare,
i numeri di riga possono essere leggermente slittati se altri task sono già stati applicati.

### 1. Il campo di selezione modello parte pre-riempito

`_create_new_model_profile`, righe 402-411:
```python
model_in = questionary.autocomplete(
    "Seleziona o digita il modello LLM:",
    choices=models_list,
    default=models_list[0],
    ...
).ask()
```
`default=models_list[0]` pre-seleziona sempre il primo modello restituito dal fetch live (es.
`deepseek/deepseek-v4.1-flash` se è il primo della lista OpenRouter) — l'utente lo osserva come
"un modello predigitato che va cancellato" prima di poter scegliere/digitare il proprio. Va
sempre lasciato vuoto all'apertura: l'utente deve scegliere o digitare attivamente.

**Fix**: rimuovi `default=models_list[0]`, usa `default=None` (o l'equivalente per lasciare il
campo vuoto in `questionary.autocomplete`).

### 2. Nessun avviso "chiave già presente" per il percorso a chiave singola

Il percorso round-robin (righe 262-263) stampa esplicitamente
`f"\nTrovate {len(existing_creds)} chiavi round-robin già configurate per {provider}."` prima di
chiedere cosa fare. Il percorso a chiave singola (righe 309-323, ramo `if not is_multi:`) non ha
un equivalente: si limita a cambiare il testo del prompt in
`f"API key per {provider} (lascia vuoto per mantenere esistente):"` (riga 316) — un dettaglio
facile da non notare in mezzo a una sequenza di altri prompt, a differenza di una riga stampata
separatamente. L'utente ha riportato di non essere stato avvisato che per `openrouter` esisteva
già una chiave configurata da un giro precedente dello stesso wizard.

**Fix**: quando `existing_key` (riga 314) è non vuoto, stampa una riga esplicita PRIMA del
prompt, sullo stile della riga 263, es.:
```python
if existing_key:
    print(f"\nTrovata una chiave già configurata per {provider}.")
```

### 3. Token Telegram placeholder di `.env.example` trattato come "già configurato"

`.env.example:7` contiene `RT_TELEGRAM_BOT_TOKEN=123456:ABC-your-bot-token` come valore di
esempio. `_resolve_or_bootstrap_config_paths` (righe 86-111, in particolare riga 111
`shutil.copy2(example_env, root_env)`) copia `.env.example` in `.env` verbatim alla prima
esecuzione, quindi questo valore placeholder finisce realmente nell'ambiente di chi non ha
ancora configurato Telegram. Il controllo "token già presente" in `_configure_telegram_section`
(righe 775-781):
```python
existing_token = os.environ.get("RT_TELEGRAM_BOT_TOKEN", "")
bot_token = ""
if existing_token:
    masked = existing_token[:6] + "..." if len(existing_token) > 6 else existing_token
    change = questionary.confirm(f"Bot token Telegram già presente ({masked}). Vuoi modificarlo?", default=False).ask()
```
è una semplice verifica di non-vuotezza, quindi tratta il placeholder come un token reale già
configurato (`"Bot token Telegram già presente (123456...)."`, riprodotto empiricamente
dall'utente).

**Fix**: aggiungi una funzione helper (es. `_is_placeholder_or_invalid_bot_token(token: str) ->
bool`) che riconosce il valore letterale del placeholder di `.env.example`
(`"123456:ABC-your-bot-token"`, confronto esatto va bene, non serve regex fuzzy) E,
opzionalmente per robustezza, verifica che il formato assomigli a un vero token Telegram
(pattern tipico `^\d+:[A-Za-z0-9_-]{30,}$` — un vero bot token ha un ID numerico, `:`, poi un
secret di ~35 caratteri; il placeholder ha `123456:ABC-your-bot-token` che NON rispetta questo
pattern per via dei trattini/testo leggibile). Se `_is_placeholder_or_invalid_bot_token`
ritorna `True`, tratta `existing_token` come assente (comportati come se `existing_token` fosse
vuoto: chiedi direttamente il token nuovo, senza il prompt "già presente... vuoi modificarlo?").

### 4. Nessun percorso robusto di errore diagnosticabile nel fetch dei modelli

`_create_new_model_profile`, righe 384-401 (il blocco "4. Recupero Modelli"):
```python
if api_key and effective_base_url:
    try:
        target_url = effective_base_url.rstrip("/") + "/models"
        headers = {"Authorization": f"Bearer {api_key}"}
        resp = requests.get(target_url, headers=headers, timeout=8)
        if resp.status_code == 200:
            body = resp.json()
            if isinstance(body, dict) and "data" in body and isinstance(body["data"], list):
                for item in body["data"]:
                    if isinstance(item, dict) and "id" in item and isinstance(item["id"], str):
                        models_list.append(item["id"])
    except Exception:
        pass
```
Qualunque causa di fallimento (nessuna chiave, HTTP non-200, eccezione di rete, JSON malformato,
endpoint che non implementa `/models`) collassa nello stesso messaggio generico
`"ℹ️ Impossibile recuperare la lista modelli automaticamente."` (riga ~417), rendendo impossibile
distinguere le cause. Questo è stato riprodotto empiricamente sia per `google` (con 12 chiavi
round-robin già configurate: `api_key = collected_keys[0][2]` a riga 380 dovrebbe essere
popolato correttamente da `os.environ.get(ce, "")`, quindi il fallimento non è "nessuna
chiave") sia per `openrouter` (con una singola chiave già esistente).

`default_base` per `google` (`KNOWN_PROVIDER_DEFAULT_BASE_URLS` in `rt/core/config.py:28`) è
`https://generativelanguage.googleapis.com/v1beta/openai` — un layer di compatibilità OpenAI di
Google. È plausibile che questo layer non implementi l'endpoint `/models` di listing (molti
layer di compatibilità OpenAI implementano solo `/chat/completions`), il che spiegherebbe un
fallimento sistematico per `google` indipendentemente da quante chiavi siano configurate,
diversamente da un problema di autenticazione.

**Fix**:
- Sostituisci il generico `except Exception: pass` con una gestione che cattura il motivo
  specifico (nessuna chiave/base url, `resp.status_code != 200` con il codice, eccezione di rete
  con il tipo/messaggio) e stampa un messaggio diagnostico diverso per ciascun caso invece
  dell'unico messaggio "impossibile recuperare" — questo da solo rende il problema
  diagnosticabile per l'utente anche senza il fix specifico sotto.
- Per `google` specificamente: verifica empiricamente (con una richiesta reale, se hai una
  chiave di test disponibile nell'ambiente Antigravity, altrimenti documenta che non hai potuto
  verificarlo) se `GET https://generativelanguage.googleapis.com/v1beta/openai/models` con
  `Authorization: Bearer <key>` funziona. Se NON funziona (404/405/endpoint non supportato),
  aggiungi un percorso alternativo specifico per `provider == "google"` che usa l'endpoint
  nativo Google `GET https://generativelanguage.googleapis.com/v1beta/models?key=<api_key>`
  (autenticazione via query param, non Bearer — è lo schema nativo Google, diverso da quello
  OpenAI-compatibile), estraendo gli ID modello dal campo `name` di ciascun elemento
  (tipicamente nel formato `"models/gemini-2.5-flash"`) e togliendo il prefisso `models/` per
  ottenere l'ID da passare poi alle chiamate reali via il layer OpenAI-compatibile (verifica che
  il formato senza prefisso sia effettivamente quello accettato da `rt/llm/providers/google.py`
  per il campo `model`, per coerenza con come i modelli vengono già invocati altrove nel
  progetto).

### 5. Nessuna pulizia di virgolette per il percorso `lessons_root`

`_configure_telegram_section`, righe 940-952:
```python
lessons_root_in = questionary.text(
    "Percorso assoluto cartella lezioni (lessons_root per Telegram /list e /recall):",
    default=curr_lessons_root
).ask()

if lessons_root_in is not None:
    clean_root = os.path.expanduser(lessons_root_in.strip())
    if clean_root and not os.path.isdir(clean_root):
        print(f"⚠️  Avviso: la cartella '{clean_root}' non esiste attualmente su questo sistema.")
```
Solo `.strip()` + `os.path.expanduser()`, nessuna rimozione di virgolette circostanti. Se
l'utente incolla un percorso copiato con le virgolette (es. da Finder "Copia come percorso", che
su alcuni sistemi include le doppie virgolette), il controllo `os.path.isdir` fallisce anche se
la cartella esiste realmente, riprodotto empiricamente dall'utente
(`⚠️  Avviso: la cartella ''/Users/.../S1/_RT Lezioni'' non esiste...` — notare le virgolette
doppie attorno al path già visibili nel messaggio stesso).

**Fix**: riusa (importa) `clean_input_path` da `rt/pipeline/setup.py` invece di reimplementare
la pulizia inline — è esattamente il caso d'uso per cui esiste già (rimuove virgolette
circostanti e unescape di backslash). Sostituisci `os.path.expanduser(lessons_root_in.strip())`
con `clean_input_path(lessons_root_in)`.

## Test

Per ciascun punto, aggiungi un test mirato in `tests/` (probabilmente in un file esistente
dedicato a `configure.py`, verifica quale):
- Punto 1: verifica che la chiamata a `questionary.autocomplete` per la selezione modello non
  passi più `default=models_list[0]` (o che passi `default=None`).
- Punto 2: verifica che venga stampato un messaggio esplicito quando `existing_key` è non vuoto
  nel percorso a chiave singola (puoi catturare `capsys`/`capfd` o mockare `print`).
- Punto 3: test unitario diretto su `_is_placeholder_or_invalid_bot_token` con almeno: il valore
  letterale del placeholder → `True`; un token realistico tipo
  `"123456789:AAHhqTGxHf9nqDTQGSKZ..."` (35+ caratteri dopo i due punti, valore fittizio non
  reale) → `False`; stringa vuota → comportamento consistente con "nessun token".
- Punto 4: test che verifica che un errore HTTP (es. mock di `requests.get` che ritorna
  `status_code=404`) produca un messaggio diagnostico diverso da un'eccezione di rete (mock che
  solleva `requests.exceptions.ConnectionError`). Se implementi il fallback nativo Google, un
  test che verifica il parsing di una risposta di esempio dell'endpoint nativo (`{"models":
  [{"name": "models/gemini-2.5-flash", ...}]}`) in una lista di ID senza il prefisso `models/`.
- Punto 5: test che verifica che un `lessons_root` incollato con virgolette doppie attorno venga
  ripulito correttamente prima del controllo di esistenza.

Esegui `python3 -m pytest tests/ -q` e correggi finché l'intera suite passa.

## Vincoli

Verifica il bug di portabilità ricorrente sulle annotazioni `typing` per qualunque riga toccata
(vedi `.agents/00-README.md`).

Non toccare la logica di round-robin per le chiavi (righe 250-307): funziona correttamente,
`collected_keys` include già le chiavi esistenti sia per "➕ Aggiungi altre chiavi" (riga 285)
sia per "⏭ Mantieni le chiavi esistenti" (riga 279) — il fetch modelli con chiavi round-robin
già configurate usa correttamente `collected_keys[0][2]`, il problema è solo la mancanza di
diagnostica (punto 4), non la selezione della chiave.

## Verifica finale

1. `python3 -m pytest tests/ -q`.
2. Test funzionale diretto di `rt config` (anche solo la sezione LLM con `rt config` fino al
   primo prompt modello, e la sezione Telegram con `rt config --telegram`) verificando a schermo
   che il campo modello parta vuoto e che il messaggio di errore fetch modelli (se riproducibile
   nell'ambiente Antigravity con una chiave di test) sia ora specifico invece che generico.
