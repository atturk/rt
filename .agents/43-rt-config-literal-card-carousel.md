# Task 43 — `rt config`: card carousel letterale per le fasi LLM (corregge il Task 38)

Sostituisce/corregge il Task 38 (già implementato ma con un meccanismo diverso da quello
richiesto — vedi sotto). Esegui questo task DOPO il Task 40 (rimozione review_asr, rename
review_science→review): il Task 40 cambia l'elenco dei gruppi di fasi che questa schermata deve
mostrare (`_JOB_GROUPS`), quindi va fatto prima per evitare di lavorare su un elenco che sta per
cambiare sotto i piedi. Non serve invece aspettare i Task 41/42 (toccano `review.py`, non
`configure.py`, nessun conflitto). Nel progetto RT (/Users/attilioturco/Desktop/trt), implementa
direttamente, senza produrre un piano preliminare.

## Perché questo task esiste

Il Task 38 chiedeva una UI "a blocchi navigabili avanti/indietro, stile science-review". È stato
implementato con `questionary.select` e voci di menu testuali "⬅️ Fase precedente"/"➡️ Fase
successiva" (in `rt/pipeline/configure.py::_configure_llm_provider_section`) — funzionalmente
nella direzione giusta (navigazione libera, scrittura differita a conferma, modifica dopo
conferma) ma NON la UI richiesta: niente frecce dirette, niente rendering a card, resta un
elenco di scelte testuali una sopra l'altra. L'utente ha ora precisato ulteriormente la UX
desiderata (dettagliata sotto) — implementa QUELLA, non una tua interpretazione alternativa.

## Specifica UX (fornita dall'utente, non negoziabile nei dettagli)

- Una **card per ciascuna fase/gruppo che richiede un LLM**: outline, rewrite, `review`
  (rinominata dal Task 40), il gruppo `recall` (5 job), il gruppo `immagini`/add-images (2 job) —
  stessa lista di gruppi già calcolata da `_JOB_GROUPS`/`grouped_jobs` in
  `_configure_llm_provider_section`, non cambiare quella logica di raggruppamento.
- Su ciascuna card, le opzioni disponibili sono: **Salta** (lascia non configurato), **scegli un
  modello tra quelli già creati** (i profili salvati esistenti), oppure **crea un nuovo
  modello**.
- Solo se l'utente sceglie "crea un nuovo modello" si apre un VERO questionario (sequenza di
  domande `questionary` una alla volta, come oggi) che chiede base URL, API key, nome del
  profilo, provider, pricing e il resto — questo è esattamente `_create_new_model_profile`
  così com'è oggi, NON va riscritto come card: resta un flusso a domande sequenziali classico,
  si apre SOPRA/AL POSTO del carosello di card solo per la durata di quella creazione, poi si
  torna al carosello con quella card ora assegnata al nuovo profilo.
- Dopo aver assegnato/lasciato in sospeso tutte le card, l'utente può confermare in due modi
  equivalenti: **scorrendo con la freccia destra oltre l'ultima card** (arrivando a una card
  finale di conferma), oppure **selezionando un'opzione di conferma esplicita fuori dal
  carosello** (non dentro il flusso di scelta di una singola card). Confermare chiude
  definitivamente tutte le configurazioni aperte e salva tutto così com'è in quel momento.
- Dopo la conferma, deve restare possibile riaprire la configurazione e modificarla (stesso
  concetto già presente nell'implementazione attuale: una schermata di riepilogo con
  Conferma/Modifica).

## Implementazione

Riusa esplicitamente l'infrastruttura già esistente nel repo per UI a card testuali —
`rt/pipeline/issue_review.py::run_interactive_review` (righe 351-900 circa) è il precedente
diretto e funzionante: `rich.Live(console=console, auto_refresh=False, transient=False,
vertical_overflow="visible")` per il rendering in-place, `rt.core.keyboard.raw_mode()` +
`read_single_key(already_raw=is_raw)` per l'input a tasto singolo (supporta nativamente
`"LEFT"`/`"RIGHT"`/`"UP"`/`"DOWN"`, vedi `rt/core/keyboard.py:60-67`), un `rich.Panel` per card
con titolo che mostra la posizione (`f"... [{idx + 1}/{total}]"`). Non inventare un meccanismo
diverso.

Struttura proposta per `_configure_llm_provider_section` (`rt/pipeline/configure.py`, riga 692
al momento della stesura):

1. Calcola `grouped_jobs` come oggi (righe 718-729, invariato).
2. Stato locale: `curr_idx` (card corrente, `0..len(grouped_jobs)`, dove l'indice
   `len(grouped_jobs)` rappresenta la card finale di conferma), `pending_selections` (come
   oggi), più un secondo indice per la posizione DENTRO la card corrente (quale opzione tra
   Salta/profilo-1/profilo-2/.../Nuovo è attualmente evidenziata — UP/DOWN ci si muove, non
   LEFT/RIGHT che restano riservati al cambio di card).
3. Loop principale con `raw_mode()`/`Live`:
   - Se `curr_idx < len(grouped_jobs)`: disegna la card per quel gruppo — nome del gruppo,
     assegnazione attuale (o "non configurato"), l'elenco delle opzioni (Salta, profili
     esistenti, Nuovo) con quella attualmente evidenziata marcata visivamente (es. `▶` o colore
     diverso). Un'intestazione FISSA sopra il carosello (non dentro il pannello della singola
     card, o comunque sempre visibile) mostra lo stato ✅/⏳ di TUTTE le fasi, non solo quella
     corrente — così l'utente vede l'avanzamento complessivo senza dover scorrere.
   - Tasti: `UP`/`DOWN` spostano l'opzione evidenziata dentro la card corrente; `LEFT`/`RIGHT`
     cambiano card (salvando in `pending_selections` l'opzione evidenziata al momento del
     cambio, SENZA scrivere nulla su disco); `Invio`/`Spazio` conferma l'opzione evidenziata per
     quella card — se è "Nuovo modello", ferma il rendering (`live.stop()`), esegui
     `_create_new_model_profile` esattamente come oggi, poi `live.start()` e aggiorna
     `pending_selections` per quella card col nuovo profilo creato; se è un profilo esistente o
     "Salta", aggiorna semplicemente `pending_selections` e resta sulla stessa card (l'utente
     può comunque muoversi con LEFT/RIGHT quando vuole); un tasto per tornare direttamente alla
     card di conferma da qualunque punto (es. `C` o `F`, documentalo nell'help a schermo).
   - Se `curr_idx == len(grouped_jobs)`: disegna la card finale di conferma — riepilogo di tutte
     le assegnazioni pendenti (stile riepilogo già presente nell'implementazione attuale del
     Task 38, righe 772-779), con due azioni: **Conferma e applica** (scrive tutto su disco:
     `_apply_profile_to_job` per ogni gruppo, `_save_model_profiles`, come fa oggi il ramo
     `confirm_action.startswith("✅")`) e **torna indietro a modificare** (`LEFT` riporta
     all'ultima card di fase). Raggiungere questa card sia navigando `RIGHT` oltre l'ultima fase
     sia — se preferisci offrire anche una scorciatoia diretta dal punto 3 sopra (il tasto `C`/`F`)
     — tramite quella scorciatoia: entrambe le vie devono portare alla STESSA card di conferma,
     non a due schermate diverse.
4. Nessuna scrittura su disco (`_apply_profile_to_job`, `_save_model_profiles`,
   `_atomic_write_text` su `general.yaml`) deve avvenire PRIMA che l'utente prema esplicitamente
   "Conferma e applica" sulla card finale — eccezione accettabile e preesistente: la creazione di
   un NUOVO profilo (`_create_new_model_profile`) scrive già le sue credenziali/profilo su
   `general.yaml`/`.env` nel momento in cui viene creato (side-effect preesistente, già presente
   nell'implementazione attuale, accettabile perché il profilo resta comunque riusabile anche se
   l'utente cambia poi l'assegnazione fase→profilo prima di confermare) — quello che DEVE
   aspettare la conferma è solo l'ASSEGNAZIONE fase→profilo scritta nei singoli file job YAML.
5. Dopo "Conferma e applica", permetti di rientrare nel carosello per modificare ulteriormente
   (stessa logica già presente: una scelta "Modifica" che riporta al carosello mantenendo lo
   stato).

## Test

Adatta i test già scritti per il Task 38 (probabilmente in un file tipo
`tests/test_configure_wizard.py` o un file dedicato) al nuovo meccanismo di input. Dato che ora
l'input passa da `read_single_key` invece che da `questionary.select().ask()`, segui lo stesso
approccio di test già usato per `run_interactive_review` in `tests/test_issue_review.py` (mock di
`read_single_key` con una sequenza di tasti predefinita via `side_effect`) — verifica come sono
scritti quei test esistenti e replica lo stesso stile qui.

Copri almeno:
- Navigazione `RIGHT` attraverso tutte le card di fase più la card di conferma, poi `LEFT`
  indietro fino alla prima: nessuna scrittura su disco durante questo percorso.
- `UP`/`DOWN` dentro una card cambiano l'opzione evidenziata senza cambiare card.
- Selezionare "Nuovo modello" e confermarlo apre il flusso `_create_new_model_profile` esistente
  (mockalo) e, al ritorno, la card mostra il nuovo profilo come assegnazione pendente.
- "Conferma e applica" sulla card finale scrive su disco esattamente le assegnazioni pendenti al
  momento della conferma (non quelle di uno stato intermedio precedente).
- Raggiungere la card di conferma sia scorrendo `RIGHT` oltre l'ultima fase sia con la
  scorciatoia diretta (se implementata) porta allo stesso stato.

Esegui `python3 -m pytest tests/ -q` e correggi finché l'intera suite passa.

## Vincoli

Verifica il bug di portabilità ricorrente sulle annotazioni `typing` per qualunque riga toccata
(vedi `.agents/00-README.md`).

Non toccare `issue_review.py`: è solo il riferimento di stile/infrastruttura da riusare
(`read_single_key`, `raw_mode`), non va modificato in questo task.

Non toccare la logica interna di `_create_new_model_profile`: resta un questionario sequenziale
classico, invariato — questo task cambia solo il livello SOPRA di esso (come si arriva a
invocarlo e come ci si muove tra le fasi).

## Verifica finale

1. `python3 -m pytest tests/ -q`.
2. Test funzionale diretto: lancia `rt config`, verifica a schermo che (a) le fasi siano
   presentate come card navigabili con LEFT/RIGHT (non un elenco `questionary.select`), (b)
   dentro una card UP/DOWN scelgano tra Salta/profili/Nuovo, (c) scegliere "Nuovo" apra il
   questionario classico e al ritorno la card rifletta il nuovo profilo, (d) scorrere RIGHT oltre
   l'ultima card porti alla card di conferma, (e) nulla venga scritto su disco (assegnazioni
   fase→profilo) finché non si preme "Conferma e applica".
