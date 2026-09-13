# Task 58 — Elimina automaticamente il messaggio "sto generando le domande" quando arriva la prima domanda

Indipendente dagli altri task attivi. Nel progetto RT (/Users/attilioturco/Desktop/trt),
implementa direttamente, senza produrre un piano preliminare.

## Contesto

Il Task 51 ha aggiunto un messaggio "⏳ Sto generando le domande per il recall, ti avviso appena
il primo batch è pronto." all'avvio di `/recall` su Telegram
(`rt/pipeline/recall_session.py::start_recall_via_telegram`). L'utente conferma che è utile, ma
chiede che una volta arrivata la prima domanda (dopo `_ensure_initial_batch`, tramite
`send_current_recall_question`), il messaggio "sto generando" venga eliminato automaticamente
per evitare che resti a "floodare" la chat inutilmente.

## Modifica

In `start_recall_via_telegram`, cattura il `message_id` restituito dall'invio del messaggio
"sto generando" (verifica cosa ritorna `tg_client.send_message` — dovrebbe essere un dict con
`message_id`, stesso pattern già usato altrove nel file, es. `poll_res.get("message_id")` in
`send_current_recall_question`). Dopo che `_ensure_initial_batch` e
`send_current_recall_question` sono stati eseguiti con successo (la prima domanda è stata
effettivamente inviata), cancella il messaggio "sto generando" con `context.bot.delete_message`/
l'equivalente già usato nel progetto per cancellare messaggi (cerca il pattern già usato per
altri messaggi effimeri, es. nei bottoni recall in `rt/telegram/daemon.py`) — avvolgi la
cancellazione in un `try/except` che ignora silenziosamente eventuali errori (il messaggio
potrebbe essere già stato cancellato manualmente dall'utente, o troppo vecchio per Telegram).

## Test

- Test che verifica che, dopo l'invio riuscito della prima domanda, venga chiamata la
  cancellazione del messaggio "sto generando" con il `message_id` corretto.
- Test che verifica che un errore nella cancellazione (es. messaggio già cancellato) non
  blocchi né sollevi eccezioni nel flusso principale.

Esegui `python3 -m pytest tests/ -q` e correggi finché l'intera suite passa.

## Vincoli

Verifica il bug di portabilità ricorrente sulle annotazioni `typing` per qualunque riga toccata
(vedi `.agents/00-README.md`).

## Verifica finale

1. `python3 -m pytest tests/ -q`.
2. Se hai un bot Telegram di test disponibile: avvia `/recall`, verifica che il messaggio "sto
   generando" sparisca non appena arriva la prima domanda.
