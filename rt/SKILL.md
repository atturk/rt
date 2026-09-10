---
name: rt
description: Workflow ibrido avanzato per la rielaborazione accademica delle lezioni universitarie. Combina codice deterministico per segmenti ASR, tracciamento temporale millisecondi, validazione e build finale con job LLM strutturati (Outline, Rewrite a finestre, ASR Review con confidence gating, Science Critic) e Human-in-the-Loop decision ledger.
---

# Workflow RT 2.0: Rielaborazione Accademica Lezioni Universitarie

Architettura ibrida deterministica/cognitiva per la trasformazione di registrazioni audio e trascrizioni ASR in compendi accademici universitari rigorosi, privi di errori concettuali e con ancoraggio temporale esatto.

## 🏛️ Architettura e Principi Fondamentali

1. **Segmenti ASR come Source of Truth**: L'unità atomica di verità è il segmento temporizzato ASR (`segments.json`). Ogni segmento possiede un ID immutabile (`seg_000001`), indici, `start_seconds`, `end_seconds` e testo grezzo.
2. **Vincolo Assoluto sui Timestamp**: Nessun timestamp visualizzato (es. `36:30`) viene inventato o scritto dall'LLM. Il modello seleziona unicamente `start_segment_id` (es. `seg_000184`), e il builder deterministico calcola il timecode matematicamente: `segments[seg_id].start_seconds → format_timestamp()`.
3. **Provenienza Strutturata del Testo**: Ogni unità didattica conserva esplicitamente in `draft.json` la lista dei `source_segment_ids`. Da qualsiasi frase rielaborata è sempre possibile risalire al frammento audio sorgente.
4. **Confidence Gating a Tre Livelli (ASR Review)**:
   - **GREEN** (confidenza ≥ 0.95): correzioni ovvie/fonetiche certe (es. *"glucosio se fosfato"* → *glucosio-6-fosfato*), applicate automaticamente nel ledger con tracciamento.
   - **YELLOW** (confidenza 0.75–0.94): ipotesi plausibili ma ambigue, inserite nella coda di revisione utente.
   - **RED** (confidenza < 0.75): termini ad alto rischio (numeri, dosi, enzimi critici, frasi incerte), richiedono conferma o verifica d'ascolto.
5. **Science Critic Indipendente**: Un job separato contesta il rielaborato distinguendo categoricamente:
   - `ERR_DOCENTE`: lapsus pronunciato dal docente, accompagnato da domanda diplomatica.
   - `ERR_RECONSTRUCTION`: allucinazione o errore introdotto dall'LLM.
   - `SCIENCE_CHECK`: affermazione plausibile ma ad alto rischio da verificare.
6. **Decision Ledger Immutabile**: Tutte le decisioni umane vengono persistite in `review_decisions.json`. Il builder applica le risoluzioni una sola volta in modo idempotente.

---

## 💻 CLI Unificata (`rt`)

Tutte le operazioni sono orchestrate tramite la CLI deterministica:

```bash
# Esecuzione completa end-to-end (modalità standard)
./bin/rt run "<cartella_lezione>"

# Oppure esecuzione fase per fase:
./bin/rt prepare "<cartella_lezione>"
./bin/rt outline "<cartella_lezione>"
./bin/rt validate-outline "<cartella_lezione>"
./bin/rt rewrite "<cartella_lezione>"
./bin/rt validate-draft "<cartella_lezione>"
./bin/rt review-asr "<cartella_lezione>"
./bin/rt review-science "<cartella_lezione>"
./bin/rt build "<cartella_lezione>"     # Assemblaggio deterministico Markdown
./bin/rt status "<cartella_lezione>"    # Stato, segmenti e issue
```

---

## 📂 Struttura della Cartella della Lezione

Ogni lezione processata contiene la seguente struttura riproducibile:

```text
[AAAA-MM-GG] MATERIA - Titolo Lezione/
├── audio.m4a                       # File audio originale
├── info.yaml                       # Metadati e macchina a stati
├── manifest.json                   # Tracciabilità completa e checksum
├── trascritto grezzo.md            # Trascrizione originale grezza (immutata)
├── trascritto grezzo.json          # (Se disponibile) Export ASR nativo mw
├── segments.json                   # Source of truth dei segmenti con start/end in secondi
├── transcript_normalized.md        # Trascritto normalizzato con segment ID per lettura umana
├── outline.json                    # Struttura didattica gerarchica (macro e unità con segment_id)
├── draft.json                      # Testo rielaborato con provenance (source_segment_ids)
├── asr_issues.json                 # Registro delle ambiguità fonetiche con confidenza e livello
├── science_issues.json             # Registro delle anomalie scientifiche rilevate dal critic
├── review_decisions.json           # Ledger atomico delle decisioni umane (ACCEPT/REJECT/EDIT)
├── pre-elaborato.md                # Markdown di lavoro con timecode e marker
├── rielaborato.md                  # Markdown definitivo pulito pronto per lo studio
├── Revisioni ASR.md                # Tabella delle revisioni con coordinate di ascolto audio
├── Errori concettuali.md           # Lapsus docente con spiegazioni e domande diplomatiche
├── Problemi scientifici.md         # Verifiche di fedeltà e correzioni di ricostruzione
└── [AAAA-MM-GG] MATERIA - Titolo.md # Copia intitolata del rielaborato finale
```

---

## 🔄 Macchina a Stati

Lo stato della lezione avanza rigorosamente controllato in `info.yaml` e `manifest.json`:

| Stato (`fase_corrente`) | Significato | Prossimo Passo |
| :--- | :--- | :--- |
| `setup_completato` | Audio trascritto da `rt_setup.py` | `rt prepare` |
| `preparato` | `segments.json` generato e validato | `rt outline` |
| `outline_validata` | Outline gerarchica convalidata | `rt rewrite` |
| `draft_validato` | Rielaborazione completata con provenance | `rt review-asr` |
| `revisione_asr_completata` | Ambiguità fonetiche classificate (GREEN/YELLOW/RED) | `rt review-science` |
| `revisione_scientifica_completata` | Critic scientifico completato | `rt build` |
| `in_attesa_revisione_umana` | Presenza di casi YELLOW/RED in attesa | `rt review-asr` / `rt review-science` |
| `pronto_per_build` | Tutte le issue risolte nel ledger | `rt build` |
| `completato` | File Markdown finali assemblati con successo | Studio / Obsidian / Telegram |

---

## 🔒 Sicurezza e Credenziali

- Le API key per i modelli LLM sono lette **esclusivamente** da variabili d'ambiente (`OPENROUTER_API_KEY`, `DEEPSEEK_API_KEY`) o file `.env` locale non versionato.
- È fatto divieto di cercare chiavi nel Desktop o salvare segreti nei file esportati.
- È supportata la modalità `--mock` per esecuzione offline e test deterministici.
