# Task 57 — `rt config`: chiarire che i fallback sono opzionali + mostrare il numero di chiavi round-robin nel riepilogo

Indipendente dagli altri task attivi. Nel progetto RT (/Users/attilioturco/Desktop/trt),
implementa direttamente, senza produrre un piano preliminare.

## Contesto

Due piccoli miglioramenti di chiarezza trovati in un giro di test reale sul carosello di `rt
config` (Task 43/53).

### 1. La lista di ruoli in ogni card può spaventare l'utente

Ogni card di fase mostra sempre tutti e 6 i ruoli (Primario + 5 fallback) con "(non impostato)"
per quelli vuoti:
```
Primario:             (non impostato)
Fallback timeout:     (non impostato)
Fallback rate-limit:  (non impostato)
Fallback safety:      (non impostato)
Fallback auth:        (non impostato)
Fallback generico:    (non impostato)
```
Un utente alla prima configurazione potrebbe pensare di dover impostare TUTTI questi campi,
mentre solo il Primario è necessario — i fallback sono facoltativi.

**Fix**: nel testo introduttivo della schermata (o direttamente sopra la lista dei ruoli),
chiarisci esplicitamente che solo "Primario" è obbligatorio e tutti i "Fallback" sono opzionali.
Valuta anche di etichettare visivamente i 5 fallback come gruppo distinto (es. un'intestazione
"Fallback (tutti opzionali):" sopra le 5 righe, invece di elencarli allo stesso livello del
Primario) per rendere la gerarchia immediatamente chiara a colpo d'occhio, non solo a parole.

### 2. Il riepilogo finale non mostra quante chiavi round-robin sono coinvolte

Nella card di conferma finale, un'assegnazione con più chiavi round-robin appare identica a una
con una sola chiave:
```
✅ [2/5] rewrite: google1_gemini-3.5-flash-lite [FB: rate_limit->google2_gemini-3.5-flash-lite]
```
**Fix**: se il profilo assegnato ha `round_robin: true` con N route, mostra il conteggio, es.:
```
✅ [2/5] rewrite: google1_gemini-3.5-flash-lite (3 chiavi API) [FB: rate_limit->google2_gemini-3.5-flash-lite]
```
Applica lo stesso trattamento a QUALUNQUE punto del wizard che mostra il nome di un profilo
round-robin in un riepilogo (verifica se ce ne sono altri oltre alla card di conferma finale,
es. la card di fase stessa quando mostra "Primario: <nome>").

## Test

- Test che verifica che il testo introduttivo/la card menzioni esplicitamente che i fallback
  sono opzionali.
- Test che verifica che il riepilogo finale mostri "(N chiavi API)" per un profilo con
  `round_robin: true` e N route, e NON mostri quella nota per un profilo a chiave singola.

Esegui `python3 -m pytest tests/ -q` e correggi finché l'intera suite passa.

## Vincoli

Verifica il bug di portabilità ricorrente sulle annotazioni `typing` per qualunque riga toccata
(vedi `.agents/00-README.md`).

## Verifica finale

1. `python3 -m pytest tests/ -q`.
2. Test funzionale diretto: configura un profilo round-robin a 3 chiavi per una fase, verifica
   a schermo che il riepilogo finale mostri "(3 chiavi API)".
