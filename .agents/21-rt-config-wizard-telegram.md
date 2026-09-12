# Task 21 — `rt config`: sezione Telegram con discovery live di gruppo/topic

Dipende dal task 20 (scheletro `run_config_wizard()` + funzione `_configure_llm_provider_section`
già creati in `rt/pipeline/configure.py` o dove il task 20 li abbia posizionati — leggi quel
codice prima di procedere, questo task aggiunge una sezione successiva alla stessa funzione,
non la riscrive). Nel progetto RT (/Users/attilioturco/Desktop/trt), implementa direttamente,
senza produrre un piano preliminare.

## Contesto

RT instrada le notifiche di build/i comandi Telegram su topic diversi in base alla materia
(`TelegramRuntimeConfig.topics: Dict[str, int]` in `rt/core/config.py`, mappa materia →
`message_thread_id`). Oggi ottenere questi ID richiede di aprire Telegram Web, aprire ogni
topic e leggere l'ID dall'URL — scomodo. Obiettivo: automatizzare la configurazione di
`RT_TELEGRAM_BOT_TOKEN`, `RT_TELEGRAM_CHAT_ID`, `telegram.topics`, `telegram.misc_topic_id`,
`telegram.lessons_root`.

**Perché non un metodo "automatico al 100%" col bot aggiunto al gruppo**: la Bot API di
Telegram (quella usata da `python-telegram-bot`, già dipendenza del progetto) NON espone alcun
metodo per elencare i topic esistenti di un forum (quel metodo, `messages.getForumTopics`,
esiste solo nell'API client MTProto completa, che richiederebbe un login con numero di telefono
— sproporzionato per questo tool). Verificalo tu stesso con `python-telegram-bot`'s `Bot`
prima di procedere, per conferma.

**Soluzione scelta (discovery live via polling temporaneo)**: il demone Telegram di RT
(`rt/telegram/daemon.py`) già riceve messaggi di testo pieni dal gruppo
(`MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)`), quindi il bot ha già i
permessi giusti (privacy mode disabilitata o bot amministratore) — non serve altro setup lato
Telegram oltre a quanto già richiesto per il resto del bot. Il wizard avvia un polling
temporaneo (solo per la durata di questo step, non il demone completo) e mostra in diretta ogni
messaggio ricevuto con il suo `chat.id` e `message_thread_id`, mentre l'utente manda un
messaggio da telefono in ciascun topic che vuole mappare.

## Sezione Telegram (`_configure_telegram_section`)

Aggiungi questa funzione e richiamala da `run_config_wizard()` dopo la sezione LLM, con un
prompt iniziale skippabile: `questionary.confirm("Configurare Telegram ora?", default=True)`
(a differenza della sezione LLM che è centrale, questa è opzionale — chi non usa Telegram deve
poter saltarla senza errori a valle: verifica che il resto di RT già tolleri
`telegram.topics={}`/token assente, dato che è già lo stato di default di `RTConfig`).

1. **Bot token**: se `RT_TELEGRAM_BOT_TOKEN` è già in `.env`, proponilo come "già configurato,
   vuoi cambiarlo?" (default no, salta al passo successivo riusando il valore esistente).
   Altrimenti chiedi con `questionary.password`, spiega brevemente come ottenerlo
   (`@BotFather` → `/newbot`), e scrivilo in `.env` con lo stesso meccanismo del task 20
   (sostituisci se la chiave esiste già, altrimenti aggiungi in fondo).

2. **Discovery live di gruppo e topic**: spiega chiaramente all'utente cosa sta per succedere,
   es.:
   ```
   Ora aggiungi il bot al tuo gruppo Telegram (se non l'hai già fatto) e manda un messaggio
   qualsiasi in ciascun topic che vuoi mappare a una materia (uno alla volta, aspetta che
   compaia qui prima del prossimo). Premi INVIO senza scrivere nulla quando hai finito.
   ```
   Poi avvia un polling temporaneo con `python-telegram-bot` (usa `telegram.Bot(token=...)` +
   `get_updates(offset=..., timeout=...)` in un loop, oppure `Application` se preferisci — scegli
   l'approccio più semplice da integrare in un comando CLI sincrono/bloccante, non serve
   l'infrastruttura async del demone completo) con un ciclo che:
   - Fa polling ogni ~2s (o usa il long-polling nativo di `get_updates` con `timeout=` per
     ridurre le richieste).
   - Per ogni update con `message.text` (ignora comandi e altri tipi di update): se `chat.id`
     non è ancora stato visto in questa sessione di discovery, stampalo come gruppo rilevato
     (`chat.title`, `chat.id`) e fissalo come il gruppo candidato per questa sessione (un solo
     gruppo alla volta — RT usa un solo `RT_TELEGRAM_CHAT_ID` globale). Se arriva un messaggio
     da un `chat.id` diverso da quello già fissato, avvisa e ignoralo (probabile rumore da un
     altro chat in cui il bot è presente).
   - Per ogni messaggio, leggi `message.message_thread_id` (None = topic "Generale"). Se questo
     `message_thread_id` non è già stato mappato in questa sessione, chiedi subito
     interattivamente (`questionary.text`, mentre il polling è momentaneamente in pausa per
     l'input) "Materia per questo topic (testo rilevato: '<message.text troncato>')? [invio per
     ignorare/usare come Varie]" e registra la mappatura `materia.upper() → message_thread_id`
     in memoria. Se l'utente lascia vuoto e vuole comunque usarlo come topic "Varie/Generale"
     per lezioni non mappate, offri esplicitamente questa scelta (es. rispondendo "varie" invece
     di lasciare vuoto) da assegnare a `misc_topic_id`.
   - Usa `get_updates(offset=last_update_id + 1, ...)` correttamente per non processare due
     volte lo stesso update (pattern standard di long-polling: salva sempre l'`update_id` più
     alto visto e usalo come offset alla chiamata successiva).
   - Il loop termina quando l'utente preme invio su un prompt dedicato "Premi invio quando hai
     finito di mandare messaggi nei topic (o scrivi 'stop')" — implementalo con un piccolo
     controllo periodico non bloccante (es. `input()` con timeout tramite thread separato, o più
     semplicemente esegui il polling in un thread di background e nel thread principale aspetta
     `input()`; scegli l'approccio più semplice e testabile, non serve asyncio completo).
   - Timeout di sicurezza complessivo (es. 3 minuti) oltre il quale il polling si ferma
     comunque con un messaggio chiaro, per evitare che il comando resti appeso indefinitamente
     se l'utente si distrae.

3. **Fallback manuale (se la discovery live non rileva nulla)**: se al termine del timeout/della
   sessione non è stato rilevato alcun messaggio, stampa una diagnosi chiara:
   ```
   Nessun messaggio rilevato. Verifica che:
   - il bot sia stato aggiunto al gruppo,
   - il bot abbia i permessi per leggere i messaggi (BotFather → /mybots → il tuo bot →
     Bot Settings → Group Privacy → Turn off), oppure sia amministratore del gruppo.
   ```
   e offri un metodo alternativo manuale: chiedi all'utente di incollare un link a un messaggio
   di quel topic nel formato `https://t.me/c/<chat_numeric>/<topic_id>/<message_id>` (Telegram
   lo fornisce col menu "Copia link" su un messaggio); parsa questo link con una regex
   (`r"t\.me/c/(\d+)/(\d+)(?:/(\d+))?"`), ricava `chat_id = int(f"-100{match.group(1)}")` (il
   prefisso `-100` è la convenzione nota di Telegram per gli ID dei supergruppi/canali derivati
   da questi link) e `topic_id = int(match.group(2))`, poi chiedi la materia da associare. Ripeti
   finché l'utente non conferma di aver finito. Questo fallback deve essere disponibile anche
   come scelta esplicita (non solo dopo un timeout), nel caso l'utente preferisca direttamente
   questo metodo.

4. **Scrittura risultati**: `RT_TELEGRAM_CHAT_ID` in `.env` (stesso meccanismo di
   sostituzione/aggiunta già usato per il bot token); `telegram.topics`, `telegram.misc_topic_id`
   in `config/general.yaml` (merge con eventuali voci già esistenti — non sovrascrivere una
   mappa `topics` esistente con solo le nuove voci rilevate in questa sessione, unisci le due).

5. **`lessons_root`**: prompt di testo libero (`questionary.text`, con default il valore già
   presente in config se c'è) per il percorso assoluto della cartella che contiene tutte le
   lezioni (usata da `/list`/`/recall <query>` su Telegram, vedi
   `TelegramRuntimeConfig.lessons_root`). Espandi `~` con `os.path.expanduser`. Se la cartella
   non esiste, avvisa chiaramente ma non bloccare (l'utente potrebbe volerla creare dopo, o
   questo potrebbe girare su una macchina diversa da quella dove vivono le lezioni — es.
   configurazione preparata in anticipo prima di spostare i file).

## Vincoli

- Nessuna dipendenza nuova: usa `python-telegram-bot` (già in `requirements.txt`) per le
  chiamate Bot API di discovery.
- Il polling temporaneo di questo step NON deve interferire con un eventuale `rt telegram-daemon`
  già in esecuzione sulla stessa macchina: **prima di avviare il polling**, avvisa chiaramente
  l'utente se rileva che potrebbe esserci un conflitto (Telegram permette un solo consumer di
  `get_updates` alla volta per bot — se un demone è già attivo su questo stesso bot, `get_updates`
  fallirebbe con un errore 409 "Conflict"; se osservi questo errore reale durante i tuoi test,
  cattura il caso e stampa un messaggio chiaro: "sembra che `rt telegram-daemon` sia già in
  esecuzione per questo bot: fermalo prima di eseguire questo step, altrimenti la discovery non
  può ricevere messaggi").
- Verifica il bug di portabilità ricorrente sulle annotazioni `typing` (vedi `.agents/00-README.md`).

## Test

Estendi `tests/test_configure_wizard.py` (creato nel task 20). La parte di polling Telegram va
testata mockando `telegram.Bot`/le chiamate `get_updates` (nessuna chiamata di rete reale nei
test), simulando una sequenza di update fittizi che includa: un messaggio nel topic Generale,
due messaggi in due topic diversi, e un messaggio da un `chat.id` diverso da ignorare. Verifica
che `topics`/`misc_topic_id`/`chat_id` risultanti in config siano corretti. Testa anche il
parsing del link di fallback (`https://t.me/c/4490473926/541/679` → `chat_id=-1004490473926`,
`topic_id=541`) con un test unitario dedicato sulla funzione di parsing (estraila come funzione
pura separata, facilmente testabile senza mockare l'intero flusso interattivo).

Esegui `python3 -m pytest tests/ -q` e correggi finché l'intera suite passa.

## Verifica finale

1. `python3 -m pytest tests/ -q`.
2. Se hai accesso a un bot Telegram di test reale in questa sessione (chiedilo esplicitamente
   nel resoconto finale se non è disponibile, non inventare credenziali): esegui `./bin/rt config`
   in una copia temporanea del repo, testa la discovery live mandando davvero un messaggio in un
   topic di prova, e verifica che venga rilevato correttamente. Se non hai un bot disponibile per
   un test end-to-end reale, verifica comunque manualmente il fallback a link (che non richiede
   una sessione Telegram live, solo il parsing) e documenta chiaramente nel resoconto che la
   parte di polling live è stata verificata solo con i test automatici mockati, non end-to-end.
