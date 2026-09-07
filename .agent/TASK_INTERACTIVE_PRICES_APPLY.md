Questo documento è già il piano di implementazione completo e concordato: procedi direttamente alle modifiche, senza produrre un piano separato da approvare prima.

**Prerequisito**: questo task presuppone che `TASK_NO_SILENT_CONFIG_DEFAULT_AND_DEPRECATE_SINGLE_FILE.md` sia già stato applicato (in particolare la funzione `_has_real_config_source()` in `rt/cli.py`). Se per qualche motivo non lo fosse ancora, implementare comunque un controllo equivalente localmente (`os.path.isdir(os.path.join(os.getcwd(), "config"))`) prima di procedere con la scrittura.

# TASK: `rt prices-check --interactive` — selezione e applicazione interattiva dei prezzi live

## Contesto

`rt prices-check` (`rt/cli.py:cmd_prices_check`, `rt/llm/pricing_sync.py:check_configured_pricing`) oggi produce solo un report a schermo, senza applicare nulla. L'utente vuole una modalità `--interactive` che mostri un checklist multi-selezione (libreria `questionary`, nuova dipendenza) sulle voci del report, pre-selezionando solo quelle marcate `stale`, e che scriva i prezzi selezionati direttamente nel file `config/<job>.yaml` corretto, sotto la route esatta a cui si riferiscono — usando `ruamel.yaml` (nuova dipendenza) per preservare commenti e formattazione del file durante la riscrittura.

Non è richiesto il flag `--apply` non interattivo: l'utente ha esplicitamente chiesto solo il flusso interattivo con selezione granulare, per poter escludere a mano modelli free-tier che vuole mantenere a costo zero anche se il catalogo live riporta un prezzo diverso da zero.

---

## A. Tracciare la posizione esatta di ogni route nel file YAML del job

In `rt/llm/pricing_sync.py`, funzione `collect_configured_routes(cfg)`: oggi enumera le route (primary, secondary, primary_routes, ognuna delle 5 chiavi di fallback) ma non registra DOVE si trova ciascuna route all'interno della struttura del job. Serve per poter riscrivere il file giusto nel punto giusto senza ambiguità.

Aggiungere ad ogni voce del risultato una chiave `"path"`, una tupla che descrive il percorso della route dentro al file `config/<job>.yaml` (che corrisponde 1:1 alla struttura di `JobRoutingConfig`, essendo il contenuto grezzo del file per-job):
- `("primary",)` per `job_cfg.primary`
- `("secondary",)` per `job_cfg.secondary`
- `("primary_routes", i)` per l'i-esimo elemento di `job_cfg.primary_routes` (indice a partire da 0, nello stesso ordine di iterazione già usato)
- `("fallback", fb_field)` per ciascuna delle chiavi di fallback già iterate (`"timeout"`, `"rate_limit"`, `"safety"`, `"auth"`, `"generic"`)

Esempio di modifica minima (adattare ai nomi di variabile reali già presenti nella funzione, non riscriverla da zero):
```python
for job_name, job_cfg in cfg.jobs.items():
    candidates = []  # ogni elemento ora è una tupla (route, path)
    if job_cfg.primary:
        candidates.append((job_cfg.primary, ("primary",)))
    if job_cfg.secondary:
        candidates.append((job_cfg.secondary, ("secondary",)))
    if job_cfg.primary_routes:
        for i, r in enumerate(job_cfg.primary_routes):
            candidates.append((r, ("primary_routes", i)))
    for fb_field in ("timeout", "rate_limit", "safety", "auth", "generic"):
        fb_route = getattr(job_cfg.fallback, fb_field, None)
        if fb_route:
            candidates.append((fb_route, ("fallback", fb_field)))
    for route, path in candidates:
        key = (route.provider.lower().strip(), route.model.lower().strip().lstrip("~"))
        if key in seen:
            continue
        seen.add(key)
        routes.append({"job": job_name, "provider": key[0], "model": key[1], "path": path})
```
Mantenere invariata la deduplica per `(provider, model)` — se due job diversi condividono la stessa coppia provider/model, oggi vengono comunque riportati separatamente perché la deduplica avviene per job (verificare che il comportamento attuale sia effettivamente questo leggendo la funzione reale prima di modificare; se la deduplica fosse invece globale fra job, va corretta la comprensione ma NON il comportamento — non introdurre regressioni sul report esistente, l'obiettivo di questo task è solo aggiungere `path`, non cambiare quali righe vengono riportate).

In `check_configured_pricing(cfg)`, propagare `"path"` (e implicitamente `"job"`, già presente) da `route` dentro ogni `entry` del report, così l'informazione arriva fino a `rt/cli.py`.

---

## B. Nuovo flag `--interactive` su `prices-check`

In `rt/cli.py`, sezione argparse del comando `prices-check` (vicino a `p_pc = subparsers.add_parser("prices-check", ...)`):
```python
p_pc.add_argument("--interactive", action="store_true", help="Seleziona interattivamente quali prezzi live applicare ai file config/<job>.yaml")
```

In `cmd_prices_check(args)`: dopo aver calcolato `report = check_configured_pricing(cfg)` e stampato il report testuale esistente (comportamento invariato quando `--interactive` non è passato), se `getattr(args, "interactive", False)` è vero:

1. Verificare `_has_real_config_source()` (la funzione già introdotta nel task di deprecazione del config singolo). Se assente, stampare un errore chiaro su stderr ed uscire con `sys.exit(1)` — non ha senso scrivere prezzi interattivamente se non esiste alcun `config/<job>.yaml` reale su cui scrivere.
2. Costruire la lista delle voci "applicabili": solo gli `entry` del report con `entry.get("live_match")` non nullo (senza un match live non c'è nulla da applicare). Se questa lista è vuota, stampare "Nessun prezzo live disponibile da applicare." ed uscire senza errore.
3. Costruire le scelte per `questionary.checkbox`, una per voce applicabile:
   ```python
   import questionary
   choices = []
   for entry in applicable_entries:
       lm = entry["live_match"]
       label = (
           f"[{entry['job']}] {entry['provider']}/{entry['model']}  "
           f"in uso: in=${entry['used_input_per_million']}/M out=${entry['used_output_per_million']}/M  →  "
           f"live: in=${lm['input_per_million']}/M out=${lm['output_per_million']}/M"
       )
       choices.append(questionary.Choice(title=label, value=entry, checked=bool(entry.get("stale"))))

   selected = questionary.checkbox(
       "Seleziona i prezzi da applicare ai file di configurazione (barra spazio per selezionare, invio per confermare):",
       choices=choices
   ).ask()
   ```
4. Gestire l'annullamento: se `selected` è `None` (utente ha premuto Ctrl+C durante il prompt), stampare "Annullato, nessuna modifica applicata." ed uscire senza errore (non un traceback).
5. Se `selected` è una lista vuota (nessuna voce selezionata, confermato comunque con invio), stampare "Nessuna voce selezionata, nessuna modifica applicata." ed uscire senza errore.
6. Per le voci selezionate, raggruppare per `job` (più voci selezionate possono appartenere allo stesso file), poi per ciascun job:
   - Caricare `config/<job>.yaml` con `ruamel.yaml.YAML()` in modalità round-trip (`typ="rt"`, il default), preservando commenti/ordine/stile.
   - Per ciascuna voce selezionata di quel job, navigare la struttura caricata seguendo `entry["path"]` (es. `data["primary"]`, `data["primary_routes"][i]`, `data["fallback"]["timeout"]`) e impostare/sovrascrivere la chiave `pricing:` di quel nodo con:
     ```python
     node["pricing"] = {
         "input_per_million": entry["live_match"]["input_per_million"],
         "output_per_million": entry["live_match"]["output_per_million"],
     }
     ```
     (Usare un `ruamel.yaml.comments.CommentedMap` o un semplice dict — ruamel accetta entrambi in scrittura; se il nodo non ha ancora una chiave `pricing`, va creata; se ce l'ha già, va sovrascritta interamente con i due soli campi indicati, senza tentare di preservare un eventuale valore preesistente di `reasoning_per_million` non pertinente qui.)
   - Scrivere il file una sola volta per job (non una volta per voce), con `yaml.dump(data, open(path, "w", encoding="utf-8"))` usando la stessa istanza `ruamel.yaml.YAML()` usata per il caricamento.
7. Al termine, stampare un riepilogo: per ciascun file toccato, quante voci sono state aggiornate, es. `"✔ config/outline.yaml: 1 prezzo aggiornato (deepseek/deepseek-v4-flash)"`.

### Edge case e invarianti
- Mai toccare `rt.config.yaml` (deprecato) — questo comando scrive esclusivamente in `config/<job>.yaml`.
- Il pre-check di default (`checked=bool(entry.get("stale"))`) è solo un default: l'utente può comunque selezionare/deselezionare liberamente qualunque voce, incluse quelle non stale — non introdurre alcuna restrizione che impedisca di selezionare una voce non stale.
- Se un job del report non corrisponde a un file esistente in `config/` (caso limite non dovrebbe verificarsi dato che i job vengono enumerati proprio a partire dai file caricati, ma va gestito difensivamente), saltare quel job stampando un avviso invece di sollevare un'eccezione non gestita.
- Senza `--interactive`, il comportamento di `prices-check` resta **esattamente identico** a oggi (stesso output testuale, nessuna nuova dipendenza richiesta a runtime per l'uso non interattivo — import di `questionary`/`ruamel.yaml` solo dentro il ramo `if args.interactive`, per non rompere l'uso base del comando se per qualche motivo le nuove dipendenze non fossero installate in un ambiente esistente).

---

## C. Nuove dipendenze

Aggiungere a `requirements.txt`:
```
questionary>=2.0
ruamel.yaml>=0.18
```

---

## D. Test di accettazione (`pytest tests/`)

Nuovo file `tests/test_prices_interactive.py` (o estendere `tests/test_config_split.py`/un file pricing esistente):

1. Test su `collect_configured_routes`: verificare che ogni voce restituita contenga una chiave `"path"` corretta per almeno un caso con `primary`, uno con `primary_routes` (indice corretto), e uno con una chiave di `fallback` (es. `"timeout"`).
2. Test end-to-end della scrittura: costruire in `tmp_path` una cartella `config/` con un `general.yaml` minimo e un `outline.yaml` con una route `primary` nota (provider/model noti, senza `pricing:` preesistente). Con `monkeypatch.chdir(tmp_path)`, mockare `questionary.checkbox(...).ask()` (via `unittest.mock.patch`) per restituire direttamente la entry desiderata (bypassando l'interazione reale da terminale — non è possibile né sensato testare l'input a tastiera reale), mockare `lookup_live_price`/`check_configured_pricing` per restituire un `live_match` noto e deterministico, invocare `cmd_prices_check(args)` con `args.interactive = True`, poi ricaricare `config/outline.yaml` con `ruamel.yaml` e verificare che `data["primary"]["pricing"]["input_per_million"]` e `["output_per_million"]` corrispondano esattamente ai valori del `live_match` mockato.
3. Test che verifica la preservazione dei commenti: dato un `outline.yaml` con un commento a inizio file (es. un blocco di intestazione `# ...` come nei file di `config.example/`), dopo la scrittura interattiva il commento deve essere ancora presente leggendo il file come testo grezzo (non solo come YAML parsato).
4. Test per il caso "nessuna voce applicabile" (nessun `live_match` in nessuna entry del report): verificare che non venga invocato `questionary.checkbox` affatto e che non venga scritto alcun file.
5. Test per il caso "utente annulla" (`questionary.checkbox(...).ask()` mockato per restituire `None`): verificare che non venga scritto alcun file e che non venga sollevata eccezione.
6. Test per il guard `_has_real_config_source()`: con `--interactive` ma senza cartella `config/` in `tmp_path`, verificare `SystemExit(1)` prima di qualunque chiamata a `questionary`.
7. Rieseguire l'intera suite (`python3 -m pytest tests/ -q`) e confermare che tutti i test esistenti continuino a passare, in particolare quelli in `tests/test_config_split.py` che riguardano `collect_configured_routes`/`check_configured_pricing` (la modifica del punto A aggiunge solo una chiave `"path"`, non deve cambiare nessun valore già asserito da quei test esistenti).

## Verifica finale
Rieseguire `python3 -m pytest tests/ -q`. Verificare manualmente (se possibile nell'ambiente di sviluppo di Antigravity) che `pip install questionary ruamel.yaml` non introduca conflitti con le dipendenze già presenti in `requirements.txt`.
