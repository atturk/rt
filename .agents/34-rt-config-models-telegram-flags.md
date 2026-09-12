# Task 34 — `rt config --models` (gestione profili) e `rt config --telegram` (sezione diretta)

Dipende dallo stato attuale di `rt/pipeline/configure.py` e `rt/cli.py` (leggi entrambi per
intero prima di procedere, in particolare `_load_model_profiles`, `_save_model_profiles`,
`_create_new_model_profile`, `configure_config_parser`, `cmd_config`). Indipendente dai task 32
e 33 (tocca `configure_config_parser`/`cmd_config`/una nuova funzione di gestione profili, non le
parti che quei task modificano), ma se eseguito nello stesso giro va bene in qualunque ordine.
Nel progetto RT (/Users/attilioturco/Desktop/trt), implementa direttamente, senza produrre un
piano preliminare.

## Contesto

Oggi `rt config -h` non documenta alcuna opzione utile (`configure_config_parser` è un no-op) e
l'unico modo per rivedere/modificare un profilo modello già salvato è rilanciare l'intero wizard
da capo. L'utente ha chiesto due scorciatoie dirette:
- `rt config --models`: apre un menu dedicato alla gestione dei profili modello salvati
  (`model_profiles:` in `config/general.yaml`) — permette di vederli, modificarne i campi
  (nome, provider, base URL, nome modello, API key, pricing) o eliminarli, senza dover
  attraversare l'intero wizard.
- `rt config --telegram`: salta dritto alla sezione Telegram (bot token, discovery topic,
  lessons_root), senza dover attraversare prima la configurazione dei modelli LLM.

## 1. Wiring CLI

In `configure_config_parser(parser)` (oggi `return parser` senza fare nulla), aggiungi:
```python
def configure_config_parser(parser: Any) -> Any:
    """Configura l'argparse parser per rt config."""
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--models", action="store_true", help="Apre direttamente il menu di gestione dei profili modello salvati (senza attraversare l'intero wizard)")
    group.add_argument("--telegram", action="store_true", help="Configura direttamente solo la sezione Telegram (senza attraversare l'intero wizard)")
    return parser
```
(`add_mutually_exclusive_group` perché non ha senso passare entrambi insieme — se preferisci una
struttura diversa va bene, l'importante è che i due flag restino mutuamente esclusivi con un
errore chiaro di argparse se combinati).

In `rt/cli.py::cmd_config`, instrada in base ai flag:
```python
def cmd_config(args: argparse.Namespace) -> None:
    if getattr(args, "models", False):
        from rt.pipeline.configure import run_models_management
        run_models_management()
    elif getattr(args, "telegram", False):
        from rt.pipeline.configure import run_telegram_only
        run_telegram_only()
    else:
        from rt.pipeline.configure import run_config_wizard
        run_config_wizard()
```
(nomi delle nuove funzioni a tua discrezione, ma tienili coerenti con quanto descritto sotto).

## 2. `run_telegram_only()` — sezione Telegram isolata

Funzione breve in `rt/pipeline/configure.py`: risolve `config_dir`/`env_path` (riusa
`_resolve_or_bootstrap_config_paths()`, stessa funzione già usata da `run_config_wizard`), poi
chiama direttamente `_configure_telegram_section(config_dir, env_path)` — quella funzione
stampa già il proprio riepilogo internamente, non serve altro oltre a un'intestazione/chiusura
minima coerente con lo stile del resto del wizard (banner iniziale tipo quello di
`run_config_wizard`, es. "⚙️ RT CONFIG — Configurazione Telegram").

## 3. `run_models_management()` — menu di gestione profili

Nuova funzione che implementa un ciclo di gestione CRUD sui profili salvati in
`config/general.yaml` → `model_profiles:`:

```python
def run_models_management() -> None:
    config_dir, env_path = _resolve_or_bootstrap_config_paths()
    general_yaml_path = os.path.join(config_dir, "general.yaml")
    while True:
        general_data = ...  # carica fresco da disco ad ogni giro del ciclo esterno
        profiles = _load_model_profiles(general_data)
        if not profiles:
            print("Nessun profilo modello salvato. Usa 'rt config' per crearne uno.")
            return
        EXIT = "⏭ Esci"
        NEW = "➕ Crea un nuovo profilo"
        choice = questionary.select(
            "Profili modello salvati (seleziona per modificare):",
            choices=sorted(profiles.keys()) + [NEW, EXIT]
        ).ask()
        if choice is None or choice == EXIT:
            return
        if choice == NEW:
            p_name, p_dict = _create_new_model_profile(config_dir, env_path, general_data)
            if p_name:
                profiles[p_name] = p_dict
                _save_model_profiles(general_data, profiles)
                _atomic_write_text(general_yaml_path, yaml.safe_dump(general_data, sort_keys=False, allow_unicode=True))
            continue
        _edit_model_profile(config_dir, env_path, general_data, profiles, choice)
```

Implementa `_edit_model_profile(config_dir, env_path, general_data, profiles, profile_name)`:
mostra i valori correnti del profilo selezionato (provider, base_url, round_robin, route/e con
credenziali e modello — e se presente, il pricing associato letto da
`general_data.get("pricing", {}).get(provider, {}).get(model, {})`), poi propone un menu di cosa
modificare:
```
✏️  Rinomina profilo
🔧 Cambia provider/base URL/modello (riconfigura da capo questo profilo)
🔑 Aggiorna API key
💰 Modifica pricing
🗑️  Elimina profilo
⏭  Torna alla lista
```
Per ciascuna opzione:
- **Rinomina**: chiedi un nuovo nome (con lo stesso controllo di unicità/sovrascrittura già
  presente in `_create_new_model_profile` per coerenza), aggiorna la CHIAVE nel dizionario
  `profiles` (rimuovi la vecchia, inserisci con il nuovo nome, stesso valore) — nota che
  `_find_matching_profile` fa match per CONTENUTO (provider/modello/credenziali), non per nome,
  quindi rinominare un profilo non rompe il riconoscimento nei job che già lo usano al prossimo
  giro di `rt config`.
- **Cambia provider/base URL/modello**: il modo più semplice e coerente è richiamare
  `_create_new_model_profile(config_dir, env_path, general_data, default_name_hint=profile_name)`
  per raccogliere da capo i valori (riusa tutta la logica già esistente, incluso il Task 33 se
  già completato), poi sostituire il contenuto del profilo esistente con quello nuovo mantenendo
  lo stesso nome se l'utente non lo cambia esplicitamente nel sotto-flusso.
- **Aggiorna API key**: chiedi una nuova chiave (`questionary.password`) per l'`env_var` già
  associato alla credenziale di quella route (o di tutte le route, se round-robin — chiarisci
  quale stai aggiornando se ce ne sono più di una), scrivila con `_update_env_file`.
- **Modifica pricing**: riusa `_configure_pricing_section(config_dir, provider, model)` già
  esistente.
- **Elimina profilo**: chiedi conferma (`questionary.confirm`, default `False`), poi rimuovi la
  chiave da `profiles` e salva. Avvisa chiaramente prima di eliminare che eventuali job che oggi
  risultano assegnati a questo profilo NON verranno modificati nei loro file YAML (restano con
  la configurazione che hanno), ma al prossimo `rt config` non verranno più riconosciuti come
  corrispondenti a un profilo salvato (finiranno nel caso "configurazione non riconosciuta").

Dopo ogni modifica, salva su disco (`_save_model_profiles` + `_atomic_write_text`, stesso
pattern usato ovunque nel file) e torna al menu principale della lista profili (ricaricala da
disco per riflettere lo stato aggiornato).

## Vincoli

- Riusa le funzioni già esistenti (`_create_new_model_profile`, `_configure_pricing_section`,
  `_update_env_file`, `_load_model_profiles`, `_save_model_profiles`, `_atomic_write_text`) —
  non duplicarne la logica.
- Verifica il bug di portabilità ricorrente sulle annotazioni `typing` per qualunque riga
  toccata (vedi `.agents/00-README.md`).

## Test

Estendi `tests/test_configure_wizard.py` con almeno:
- `rt config --models` con zero profili salvati: mostra il messaggio corretto e non entra in un
  ciclo infinito.
- Rinomina di un profilo esistente: la chiave cambia in `model_profiles`, il contenuto resta
  identico.
- Eliminazione di un profilo (con conferma): la chiave sparisce da `model_profiles` dopo il
  salvataggio su disco.
- Aggiornamento dell'API key di un profilo esistente: `.env` riflette il nuovo valore per
  l'`env_var` corretto.
- `rt config --telegram` invoca `_configure_telegram_section` e NON tocca in alcun modo
  `model_profiles`/i file `<job>.yaml` (verifica che restino bit-per-bit identici a prima della
  chiamata, se già presenti).
- `configure_config_parser`: verifica che `--models` e `--telegram` insieme producano un errore
  di argparse (mutuamente esclusivi) — testalo con `parser.parse_args(["--models", "--telegram"])`
  e verifica che sollevi `SystemExit`.

Esegui `python3 -m pytest tests/ -q` e correggi finché l'intera suite passa.

## Verifica finale

1. `python3 -m pytest tests/ -q`.
2. Test manuale in una copia temporanea del repo con almeno 2 profili modello già salvati (crea
   una config di prova a mano o con un `rt config` completo prima): esegui `./bin/rt config
   --models`, prova a rinominare un profilo, modificarne il pricing, ed eliminarne uno —
   verifica che `config/general.yaml` rifletta ogni modifica correttamente dopo ciascun passo.
   Esegui poi `./bin/rt config --telegram` e verifica che venga chiesto solo bot
   token/topic/lessons_root, nient'altro. Verifica anche `./bin/rt config -h` per confermare che
   i due flag siano ora documentati correttamente nell'help. Pulisci la cartella temporanea alla
   fine.
