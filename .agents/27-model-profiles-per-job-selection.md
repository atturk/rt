# Task 27 — `rt config`: selezione del modello per singola fase

Dipende dal Task 26 (libreria di profili modello: `_load_model_profiles`,
`_save_model_profiles`, `_create_new_model_profile`, `_apply_profile_to_job` già estratte in
`rt/pipeline/configure.py`) — leggi quel codice prima di procedere, questo task sostituisce
SOLO la parte finale di `_configure_llm_provider_section` (quella che oggi, dopo il Task 26,
applica un unico profilo a tutti i job) con la vera selezione per-fase. Nel progetto RT
(/Users/attilioturco/Desktop/trt), implementa direttamente, senza produrre un piano preliminare.

## Contesto

Il Task 26 ha introdotto la libreria di profili ma ha lasciato il comportamento finale invariato
("un profilo per tutti i job"). Questo task implementa il vero obiettivo: per ciascuna fase
(job), il wizard propone la scelta tra il profilo `"generale"`, qualunque altro profilo già
configurato (in questa sessione o in un run precedente), oppure la creazione al volo di un nuovo
profilo dedicato a quella fase — esattamente come descritto dall'utente:

> ... per ogni fase l'utente può scegliere se usare quel modello, però può anche scegliere di
> aggiungere altri modelli man mano (es. ne aggiunge uno nella fase di outline, poi passa alla
> fase di rewrite e qui può scegliere tra modello generale, modello configurato nella fase di
> outline oppure configurare un nuovo modello) ... se in futuro farà di nuovo `rt config`, i
> modelli configurati in passato saranno salvati.

## Ordine delle fasi nel wizard

Presenta i job in un ordine che segue il flusso naturale della pipeline, non l'ordine alfabetico
di `find_job_yaml_paths`:
```python
_JOB_DISPLAY_ORDER = [
    "outline", "rewrite", "review_asr", "review_science",
    "image_description", "image_unit_judge",
    "recall_quiz", "recall_mirata", "recall_vasta", "recall_eval_mirata", "recall_eval_vasta",
]
```
Costruisci l'ordine finale prendendo prima i job di `_JOB_DISPLAY_ORDER` che esistono davvero
(risultato di `find_job_yaml_paths`), poi in coda qualunque altro job scoperto ma non presente in
questa lista (ordine alfabetico) — così il wizard resta robusto se in futuro vengono aggiunti
altri job senza aggiornare questa costante.

## Rilevamento del profilo attualmente assegnato (fondamentale per i rerun)

Per ogni job, prima di chiedere, determina cosa ha GIÀ configurato leggendo il suo YAML
esistente (`primary`/`primary_routes`/`round_robin`):
- Se il job non ha alcun provider configurato (guscio vuoto, `primary.provider: null`): nessuna
  configurazione attuale, non proporre l'opzione "mantieni".
- Se il job ha una configurazione reale: confrontala con ciascun profilo noto per trovare una
  corrispondenza — stesso `provider`, stesso `round_robin`, stesso insieme di `(credential,
  model)` per tutte le route (confronto come insieme, non sensibile all'ordine, dato che
  l'ordine delle route in un round-robin non è semanticamente distintivo). Se trovi una
  corrispondenza esatta con un profilo esistente: quello è il default proposto per questo job.
  Se la configurazione esistente NON corrisponde a nessun profilo noto (es. modificata a mano,
  o scritta da un run del wizard precedente al Task 26): non scartarla silenziosamente — aggiungi
  una scelta esplicita `"🔧 Mantieni configurazione attuale (non riconosciuta come profilo
  salvato)"` come default proposto, e se l'utente la seleziona NON chiamare
  `_apply_profile_to_job` per quel job (lascia il file invariato).

Implementa questo confronto come una funzione pura testabile separatamente, es.
`_find_matching_profile(job_data: dict, profiles: Dict[str, dict]) -> Optional[str]` (nome del
profilo corrispondente, o `None`).

## Il loop per-fase

Sostituisci i passi 3-4 di `_configure_llm_provider_section` (come lasciati dal Task 26: "usa il
profilo generale/il primo disponibile e applicalo a tutti i job") con:

```python
job_assignments: Dict[str, str] = {}
for job_name, job_file in ordered_jobs:  # ordine da _JOB_DISPLAY_ORDER + coda
    job_data = ... # carica lo YAML del job
    current_match = _find_matching_profile(job_data, profiles)
    has_existing_unrecognized = (current_match is None and _job_has_real_config(job_data))

    choices = []
    default_choice = None
    if has_existing_unrecognized:
        keep_label = "🔧 Mantieni configurazione attuale (non riconosciuta come profilo salvato)"
        choices.append(keep_label)
        default_choice = keep_label
    choices.extend(sorted(profiles.keys()))
    NEW_PROFILE = "➕ Configura un nuovo modello per questa fase"
    choices.append(NEW_PROFILE)

    if default_choice is None:
        default_choice = current_match if current_match else ("generale" if "generale" in profiles else choices[0])

    selection = questionary.select(f"Modello per la fase '{job_name}':", choices=choices, default=default_choice).ask()

    if selection is None:
        # operazione annullata: interrompi qui, ritorna gli assignment fatti finora (non lasciare a metà in modo incoerente — decidi tu il comportamento più sicuro, es. non toccare i job non ancora processati)
        break

    if has_existing_unrecognized and selection == keep_label:
        job_assignments[job_name] = "(configurazione attuale mantenuta)"
        continue

    if selection == NEW_PROFILE:
        profile_name, profile_dict = _create_new_model_profile(config_dir, env_path, general_data, default_name_hint=job_name)
        profiles[profile_name] = profile_dict
        selection = profile_name

    _apply_profile_to_job(job_file, profiles[selection])
    job_assignments[job_name] = selection

_save_model_profiles(general_data, profiles)
# persisti general_data (credenziali/model_profiles) su disco
```
(pseudocodice indicativo — adattalo allo stile e alle funzioni già presenti nel file, in
particolare il pattern di lettura/scrittura YAML già usato ovunque con `_atomic_write_text`).

Nota importante: un profilo creato al volo per il job N deve essere immediatamente disponibile
nelle scelte per i job N+1, N+2, ... successivi nello stesso giro (aggiorna `profiles` in memoria
subito dopo la creazione, non solo a fine funzione).

`_configure_llm_provider_section` ritorna `job_assignments` (stesso contratto già introdotto dal
Task 26: `Dict[str, str]`, job_name → nome profilo o l'etichetta "(configurazione attuale
mantenuta)").

## Aggiornamento del riepilogo finale in `run_config_wizard()`

Sostituisci l'elenco placeholder introdotto dal Task 26 (tutti i job con lo stesso profilo) con
l'elenco REALE `job_profiles` (ora effettivamente differenziato per fase):
```
Modelli assegnati:
- outline: generale
- rewrite: rewrite_rr_gemini
- review_science: science_strong
- recall_quiz: quiz_glm
...
```

## Documentazione

In `docs/CONFIGURATION_REFERENCE.md`, vicino al box "💡 Configurazione Automatica" già esistente
in cima al documento, aggiungi un paragrafo breve che spiega il concetto di `model_profiles:`:
un profilo è un bundle nominato (provider + modello + una o più credenziali, eventualmente
round-robin) che il wizard `rt config` propone di riusare tra una fase e l'altra della pipeline;
è pura comodità del wizard — **`RTConfig`/il motore di routing la ignorano completamente**, ciò
che conta davvero per l'esecuzione resta `primary:`/`primary_routes:`/`round_robin:` in ciascun
`config/<job>.yaml`, scritti dal wizard in base al profilo scelto per quella fase. Chi preferisce
continuare a editare i file a mano può farlo esattamente come prima, ignorando del tutto
`model_profiles:`.

## Test

Estendi `tests/test_configure_wizard.py` con almeno:
- Test dedicato per `_find_matching_profile` (match esatto su provider+round_robin+insieme
  credential/model; nessun match se un solo campo differisce; nessun match se il job non ha
  alcuna configurazione).
- Flusso end-to-end con almeno 3 job fittizi: il primo forza la creazione del profilo
  "generale", il secondo crea un NUOVO profilo dedicato, il terzo riusa quello appena creato al
  passo precedente (verifica che sia già tra le scelte proposte).
- Rerun: un job la cui YAML corrisponde già a un profilo noto → quel profilo proposto come
  default (verificalo ispezionando l'argomento `default=` passato al mock di
  `questionary.select`, stesso pattern già usato nei test esistenti di questo file).
- Rerun: un job con configurazione esistente non riconosciuta (es. scritta a mano con un
  provider/modello che non corrisponde a nessun profilo) → selezionando "mantieni configurazione
  attuale", il file YAML di quel job NON viene toccato (confronta contenuto prima/dopo).

Esegui `python3 -m pytest tests/ -q` e correggi finché l'intera suite passa.

## Vincoli

Verifica il bug di portabilità ricorrente sulle annotazioni `typing` per qualunque riga toccata
(vedi `.agents/00-README.md`).

## Verifica finale

1. `python3 -m pytest tests/ -q`.
2. Test manuale end-to-end in una copia temporanea del repo senza `config/`: esegui
   `./bin/rt config`, crea il profilo "generale", poi per almeno un altro job (es. `rewrite`)
   configura un nuovo profilo round-robin multi-chiave dedicato, e per un terzo job (es.
   `review_science`) riusa quel profilo appena creato. Verifica che i file YAML risultanti siano
   coerenti (job diversi con provider/modelli diversi). Riesegui `./bin/rt config` una seconda
   volta e verifica che ciascun job proponga come default il profilo corretto già assegnato in
   precedenza. Pulisci la cartella temporanea alla fine.
3. Riporta nel resoconto finale l'elenco completo dei file toccati da entrambi i task (26 e 27)
   per facilitare la revisione del diff complessivo.
