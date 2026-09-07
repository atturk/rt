Questo documento è già il piano di implementazione completo e concordato: procedi direttamente alle modifiche, senza produrre un piano separato da approvare prima.

# TASK: Nessun default hardcoded silenzioso + rimozione completa della modalità "file singolo"

## Contesto

Due decisioni prese in sessione:
1. Oggi `load_config()`, se non trova alcuna sorgente di configurazione, restituisce silenziosamente `RTConfig()` con i default hardcoded (solo DeepSeek generico) — **zero avvisi all'utente**. Un `rt run` lanciato senza aver mai configurato nulla eseguirebbe silenziosamente con impostazioni sbagliate. Va reso un arresto controllato con messaggio chiaro, non un fallback silenzioso.
2. La modalità "file singolo" (`rt.config.yaml`/`rt.config.yaml.example`) non deve più esistere come opzione documentata/consigliata. Da ora in poi l'unico modo per configurare RT è copiare `config.example/` in `config/` e modificare i file al suo interno.

**Importante — cosa NON va toccato**: la funzione di basso livello che legge un singolo file YAML esplicito (`_load_rtconfig_from_file` in `rt/core/config.py`, e il comportamento di `load_config(config_path=<path esplicito>)`) **deve restare invariata**. Non è "il file mastodontico" di cui l'utente vuole liberarsi — è un'utility generica usata da moltissimi test esistenti per costruire configurazioni isolate in `tmp_path` (es. `load_config(str(tmp_path / "qualcosa.yaml"))`, `LLMClient(config_path=...)`). Rimuoverla romperebbe una parte enorme della suite senza alcun beneficio reale. Quello che va eliminato è solo: (a) il fallback automatico a `rt.config.yaml` nella working directory quando `load_config()` è chiamata SENZA path esplicito, e (b) i file `rt.config.yaml`/`rt.config.yaml.example` stessi e ogni riferimento a quella modalità nella documentazione.

---

## A. Rimuovere il fallback automatico a `rt.config.yaml`

In `rt/core/config.py`, funzione `load_config` (l'ultima parte, dopo il controllo su `config/`):
```python
def load_config(config_path: Optional[str] = None) -> RTConfig:
    """Carica la configurazione. Se config_path è esplicito, comportamento invariato
    (singolo file, usato da test/codice che lo richiede esplicitamente). Se None: usa
    la cartella 'config/' se presente; altrimenti nessuna sorgente trovata, restituisce
    i default (il chiamante a livello CLI deve verificare esplicitamente l'esistenza di
    una sorgente reale prima di eseguire lavoro — vedi rt/cli.py, _has_real_config_source)."""
    if config_path is not None:
        return _load_rtconfig_from_file(config_path)

    config_dir = os.path.join(os.getcwd(), "config")
    if os.path.isdir(config_dir):
        try:
            return _load_config_dir(config_dir)
        except Exception:
            pass
        return RTConfig()

    return RTConfig()
```
(Rimossa la riga `return _load_rtconfig_from_file(os.path.join(os.getcwd(), "rt.config.yaml"))` finale, sostituita da `return RTConfig()` diretto — nessun controllo su `rt.config.yaml` quando non c'è path esplicito.)

`_load_rtconfig_from_file` resta esattamente com'è, non toccarla.

---

## B. Arresto controllato nei comandi CLI se nessuna configurazione reale esiste

In `rt/cli.py`, aggiungere una funzione helper (vicino alle altre utility di modulo, es. accanto a `_print_phase_action`):
```python
def _has_real_config_source() -> bool:
    """Vero se esiste una sorgente di configurazione reale (cartella config/) nella
    working directory corrente. Usata dai comandi CLI che eseguono lavoro LLM reale
    per evitare di procedere silenziosamente con i default hardcoded."""
    return os.path.isdir(os.path.join(os.getcwd(), "config"))
```

Aggiungere, all'inizio di ciascuna di queste 5 funzioni — **solo quando non è attiva la modalità `--mock`** (il mock non richiede una configurazione reale, è un caso d'uso legittimo per provare la pipeline prima di aver configurato modelli veri):

```python
if not getattr(args, "mock", False) and not _has_real_config_source():
    print(
        "❌ Nessuna configurazione trovata (cartella 'config/' mancante).\n"
        "   Copia 'config.example/' in 'config/' e personalizza i modelli prima di eseguire questo comando:\n"
        "   cp -r config.example config",
        file=sys.stderr
    )
    sys.exit(1)
```

Punti di aggancio esatti (verificare i numeri di riga correnti con una ricerca, potrebbero essere leggermente diversi da quelli qui indicati per modifiche intercorse):
- `cmd_outline` (riga ~63), prima di `res = run_outline(...)`.
- `cmd_rewrite` (riga ~77), prima di `res = run_rewrite(...)`.
- `cmd_review_asr` (riga ~93), prima di `res = run_review_asr(...)`.
- `cmd_review_science` (riga ~100), prima di `res = run_review_science(...)`.
- `cmd_run` (riga ~624): inserire subito dopo la determinazione di `mock_mode = getattr(args, "mock", False)`, usando `mock_mode` al posto di `getattr(args, "mock", False)` per coerenza con il resto della funzione, PRIMA di qualunque step della pipeline.

**Non toccare** `cmd_test_llm` (è un comando diagnostico esplicito, accetta già un `--config`/parametri propri e ha un caso d'uso legittimo anche senza `config/`), né `cmd_prepare`/`cmd_build`/`cmd_status`/i comandi di validazione (non eseguono mai chiamate LLM).

### Edge case e invarianti
- Con `--mock` attivo, nessun controllo — comportamento invariato.
- Il messaggio va su `stderr`, `sys.exit(1)` — nessun traceback, coerente con l'arresto controllato già esistente per `LLMFailure` in `main()`.
- `load_config()` con path esplicito resta invariata al 100% — nessun impatto sui test che la usano.
- **Dopo aver rimosso il fallback**, rieseguire l'intera suite con attenzione: se un qualunque test smette di passare o cambia comportamento silenziosamente (es. un test che si affidava implicitamente alla presenza del vero `rt.config.yaml` dello sviluppatore nella working directory, invece di costruire la propria configurazione esplicita — pattern di isolamento test già incontrato e corretto più volte in questa sessione), applicare la stessa correzione già usata in quei casi precedenti (costruire la config esplicitamente nel test, non affidarsi a file ambientali).

---

## C. Rimozione completa della modalità "file singolo"

1. `git rm rt.config.yaml.example` (file tracciato — va rimosso dal repository). **Non toccare** l'eventuale `rt.config.yaml` reale dell'utente sul disco (file non tracciato/ignorato da git, gestito manualmente dall'utente stesso — non è compito di questo task cancellarlo).
2. In `.gitignore`: rimuovere la riga `!rt.config.yaml.example` (non serve più, il file non esiste). Mantenere invece la riga `rt.config.yaml` (protezione difensiva: se qualcuno crea ancora un file con quel nome per qualunque motivo, resta comunque escluso da git).
3. In `README.md`: sostituire l'intera sezione "Configurazione dei job e dei modelli (due modalità equivalenti)" (quella con i due blocchi `cp -r config.example config` / `cp rt.config.yaml.example rt.config.yaml` e la nota sulla precedenza) con una sola modalità:
```markdown
Configurazione dei job e dei modelli:
```bash
cp -r config.example config
# Modifica config/general.yaml e i singoli file per-job config/<job>.yaml
```
> È possibile specificare un listino `pricing:` direttamente sotto ogni singola route.
```
4. In `docs/DEVELOPMENT.md`: applicare la stessa sostituzione ovunque venga menzionata la modalità a file singolo o `rt.config.yaml.example` (cercare tutte le occorrenze nel file, non solo la prima).
5. Cercare in tutta la repo (`grep -rn "rt.config.yaml.example"`) altri riferimenti residui (es. `docs/ARCHITECTURE.md`, `docs/SCHEMAS.md`, commenti nel codice) e aggiornarli o rimuoverli in modo coerente.

### Edge case
- Non modificare né cancellare `config.example/` — resta l'unico template da ora in poi.
- Non modificare il comportamento di caricamento con path esplicito (punto A) — questo task riguarda solo l'auto-discovery di default e la documentazione/i file di esempio.

---

## Test di accettazione (`pytest tests/`)

In `tests/test_config_split.py` (estendere quello esistente) o un nuovo file:
1. Verificare che `load_config()` (nessun path, `monkeypatch.chdir` su una `tmp_path` che contiene un `rt.config.yaml` con un valore distintivo ma NESSUNA cartella `config/`) restituisca i default di `RTConfig()`, **non** i valori di quel file — prova diretta che il fallback è stato rimosso.
2. Verificare che `load_config(path_esplicito)` continui a funzionare esattamente come prima (nessuna regressione) anche se punta a un file chiamato `rt.config.yaml`.
3. Per ciascuno dei 5 comandi CLI toccati: un test che, in una `tmp_path` senza `config/` e senza `--mock`, verifica `SystemExit(1)` e il messaggio d'errore su stderr; e un test che verifica che con `--mock` il comando proceda oltre il controllo (non serve verificare l'intera esecuzione, basta che non sollevi l'errore di configurazione mancante).
4. Rieseguire l'intera suite (`python3 -m pytest tests/ -q`) e, come indicato sopra, investigare e correggere singolarmente qualunque test che smetta di passare o cambi comportamento a causa della rimozione del fallback — non limitarsi a modificarne l'asserzione per farlo tornare verde senza capire la causa.

## Verifica finale
Rieseguire `python3 -m pytest tests/ -q`. Verificare che la CI passi su entrambe le versioni Python della matrice. Verificare con `grep -rn "rt.config.yaml.example"` che non restino riferimenti orfani nella repo dopo le modifiche.
