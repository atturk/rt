# RT 2.0 — Academic Lecture Transcription & Reconstruction Engine

Sistema ibrido industriale per la trascrizione e rielaborazione accademica delle lezioni universitarie.

Combina **codice deterministico** (parsing ASR, normalizzazione temporale in secondi, segmenti strutturati, validazione, decision ledger e assemblaggio Markdown) con **job cognitivi LLM specializzati** (Outline gerarchico vincolato a segmenti, Rielaborazione a finestre con memoria di contesto e provenance, ASR Review con Confidence Gating e Science Critic indipendente — un **LLM-based scientific plausibility critic**: analizza la plausibilità concettuale del testo tramite un modello linguistico, non un sistema di verifica bibliografica/RAG contro fonti esterne).

---

## ⚡ Caratteristiche Principali

- **Timestamp Deterministici e Tracciabili**: Nessun timestamp arbitrario generato dall'LLM. Tutti i timecode nel Markdown derivano rigorosamente dai segmenti audio ASR (`seg_ID → start_seconds → MM:SS`).
- **Provenienza Completa**: Ogni paragrafo rielaborato è collegato in modo bidirezionale ai segmenti sorgente (`source_segment_ids`).
- **Routing Engine Multi-Provider & Dual-Key**:
  - Supporto per DeepSeek, OpenRouter, Google Gemini Dual-Key (`google_1`, `google_2`) e Mock deterministico.
  - Round-Robin deterministico e thread-safe tra Primary e Secondary.
  - Error-Aware Failover mirato per classe di fallimento (`timeout`, `rate_limit`, `safety`, `auth`, `generic`).
  - Loop Protection rigida (`visited_routes`) e Hard Cap globale (`max_attempts`).
  - Output Explosion Guard (limite rigido caratteri in streaming SSE).
- **Confidence Gating a 3 Livelli**:
  - **GREEN**: correzioni ovvie/fonetiche certe (auto-applicate con log).
  - **YELLOW**: ipotesi plausibili ma ambigue (coda di revisione utente).
  - **RED**: termini ad alto rischio o incerti (richiesta conferma d'ascolto).
- **Critic Scientifico Indipendente**: Distingue chiaramente tra lapsus del docente (`ERR_DOCENTE`), allucinazioni del modello (`ERR_RECONSTRUCTION`) e controlli di plausibilità (`SCIENCE_CHECK`).
- **Human Decision Ledger**: Persistenza di tutte le decisioni in `review_decisions.json`. Riproducibile e idempotente.
- **Retrocompatibilità Totale**: Supporta sia le trascrizioni storiche Markdown sia i nuovi export JSON nativi di MacWhisper.

---

## 🚀 Guida Rapida

### 1. Requisiti e Configurazione

Python 3.10+ con dipendenze installate:
```bash
pip install -r requirements.txt
```
Per lo sviluppo e l'esecuzione dei test:
```bash
pip install -r requirements-dev.txt
```

Copia il template per le variabili d'ambiente (opzionale se si usano chiamate LLM reali):
```bash
cp .env.example .env
# Le chiavi che inserirai qui devono corrispondere ai nomi 'env_var' che dichiari
# in config/general.yaml sotto 'credentials:' (vedi docs/CONFIGURATION_REFERENCE.md)
```

Configurazione dei job e dei modelli:
```bash
cp -r config.example config
# Modifica config/general.yaml e i singoli file per-job config/<job>.yaml
```
> I file YAML in `config.example/` sono volutamente senza commenti: il significato di ogni campo e le funzionalità opzionali (credenziali custom, pricing globale/per-route) sono documentati in [Guida alla Configurazione (CONFIGURATION_REFERENCE.md)](docs/CONFIGURATION_REFERENCE.md).


### 2. Esecuzione End-to-End di una Lezione

```bash
./bin/rt run "percorso/cartella_lezione"
```

Per testare offline senza consumare crediti API:
```bash
./bin/rt run "percorso/cartella_lezione" --mock --auto-accept
```

### 3. Esecuzione Passo-Passo

```bash
./bin/rt prepare "cartella_lezione"           # Estrae segmenti e crea segments.json
./bin/rt outline "cartella_lezione"           # Genera outline strutturata con LLM
./bin/rt validate-outline "cartella_lezione"  # Valida monotonicità e copertura
./bin/rt rewrite "cartella_lezione"           # Rielabora a finestre con provenance
./bin/rt validate-draft "cartella_lezione"    # Valida il draft prodotto
./bin/rt review-asr "cartella_lezione"        # Rileva ambiguità ASR con confidence gating
./bin/rt review-science "cartella_lezione"    # Esegue il science critic
./bin/rt review "cartella_lezione"            # Interfaccia interattiva per casi YELLOW/RED
./bin/rt build "cartella_lezione"             # Genera i documenti Markdown definitivi
./bin/rt status "cartella_lezione"            # Mostra lo stato di avanzamento
```

---

## 📚 Documentazione Dettagliata

- [Guida alla Configurazione (CONFIGURATION_REFERENCE.md)](docs/CONFIGURATION_REFERENCE.md)
- [Architettura del Sistema (ARCHITECTURE.md)](docs/ARCHITECTURE.md)
- [Workflow e Ciclo di Vita (WORKFLOW.md)](docs/WORKFLOW.md)
- [Modelli Dati e Contratti JSON (SCHEMAS.md)](docs/SCHEMAS.md)
- [Guida allo Sviluppo e Test Suite (DEVELOPMENT.md)](docs/DEVELOPMENT.md)
- [Motori di Trascrizione Alternativi (ALTERNATIVE_TRANSCRIPTION.md)](docs/ALTERNATIVE_TRANSCRIPTION.md)


---

## 🧪 Esecuzione dei Test

La suite di test comprende unit test, test di validazione timestamp, test del critic scientifico, test del decision ledger e regressione su una lezione reale di biochimica:

```bash
python3 -m pytest tests/
```
