# Task 32 — `rt config`: rimuove il bootstrap "generale" obbligatorio, raggruppa recall/immagini, aggiunge "lascia vuoto"

Dipende dallo stato attuale di `rt/pipeline/configure.py` (task 20-27 già completati) — leggi
per intero `_create_new_model_profile`, `_apply_profile_to_job`, `_find_matching_profile`,
`_configure_llm_provider_section` prima di procedere: questo task le modifica, non le riscrive
da zero. Indipendente dai task 33-34 (che estendono altre parti dello stesso file), ma se
vengono eseguiti nello stesso giro fallo per primo perché gli altri due si appoggiano alla
struttura che questo task ridisegna. Nel progetto RT (/Users/attilioturco/Desktop/trt),
implementa direttamente, senza produrre un piano preliminare.

## Contesto

Test reale su un MacBook Air (funzionante per la prima volta dopo una lunga serie di fix a
`install.sh`) ha mostrato diversi problemi di UX reali nel wizard `rt config`:

1. **"1. Configurazione Provider LLM per ciascuna fase" configura in realtà UN SOLO modello
   all'inizio**, forzato (`_configure_llm_provider_section` crea sempre un primo profilo
   chiamato "generale" prima del loop per-fase) — l'utente lo percepisce come "sto configurando
   IL modello", scoprendo solo dopo che si tratta di un default riusabile. Decisione presa con
   l'utente: **eliminare del tutto questo passo forzato**. Si va direttamente al loop per-fase;
   ogni fase propone "lascia vuoto per ora" o "configura un nuovo modello per questa fase" (più
   eventuali profili già creati in fasi precedenti dello stesso giro o di giri passati).
2. **`"Vuoi configurare più chiavi API per {provider} in round-robin (per distribuire le
   richieste su più account/quote)?"`** è inutilmente lungo — va accorciato a
   `"Vuoi configurare più chiavi API per {provider}?"`.
3. **`"API key per {provider} (lascia vuoto per mantenere esistente):"`** è fuorviante quando
   NON esiste ancora nessuna chiave (caso comune: prima configurazione) — il messaggio deve
   cambiare in base a se `existing_key` è vuota o no.
4. **5 domande identiche per i job di recall** (`recall_quiz`, `recall_mirata`, `recall_vasta`,
   `recall_eval_mirata`, `recall_eval_vasta`) — l'utente vuole UNA sola domanda per l'intero
   "recall", applicata a tutti e 5 i job. Stessa cosa per i 2 job di immagini
   (`image_description`, `image_unit_judge`) — coerente con quanto l'utente aveva già descritto
   in una fase precedente di questa sessione ("per le immagini... basta un modello vision
   leggero e come judge anche questo può essere leggero come modello", implicando lo stesso
   modello per entrambi).
5. **Nessuna opzione "lascia vuoto per ora"** nel selettore per-fase — utile soprattutto per le
   fasi opzionali (immagini, recall) che l'utente potrebbe non voler configurare subito.

## 1. Messaggio round-robin più corto

In `_create_new_model_profile`, riga con `multi_input = questionary.confirm(...)`: cambia il
testo in `f"Vuoi configurare più chiavi API per {provider}?"` (rimuovi la spiegazione sul
round-robin dal testo della domanda — se vuoi mantenerla da qualche parte per chi non sa cosa
significhi, mettila come riga informativa stampata PRIMA della domanda con `print(...)`, non
dentro il testo della domanda stessa).

## 2. Messaggio API key condizionale

Nello stesso file, blocco `if not is_multi: ... api_key_input = questionary.password(f"API key
per {provider} (lascia vuoto per mantenere esistente):", default=existing_key)`: rendi il testo
condizionale a seconda che `existing_key` sia valorizzata o meno:
- Se `existing_key` è non vuota: mantieni il testo attuale ("...lascia vuoto per mantenere
  esistente...").
- Se `existing_key` è vuota (nessuna chiave preesistente, caso tipico prima configurazione):
  usa un testo diverso, es. `f"API key per {provider}:"` senza menzionare "mantenere esistente"
  (che non ha senso se non esiste nulla da mantenere). Valuta se in questo caso vuoi anche
  rendere il campo obbligatorio (richiedi che non sia vuoto, con un ciclo di richiesta se
  l'utente prova a lasciarlo vuoto senza che esista nulla da riusare) — a tua discrezione, ma
  segnalalo chiaramente nel resoconto finale se scegli di NON renderlo obbligatorio.

## 3. Rimuovi il bootstrap forzato del profilo "generale"

In `_configure_llm_provider_section`, rimuovi interamente questo blocco:
```python
if not profiles:
    prof_name, prof_dict = _create_new_model_profile(config_dir, env_path, general_data, default_name_hint="generale")
    if not prof_name:
        print("Operazione annullata dall'utente.")
        return {}
    profiles[prof_name] = prof_dict
    _save_model_profiles(general_data, profiles)
```
Il loop per-fase (che già gestisce correttamente il caso `profiles` vuoto — verificalo, i
`choices` costruiti da `sorted(profiles.keys())` restano semplicemente vuoti in quel caso, nessun
crash atteso) deve partire direttamente. Aggiungi invece, prima del loop, un breve messaggio
introduttivo che spiega cosa sta per succedere (l'utente ha esplicitamente chiesto di chiarire
questo, invece del framing fuorviante attuale), es.:
```python
print("Ora configuriamo il modello LLM da usare per ciascuna fase della pipeline.")
print("Puoi configurarne uno e riusarlo ovunque, oppure uno diverso per fase (es. un modello")
print("più potente per l'outline, uno economico in round-robin per il rewrite, ecc.).")
print("Per ogni fase puoi anche scegliere di lasciarla non configurata per ora.\n")
```
(adatta il testo, l'importante è che chiarisca SUBITO che si sta per configurare per-fase, non
un singolo modello globale).

Rimuovi anche la relativa priorità speciale `elif "generale" in profiles: default_choice =
"generale"` nel calcolo del default choice del loop (righe vicino a "if default_choice is
None") — non ha più senso privilegiare un nome specifico ora che non viene più creato
forzatamente. Sostituiscila con una scelta di default ragionevole: se non c'è
`current_match` e non ci sono profili esistenti proposti come scelta naturale, fai puntare il
default alla nuova opzione "➕ Configura un nuovo modello per questa fase" (vedi punto 5 per la
label esatta della nuova opzione "lascia vuoto").

## 4. Raggruppa i job di recall e di immagini in un'unica domanda ciascuno

Sostituisci `_JOB_DISPLAY_ORDER` (lista piatta di job) con una struttura a **gruppi**, dove ogni
gruppo ha un'etichetta leggibile e la lista dei job YAML sottostanti a cui applicare la stessa
scelta:
```python
_JOB_GROUPS: List[Tuple[str, List[str]]] = [
    ("outline", ["outline"]),
    ("rewrite", ["rewrite"]),
    ("review_asr", ["review_asr"]),
    ("review_science", ["review_science"]),
    ("immagini (descrizione slide/foto + assegnazione a sezione)", ["image_description", "image_unit_judge"]),
    ("recall (quiz, domande mirate/vaste, valutazioni)", ["recall_quiz", "recall_mirata", "recall_vasta", "recall_eval_mirata", "recall_eval_vasta"]),
]
```
Ristruttura il loop in `_configure_llm_provider_section` per iterare sui GRUPPI invece che sui
singoli job: costruisci comunque `job_paths = find_job_yaml_paths(config_dir)` come oggi, ma per
ogni gruppo filtra solo i job del gruppo effettivamente presenti (`[jn for jn in group_jobs if jn
in job_paths]` — salta gruppi/job non trovati, es. se in futuro `image_*` non esistesse per
qualche motivo, così non si rompe). Poi:
- Per determinare `current_match`/`has_unrecognized` del gruppo, verifica il PRIMO job del
  gruppo presente (assunzione ragionevole: i job di uno stesso gruppo vengono configurati
  insieme da questo stesso wizard, quindi in condizioni normali condividono lo stesso stato —
  non serve una logica più sofisticata per il caso raro in cui divergano per modifica manuale).
- Poni la domanda UNA sola volta per il gruppo (`f"Modello per '{group_label}':"` invece di
  `f"Modello per la fase '{job_name}':"`).
- Applica la scelta (profilo esistente, nuovo profilo creato al volo, o "lascia vuoto" — vedi
  punto 5) a **tutti** i job del gruppo con `_apply_profile_to_job`, in un ciclo interno.
- In `job_assignments` (il dizionario ritornato dalla funzione, usato per il riepilogo finale),
  continua a mappare OGNI singolo job del gruppo al valore scelto (non solo il gruppo) — così il
  riepilogo finale resta granulare e leggibile job per job, anche se la domanda è stata posta
  una sola volta.

Aggiorna qualunque altro riferimento a `_JOB_DISPLAY_ORDER` nel file (cercalo con grep prima di
procedere) per usare la nuova struttura a gruppi.

## 5. Aggiungi l'opzione "lascia vuoto per ora"

Nelle scelte proposte per ogni gruppo (`choices` nel loop), aggiungi una nuova opzione sempre
presente (non solo quando c'è una configurazione non riconosciuta, a differenza dell'attuale
`keep_label` che appare solo in quel caso specifico):
```python
SKIP_LABEL = "⏭ Lascia vuoto per ora"
```
Inseriscila nelle scelte (posizione a tua discrezione, es. subito dopo l'eventuale `keep_label`
e prima dei profili esistenti, o in fondo prima di "➕ Configura un nuovo modello" — scegli
l'ordine che ti sembra più naturale). Se l'utente la seleziona:
- NON chiamare `_apply_profile_to_job` per nessuno dei job del gruppo (lascia i file YAML
  invariati — per un job mai configurato prima, questo significa restare al guscio vuoto di
  `config.example/`, esattamente lo stato "non configurato" già gestito correttamente altrove
  nel codebase).
- Registra in `job_assignments[job_name] = "(non configurato)"` per ciascun job del gruppo.

**Verifica che il resto del sistema gestisca bene un job lasciato vuoto**: controlla
`rt/cli.py::_ensure_config_ready`/`_job_config_hint` — questi già producono un messaggio di
errore chiaro quando l'utente prova a eseguire una fase il cui job non ha `provider`/`model`
configurati (verificato in una revisione precedente di questa sessione, dovrebbe già funzionare
correttamente senza modifiche — controllalo comunque con un test manuale mirato, vedi sezione
Test).

## Vincoli

Verifica il bug di portabilità ricorrente sulle annotazioni `typing` per qualunque riga toccata
(vedi `.agents/00-README.md`).

## Test

Estendi/adatta `tests/test_configure_wizard.py` (molti test esistenti assumono la vecchia
struttura con bootstrap "generale" forzato e domande individuali per i 5 job di recall — **non
è una regressione da preservare, è il redesign voluto**, riscrivili per riflettere il nuovo
comportamento invece di provare a mantenerne l'assert letterale, come già fatto nei task
precedenti quando il contratto è cambiato intenzionalmente). Copri almeno:
- Primo avvio, nessun profilo esistente: il loop NON forza la creazione di un profilo "generale"
  prima di iniziare; la prima fase (`outline`) propone "lascia vuoto"/"nuovo modello" come uniche
  scelte disponibili.
- Selezionando "lascia vuoto per ora" per un gruppo, i file YAML dei job di quel gruppo restano
  invariati (guscio vuoto) e `job_assignments` riporta "(non configurato)" per ciascuno.
- Il gruppo "recall" pone UNA sola domanda `questionary.select`/`questionary.confirm` e applica
  lo stesso profilo scelto a tutti e 5 i file `recall_*.yaml` — verifica il contenuto di tutti e
  5 dopo la scelta.
- Il gruppo "immagini" pone UNA sola domanda e applica lo stesso profilo a
  `image_description.yaml` e `image_unit_judge.yaml`.
- Il messaggio dell'API key cambia correttamente in base alla presenza o meno di una chiave
  esistente nell'ambiente (mocka `os.environ` in entrambi gli scenari e verifica il testo del
  prompt passato al mock di `questionary.password`).

Esegui `python3 -m pytest tests/ -q` e correggi finché l'intera suite passa (molti test esistenti
richiederanno modifiche per il cambio di contratto, è atteso).

## Verifica finale

1. `python3 -m pytest tests/ -q`.
2. Test manuale in una copia temporanea del repo senza `config/`: esegui `./bin/rt config`,
   verifica che NON venga mai forzata la creazione di un "primo modello generale" prima del loop
   per-fase, che il messaggio round-robin e quello dell'API key siano quelli nuovi/corretti, che
   `recall`/`immagini` pongano una sola domanda ciascuno, e che "lascia vuoto per ora" funzioni
   (nessun file toccato per quel gruppo). Prova poi a lanciare `./bin/rt run <lezione_mock>
   --mock` (o semplicemente `./bin/rt outline <lezione>` su una fase lasciata vuota) per
   confermare che il messaggio d'errore di configurazione mancante resti chiaro. Pulisci la
   cartella temporanea alla fine.
3. Riporta nel resoconto finale se hai reso l'API key obbligatoria al primo inserimento o no
   (vedi punto 2), e l'ordine scelto per "lascia vuoto per ora" nelle scelte.
