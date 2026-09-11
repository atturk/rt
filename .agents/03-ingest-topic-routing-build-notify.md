# Task 03 — Ingest semplificato + routing topic Telegram unificato + notifica build sempre attiva

Indipendente — eseguibile in parallelo con 01, 02, 04. Piccola sovrapposizione prevista con 02
su `rt/cli.py`/`rt/telegram/notify.py` (funzioni diverse, non righe adiacenti) e su
`rt/core/config.py` (campi diversi di `TelegramRuntimeConfig`) — si ricompone bene al merge.
**Task 05 dipende da questo task**: non lanciarlo finché questo non è completato.

Nel progetto RT (/Users/attilioturco/Desktop/trt), implementa direttamente questi cambi
correlati, senza produrre un piano preliminare. NOTA: rt/cli.py e rt/telegram/notify.py sono
condivisi con un altro task in corso in parallelo (rimozione conferma outline via Telegram) —
tocca SOLO le righe descritte qui sotto, che riguardano funzioni/blocchi diversi da quello.

PARTE 1 — Ingest: solo Data e Materia richiesti interattivamente, Materia da lista configurata.

1. In rt/core/config.py, classe `TelegramRuntimeConfig` (dopo il campo `topics`), aggiungi:
   ```python
   misc_topic_id: Optional[int] = Field(
       default=None,
       description="message_thread_id del topic 'Varie/Generale' per lezioni la cui materia "
                   "non è mappata in 'topics'. Se non impostato, tali lezioni continuano ad "
                   "andare nel topic Generale nativo di Telegram (nessun message_thread_id)."
   )
   lessons_root: Optional[str] = Field(
       default=None,
       description="Cartella che contiene direttamente tutte le sotto-cartelle di lezione (una "
                   "per lezione, struttura piatta senza annidamento), usata da /list e /recall "
                   "<query> su Telegram per enumerare le lezioni disponibili."
   )
   ```

2. In rt/telegram/config.py, `resolve_topic_id(lesson_dir, topics)` (riga ~31-45): aggiungi un
   terzo parametro opzionale retro-compatibile:
   ```python
   def resolve_topic_id(lesson_dir: str, topics: dict, misc_topic_id: Optional[int] = None) -> Optional[int]:
       ...  # stessa logica di lettura materia da info.yaml
       if not materia or not isinstance(topics, dict):
           return misc_topic_id
       return topics.get(materia, misc_topic_id)
   ```
   (i 5 test esistenti che chiamano `resolve_topic_id(lesson_dir, topics)` a 2 argomenti restano
   validi, il default è `None` = comportamento invariato). Aggiungi anche una nuova funzione:
   ```python
   def reverse_resolve_materia(thread_id: Optional[int], topics: dict) -> Optional[str]:
       """Inversa di resolve_topic_id: la materia mappata su questo thread_id, o None se
       thread_id è il topic Generale o non corrisponde a nessuna voce di 'topics'."""
       if thread_id is None or not isinstance(topics, dict):
           return None
       return next((m for m, tid in topics.items() if tid == thread_id), None)
   ```

3. Aggiorna questi call-site che oggi chiamano `resolve_topic_id(lesson_dir, runtime_cfg.topics)`
   a 2 argomenti, per passare anche `runtime_cfg.misc_topic_id` come terzo argomento:
   - rt/telegram/notify.py: `notify_build_completed` e `notify_issues_ready` (SOLO questa riga
     della chiamata a resolve_topic_id, non toccare altro in questo file — vedi parte 3 sotto
     per l'altro cambio in questo stesso file, fallo nella stessa modifica).
   - rt/pipeline/recall_session.py (2 punti).
   - rt/pipeline/issue_review.py (3 punti) — attenzione: questo file sarà anche oggetto di un
     grosso refactor della UI in un altro task; limitati SOLO ad aggiungere il terzo argomento
     alle chiamate esistenti a resolve_topic_id, non toccare nient'altro in questo file.

4. In rt/pipeline/setup.py, dentro `run_setup`:
   - Rimuovi il prompt interattivo di `argomenti` (cerca dove oggi chiede "Argomenti" a
     schermo): il campo resta `argomenti_val = argomenti.strip() if argomenti else ""`,
     semplicemente non viene più chiesto interattivamente. Il flag CLI `-a/--argomenti`
     (in `configure_setup_parser` e in `p_run` di cli.py) NON va rimosso — resta disponibile
     per uso non interattivo/scriptato, cambia solo il fatto che non c'è più un prompt a
     schermo che lo richiede quando mancante.
   - Sostituisci il prompt libero di `materia` (oggi un `prompt_clean(...)` testuale) con una
     nuova funzione helper:
     ```python
     def _prompt_materia_select(default_guess: str = "") -> str:
         """Propone le materie già mappate in config (telegram.topics) come selezione,
         con una voce 'Altro' per materia libera. Degrada a prompt testuale libero se la
         config non è disponibile, topics è vuoto, questionary fallisce, o non siamo in un TTY."""
         try:
             from rt.core.config import load_config
             topic_keys = sorted(load_config().telegram.topics.keys())
         except Exception:
             topic_keys = []

         ALTRO = "➕ Altro (nuova materia)"
         if topic_keys:
             try:
                 import questionary
                 default_choice = default_guess.upper() if default_guess.upper() in topic_keys else None
                 selection = questionary.select("Materia:", choices=topic_keys + [ALTRO], default=default_choice).ask()
                 if selection is None:
                     print(f"\nOperazione annullata dall'utente.")
                     sys.exit(0)
                 if selection != ALTRO:
                     return selection
             except Exception:
                 pass
         return prompt_clean("Materia (es. BIOINFORMATICA, BIOCHIMICA)", default=default_guess)
     ```
     Usala nel loop esistente che chiede la materia finché non è valorizzata, chiamandola solo
     quando siamo interattivi e su un TTY reale (stessa condizione già usata oggi per gli altri
     prompt interattivi in questa funzione); fuori da un contesto interattivo, mantieni il
     fallback esistente (guess dal nome file o "LEZIONE"). Dopo aver ottenuto `materia_val`,
     applica lo stesso sanitize/uppercase già fatto oggi.

5. In config.example/general.yaml (oggi non ha alcuna sezione `telegram:`), aggiungi:
   ```yaml
   telegram:
     default_channel: "terminal"
     lessons_root: "/percorso/assoluto/cartella/che/contiene/tutte/le/lezioni"
     topics:
       BIOCHIMICA: 123
       FARMACOLOGIA: 456
     misc_topic_id: 789
   ```

6. In docs/CONFIGURATION_REFERENCE.md, aggiungi una nuova sezione che documenta `telegram.topics`,
   `telegram.misc_topic_id`, `telegram.lessons_root`, `telegram.default_channel` (nessuno di
   questi è documentato oggi) — posizionala vicino alla sezione esistente che parla di
   `recall_lessons.yaml`.

PARTE 2 — La notifica "lezione pronta" deve partire sempre, non solo quando --channel=telegram.

7. In rt/cli.py: nella funzione `cmd_build`, oggi la chiamata a `notify_build_completed(...)`
   è dentro `if channel == "telegram":`. Rimuovi quel gate — la chiamata a
   `notify_build_completed` va fatta sempre dopo una build riuscita, indipendentemente dal
   valore di `channel` (che resta usato per altri scopi in quella funzione, se presenti; se
   `channel` non serve più a nient'altro in `cmd_build` dopo questa rimozione, puoi anche
   rimuovere la sua risoluzione, ma solo se verifichi che non è più letto altrove nella
   funzione). Fai lo stesso identico cambio nella funzione `cmd_run`: rimuovi il gate
   `if channel == "telegram":` attorno alla chiamata a `notify_build_completed` in fondo alla
   funzione (channel resta necessario più sopra in cmd_run per la review — non toccare quella
   parte, tocca SOLO il gate attorno a notify_build_completed).
   Rimuovi anche l'argomento `--channel` dal subparser `p_bld` (diventa vestigiale: non è più
   letto da nessuna parte in cmd_build dopo questo cambio).

8. In rt/telegram/notify.py: distingui "Telegram non configurato affatto" da "Telegram
   configurato ma invio fallito". Oggi (verifica il codice esatto) probabilmente c'è un
   `try: tg_cfg = load_telegram_config() except TelegramConfigError as e: print(warning); return`
   che stampa lo stesso avviso in entrambi i casi. Cambia perché il caso "config assente/non
   impostata" (nessuna variabile d'ambiente/credenziale Telegram impostata) non stampi nulla
   (no-op silenzioso, dato che ora questa funzione viene chiamata sempre anche da chi non ha
   mai configurato Telegram), mentre il caso "config presente ma la chiamata API fallisce"
   (errore di rete/HTTP) continui a stampare il warning attuale su stderr. La funzione deve
   restare comunque fire-and-forget (mai sollevare eccezioni verso il chiamante).

9. Esegui la test suite (pytest tests/ -q) e assicurati che passi. Aggiorna/aggiungi test per
   `resolve_topic_id` col nuovo terzo argomento e per `reverse_resolve_materia`, e per il nuovo
   comportamento silenzioso di notify_build_completed quando Telegram non è configurato.
