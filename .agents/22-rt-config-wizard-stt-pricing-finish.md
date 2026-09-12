# Task 22 — `rt config`: motore STT, pricing opzionale, riepilogo finale e docs

Dipende dai task 20 (scheletro) e 21 (sezione Telegram) di `rt/pipeline/configure.py` — leggi
quel codice prima di procedere, aggiungi le sezioni finali alla stessa `run_config_wizard()`
senza riscriverla. Dipende anche dal task 19 (migrazione a `macparakeet-cli`): se il task 19 è
già stato completato, il default di `stt_engine` in `rt/core/config.py` è `"macparakeet"`; se
per qualche motivo non lo fosse ancora, verifica lo stato reale del campo prima di scrivere
questa sezione e adattati di conseguenza (non assumere ciecamente il nome). Nel progetto RT
(/Users/attilioturco/Desktop/trt), implementa direttamente, senza produrre un piano preliminare.

## 1. Sezione motore STT (`_configure_stt_section`)

Configura `telegram.recall.stt_engine` (usato per trascrivere le risposte vocali durante le
sessioni di active recall via Telegram, vedi `rt/core/recall_stt.py`). Prompt
`questionary.select` con le opzioni disponibili nel codice (verifica i valori validi reali in
`rt/core/recall_stt.py::transcribe_voice_answer` — attualmente `"macparakeet"`/`"macwhisper"` a
seconda dello stato del task 19, e `"api"`). Se l'utente seleziona `"api"`, mostra un avviso
chiaro che quel motore non è ancora implementato in RT (`NotImplementedError` nel codice) e
chiedi conferma esplicita prima di scriverlo comunque (per chi vuole prepararlo in anticipo),
altrimenti riproponi la scelta. Scrivi il valore in `config/general.yaml` sotto
`telegram.recall.stt_engine`. Pre-compila col valore già presente se la sezione viene rieseguita.

## 2. Sezione pricing custom (opzionale, `_configure_pricing_section`)

Skippabile di default (`questionary.confirm("Configurare un listino prezzi custom per il
provider/modello scelto? (opzionale, RT ha già stime interne)", default=False)`). Se accettata:
- Riusa provider/modello impostati nella sezione LLM del task 20 (tienili in memoria/passa lo
  stato tra le funzioni della stessa esecuzione del wizard, non richiederli di nuovo).
- Chiedi `input_per_million` e `output_per_million` (float, in USD per 1M token — vedi
  `rt/llm/pricing.py::ModelPricing` per i nomi esatti dei campi) con `questionary.text` e
  validazione numerica (`validate=` di questionary, o un ciclo di retry se il parsing float
  fallisce). `reasoning_per_million` è opzionale: chiedi se il modello ha un costo di reasoning
  separato dall'output standard, default no.
- Scrivi in `config/general.yaml` sotto `pricing.<provider>.<model>` (struttura vista in
  `docs/CONFIGURATION_REFERENCE.md`, sezione pricing custom globale — riusa quella struttura
  esatta, es.:
  ```yaml
  pricing:
    deepseek:
      deepseek-v4-flash:
        input_per_million: 0.14
        output_per_million: 0.28
  ```
  ), preservando eventuali altre voci di pricing già presenti (merge, non sovrascrittura totale
  del dizionario `pricing`).

## 3. Riepilogo finale

Al termine di `run_config_wizard()` (dopo tutte le sezioni: LLM, Telegram, STT, pricing),
stampa un riepilogo chiaro e ordinato di cosa è stato configurato in questa sessione (provider/
modello, job aggiornati, se Telegram è stato configurato e con quanti topic mappati, motore STT,
se il pricing custom è stato impostato), e i prossimi passi suggeriti, sul modello del
riepilogo finale già stampato da `install.sh` (Task 18) — es.:
```
✅ Configurazione completata.

Riepilogo:
- Provider LLM: <provider> / <modello> (applicato a N job)
- Telegram: configurato (M topic mappati) / non configurato
- Motore STT: <engine>
- Pricing custom: impostato per <provider>/<modello> / non impostato

Prossimi passi:
1. Verifica la configurazione con: ./bin/rt status <una_lezione_di_prova>
2. Prova una pipeline di test senza costi con: ./bin/rt run <cartella_lezione> --mock
3. Puoi rilanciare `rt config` in qualsiasi momento per modificare una singola sezione.
```

## 4. Wiring finale nel flusso di installazione

In `install.sh` (Task 18), dopo il passo "3. Configurazione" (copia `config.example/`→`config/`
e `.env.example`→`.env`), aggiungi al messaggio di riepilogo finale (sezione "Prossimi passi")
un'indicazione che `./bin/rt config` è ora disponibile come modo guidato per completare la
configurazione, come alternativa a modificare `config/general.yaml`/`.env` a mano — non
rimuovere le istruzioni manuali esistenti (restano valide e utili come riferimento/fallback),
aggiungi semplicemente l'opzione guidata come raccomandata. Esempio di modifica minima al
messaggio (adatta la numerazione se necessario):
```
Prossimi passi:
1. Esegui './bin/rt config' per una configurazione guidata (chiavi API, Telegram, modelli),
   oppure apri manualmente config/general.yaml e .env se preferisci editarli a mano
   (vedi docs/CONFIGURATION_REFERENCE.md per la sintassi).
2. Per usare 'rt' da qualunque cartella, aggiungi questa riga al tuo ~/.zshrc:
     export PATH="<percorso_reale>/bin:$PATH"
3. Verifica con: ./bin/rt -h
4. Prova una pipeline di test senza costi con: ./bin/rt run <cartella_lezione> --mock
```

In `README.md`, sezione "🚀 Guida Rapida" → "1. Requisiti e Configurazione", subito dopo il
blocco `git clone ... && cd rt && ./install.sh`, aggiungi una riga che menzioni `./bin/rt config`
come passo guidato consigliato per completare le chiavi/i modelli/Telegram, con un rimando a
`docs/CONFIGURATION_REFERENCE.md` per chi preferisce la configurazione manuale completa.

In `docs/CONFIGURATION_REFERENCE.md`, aggiungi una sezione introduttiva breve (in cima, prima
del resto del documento che spiega la sintassi YAML manuale) che presenta `rt config` come il
modo più rapido per iniziare, lasciando il resto del documento invariato come riferimento per la
configurazione manuale/avanzata (multi-route, round-robin, fallback per classe di errore,
pricing per-route, ecc. — cose che il wizard non copre e restano da fare a mano).

## Vincoli

Verifica il bug di portabilità ricorrente sulle annotazioni `typing` (vedi `.agents/00-README.md`).

## Test

Estendi `tests/test_configure_wizard.py`. Copri: selezione motore STT e scrittura in config;
rifiuto/conferma del motore `"api"` non implementato; sezione pricing con merge corretto di
voci preesistenti; il riepilogo finale non solleva eccezioni quando alcune sezioni sono state
saltate (es. Telegram saltato — verifica che il riepilogo lo indichi come "non configurato"
senza `KeyError`/`AttributeError`).

Esegui `python3 -m pytest tests/ -q` e correggi finché l'intera suite passa.

## Verifica finale

1. `python3 -m pytest tests/ -q`.
2. Test manuale end-to-end completo in una cartella temporanea pulita (clonata da questo repo,
   senza `config/`): esegui `./bin/rt config` dall'inizio alla fine attraversando tutte le
   sezioni (LLM, Telegram — puoi saltarla se non hai un bot di test disponibile, documentalo nel
   resoconto — STT, pricing), verifica il riepilogo finale stampato, e verifica che
   `config/general.yaml`/`config/rt/*.yaml`/`.env` risultanti siano coerenti con le risposte
   date. Pulisci la cartella temporanea alla fine.
3. Riporta nel resoconto finale l'elenco completo dei file toccati da tutti e 3 i task del
   comando `rt config` (20, 21, 22) per facilitare la revisione del diff complessivo.
