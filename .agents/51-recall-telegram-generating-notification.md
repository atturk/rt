# Task 51 — Notifica "sto generando le domande" prima del primo batch di recall

Indipendente dagli altri task attivi. Nel progetto RT (/Users/attilioturco/Desktop/trt),
implementa direttamente, senza produrre un piano preliminare.

## Contesto

`/recall` su Telegram (senza argomenti) genera il primo batch di domande sincronamente prima di
mandare la prima domanda — la generazione può richiedere anche oltre un minuto (più tipi di
domanda, ciascuno con una chiamata LLM separata, specialmente con provider lenti tipo
OpenRouter free tier, osservato dall'utente nei log del daemon). Oggi, tra il comando `/recall`
e l'arrivo della prima domanda, l'utente non riceve alcun feedback — sembra che non sia successo
nulla.

**Punto esatto**: `rt/pipeline/recall_session.py::start_recall_via_telegram` (righe 179-216).
Dopo `tg_session.start_session(...)` (riga 202) e prima di `_ensure_initial_batch(lesson_dir,
force_mock=force_mock)` (riga 212, il passo lento che genera le domande via LLM), non viene
mandato alcun messaggio. `send_current_recall_question` (riga 215) — che effettivamente
funziona già come notifica "il batch è pronto", dato che manda la prima domanda non appena
`_ensure_initial_batch` finisce — arriva quindi dopo un'attesa silenziosa.

## Modifica

Subito dopo `tg_session.start_session(...)` (riga 202) e prima di `_ensure_initial_batch` (riga
212), manda un messaggio esplicito:
```python
tg_client.send_message(
    tg_cfg,
    text="⏳ Sto generando le domande per il recall, ti avviso appena il primo batch è pronto.",
    message_thread_id=thread_id,
)
```
Usa lo stesso stile/formattazione dei messaggi già presenti in questa funzione (`busy_msg`,
`reminder_msg` sopra nello stesso file). Non serve toccare `_ensure_initial_batch` né
`send_current_recall_question`: l'arrivo della prima domanda funziona già come segnale "batch
pronto", il problema era solo l'assenza del messaggio iniziale di conferma/attesa.

## Test

- Test che verifica che `start_recall_via_telegram` mandi il messaggio "sto generando..." PRIMA
  di chiamare `_ensure_initial_batch` (mocka entrambe le funzioni/il client Telegram e verifica
  l'ordine delle chiamate).
- Verifica che il messaggio non venga mandato nei rami di uscita anticipata (sessione già
  attiva, Telegram non configurato, ecc. — righe 189-210) — solo quando la sessione parte
  davvero.

Esegui `python3 -m pytest tests/ -q` e correggi finché l'intera suite passa.

## Vincoli

Verifica il bug di portabilità ricorrente sulle annotazioni `typing` per qualunque riga toccata
(vedi `.agents/00-README.md`).

## Verifica finale

1. `python3 -m pytest tests/ -q`.
2. Se hai un bot Telegram di test disponibile: avvia `/recall` su una lezione reale e verifica
   che il messaggio "sto generando" arrivi subito, seguito dalla prima domanda quando pronta.
