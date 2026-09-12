# Task 37 — `rt config`: inserimento chiavi API round-robin in batch

Indipendente dal Task 35. Se lavori nello stesso giro del Task 36, fai prima il 36 (bug fix
puntuali), poi questo, per isolare i commit per causa. Nel progetto RT
(/Users/attilioturco/Desktop/trt), implementa direttamente, senza produrre un piano
preliminare.

## Contesto

`_create_new_model_profile` in `rt/pipeline/configure.py`, righe 287-299, raccoglie le chiavi
API round-robin una alla volta:
```python
if rr_action != "keep":
    while True:
        curr_idx = len(collected_keys) + 1
        cn = "google_1" if (provider == "google" and curr_idx == 1) else f"{provider.lower()}_{curr_idx}"
        ce = f"{provider.upper()}_API_KEY_{curr_idx}"
        prompt_str = f"API key #{curr_idx} per {provider} (invio vuoto per terminare se hai già inserito tutte le chiavi):"
        key_in = questionary.password(prompt_str).ask()
        if key_in is None:
            return "", {}
        key_val = key_in.strip()
        if not key_val:
            break
        collected_keys.append((cn, ce, key_val))
```
Un utente reale con 12-13 chiavi (es. account Google multipli per aggirare i rate limit) deve
rispondere a 12-13 prompt separati in sequenza, ciascuno con una riga vuota residua nell'output
del terminale (artefatto di `questionary.password`) — verificato empiricamente come
"macchinoso" su un giro di test reale (screenshot con 13 prompt `API key #1`...`#13` in
sequenza).

## Modifica

Sostituisci il loop uno-alla-volta con un singolo prompt che accetta più chiavi separate da
virgola in un colpo solo, mantenendo la possibilità di aggiungerne altre dopo se l'utente lo
desidera (per chi preferisce comunque incollarle una alla volta, o non le ha tutte pronte
insieme).

Proposta di implementazione:
```python
if rr_action != "keep":
    batch_prompt = (
        f"Incolla una o più API key per {provider}, separate da virgola "
        f"(invio vuoto per terminare se hai già inserito tutte le chiavi):"
    )
    while True:
        batch_in = questionary.password(batch_prompt).ask()
        if batch_in is None:
            return "", {}
        raw_keys = [k.strip() for k in batch_in.split(",") if k.strip()]
        if not raw_keys:
            break
        for key_val in raw_keys:
            curr_idx = len(collected_keys) + 1
            cn = "google_1" if (provider == "google" and curr_idx == 1) else f"{provider.lower()}_{curr_idx}"
            ce = f"{provider.upper()}_API_KEY_{curr_idx}"
            collected_keys.append((cn, ce, key_val))
        print(f"✅ {len(raw_keys)} chiave/i aggiunta/e (totale: {len(collected_keys)}).")
```
Adatta i dettagli (nomi variabili, messaggi) allo stile del resto del file, ma mantieni
l'invariante di naming esistente (`cn`/`ce` con indice progressivo `_N`, `google_1` come caso
speciale per la prima chiave Google) dato che è usato altrove nel file (es. `_edit_model_profile`)
per riconoscere/modificare le credenziali salvate — non cambiare lo schema di naming, solo il
modo in cui vengono raccolte.

`questionary.password` maschera l'input (mostra `*` per carattere) — verifica che il carattere
separatore `,` funzioni bene digitato/incollato in un campo mascherato (dovrebbe, dato che
`questionary.password` è comunque un campo di testo normale con solo il rendering mascherato).
Se noti che l'incolla multi-chiave con `,` ha problemi di rendering nel campo mascherato per via
di caratteri speciali nelle chiavi stesse (alcuni provider usano `,` raramente nei valori delle
chiavi, ma verificalo), valuta se usare `questionary.text` invece di `questionary.password` per
questo prompt specifico (mostrando le chiavi in chiaro solo per l'inserimento in batch — accettabile
dato che l'utente le sta comunque incollando lui stesso, ma nota il trade-off nel commit).

Aggiorna anche il messaggio di riepilogo dopo la raccolta (dove oggi probabilmente non c'è nulla
di esplicito oltre l'uscita dal loop) per mostrare in una riga compatta quante chiavi totali
sono configurate, invece di stampare una riga per chiave.

## Test

Aggiungi test in `tests/` (file esistente dedicato a `configure.py` o `_create_new_model_profile`)
che verificano:
- Un input tipo `"key1, key2,key3"` (con spazi variabili attorno alle virgole) produce
  `collected_keys` con esattamente 3 elementi, valori `"key1"`, `"key2"`, `"key3"` (spazi
  rimossi), nomi credenziale/env-var progressivi corretti.
- Un input con virgole ripetute o vuote (es. `"key1,,key2,"`) non produce chiavi vuote spurie.
- Chiamare il prompt una seconda volta dopo aver già inserito chiavi in batch (per aggiungerne
  altre) continua la numerazione progressiva correttamente (non ricomincia da 1).
- Input vuoto (invio a vuoto) termina il loop senza aggiungere chiavi, comportamento
  invariato rispetto a prima.

Esegui `python3 -m pytest tests/ -q` e correggi finché l'intera suite passa.

## Vincoli

Verifica il bug di portabilità ricorrente sulle annotazioni `typing` per qualunque riga toccata
(vedi `.agents/00-README.md`).

Non toccare la logica di gestione round-robin già esistente (menu "➕ Aggiungi altre chiavi" /
"🔄 Sostituisci tutte le chiavi da zero" / "⏭ Mantieni le chiavi esistenti", righe 262-286): resta
invariata, questo task modifica solo COME vengono raccolte le nuove chiavi una volta scelta
un'azione che le richiede.

## Verifica finale

1. `python3 -m pytest tests/ -q`.
2. Test funzionale diretto: lancia `rt config`, arriva al punto di configurazione di un
   provider con round-robin, incolla 3+ chiavi fittizie separate da virgola in un colpo solo,
   verifica a schermo che vengano registrate tutte correttamente (es. controllando
   `config/general.yaml` → `credentials:` e `.env` dopo l'esecuzione).
