# Task 40 — Rimuovi review_asr (inutilizzato), rinomina completamente review_science in review

Indipendente dagli altri task attivi, ma è il PREREQUISITO dei Task 41 e 42 (che estendono la
fase rinominata `review`): fallo per primo. Nel progetto RT (/Users/attilioturco/Desktop/trt),
implementa direttamente, senza produrre un piano preliminare.

**Nota di contesto**: siamo ancora in fase di test, non esistono lezioni reali già processate da
proteggere — l'utente ha esplicitamente richiesto un rename INTERNO completo (non solo il
comando CLI), l'unico vincolo è che lo script resti internamente coerente e funzionante (nessuna
retrocompatibilità richiesta con vecchi nomi di fase persistiti su disco).

## Contesto

Decisione esplicita dell'utente dopo mesi di uso reale: la fase `review_asr`
(`rt/pipeline/review_asr.py`, correzione di termini tecnici biomedici via LLM con confidence
gating GREEN/YELLOW/RED) non porta valore — il modello di rewrite già gestisce da solo il ~95%
dei casi di correzione/comprensione degli errori ASR di Parakeet, e questa fase è di fatto MAI
usata nel flusso reale. Va **rimossa completamente**: modulo, comando CLI, job YAML di
configurazione, prompt LLM dedicato, soglie di configurazione, wiring nella pipeline completa
(`rt run`), integrazione nella review interattiva/Telegram, riferimenti nella documentazione.

Contestualmente, con `review_asr` sparito resta solo una fase di revisione: va rinominata da
`review_science`/`review-science` a semplicemente `review` — **ovunque**, non solo nel comando
CLI: nome del modulo, nome della funzione principale, chiave di fase persistita per
l'idempotenza/checkpointing, nome del file YAML di job/routing LLM, tutte le stringhe interne che
oggi dicono `"review_science"`.

**Cosa NON rinominare**: i nomi delle classi Pydantic `ScienceIssue`, `ScienceType`,
`ScienceSeverity` (in `rt/core/models.py`) restano invariati — descrivono lo SCHEMA delle issue
(claim scientifico + gravità + tipo di errore), non il nome della fase/comando, e rinominarli
comporterebbe un refactor enorme e senza alcun beneficio pratico (sono usati in ~20 file). Stesso
discorso per `science_issues.json` come nome file: resta così com'è, è un dettaglio di
persistenza legato al modello dati (`ScienceIssue`), non al nome della fase.

## Mappa dei punti da toccare (verificata con grep diretto sul codice attuale — riverifica i
numeri di riga esatti al momento dell'implementazione, possono essere leggermente slittati)

### A. Rimozione completa di review_asr

- `rt/pipeline/review_asr.py` (intero file, elimina)
- `config/rt/review_asr.yaml` e `config.example/rt/review_asr.yaml` (elimina)
- In `rt/llm/prompts.py`: `ASR_REVIEW_SYSTEM_PROMPT` e `build_asr_review_user_prompt` (elimina)
- In `rt/core/models.py`: `ASRIssue`, `ASRLevel` (elimina — grep finale obbligatorio per
  verificare che nessun altro modulo li importi più)
- In `rt/core/config.py`: `ConfidenceThresholds` e il campo `RTConfig.thresholds` (righe
  190-192, 263 al momento della stesura) — usato ESCLUSIVAMENTE da `review_asr.py` (riconferma
  con un grep prima di rimuovere: nessun altro file dovrebbe referenziare `config.thresholds` o
  `ConfidenceThresholds`)
- In `rt/cli.py`: sottocomando `review-asr` (parser, `cmd_review_asr`, import di
  `run_review_asr`/`load_asr_issues`, `known_commands`, lista `phases` di `rt run` (riga 449 al
  momento della stesura), calcolo di `required` (riga 536), esecuzione dentro `rt run` (righe
  ~611-621 al momento della stesura: chiamata a `run_review_asr`, stampa step ASR, attesa
  completamento Telegram) — elimina tutto
- In `rt/core/idempotency.py`: rimuovi ogni voce `"review_asr"` da `PHASE_VERSIONS`,
  `PHASE_DEPENDENCIES`, il branch dedicato in `compute_source_fingerprint`, la mappa artefatti
  per fase, `OPTIONAL_UPSTREAM_DEPS`, il branch dedicato in `check_phase_status`, la mappa di
  invalidazione a cascata — vedi punto B sotto per come gestire in parallelo il rename di
  `review_science`→`review` in queste stesse strutture dati
- In `rt/pipeline/build.py`: rimuovi il parametro `asr_issues` e tutta la logica che lo consuma
  (incluso l'eventuale `render_revisioni_asr_md` e l'artefatto `revisioni_asr.md`, se esiste solo
  per questo scopo)
- In `rt/pipeline/ledger.py`: rimuovi `asr_issues`/`apply_asr_decisions_to_text` — attenzione:
  `apply_decisions_to_draft` prende sia `asr_issues` che `science_issues`, la sua firma diventa
  solo `science_issues` (propaga a tutti i chiamanti)
- In `rt/core/lesson_paths.py`: rimuovi `"asr_issues.json"` dall'elenco dei file gestiti
- In `rt/pipeline/issue_review.py`: rimuovi tutta la parte che gestisce issue di tipo `"asr"`
  (`asr_to_review: List[ASRIssue]`, `_build_asr_panel`, il ramo `if issue_type == "asr":`) — la
  parte `science` che resta è la base su cui i Task 41/42 aggiungeranno `ERR_ASR_ST`/
  `ERR_ASR_LLM`, non stravolgerla oltre la rimozione stretta di `asr`

### B. Rename completo review_science → review

Due namespace distinti sono coinvolti, gestiscili entrambi:

**1. Job di routing LLM** (config/general.yaml `jobs:`, file YAML per-job): rinomina
`config/rt/review_science.yaml` → `config/rt/review.yaml` (e l'equivalente in
`config.example/rt/`). `find_job_yaml_paths` (`rt/core/config.py:402`) deriva il nome del job dal
NOME DEL FILE (senza estensione), quindi rinominare il file basta per propagare il nuovo nome
`"review"` ovunque il job venga risolto per routing/credenziali (`rt/llm/router.py`, ecc.) —
verifica comunque che non ci siano riferimenti hardcoded alla stringa `"review_science"` come
nome di job altrove (es. `rt/pipeline/configure.py::_JOB_GROUPS`, riga 606 al momento della
stesura: `("review_science", ["review_science"])` → `("review", ["review"])`).

**2. Fase di pipeline/idempotenza** (namespace separato dal job di routing, usato per
checkpointing e dipendenze tra fasi): in `rt/core/idempotency.py` sostituisci ogni occorrenza
letterale della stringa `"review_science"` con `"review"` in: `PHASE_VERSIONS` (dai anche un
valore di versione pulito tipo `"review_v1.0"`, sarà comunque bumped dal Task 41 quando ne cambia
il comportamento), `PHASE_DEPENDENCIES`, il branch dedicato in `compute_source_fingerprint`, la
mappa artefatti per fase, `OPTIONAL_UPSTREAM_DEPS`, il branch dedicato in `check_phase_status`
(o funzione equivalente), la mappa di invalidazione a cascata (`mark_downstream_stale` o
struttura equivalente). Stesso discorso in `rt/core/state.py` (righe 169, 193-194, 215, 220 al
momento della stesura — che oggi menzionano sia `review_asr` sia `review_science`: rimuovi i
riferimenti ASR per intero, sostituisci `review_science` con `review`).

**Attenzione a un terzo punto, facile da perdere perché è solo una stringa letterale, non un
import**: dentro il modulo stesso (chiamata a `client.call_structured(..., job_name="review_science",
...)`, circa riga 290 al momento della stesura) il nome del job passato per il routing
LLM/telemetria va aggiornato a `job_name="review"` in coerenza col rename del file YAML — se
resta `"review_science"` la risoluzione del job silenziosamente non trova più
`config/rt/review.yaml` (rinominato) e la fase userebbe una configurazione vuota/di default
invece di quella scelta dall'utente in `rt config`.

**3. Modulo e funzione**: rinomina il file `rt/pipeline/review_science.py` →
`rt/pipeline/review.py`, la funzione `run_review_science` → `run_review`. Le funzioni
`get_science_issues_path`/`load_science_issues`/`save_science_issues` possono restare con questo
nome (sono legate al modello `ScienceIssue`, non al nome della fase) — a tua discrezione se
preferisci comunque uniformarle, ma non è richiesto. Aggiorna TUTTI gli import
`from rt.pipeline.review_science import ...` in tutto il repo (`rt/cli.py`, `rt/pipeline/ledger.py`,
`rt/pipeline/build.py`, `rt/core/idempotency.py`, `rt/core/state.py`, test) a
`from rt.pipeline.review import ...`.

**4. Comando CLI**: in `rt/cli.py`, il sottocomando argparse `"review-science"` diventa
`"review"` (help text, funzione `cmd_review_science` → `cmd_review`, chiamata a `run_review`),
il testo di help/usage in cima al file (righe 11-12 al momento della stesura) diventa un solo
comando `rt review <cartella> [--mock]`. Rimuovi `rt review-asr` dall'help.

**5. Documentazione**: `docs/WORKFLOW.md`, `docs/ARCHITECTURE.md`,
`docs/CONFIGURATION_REFERENCE.md`, `docs/SCHEMAS.md`, `docs/DEVELOPMENT.md` — rimuovi ogni
riferimento a `review-asr`/`review_asr`, sostituisci `review-science`/`review_science` con
`review` ovunque si riferisca al comando/fase (non ai nomi di classe `ScienceIssue` ecc., che
restano).

## Test

Ampio footprint di test esistenti da adattare (identificato con grep, verifica anche altri non
elencati qui): `tests/test_asr_m_review.py`, `tests/test_review_asr_draft_aware.py`,
`tests/test_cli_review.py`, `tests/test_ledger.py`, `tests/test_idempotency.py`,
`tests/test_checkpointing.py`, `tests/test_dag_freshness.py`, `tests/test_force_review_ledger_purge.py`,
`tests/test_issue_review.py`, `tests/test_science.py`, `tests/test_integration.py`,
`tests/test_audio_run.py`, `conftest.py` e altri.

Per ciascuno: se il test verifica ESCLUSIVAMENTE comportamento di `review_asr`, rimuovilo insieme
al codice che testa. Se il test verifica comportamento misto o usa la stringa `"review_science"`
come nome di fase/job/import, aggiornalo al nuovo nome `"review"` (import da
`rt.pipeline.review`, chiavi di fase `"review"`) SENZA indebolire le asserzioni.

Aggiungi un test esplicito che verifica che `rt review-asr` e `rt review-science` non esistano
più come sottocomandi (argparse deve rifiutarli con l'errore standard "invalid choice"), e che
`rt review <lezione> --mock` esegua correttamente quello che faceva `rt review-science`.

Esegui `python3 -m pytest tests/ -q` e correggi finché l'intera suite passa. Dato il numero di
file toccati, procedi in modo sistematico: prima rimuovi/rinomina il codice sorgente non di
test, poi esegui la suite e usa i fallimenti per guidare l'aggiornamento dei test uno per uno —
non indovinare quali test toccare, lasciali guidare da pytest.

## Vincoli

Verifica il bug di portabilità ricorrente sulle annotazioni `typing` per qualunque riga toccata
(vedi `.agents/00-README.md`).

Al termine, esegui un grep finale su tutto `rt/`, `tests/`, `config/`, `config.example/`,
`docs/` per `review_asr`, `ASRIssue`, `ASRLevel`, `ConfidenceThresholds`, `asr_issues`,
`review_science`, `review-science`, `review-asr` — non deve restare NULLA (nessun alias, nessuna
retrocompatibilità richiesta in questo giro).

## Verifica finale

1. `python3 -m pytest tests/ -q`.
2. Test funzionale diretto: `rt -h` deve mostrare solo `rt review <cartella> [--mock]`, nessuna
   menzione di `review-asr`/`review-science`; `rt review-asr` e `rt review-science` devono
   fallire con errore argparse; `rt review <lezione> --mock` deve funzionare.
3. Verifica che `rt run` su una lezione mock end-to-end non tenti più una fase ASR review e
   produca comunque un documento finale coerente (senza sezione "revisioni ASR").
