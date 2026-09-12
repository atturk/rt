# Task 33 — `rt config`: ricerca testuale per il modello + possibilità di tornare indietro

Dipende dal Task 32 (ridisegna `_configure_llm_provider_section`/il loop per-fase — leggi quel
task e il suo effetto sul file prima di procedere, se non è stato ancora eseguito segnalalo e
implementa comunque questo task sopra alla struttura attuale, i due si toccano solo
marginalmente: questo task modifica esclusivamente la sezione "4. Recupero Modelli" dentro
`_create_new_model_profile`). Indipendente dal Task 34. Nel progetto RT
(/Users/attilioturco/Desktop/trt), implementa direttamente, senza produrre un piano preliminare.

## Contesto

Test reale su un MacBook Air: quando la lista modelli viene recuperata da OpenRouter (o altro
provider), può contenere decine/centinaia di voci — vedi screenshot condiviso dall'utente,
`questionary.select` mostra tutta la lista con le frecce, senza alcun modo di filtrare per
nome. L'utente ha chiesto un filtro testuale dinamico stile selettore modello dei coding agent
(digiti, la lista si restringe ai risultati che corrispondono), e la possibilità di tornare
indietro se sbaglia la selezione.

## 1. Sostituisci `questionary.select` con `questionary.autocomplete` per la lista modelli

In `_create_new_model_profile`, sezione "4. Recupero Modelli" (la parte con `if models_list: ...
selected_model = questionary.select("Seleziona il modello LLM:", choices=choices, ...)`):
`questionary` (già dipendenza del progetto) offre nativamente `questionary.autocomplete(message,
choices, ignore_case=True, match_middle=True, ...)` — filtro testuale dinamico live mentre si
digita, esattamente il comportamento richiesto, nessuna nuova dipendenza necessaria (verificato
che la funzione esiste nella versione già installata in questo progetto).

Sostituisci l'intero blocco:
```python
chosen_model = ""
MANUAL_ENTRY = "✍️ Inserisci manualmente"

if models_list:
    choices = models_list + [MANUAL_ENTRY]
    selected_model = questionary.select(
        "Seleziona il modello LLM:",
        choices=choices,
        default=choices[0]
    ).ask()

    if selected_model is None:
        return "", {}

    if selected_model != MANUAL_ENTRY:
        chosen_model = selected_model

if not chosen_model:
    if not models_list:
        print("ℹ️ Impossibile recuperare la lista modelli automaticamente.")
    manual_model = questionary.text(
        "ID Modello (es. deepseek-chat, google/gemini-2.5-flash):"
    ).ask()
    if not manual_model:
        return "", {}
    chosen_model = manual_model.strip()
```
con una versione basata su `autocomplete` quando `models_list` è disponibile, e `questionary.text`
libero altrimenti (comportamento invariato in quel caso — nessuna lista da filtrare). Nota
importante: `autocomplete` accetta nativamente QUALUNQUE testo digitato dall'utente, non lo
costringe a scegliere solo tra i `choices` — questo sostituisce automaticamente il vecchio
sentinel `MANUAL_ENTRY`/`"✍️ Inserisci manualmente"`, che non serve più: se l'utente digita un
ID modello non presente nella lista, va comunque accettato come inserimento manuale (aggiungi
comunque un `validate=` che richieda un testo non vuoto).

## 2. Conferma con possibilità di tornare indietro

Dopo aver ottenuto `chosen_model` (sia dal ramo `autocomplete` sia dal ramo `text` manuale),
avvolgi l'intera selezione in un ciclo che permette di rifare la scelta se l'utente si accorge di
aver sbagliato, invece di proseguire subito a pricing/nome profilo:
```python
while True:
    # ... (logica di selezione esistente/nuova con autocomplete o text, invariata) ...
    if chosen_model is None:  # utente ha annullato con Ctrl+C/Esc durante il prompt
        return "", {}
    confirm_model = questionary.confirm(
        f"Hai selezionato '{chosen_model}' — confermi?",
        default=True
    ).ask()
    if confirm_model is None:
        return "", {}
    if confirm_model:
        break
    # altrimenti richiedi di nuovo la selezione (torna in cima al ciclo)
```
(pseudocodice indicativo — integralo nella struttura esistente della sezione "4. Recupero
Modelli" in modo pulito, senza duplicare inutilmente la logica di recupero via HTTP, che va
eseguita una sola volta prima del ciclo — solo la SELEZIONE va ripetuta se l'utente rifiuta la
conferma, non la chiamata di rete).

## Vincoli

Verifica il bug di portabilità ricorrente sulle annotazioni `typing` per qualunque riga toccata
(vedi `.agents/00-README.md`).

## Test

Estendi `tests/test_configure_wizard.py`. `questionary.autocomplete` va mockato con lo stesso
pattern già usato per `questionary.select`/`text` negli altri test di questo file (patch su
`questionary.autocomplete` con un `side_effect` che ritorna un `MagicMock(ask=...)`). Copri
almeno:
- Selezione di un modello presente nella lista recuperata via HTTP, con conferma "sì" al primo
  giro → il profilo risultante ha quel modello.
- Rifiuto della conferma seguito da una seconda selezione diversa → il profilo risultante
  riflette la SECONDA scelta, non la prima (verifica che il ciclo "torna indietro" funzioni
  davvero, non solo che non vada in crash).
- Inserimento di un testo libero non presente nella lista recuperata (simula
  `questionary.autocomplete` che ritorna un valore fuori da `choices`) → accettato come modello
  valido, nessun errore, nessun riferimento residuo al vecchio sentinel `MANUAL_ENTRY`.
- Percorso senza lista modelli disponibile (fallback HTTP fallito) → il prompt `questionary.text`
  libero funziona ancora, con lo stesso ciclo di conferma/torna-indietro applicato.

Esegui `python3 -m pytest tests/ -q` e correggi finché l'intera suite passa.

## Verifica finale

1. `python3 -m pytest tests/ -q`.
2. Test manuale in una copia temporanea del repo: esegui `./bin/rt config` con una API key reale
   di un provider con molti modelli (es. OpenRouter), verifica che digitando alcune lettere la
   lista si filtri dinamicamente, che la conferma con "no" permetta di riselezionare, e che un
   testo libero non presente nella lista venga comunque accettato. Pulisci la cartella temporanea
   alla fine.
