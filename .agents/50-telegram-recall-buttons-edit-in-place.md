# Task 50 — Bottoni 📖/🔊 in active recall: testo modificato in place, audio come risposta collegata

Indipendente dagli altri task attivi. Nel progetto RT (/Users/attilioturco/Desktop/trt),
implementa direttamente, senza produrre un piano preliminare.

## Contesto

Oggi, quando l'utente preme il bottone 📖 (mostra unità testuale) o 🔊 (mostra audio unità)
durante l'active recall, il bot manda sempre un NUOVO messaggio separato (cancellandolo se si
riclicca per nasconderlo). Questo è scomodo: per ricliccare e nascondere il messaggio, l'utente
deve risalire manualmente al messaggio inviato.

**Codice attuale**: `rt/telegram/daemon.py`, dentro `_handle_post_answer_callback` (righe
~496+): bottone 📖 (`action == "rut"`, righe 553-566) e bottone 🔊 (`action == "rua"`, righe
568-586) — entrambi fanno toggle cancella/crea-nuovo-messaggio (`context.bot.delete_message` se
già presente, altrimenti `context.bot.send_message`/`send_unit_audio` per crearne uno nuovo),
mai una modifica in place del messaggio.

**Vincolo dell'API Bot Telegram (verificato)**: `editMessageMedia` può SOLO sostituire il media
di un messaggio che ha GIÀ un media allegato — non può trasformare un messaggio di solo testo in
uno con audio, né viceversa rimuovere un media convertendolo in solo testo. Quindi:
- Il testo dell'unità PUÒ essere gestito con vera modifica in place (`editMessageText` sullo
  stesso messaggio, o crearlo la prima volta e poi editarlo per aggiornare/nascondere il
  contenuto) — nessun vincolo tecnico lo impedisce.
- L'audio NON può essere agganciato/sganciato dallo stesso messaggio via edit — deve restare un
  messaggio separato, ma può essere mandato **in risposta** (`reply_to_message_id`) al messaggio
  della domanda originale con i bottoni, così è facile risalire da dove è arrivato senza dover
  cercare nella chat.

Questo è esattamente l'approccio ibrido che l'utente ha indicato come preferito quando il
"tutto in un solo messaggio" non è tecnicamente possibile.

## Modifica

### 1. Bottone 📖 (testo unità) — modifica in place invece di cancella+ricrea

Nel ramo `action == "rut"`: invece di cancellare il messaggio esistente e non fare altro (per
nasconderlo) o mandarne uno nuovo (per mostrarlo), mantieni un messaggio DEDICATO per il testo
dell'unità (crealo la prima volta con `send_message`, salva `unit_text_message_id` come già
fatto oggi) e, per le volte successive, usa `context.bot.edit_message_text` per:
- "Nascondi": modifica il testo a un placeholder minimale (es. "—" o una singola emoji), oppure
  valuta se preferisci comunque cancellarlo — ma se l'obiettivo primario dell'utente è "non dover
  risalire al messaggio per ricliccare", la parte cruciale è il punto 2 sotto (associare il
  bottone al messaggio giusto), quindi qui puoi mantenere il comportamento di cancellazione
  ESISTENTE per "nascondi" se semplifica, ma la RICOMPARSA (dopo nascosto) deve riusare
  `edit_message_text` su un messaggio riaperto invece di crearne sempre uno nuovo quando
  possibile — la richiesta esplicita dell'utente è di aggiornare lo stesso messaggio invece di
  crearne sempre di nuovi.
- Se scegli di NON cancellare mai il messaggio (solo modificarne il contenuto — l'opzione più
  elegante e quella esplicitamente preferita dall'utente): sostituisci il testo con un
  placeholder tipo "📖 (nascosto, premi di nuovo per mostrare)" quando l'utente lo nasconde,
  invece di cancellarlo — così il messaggio resta sempre lo stesso ID, riusabile via
  `edit_message_text` ad ogni toggle, senza mai crearne di nuovi dopo il primo. Preferisci
  QUESTA opzione se non ci sono vincoli evidenti che la rendano problematica (verifica che
  `unit_text_message_id` sia già tracciato in modo persistente per la sessione di recall,
  altrimenti aggiungilo).

### 2. Bottone 🔊 (audio unità) — messaggio separato ma in risposta al messaggio originale

Nel ramo `action == "rua"`: quando si invia l'audio (righe 579-585, `send_unit_audio`/
`send_audio` in `rt/telegram/client.py`), passa `reply_to_message_id` impostato all'ID del
messaggio ORIGINALE della domanda (quello con i bottoni 📖/🔊), non lasciarlo come messaggio
"sciolto" in coda alla chat. Verifica la firma di `send_audio`
(`rt/telegram/client.py`) e di `send_unit_audio` (`rt/pipeline/recall_session.py`, riga 41) per
capire se già supportano un parametro di reply — se non lo fanno, aggiungilo (pass-through del
parametro Telegram `reply_to_message_id`/`reply_parameters` a seconda della versione dell'API
usata nel progetto).

Il toggle cancella/nascondi per l'audio (righe 569-576) può restare com'è (cancellazione del
messaggio audio quando l'utente lo nasconde) — è l'unica opzione tecnicamente possibile per
questo caso, dato il vincolo API sopra.

## Test

- Test che verifica che, alla seconda pressione del bottone 📖 sulla stessa domanda, venga
  chiamato `edit_message_text` sullo STESSO `message_id` invece di `send_message` per crearne
  uno nuovo.
- Test che verifica che l'invio dell'audio (bottone 🔊) includa sempre `reply_to_message_id`
  impostato all'ID del messaggio della domanda originale.
- Verifica che i test esistenti su questi due bottoni (cerca in `tests/test_telegram_*.py`)
  vengano adattati, non ignorati, se le loro asserzioni assumevano il vecchio comportamento
  cancella+ricrea per il testo.

Esegui `python3 -m pytest tests/ -q` e correggi finché l'intera suite passa.

## Vincoli

Verifica il bug di portabilità ricorrente sulle annotazioni `typing` per qualunque riga toccata
(vedi `.agents/00-README.md`).

## Verifica finale

1. `python3 -m pytest tests/ -q`.
2. Se hai un bot Telegram di test disponibile: verifica manualmente che ricliccando 📖 più
   volte sulla stessa domanda il messaggio si aggiorni in place (stesso message_id nella chat,
   non un nuovo messaggio ogni volta), e che l'audio arrivi sempre come risposta al messaggio
   della domanda. Altrimenti documenta che non è stato possibile verificarlo end-to-end.
