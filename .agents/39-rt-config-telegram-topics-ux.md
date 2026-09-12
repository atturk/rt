# Task 39 — Telegram: discovery topic senza fallback forzato, anonimizzazione esempio, `rt config --topics`

Indipendente dagli altri task attivi. Nel progetto RT (/Users/attilioturco/Desktop/trt),
implementa direttamente, senza produrre un piano preliminare.

## Contesto

Tre problemi indipendenti trovati in un giro di test reale sulla configurazione Telegram
(`rt/pipeline/configure.py`, funzione `_configure_telegram_section`, def a riga 760).

### 1. La discovery live, se fallisce, entra SEMPRE nel link manuale senza possibilità di ritentare

Il menu iniziale (righe 795-802) offre 3 scelte: discovery live, link manuale, salta. Se
l'utente sceglie discovery live e questa non rileva nulla entro il timeout (righe 808-882, 180
secondi), il controllo a riga 884:
```python
if (mode and mode.startswith("🔗")) or (not topics_map and not detected_chat_id and mode and not mode.startswith("⏭")):
    if mode and mode.startswith("📡") and not topics_map:
        print("\n⚠️  Nessun messaggio rilevato via discovery live.")
        print("Verifica che il bot sia nel gruppo e che abbia i permessi di lettura messaggi.")

    print("\n--- 🔗 Inserimento Manuale via Link Topic ---")
    while True:
        link = questionary.text(...).ask()
```
entra SEMPRE ed incondizionatamente nel loop di inserimento manuale via link quando la
discovery non ha trovato nulla — non c'è modo di ritentare la discovery (es. dopo aver
sistemato i permessi del bot nel gruppo, come suggerito dal messaggio stesso) né di annullare
del tutto senza uscire dal wizard con Ctrl+C. Riprodotto empiricamente dall'utente, che nel
frattempo aveva anche incontrato un errore preesistente e indipendente
(`⚠️ Conflitto 409: sembra che 'rt telegram-daemon' sia già attivo per questo bot. Fermalo prima
di proseguire.` — la discovery e il daemon condividono lo stesso bot token e non possono fare
polling `getUpdates` in contemporanea; questo conflitto specifico NON è in scope di questo task,
è un vincolo noto dell'API Telegram, ma è il motivo per cui la discovery può fallire anche con
tutto configurato correttamente, rendendo ancora più importante poter ritentare invece di
finire forzatamente nel link manuale).

**Fix**: quando la discovery live termina senza risultati, mostra un menu (invece di entrare
direttamente nel link manuale) con almeno 3 opzioni: "🔄 Riprova discovery live", "🔗 Passa
all'inserimento manuale via link", "⏭ Annulla/salta questa parte". Solo scegliendo la seconda
opzione si entra nel loop di inserimento link esistente (righe 890+, logica interna invariata).
Se l'utente sceglie "Riprova", rilancia lo stesso blocco di discovery (righe 808-882) da capo.

### 2. Esempio con un ID di canale/gruppo reale nei messaggi di prompt

Tre punti nel file usano lo stesso esempio con un ID reale riconducibile a un canale privato
esistente (`4490473926`, `541`, `679`):
- riga 892: `"Incolla il link a un messaggio del topic (es. https://t.me/c/4490473926/541/679) [invio per terminare]:"`
- riga 898: `"❌ Formato link non valido. Esempio atteso: https://t.me/c/4490473926/541/679"`
- riga 27 (docstring della funzione di parsing del link): stesso esempio.

**Fix**: sostituisci l'ID con valori chiaramente fittizi/inventati che non corrispondano a
nessun canale reale (es. `https://t.me/c/1234567890/12/34` — un ID a 10 cifre generico, non
riconducibile a un utente specifico). Applica la stessa sostituzione in tutti e 3 i punti
(inclusa la docstring), e verifica con un `grep -rn "4490473926" rt/` che non resti nessun altro
riferimento nel codice.

### 3. Nessun modo per gestire i topic già configurati dopo il setup iniziale

Oggi `rt config --telegram` (flag esistente, gestito in `rt/cli.py::cmd_config` righe 685-687,
implementato da `run_telegram_only` in `configure.py` riga 1162) rilancia l'INTERA sezione
Telegram da capo (bot token, discovery/link, lessons_root) — non c'è modo di limitarsi a
listare, rinominare, aggiungere o rimuovere singole mappature materia→topic già salvate senza
passare di nuovo per token/discovery.

**Fix**: aggiungi un nuovo flag `rt config --topics`, sullo stesso pattern di `--models` e
`--telegram` già esistente:
- In `configure_config_parser` (`rt/pipeline/configure.py`, righe 1339-1344): aggiungi
  `group.add_argument("--topics", action="store_true", help="Apre direttamente il menu di
  gestione dei topic Telegram già configurati (senza attraversare l'intero wizard)")` allo
  stesso `group` mutuamente esclusivo.
- In `rt/cli.py::cmd_config` (righe 681-690): aggiungi un ramo
  `elif getattr(args, "topics", False): from rt.pipeline.configure import
  run_topics_management; run_topics_management()`.
- Implementa `run_topics_management()` in `configure.py` (stesso stile di
  `run_models_management`, verifica quella funzione come riferimento diretto per pattern e
  convenzioni di UI: caricamento config, `questionary.select` con le materie/topic esistenti,
  azioni disponibili). Deve permettere, sui topic già salvati in
  `config/general.yaml` → `telegram.topics` (chiave = nome materia, valore = `chat_id`/
  `message_thread_id`, verifica lo schema esatto leggendo `rt/telegram/config.py` e come
  `_configure_telegram_section` scrive `topics_map` oggi):
  - Listare le mappature esistenti (materia → chat_id/topic_id) in modo leggibile.
  - Rinominare la materia associata a un topic (senza toccare chat_id/topic_id).
  - Rimuovere una mappatura.
  - Aggiungere una nuova mappatura riusando il flusso di discovery-live O link-manuale già
    esistente in `_configure_telegram_section` (estrai quella logica in una funzione
    riutilizzabile se non lo è già, es. `_discover_or_link_single_topic(bot_token) -> Optional[Tuple[str,int,int]]`,
    così sia `_configure_telegram_section` che `run_topics_management` la chiamano senza
    duplicare codice) — richiede comunque un bot token già configurato: se assente, avvisa
    l'utente di lanciare prima `rt config --telegram`.
  - Modificare direttamente chat_id/topic_id di una mappatura esistente (per il caso in cui il
    topic sia stato spostato/ricreato su Telegram).

## Test

- Test che verifica che, dopo una discovery live senza risultati (mocka la funzione di
  discovery per restituire "nessun risultato"), venga mostrato il menu con le 3 opzioni invece
  di entrare direttamente nel link manuale — e che scegliendo "Riprova" la funzione di discovery
  venga richiamata una seconda volta.
- Test che verifica (via `grep`/lettura statica del file, o assert su una costante) che
  l'esempio di link non contenga più `4490473926`.
- Test per `run_topics_management`: lista/rinomina/rimozione di una mappatura esistente (mocka
  `config/general.yaml` con 2-3 topic pre-esistenti, verifica che dopo rinomina/rimozione il
  file scritto rifletta correttamente il cambiamento e non tocchi le altre mappature).
- Test che verifica la mutua esclusività dei flag CLI: `rt config --models --topics` deve
  fallire con l'errore standard di argparse per gruppo mutuamente esclusivo (stesso
  comportamento già testato per `--models`/`--telegram`, verifica il test esistente e replicalo
  per la nuova combinazione).

Esegui `python3 -m pytest tests/ -q` e correggi finché l'intera suite passa.

## Vincoli

Verifica il bug di portabilità ricorrente sulle annotazioni `typing` per qualunque riga toccata
(vedi `.agents/00-README.md`).

Non toccare la gestione del conflitto 409 (`rt telegram-daemon` già attivo): è un vincolo noto
dell'API Telegram (un solo consumer di `getUpdates` per bot token), non un bug, e non è in
scope di questo task — se vuoi, puoi migliorare il messaggio d'errore esistente per suggerire
esplicitamente il comando per fermare il daemon (verifica se esiste già un comando tipo `rt
telegram-daemon stop` o simile), ma non è richiesto.

## Verifica finale

1. `python3 -m pytest tests/ -q`.
2. Test funzionale diretto (se hai un bot Telegram di test disponibile nell'ambiente
   Antigravity; altrimenti documenta esplicitamente che non è stato possibile e sarà l'utente a
   verificarlo): `rt config --topics` con almeno un topic preesistente, verifica lista/rinomina/
   rimozione a schermo e che `config/general.yaml` rifletta correttamente le modifiche.
