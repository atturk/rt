# Task 25 — `rt config`: supporto a N chiavi in round-robin per lo stesso provider

Dipende dal Task 24 (round-robin N-way in `rt/llm/router.py`/`rt/core/config.py`) — deve essere
già completato prima di questo, altrimenti la configurazione scritta da questo task non
produrrebbe l'effetto voluto a runtime. Dipende anche dallo scheletro di `rt/pipeline/configure.py`
creato nei task 20-22 (leggi quel file prima di procedere: estendi la funzione
`_configure_llm_provider_section` esistente, non riscriverla da zero). Nel progetto RT
(/Users/attilioturco/Desktop/trt), implementa direttamente, senza produrre un piano preliminare.

## Contesto

Oggi `_configure_llm_provider_section` (`rt/pipeline/configure.py`) configura UNA sola API
key/credenziale per il provider scelto e la applica a `primary` in tutti i job. L'utente vuole
poter inserire più chiavi (es. 9) per lo stesso provider e farle ruotare in round-robin — il
Task 24 rende questo possibile a livello di motore/YAML (`primary_routes:` con N voci +
`round_robin: true`); questo task estende il wizard per generare quella configurazione senza
dover editare YAML a mano.

**Attenzione a un bug reale già trovato in una revisione precedente in questo stesso file**: la
pre-compilazione dei valori già esistenti su una riesecuzione del wizard deve leggere
`os.environ.get(env_var_name, "")` DIRETTAMENTE (non `get_api_key(...)`, che in questo percorso
non risolve mai nulla perché il registro `GLOBAL_CREDENTIALS` non è mai popolato da
`load_config()` prima di questa chiamata — vedi il fix già applicato per la singola chiave nella
stessa funzione). Applica lo stesso pattern per ciascuna delle N chiavi.

## Modifiche a `_configure_llm_provider_section`

Dopo la selezione di provider/base_url (passi 1-3 esistenti, invariati), inserisci un nuovo
passo prima della richiesta della singola API key:

1. **Chiedi se round-robin multi-chiave**:
   ```python
   multi = questionary.confirm(
       f"Vuoi configurare più chiavi API per {provider} in round-robin (per distribuire le "
       f"richieste su più account/quote)?",
       default=False
   ).ask()
   ```
   Se `False` (o annullato), prosegui ESATTAMENTE con il flusso a singola chiave già esistente
   (nessuna modifica al comportamento attuale in questo caso — fondamentale per non rompere
   l'uso comune a una sola chiave).

2. **Se `True`, raccogli N chiavi in loop**:
   - Prima rileva quante chiavi round-robin sono già configurate per questo provider su disco
     (rerun): cerca in `config/general.yaml` → `credentials:` tutte le entry con
     `provider == provider_scelto` e nome nel pattern `f"{provider}_<N>"`, e in un file
     `<job>.yaml` qualsiasi (es. il primo restituito da `find_job_yaml_paths`) verifica se ha già
     `round_robin: true` e `primary_routes` con più voci per lo stesso provider — se sì, mostra
     "Trovate N chiavi round-robin già configurate per {provider}" e chiedi se aggiungerne altre,
     sostituirle da zero, o lasciarle invariate (skip).
   - Loop di raccolta: per ogni nuova chiave (a partire dall'indice successivo alle esistenti),
     `questionary.password(f"API key #{i} per {provider} (invio vuoto per terminare se hai già
     inserito tutte le chiavi):")`. Termina il loop al primo input vuoto. Richiedi ALMENO 2 chiavi
     totali (esistenti + nuove) per abilitare davvero il round-robin — se alla fine risulta 1 sola
     chiave, avvisa chiaramente e procedi come singola chiave normale (round_robin: false), senza
     lasciare una configurazione incoerente.
   - Convenzione di naming (usala in modo consistente, anche per la primissima chiave quando si
     sceglie il percorso multi-chiave, per evitare ambiguità con la convenzione a chiave singola
     `f"{provider.upper()}_API_KEY"` usata nel percorso non-multi): credenziale
     `f"{provider.lower()}_{i}"` (i = 1, 2, 3, ...; usa `google_1` come già fa il codice esistente
     per coerenza quando provider è "google"), variabile d'ambiente
     `f"{provider.upper()}_API_KEY_{i}"`.
   - Scrivi ciascuna chiave in `.env` (riusa `_update_env_file`, stesso meccanismo già esistente)
     e registra ciascuna credenziale in `config/general.yaml` → `credentials:` (merge, stesso
     pattern già esistente per la singola credenziale — non duplicare entry già presenti con lo
     stesso `name`).

3. **Recupero modello**: chiedi il modello UNA sola volta (condiviso da tutte le N route — se
   l'utente vuole modelli diversi per chiave può poi personalizzare a mano il YAML, resta
   documentato in `docs/CONFIGURATION_REFERENCE.md`), riusando la stessa logica di recupero
   automatico via `GET {base_url}/models` già esistente nel percorso a chiave singola (con la
   prima chiave inserita, se `api_key` serve per l'header di autenticazione della richiesta).

4. **Scrittura sui file `<job>.yaml`**: per ciascun job trovato da `find_job_yaml_paths`, invece
   di scrivere un blocco `primary:` singolo, scrivi:
   ```yaml
   round_robin: true
   primary_routes:
     - provider: <provider>
       model: <modello>
       credential: <provider>_1
       base_url: <base_url>
       # altri campi (thinking, reasoning_effort, max_tokens, timeout_seconds) copiati dal
       # blocco primary/route esistente in questo job, se presente — vedi sotto
     - provider: <provider>
       model: <modello>
       credential: <provider>_2
       ...
   ```
   **Preserva i campi non-provider/model/credential/base_url** (`thinking`, `reasoning_effort`,
   `max_thinking_tokens`, `max_tokens`, `timeout_seconds`) copiandoli dal blocco `primary:`
   esistente in quel job (se presente) su OGNI voce generata di `primary_routes` — esattamente
   come il percorso a chiave singola preserva questi campi oggi per `primary:` (non introdurre
   una regressione per cui passare a round-robin resetta le impostazioni di tuning già presenti
   in quel job). Se il job aveva già `primary_routes` (round-robin preesistente) invece di
   `primary:`, copia i campi extra dalla prima voce esistente.
   Se l'utente aveva scelto "aggiungi altre chiavi" al passo 2 (rerun), APPENDI le nuove route a
   quelle già presenti in `primary_routes` invece di sostituirle.

5. **Riepilogo**: aggiorna il print di riepilogo esistente per indicare, quando applicabile,
   "Provider configurato in round-robin su N chiavi" invece di una singola credenziale.

## Vincoli

- Nessuna modifica al comportamento del percorso a chiave singola esistente (deve restare
  identico byte-per-byte nel caso `multi=False`, compresi i due bug fix già applicati sulla
  pre-compilazione — non reintrodurli).
- Usa `os.environ.get(...)`, mai `get_api_key(...)`, per leggere valori già presenti
  nell'ambiente in questo modulo (motivazione sopra).
- Verifica il bug di portabilità ricorrente sulle annotazioni `typing` (vedi `.agents/00-README.md`).

## Test

Estendi `tests/test_configure_wizard.py` con almeno:
- Configurazione da zero con 3 chiavi round-robin: verifica `.env` (3 variabili scritte),
  `config/general.yaml` (`credentials:` con 3 entry `provider_1/2/3`), e un `<job>.yaml`
  risultante con `round_robin: true` e `primary_routes` di 3 elementi con i `credential`
  corretti, preservando `max_tokens`/`thinking` preesistenti nel job.
- Riesecuzione che aggiunge una 4ª chiave a un job già configurato con 3 route round-robin:
  verifica che il risultato abbia 4 route (append, non sostituzione) e che le prime 3 restino
  invariate.
- Percorso con 1 sola chiave inserita nel flusso multi (l'utente conferma "sì, voglio
  round-robin" ma poi inserisce una sola chiave): verifica il fallback a configurazione singola
  con avviso, non uno stato incoerente (`round_robin: true` con una sola route).
- Percorso a chiave singola (`multi=False`) invariato: riesegui uno dei test esistenti di questo
  file per confermare che non è stato rotto.

Esegui `python3 -m pytest tests/ -q` e correggi finché l'intera suite passa.

## Verifica finale

1. `python3 -m pytest tests/ -q`.
2. Test manuale end-to-end in una copia temporanea del repo senza `config/`: esegui
   `./bin/rt config`, scegli un provider, rispondi "sì" al round-robin multi-chiave, inserisci 3
   chiavi di prova, verifica i file YAML/.env risultanti. Riesegui `./bin/rt config` una seconda
   volta e verifica che rilevi le 3 chiavi già presenti e permetta di aggiungerne altre. Pulisci
   la cartella temporanea alla fine.
