Questo documento è già il piano di implementazione completo e concordato: procedi direttamente alle modifiche, senza produrre un piano separato da approvare prima.

# TASK: Correzioni a basso rischio emerse dall'audit esterno (bug parsing timestamp, dipendenze, wording)

## Contesto

Audit esterno sulla repo + discussione interna hanno prodotto una lista di interventi a basso rischio/costo da applicare subito, distinti dagli interventi respinti (fingerprint con modello/prompt, hash chain del ledger, RAG scientifico — questi ultimi NON vanno toccati, sono stati valutati e scartati deliberatamente per il caso d'uso del progetto: uno strumento personale di studio, non un pacchetto distribuito a terzi).

Sono 4 gruppi di modifiche indipendenti tra loro, raggruppati in un solo task perché ciascuno è piccolo e a basso rischio.

---

## A. Bug fix: parsing timestamp MacWhisper (non solo wording)

### Causa verificata
In `rt/core/segments.py`, funzione `parse_segments_from_json`, "Caso 1" (righe 50-63):
```python
if "start" in item and "end" in item and isinstance(item["start"], (int, float)):
    start_val = float(item["start"])
    end_val = float(item["end"])
    if start_val > 500 or end_val > 500:
        start_sec = round(start_val / 1000.0, 3)
        end_sec = round(end_val / 1000.0, 3)
    else:
        start_sec = round(start_val, 3)
        end_sec = round(end_val, 3)
```
Questo ramo è **esclusivamente** il formato nativo MacWhisper, che esporta sempre `start`/`end` in millisecondi (il commento nel codice lo dichiara esplicitamente: "Caso 1: MacWhisper (start ed end in millisecondi)"). Verificato scandagliando l'intera repo (test, fixture, generatore di dati mock in `rt/pipeline/setup.py`): **non esiste un solo caso reale** in cui questo ramo riceva valori già in secondi. La soglia "> 500" non distingue quindi due formati reali: introduce solo un bug per un caso limite reale — un segmento che inizia e finisce entrambi prima dei 500ms dall'inizio della registrazione (`start_val` e `end_val` entrambi ≤ 500) verrebbe interpretato come se fosse già in secondi, causando un timestamp finale sbagliato di ordini di grandezza (es. 200ms letto come 200 secondi).

### Fix
Rimuovere del tutto l'euristica a soglia, trattare sempre `start`/`end` di questo ramo come millisecondi:
```python
if "start" in item and "end" in item and isinstance(item["start"], (int, float)):
    # MacWhisper esporta sempre start/end in millisecondi (es. 2720 per 2.72s)
    start_val = float(item["start"])
    end_val = float(item["end"])
    start_sec = round(start_val / 1000.0, 3)
    end_sec = round(end_val / 1000.0, 3)
```
Il resto della funzione (fallback `if end_sec <= start_sec: end_sec = start_sec + 1.0`, costruzione del `Segment`) resta invariato.

### Test di accettazione
In `tests/test_segments.py`, aggiungere un test che passa un segmento con `"start": 200, "end": 480` (entrambi sotto la vecchia soglia di 500) e verifica che `start_seconds == 0.2` e `end_seconds == 0.48` (non 200.0/480.0). Verificare anche che i test esistenti che usano valori come `"start": 2720` continuino a passare invariati (comportamento identico per tutti i casi già coperti, dato che l'euristica applicava comunque la conversione ms in quei casi).

### Wording documentazione collegato
In `docs/ARCHITECTURE.md`, sezione "3. Gestione della Provenance e Garanzia sui Timestamp", precisare che la garanzia riguarda la coerenza tra il Markdown finale e `segments.json`, non la correttezza assoluta rispetto alla registrazione audio originale (che dipende dalla correttezza del parsing iniziale, ora irrobustito dal fix sopra). Aggiungere una frase tipo: "Questa garanzia copre la coerenza tra il documento finale e `segments.json`; l'accuratezza di `segments.json` rispetto alla registrazione reale dipende a sua volta dalla correttezza del parsing iniziale della trascrizione grezza."

---

## B. Dipendenze obbligatorie: PyYAML e python-dotenv, rimozione dei parser scritti a mano

### Causa
`rt/core/config.py` ha due parser scritti a mano usati come fallback quando le librerie standard non sono installate:
1. `_simple_yaml_parse()` (righe 337-379): fallback usato in `load_config()` quando `import yaml` fallisce. **Verificato**: questo parser non gestisce affatto la sintassi delle liste YAML (`- item`), quindi un blocco tipo `primary_routes:\n  - provider: ...\n  - provider: ...` verrebbe letto in modo silenziosamente sbagliato.
2. Parsing manuale di `.env` in `load_env_file()` (righe 275-296): implementazione minimale (`k, v = stripped.split("=", 1)`), non copre tutta la semantica di un vero `.env` (es. valori multi-linea, escape).

### Fix
1. Aggiungere `PyYAML` e `python-dotenv` come dipendenze obbligatorie (vedi sezione C, `requirements.txt`).
2. In `rt/core/config.py`:
   - Aggiungere `import yaml` in cima al file (import diretto, non più dentro un `try/except ImportError`).
   - Rimuovere completamente la funzione `_simple_yaml_parse` (righe 337-379).
   - Semplificare `load_config()` (righe ~390-398): sostituire
     ```python
     try:
         import yaml
         data = yaml.safe_load(raw_text)
     except ImportError:
         data = _simple_yaml_parse(raw_text)
     ```
     con semplicemente:
     ```python
     data = yaml.safe_load(raw_text)
     ```
   - Sostituire il corpo di `load_env_file()` (righe 275-296) con una chiamata a `python-dotenv`, mantenendo **esattamente la stessa signature** `load_env_file(dotenv_path: Optional[str] = None, override: bool = False) -> None` per non impattare i 3 punti di chiamata esistenti (`rt/cli.py:719`, `rt/llm/credentials.py:79`, `rt/llm/credentials.py:87`):
     ```python
     def load_env_file(dotenv_path: Optional[str] = None, override: bool = False) -> None:
         """
         Carica variabili d'ambiente da un file .env locale (se presente).
         Non solleva errori se il file non esiste.
         """
         from dotenv import load_dotenv
         if dotenv_path is None:
             dotenv_path = os.path.join(os.getcwd(), ".env")
         load_dotenv(dotenv_path=dotenv_path, override=override)
     ```
     (`load_dotenv` di per sé non solleva eccezioni se il file non esiste, quindi il comportamento "non solleva errori se il file non esiste" resta preservato senza bisogno di try/except espliciti).

### Edge case e invarianti
- Il valore di `override` deve continuare a controllare se le variabili già presenti in `os.environ` vengono sovrascritte (`python-dotenv`'s `load_dotenv(override=...)` ha semantica equivalente).
- Nessuna modifica ai 3 punti di chiamata esistenti.
- **Prima di eseguire i test**, installare la nuova dipendenza nell'ambiente: `pip install python-dotenv` (PyYAML è già presente nell'ambiente attuale).

### Test di accettazione
- In `tests/test_llm_config.py`: i test esistenti che impostano variabili d'ambiente da un file `.env` temporaneo (es. `test_secret_from_dotenv_file`) devono continuare a passare invariati con la nuova implementazione basata su `python-dotenv`.
- Aggiungere un test che verifica che un `rt.config.yaml` con un blocco `primary_routes:` in formato lista venga letto correttamente (oggi funzionerebbe solo se PyYAML è installato; dopo il fix è garantito sempre, dato che PyYAML è obbligatorio).
- Verificare che `_simple_yaml_parse` non sia più referenziata da nessuna parte nel codice o nei test (se un test la importa/testa direttamente, va rimosso insieme alla funzione).

---

## C. `requirements.txt` (packaging minimo, riproducibilità)

Creare `requirements.txt` nella root del progetto:
```
pydantic>=2.13
PyYAML>=6.0
requests>=2.34
python-dotenv>=1.0
```
Creare anche `requirements-dev.txt` per le dipendenze di sviluppo/test:
```
-r requirements.txt
pytest>=9.1
```
Aggiornare `README.md` (sezione "Requisiti e Configurazione", che oggi dice solo "Python 3.10+ con `pydantic` installato") per riflettere l'installazione tramite:
```bash
pip install -r requirements.txt
```
(per lo sviluppo/test: `pip install -r requirements-dev.txt`).

Nota: si è scelto deliberatamente `requirements.txt` invece di un `pyproject.toml` con packaging completo (`pip install -e .`) — il progetto viene eseguito oggi tramite `./bin/rt`, non installato come pacchetto Python; un `pyproject.toml` completo richiederebbe ristrutturare il modo in cui viene invocato, fuori scope per un intervento a basso rischio. `requirements.txt` risolve il problema reale (dipendenze dichiarate e riproducibili) senza toccare il resto.

---

## D. Prompt di rewrite: distinguere fatto/inferenza/conoscenza esterna

### Causa
In `rt/llm/prompts.py`, `REWRITE_SYSTEM_PROMPT` (righe 79-88) chiede contemporaneamente prosa "approfondita" (riga 80) e il divieto di allucinare dettagli non presenti (punto 5, riga 87). Le due istruzioni possono confliggere: un modello potrebbe interpretare "approfondita" come licenza ad aggiungere conoscenza enciclopedica esterna per "arricchire" il testo.

### Fix
Modificare il punto 5 di `REWRITE_SYSTEM_PROMPT` per essere esplicito sulla distinzione, mantenendo lo stile e la numerazione esistente:
```
5. VINCOLO DI FEDELTÀ: NON allucinare dettagli non presenti nella lezione (valori numerici inventati, spiegazioni esterne non dette). "Approfondita" significa esposizione completa e ben argomentata di ciò che il docente ha detto — non aggiunta di conoscenza enciclopedica esterna. Distingui sempre tra: (a) FATTO SORGENTE — ciò che il docente ha detto esplicitamente; (b) INFERENZA DIRETTA — collegamenti logici impliciti ma evidenti nel discorso del docente; ED EVITA (c) CONOSCENZA ESTERNA — nozioni non dette dal docente, anche se vere e pertinenti, che non vanno mai aggiunte.
```

### Test di accettazione
Nessun test automatico possibile per la qualità dell'output LLM (è testo libero) — verificare solo che `REWRITE_SYSTEM_PROMPT` resti una stringa valida e che eventuali test esistenti che verificano la presenza di sottostringhe specifiche nel prompt (es. "VINCOLO DI FEDELTÀ") continuino a passare.

---

## E. Wording ASR confidence (nessun cambio di schema)

### Causa
Il campo `confidence` di `ASRIssue` (`rt/core/models.py`, riga 101) e il system prompt (`rt/llm/prompts.py`, righe 135-136: "Sei un esperto di trascrizioni biomediche e fonetica ASR") suggeriscono una vera valutazione fonetica dell'audio. In realtà il modello riceve solo testo, non l'audio — è quindi una plausibilità linguistica/contestuale stimata dal modello, non una probabilità fonetica calibrata.

### Fix (SOLO wording, NON rinominare il campo JSON `confidence` — sarebbe una modifica breaking allo schema di `asr_issues.json` esistente, fuori scope per un intervento a basso rischio)
- In `rt/core/models.py`, riga 101, aggiornare la `description` del campo:
  ```python
  confidence: float = Field(..., ge=0.0, le=1.0, description="Stima di plausibilità della correzione da parte del modello linguistico (non una probabilità fonetica calibrata sull'audio originale)")
  ```
- In `rt/llm/prompts.py`, righe 135-136, precisare che l'analisi è basata sul testo trascritto, non sull'ascolto diretto:
  ```
  Sei un esperto di terminologia biomedica incaricato di individuare correzioni testuali plausibili in trascrizioni ASR di lezioni universitarie, basandoti sul contesto linguistico e scientifico del testo (non hai accesso all'audio originale).
  ```

### Test di accettazione
Nessun cambio di comportamento atteso: verificare che i test esistenti su `ASRIssue`/`ASR_REVIEW_SYSTEM_PROMPT` continuino a passare (sono modifiche di sola descrizione/testo, il campo `confidence` e la sua validazione numerica restano invariati).

---

## F. Wording Science Critic (nessun cambio architetturale)

Aggiungere, dove il progetto descrive il "Science Critic" (almeno `README.md` riga 5 e `docs/ARCHITECTURE.md` sezione 6 "Grounding Conservativo nel Science Critic"), una clausola esplicita che chiarisce la natura dello strumento, es. aggiungendo dopo la prima menzione:
```
(un **LLM-based scientific plausibility critic**: analizza la plausibilità concettuale del testo tramite un modello linguistico, non un sistema di verifica bibliografica/RAG contro fonti esterne)
```
Nessun cambio di codice, solo testo nei due file di documentazione.

---

## G. Wording precisione documentale (Decision Ledger + pass generale)

- In `docs/SCHEMAS.md`, riga 143: sostituire "Decision Ledger persistito e immutabile." con "Decision Ledger persistito in modo incrementale (append/aggiornamento delle decisioni) — non è un file a sola lettura a livello di filesystem, ma le decisioni già prese non vengono perse tra le esecuzioni."
- Passata generale, leggera, sugli altri termini enfatici già individuati in questa sessione: dove compaiono "garanzia matematica", "immutabile" riferito a concetti che in realtà sono "coerenti/tracciabili" ma non crittograficamente immutabili, preferire un linguaggio più preciso (questo punto si sovrappone parzialmente al punto A per la sezione timestamp — non duplicare la modifica lì già descritta).

---

## Invarianti generali da rispettare in tutto il task

1. Nessuna modifica a `classify_failure`, al routing engine, o a qualunque logica di retry — questo task riguarda solo parsing timestamp, dipendenze/config loading, e testo (prompt/documentazione).
2. Nessun cambio di schema JSON esistente (`ASRIssue.confidence` resta un float 0.0-1.0, nessun campo rinominato).
3. `load_env_file` e `load_config` mantengono le stesse signature e lo stesso comportamento osservabile per tutti i casi già coperti dai test esistenti.
4. Dopo il fix del punto A, tutti i segmenti con `start`/`end` che oggi già superano 500 (la stragrande maggioranza dei casi reali) devono produrre esattamente lo stesso risultato di prima (nessuna regressione silenziosa).

## Verifica finale
Rieseguire l'intera suite (`python3 -m pytest tests/ -q`) e confermare zero regressioni sui test esistenti (169 attuali + i nuovi), dopo aver installato `python-dotenv` nell'ambiente di test.
