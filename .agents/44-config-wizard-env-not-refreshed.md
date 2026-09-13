# Task 44 — CRITICO: chiavi API già inserite non vengono mai riconosciute nella stessa sessione di `rt config`

Indipendente dagli altri task attivi, priorità alta: è la causa radice più probabile di gran
parte della confusione riportata dall'utente in un giro di test reale (chiavi "non rilevate",
round-robin che sembra perdere chiavi tra una fase e l'altra). Nel progetto RT
(/Users/attilioturco/Desktop/trt), implementa direttamente, senza produrre un piano preliminare.

## Contesto

Test reale: l'utente configura in sequenza (nello STESSO processo `rt config`, una sola
esecuzione) una chiave OpenRouter per la fase `outline`, poi 12 chiavi Google in round-robin per
`rewrite`, poi prova a riusare quelle stesse chiavi Google per `review` — ma il wizard mostra
"nessuna chiave rilevata"/richiede reinserimento anche per provider e chiavi appena inserite
pochi secondi prima nello stesso avvio del comando. Stessa cosa per OpenRouter tra `outline` e
`recall`.

**Causa esatta**: `_update_env_file` (`rt/pipeline/configure.py`, righe 72-97) scrive la nuova
chiave SOLO nel file `.env` su disco (`_atomic_write_text`), ma non aggiorna mai
`os.environ` nel processo Python corrente:
```python
def _update_env_file(env_path: str, key: str, value: str) -> None:
    ...
    _atomic_write_text(env_path, "".join(new_lines))
```
Tutti i controlli "chiave già esistente" nello stesso file leggono da `os.environ`, non dal
file appena scritto:
- round-robin, righe ~250-260: `val = os.environ.get(ce, "")` per popolare `existing_creds`
- chiave singola, riga ~314: `existing_key = os.environ.get(env_var_name, "")`

Poiché `os.environ` non viene mai aggiornato dopo una scrittura, QUALUNQUE chiave scritta in una
fase precedente della STESSA esecuzione di `rt config` risulta invisibile alle fasi successive
che ricontrollano lo stesso provider — costringendo l'utente a reinserire (o a scegliere "🔄
Sostituisci tutte le chiavi da zero" per il round-robin, pensando che le chiavi precedenti non
siano state salvate). Il valore diventa visibile solo alla PROSSIMA esecuzione del processo
`rt` (quando `load_env_file()` viene chiamato da capo all'avvio), mai all'interno della stessa
sessione del wizard.

Questo è quasi certamente un fattore chiave dietro un problema riportato separatamente
dall'utente: un round-robin Google che l'utente credeva a 12 chiavi si è rivelato, ispezionando
`.env`/`config/general.yaml` dopo la sessione, avere solo 4 chiavi Google distinte salvate (e
`rewrite.yaml` risultante con solo 2 route, non un round-robin N-way) — coerente con più cicli
di "non rilevo chiavi esistenti → l'utente sceglie di sostituire tutto da zero → incolla di
nuovo un sottoinsieme diverso di chiavi" innescati proprio da questo bug.

## Modifica

In `_update_env_file`, dopo aver scritto il file, aggiorna anche `os.environ` nel processo
corrente:
```python
def _update_env_file(env_path: str, key: str, value: str) -> None:
    ...
    _atomic_write_text(env_path, "".join(new_lines))
    os.environ[key] = value
```
Verifica tutti i call site di `_update_env_file` nel file (righe ~332, ~362) — non serve
cambiare nulla lì, l'aggiornamento di `os.environ` dentro la funzione stessa basta a far sì che
qualunque lettura successiva di `os.environ.get(...)` nella stessa sessione veda subito il
valore corretto.

Verifica anche se esistono ALTRI punti in `configure.py` che scrivono su `.env` senza passare da
`_update_env_file` (cerca `_atomic_write_text(env_path` per pattern simili) — se ce ne sono,
applica lo stesso fix lì.

## Test

- Test che, mockando `os.environ` (o usando `monkeypatch.setenv`/verificando lo stato reale di
  `os.environ` dopo la chiamata), verifica che dopo `_update_env_file(env_path, "TEST_KEY",
  "abc123")` la lettura `os.environ.get("TEST_KEY")` ritorni `"abc123"` SENZA dover ricaricare
  il file.
- Test end-to-end sul wizard: simula la creazione di un profilo OpenRouter con una chiave nella
  fase 1, poi la creazione di un secondo profilo OpenRouter (stesso provider) nella fase 2 nello
  STESSO processo di test — verifica che la fase 2 rilevi correttamente la chiave già esistente
  (branch "già presente"/"già configurate", non un flusso a chiave vuota).
- Test analogo per il percorso round-robin: 3 chiavi Google inserite per un profilo, poi un
  secondo profilo Google creato subito dopo nello stesso test — verifica che
  `existing_creds`/il messaggio "Trovate N chiavi round-robin già configurate" veda
  correttamente le 3 chiavi appena inserite.

Esegui `python3 -m pytest tests/ -q` e correggi finché l'intera suite passa.

## Vincoli

Verifica il bug di portabilità ricorrente sulle annotazioni `typing` per qualunque riga toccata
(vedi `.agents/00-README.md`). **Leggi anche la nuova nota in cima a `.agents/00-README.md` su
come isolare l'ambiente di test da `config/` reale prima di fare qualunque verifica funzionale
diretta per questo task.**

## Verifica finale

1. `python3 -m pytest tests/ -q`.
2. Test funzionale diretto **in una config directory temporanea isolata** (vedi nota in
   `00-README.md`): lancia il wizard, configura una chiave per un provider in una fase, poi
   subito dopo configura un'altra fase con lo stesso provider — verifica a schermo che la
   chiave appena inserita venga riconosciuta come già presente, senza dover reinserirla.
