# Task 62 — Bottone 📖: piega il testo dell'unità nello STESSO messaggio del commento, non un messaggio satellite

Indipendente dagli altri task attivi. Nel progetto RT (/Users/attilioturco/Desktop/trt),
implementa direttamente, senza produrre un piano preliminare.

## Contesto

Il Task 50 ha reso il bottone 📖 capace di "modificare in place" — ma il messaggio con l'unità
testuale resta comunque un messaggio SEPARATO (satellite) dal messaggio principale con il
commento/esito e i bottoni: solo le pressioni SUCCESSIVE alla prima modificano quel satellite
in place, la prima pressione lo CREA come nuovo messaggio. L'utente non vuole nessun messaggio
satellite per il testo: vuole che il testo dell'unità appaia/scompaia DENTRO il messaggio
principale (quello con "Correttezza: X% Completezza: Y% <commento>" e i bottoni sotto),
esattamente come già funziona per il bottone 🗣 (trascritto).

**Il pattern da riusare esiste già, identico, per il trascritto vocale**:
`rt/telegram/daemon.py::_handle_post_answer_callback`, ramo `action == "rtt"` (righe 523-549):
tiene `transcript_visible` in `entry`, e quando si preme il bottone fa `edit_message_text` sullo
STESSO `entry["message_id"]` (il messaggio principale), componendo il testo come
`f"🗣 Trascritto: \"{transcript}\"\n\n{eval_text}"` quando visibile, o solo `eval_text` quando
nascosto — MAI un messaggio nuovo.

Il ramo `action == "rut"` (righe 573-622) invece usa `unit_text_message_id`/
`unit_text_visible` per gestire un messaggio SEPARATO con la sua stessa logica di toggle
(`edit_message_text` sul satellite, non sul principale) — questo è il ramo da riscrivere.

## Modifica

Riscrivi il ramo `action == "rut"` seguendo ESATTAMENTE lo schema del ramo `rtt`:

- Sostituisci `unit_text_message_id`/`unit_text_visible` nell'`extra` di
  `_send_post_answer_result` (righe 413-424, chiave `"unit_text_message_id": None` da
  rimuovere) con un solo flag booleano, es. `"unit_text_visible": False` (nessun
  `message_id` satellite da tracciare più).
- Nel ramo `rut`: leggi `entry.get("unit_text_visible", False)`, inverti il valore, salva con
  `registry.update_pending`. Se il nuovo stato è "visibile", calcola il testo dell'unità con
  `format_unit_reference` (stessa funzione già usata, righe 595-596/610-611) e componi il testo
  combinato, es. `f"{eval_text}\n\n📖 {testo_unita}"` (o l'ordine che preferisci — verifica cosa
  risulta più leggibile, es. prima il commento poi l'unità, o viceversa; l'importante è che sia
  sempre lo stesso ordine per coerenza). Se il nuovo stato è "nascosto", il testo torna ad
  essere semplicemente `eval_text` (l'esito da solo, senza placeholder "nascosto" — a differenza
  del comportamento satellite attuale che mostrava un testo segnaposto, qui puoi tornare
  semplicemente al messaggio originale pulito, dato che non c'è più un messaggio a parte da
  "svuotare").
- Fai `edit_message_text` su `entry["message_id"]` (il messaggio principale, non un
  `existing_id` satellite), con lo stesso `reply_markup` esistente (verifica se
  `edit_message_text` in questo progetto richiede di ripassare `reply_markup=keyboard`
  esplicitamente per non perderlo, come fa `rtt` a riga 545 — sì, lo fa: replica lo stesso
  pattern, ricostruendo la tastiera con `tg_fmt.build_post_answer_keyboard(...)`).
- Se sia il testo del trascritto (🗣) sia quello dell'unità (📖) sono entrambi visibili
  contemporaneamente, il messaggio deve mostrare ENTRAMBI (verifica che comporre il testo tenga
  conto sia di `transcript_visible` sia di `unit_text_visible` insieme, non solo l'uno o
  l'altro — leggi come il ramo `rtt` costruisce `new_text` e generalizza la composizione del
  testo in una funzione condivisa che considera lo stato di ENTRAMBI i toggle, invece di
  duplicare la logica in due punti che potrebbero disallinearsi).
- Rimuovi il vecchio percorso "prima volta: manda messaggio nuovo con `reply_to_message_id`"
  (righe 609-622): non serve più, il messaggio esiste già (`entry["message_id"]`), si tratta
  sempre e solo di un `edit_message_text` su di esso.

**Non toccare il bottone 🔊 (audio)**: resta un messaggio satellite in risposta
(`reply_to_message_id`), confermato dal Task 50 come unica opzione tecnicamente possibile
(vincolo reale dell'API Bot Telegram: `editMessageMedia` non può aggiungere un allegato audio a
un messaggio di solo testo).

## Test

- Test che verifica che premere 📖 la PRIMA volta faccia `edit_message_text` su
  `entry["message_id"]` (non `send_message` per un nuovo messaggio).
- Test che verifica il toggle: seconda pressione di 📖 fa `edit_message_text` di nuovo sullo
  stesso `message_id`, tornando al testo `eval_text` originale.
- Test che verifica la composizione corretta quando SIA trascritto SIA unità sono visibili
  contemporaneamente (entrambi i blocchi di testo presenti nel messaggio finale).
- Adatta i test esistenti su `rut` (`tests/test_recall_session.py` o simile, cerca test
  relativi al Task 50) che assumevano il vecchio comportamento a messaggio satellite.

Esegui `python3 -m pytest tests/ -q` e correggi finché l'intera suite passa.

## Vincoli

Verifica il bug di portabilità ricorrente sulle annotazioni `typing` per qualunque riga toccata
(vedi `.agents/00-README.md`).

## Verifica finale

1. `python3 -m pytest tests/ -q`.
2. Se hai un bot Telegram di test disponibile: rispondi a una domanda mirata/vasta, premi 📖 e
   verifica che il testo dell'unità appaia DENTRO lo stesso messaggio del commento (nessun
   nuovo messaggio in chat), ripremi e verifica che sparisca tornando al messaggio originale.
