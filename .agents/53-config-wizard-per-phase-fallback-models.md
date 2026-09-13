# Task 53 — `rt config`: assegnare modelli di fallback (429/timeout/safety/auth/generico) per fase, non solo il modello primario

Dipende dal Task 43 (già completato: carosello a card per `_configure_llm_provider_section`) —
questo task lo ESTENDE, non lo sostituisce. Se lavori nello stesso giro dei Task 44-52, fai
questo per ultimo dato che tocca lo stesso file (`configure.py`) delle sezioni già toccate da
altri task su quel file. Nel progetto RT (/Users/attilioturco/Desktop/trt), implementa
direttamente, senza produrre un piano preliminare.

## Contesto

Motivazione reale dell'utente: usando molte chiavi Google in round-robin (12 chiavi, 4 account),
un giro di test ha prodotto un 429 che — investigato a fondo con un probe empirico dedicato — si
è rivelato causato molto probabilmente da un meccanismo anti-abuso non documentato di Google che
aggrega il traffico tra le chiavi correlate (stesso utente/dispositivo), NON da limiti di quota
per-progetto (che al momento del fallimento erano ampiamente disponibili sul dashboard). La
mitigazione pratica non è "aggiungere altre chiavi Google" (colpite dallo stesso meccanismo
aggregato) ma poter configurare un **fallback esplicito su un provider diverso** (es. un modello
OpenRouter economico) per quando la route primaria fallisce con un errore specifico.

**Lo schema dati esiste già e non va toccato**: `rt/core/config.py`, classe
`JobFallbackConfig` (righe 131-137):
```python
class JobFallbackConfig(BaseModel):
    timeout: Optional[RouteConfig] = None
    rate_limit: Optional[RouteConfig] = None
    safety: Optional[RouteConfig] = None
    auth: Optional[RouteConfig] = None
    generic: Optional[RouteConfig] = None
```
e `JobRoutingConfig.fallback: JobFallbackConfig` (riga 146). `rt/llm/router.py::select_fallback_route`
(righe 104+) già consulta questi 5 slot in base alla classe di errore classificata
(`TimeoutFailure`→`fallback.timeout`, `RateLimitFailure`→`fallback.rate_limit`,
`SafetyFailure`→`fallback.safety`, `AuthenticationFailure`→`fallback.auth`, tutto il resto→
`fallback.generic`) — **questo meccanismo è già interamente funzionante lato esecuzione, il gap
è SOLO che oggi non esiste alcun modo per configurarlo da `rt config`**: l'unico modo per
impostare un fallback oggi è modificare a mano il file YAML del job. Verificato anche perché
spiega un dettaglio della telemetria osservato durante l'indagine sul 429: senza `fallback:`
configurato, `select_fallback_route` ripiega SEMPRE sul ramo "cerca un'altra route non ancora
visitata nello stesso pool round-robin" (`role_tag="fallback_alternative_configured"`,
righe 160-190) — inutile contro un throttling che colpisce l'intero pool di chiavi correlate
insieme, a differenza di un vero fallback su un provider/pool di quota diverso.

## Specifica UX (fornita dall'utente)

Nel carosello a card del Task 43, quando l'utente sceglie un modello per una fase (sia
selezionando un profilo GIÀ ESISTENTE dalla lista, sia creandone uno nuovo con
`_create_new_model_profile`), subito dopo la scelta del modello viene chiesto **il ruolo** con
cui usarlo per QUELLA fase:
- Primario
- Fallback per timeout
- Fallback per rate-limit (429)
- Fallback per errore di safety
- Fallback per errore di autenticazione
- Fallback generico (qualunque altro errore)

Per un profilo esistente, questa domanda appare subito dopo averlo selezionato dalla lista
(prima di tornare alla card). Per un profilo nuovo, questa domanda è l'ULTIMA del questionario
di creazione (`_create_new_model_profile`), dopo che tutto il resto (provider, chiavi, modello,
pricing, nome profilo) è già stato deciso.

**Dopo aver assegnato un ruolo, l'utente NON esce dalla fase corrente**: torna alla stessa card
e può ripetere l'operazione per assegnare un ALTRO modello a un ALTRO ruolo nella stessa fase
(es. prima A come Primario, poi B come Fallback 429, poi B di nuovo come Fallback generico — lo
STESSO modello può coprire più ruoli di fallback diversi contemporaneamente, non c'è alcun
vincolo su questo). L'utente esce dalla fase solo navigando esplicitamente (LEFT/RIGHT/C, come
già oggi).

**Vincolo obbligatorio**: un modello non può essere contemporaneamente Primario e un qualunque
ruolo di Fallback nella STESSA fase. Se l'utente prova ad assegnare a un ruolo di fallback lo
stesso profilo già impostato come primario per quella fase (o viceversa, prova ad assegnare come
primario un profilo già impostato come fallback in quella fase), rifiuta l'assegnazione con un
messaggio chiaro e permetti di scegliere un ruolo diverso o un profilo diverso — non lasciare che
lo stato diventi incoerente.

## Modifica

### 1. Struttura dati: da assegnazione singola a mappa di ruoli per fase

In `_configure_llm_provider_section` (`rt/pipeline/configure.py`, riga 692), `pending_selections`
(riga 745, oggi `Dict[str, str]`: fase → nome-profilo-singolo) diventa una struttura più ricca
per fase, es.:
```python
pending_selections: Dict[str, Dict[str, Optional[str]]] = {}
# per ogni group_label: {"primary": nome_profilo|None, "timeout": ..., "rate_limit": ...,
#                         "safety": ..., "auth": ..., "generic": ...}
```
Aggiorna coerentemente tutti i punti che oggi leggono/scrivono `pending_selections[group_label]`
come stringa singola (inizializzazione alle righe 761-770, la card di riepilogo/conferma righe
781-849, la card di fase righe 867-940) — la label di stato mostrata per ciascuna fase (es. "✅"
vs "⏳" nel pannello di stato, righe 787-789 e 887-891) resta ✅ se almeno `primary` è impostato,
⏳ se non c'è nemmeno quello (i fallback sono sempre opzionali, non condizionano
completato/incompleto).

### 2. Card di fase: mostra tutti i ruoli assegnati, non solo uno

Nel pannello della card di fase (righe 893-905), mostra tutte le assegnazioni correnti per
quella fase, non solo "Assegnazione attuale: X", es.:
```
Primario:              gemini-3.5-flash-lite_google
Fallback timeout:      (non impostato)
Fallback rate-limit:   glm-5.3-flash_openrouter
Fallback safety:       (non impostato)
Fallback auth:         (non impostato)
Fallback generico:     glm-5.3-flash_openrouter
```
La lista di scelte della card (righe 874-879: `keep_label`/`SKIP_LABEL`/profili
esistenti/`NEW_PROFILE`) resta strutturalmente la stessa — selezionare un profilo esistente o
"Nuovo modello" innesca il passo 3 sotto invece di assegnare direttamente ed avanzare come oggi.
Aggiungi anche un'opzione per svuotare un singolo ruolo già assegnato (es. "🗑 Rimuovi
un'assegnazione") che apre un piccolo selettore dei ruoli attualmente occupati per quella fase e
li azzera uno alla volta — necessario perché SKIP_LABEL oggi svuota l'INTERA fase, non un
singolo ruolo.

### 3. Domanda del ruolo dopo la scelta del modello

Dopo che l'utente seleziona un profilo esistente dalla lista (ramo `else:` riga 940, oggi
`pending_selections[group_label] = selected_choice`) o crea un nuovo profilo (ramo
`if selected_choice == NEW_PROFILE:`, righe 931-938), invece di assegnare direttamente, chiedi
il ruolo con un `questionary.select` (o, se preferisci restare nello stile a tastiera del
carosello, con lo stesso meccanismo UP/DOWN/ENTER già usato per le altre scelte — a tua
discrezione, ma verifica cosa risulta più coerente col resto della UI appena costruita dal Task
43):
```
Come vuoi usare '<nome profilo>' per la fase '<group_label>'?
- Primario
- Fallback: timeout
- Fallback: rate-limit (429)
- Fallback: errore di safety
- Fallback: errore di autenticazione
- Fallback: generico (qualunque altro errore)
```
Applica il vincolo primario/fallback (vedi sopra) PRIMA di accettare la scelta: se in conflitto,
mostra l'errore e ripresenta la domanda del ruolo (senza perdere la selezione del modello già
fatta, per non costringere l'utente a rifare la scelta del profilo).

Per un profilo NUOVO creato con `_create_new_model_profile` (`rt/pipeline/configure.py`, riga
199): aggiungi questa stessa domanda come ULTIMO step della funzione, dopo che il profilo è
stato completamente costruito e (se applicabile) salvato — la funzione ritorna oggi
`Tuple[str, Dict[str, Any]]` (nome profilo, dizionario profilo): decidi se estendere il tipo di
ritorno per includere anche il ruolo scelto (es. `Tuple[str, Dict[str, Any], str]`, dove
l'ultimo elemento è il ruolo, es. `"primary"`/`"timeout"`/`"rate_limit"`/`"safety"`/`"auth"`/
`"generic"`) e aggiorna tutti i call site (riga 933 dentro `_configure_llm_provider_section`, e
qualunque altro punto del file che chiama `_create_new_model_profile` — verifica con un grep,
potrebbe essere usata anche da `run_models_management`/`_edit_model_profile` per altri scopi,
in tal caso valuta se serve un parametro opzionale tipo `ask_role: bool = True` per non forzare
questa domanda quando la funzione è invocata da un contesto che non ne ha bisogno, es. editing
di un profilo esistente fuori dal carosello per-fase).

### 4. Scrittura su disco: `_apply_profile_to_job` deve scrivere anche `fallback:`

`_apply_profile_to_job` (riga 535) oggi scrive solo `primary`/`primary_routes`. Estendila (o
aggiungi una funzione dedicata, es. `_apply_fallback_to_job(job_file, slot, profile)`, se
preferisci non appesantire quella esistente) per scrivere anche il blocco `fallback:` del job
YAML, nello slot corrispondente (`timeout`/`rate_limit`/`safety`/`auth`/`generic`), con la stessa
struttura già usata per `primary` (righe 584-593: provider/model/credential/base_url + campi di
tuning). **Nota sullo schema esistente**: `JobFallbackConfig` accetta un SOLO `RouteConfig` per
slot (non una lista round-robin) — se il profilo assegnato a un ruolo di fallback è esso stesso
round-robin (più credenziali), usa la PRIMA route del profilo (`profile["routes"][0]`) come
rappresentante per quello slot: è una limitazione consapevole dello schema attuale, non
introdurre un round-robin anche sui fallback in questo task, è fuori scope.

Quando la card finale "Conferma e applica" (righe 811-849 circa) scrive su disco, itera anche
sui ruoli di fallback assegnati per ciascuna fase, non solo su `primary` (riga 843
`_apply_profile_to_job(job_file, profiles[selection])` va esteso/affiancato da chiamate
analoghe per ciascun ruolo di fallback non vuoto).

## Test

- Test che verifica che assegnare lo stesso profilo come primario e poi tentare di assegnarlo
  anche come fallback (qualunque slot) nella stessa fase venga rifiutato con un messaggio
  chiaro, e viceversa (fallback prima, poi tentativo di renderlo primario).
- Test che verifica che lo STESSO profilo possa essere assegnato a PIÙ slot di fallback diversi
  nella stessa fase (es. sia `rate_limit` che `generic`) senza errori.
- Test che verifica che, dopo "Conferma e applica", il file YAML del job contenga sia `primary`
  (o `primary_routes`) sia un blocco `fallback:` corretto con gli slot assegnati.
- Test che verifica che rimuovere un'assegnazione di fallback (via la nuova opzione "🗑 Rimuovi
  un'assegnazione") svuoti solo quello specifico slot, lasciando invariati primario e altri
  fallback.
- Test end-to-end: assegna primario + 2 fallback diversi in una fase, verifica che
  `select_fallback_route` (già esistente, non toccato da questo task) risolva correttamente le
  route configurate leggendo il file YAML prodotto da questo wizard.

Esegui `python3 -m pytest tests/ -q` e correggi finché l'intera suite passa.

## Vincoli

Verifica il bug di portabilità ricorrente sulle annotazioni `typing` per qualunque riga toccata
(vedi `.agents/00-README.md`).

Non toccare `rt/llm/router.py::select_fallback_route`: è già corretto e già consuma
`job_cfg.fallback` esattamente come serve — questo task riguarda SOLO come quella
configurazione viene scritta da `rt config`, non come viene eseguita.

Non estendere `JobFallbackConfig` per supportare round-robin sui fallback: fuori scope,
usa la prima route del profilo se il profilo assegnato a un fallback è round-robin (vedi sopra).

## Verifica finale

1. `python3 -m pytest tests/ -q`.
2. Test funzionale diretto: lancia `rt config`, in una fase assegna un modello Google esistente
   come primario, poi un modello OpenRouter come fallback rate-limit, poi lo stesso modello
   OpenRouter anche come fallback generico, conferma, e verifica che il file YAML del job
   risultante contenga tutto correttamente. Verifica anche che tentare di assegnare il modello
   Google (già primario) come fallback venga rifiutato a schermo.
