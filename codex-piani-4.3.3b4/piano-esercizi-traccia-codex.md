# Piano 3 · Esercizi: la traccia dà i dati, non il metodo

Richiesta di Attilio del 22/10/2026, sulla 4.3.3b3. Un commit.

## Problema

Le tracce degli esercizi generati spiegano come impostare il problema. Esempio reale: «Impostare e
valutare l'integrale lungo una direzione radiale; indicare inoltre la dipendenza del potenziale da R
e confrontarla con quella del modulo del campo elettrico». Lo studente deve ricevere i dati e la
domanda, e scegliere da solo il procedimento.

## Dove

1. **Modello generale** `rt/recall/question_type_templates.json`, tipo `esercizio`, campo `chiedi`.
   Il punto 1 oggi dice: «La traccia riporta tutti i dati necessari e chiede il risultato e/o i
   passaggi chiave.» Sostituiscilo con una regola di questo tipo:

   > 1. La traccia riporta solo la situazione, i dati necessari e che cosa determinare (il risultato
   > o la grandezza richiesta). Non indica il metodo, le formule, le leggi o i passaggi da usare, non
   > suggerisce come impostare il problema e non aggiunge richieste di commento o confronto che non
   > fanno parte dell'esercizio svolto nel testo.

   Il procedimento resta in `pregenerated_material` e in `tipo.procedimento`: servono alla
   correzione e alle varianti, non vanno nella traccia.

2. **Varianti** `rt/llm/prompts.py`, `RECALL_VARIANT_SYSTEM_PROMPT` e
   `RECALL_TEXT_VARIANT_SYSTEM_PROMPT`. Aggiungi la stessa regola: la traccia della variante dà dati
   e obiettivo, non il procedimento. Queste costanti valgono per tutti, senza aggiornamenti manuali.

3. **Tipi già creati dagli utenti.** I tipi personalizzati sono copie del modello salvate nella
   configurazione (`cfg.recall.custom_types`, vedi `seeded_types` in `rt/recall/migration.py`), quindi
   il nuovo testo non li raggiunge da solo. Aggiungi una migrazione all'avvio, idempotente: per ogni
   tipo con `id == "esercizio"`, se `chiedi` è **identico** al testo del modello precedente,
   sostituiscilo con il nuovo. Se l'utente l'ha modificato, non toccarlo.

   Tieni il testo precedente come costante nel codice della migrazione. Il JSON del modello resta
   unico, senza versioni vecchie.

## Test

- Il `chiedi` del modello `esercizio` contiene la nuova regola e non contiene più «chiede il
  risultato e/o i passaggi chiave».
- I due prompt delle varianti contengono la regola.
- Migrazione: un tipo con il testo vecchio viene aggiornato; uno modificato a mano resta uguale; una
  seconda esecuzione non cambia niente.
