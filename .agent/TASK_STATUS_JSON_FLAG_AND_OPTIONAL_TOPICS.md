Questo documento è già il piano di implementazione completo e concordato: procedi direttamente alle modifiche, senza produrre un piano separato da approvare prima.

# TASK: Nascondere il JSON di `rt status` dietro un flag, rendere "argomenti" davvero opzionale

## Contesto

Due piccole rifiniture UX discusse e approvate:
1. `rt status` stampa sempre, incondizionatamente, un blocco JSON completo in fondo all'output — verboso per l'uso normale. Va nascosto di default, mostrato solo su richiesta esplicita.
2. Il prompt interattivo "Argomenti trattati" durante `rt setup`/`rt run` è oggi dentro un ciclo che impedisce l'invio a vuoto (richiede all'infinito finché l'utente non scrive qualcosa), e se saltato (modalità non interattiva) usa un placeholder finto ("Argomenti generali") che finisce sia nel nome cartella sia — soprattutto — nel prompt inviato all'LLM per la fase `outline` (`rt/llm/prompts.py`, `build_outline_user_prompt`), dandogli un'informazione fasulla invece di nessuna informazione. Verificato che il campo ha un contributo reale ma marginale per l'outline (il modello si basa soprattutto sul contenuto dei segmenti); va reso genuinely opzionale, con omissione pulita a valle quando assente, non un placeholder.

---

## A. `rt status --json`

### Fix
In `rt/cli.py`, subparser `status` (circa riga 807-810):
```python
p_stat.add_argument("--json", action="store_true", help="Mostra anche il blocco JSON completo dello stato")
```
In `cmd_status` (`rt/cli.py`), l'ultima riga della funzione è oggi:
```python
    print(json.dumps(res, ensure_ascii=False, indent=2))
```
Va resa condizionale:
```python
    if getattr(args, "json", False):
        print(json.dumps(res, ensure_ascii=False, indent=2))
```
Il calcolo di `res` (e di `res["issues_breakdown"]` quando `--issues` è attivo) resta invariato — si continua a costruire il dizionario, cambia solo se viene stampato. Il blocco di testo umano esistente (intestazione, stato globale, freschezza fasi/artefatti, ed eventuale report `--issues`) resta sempre visibile come oggi, invariato.

### Test di accettazione
In un test esistente o nuovo per `cmd_status`:
1. Senza `--json`: l'output catturato (`capsys`) NON deve contenere una struttura JSON valida in coda (verificare assenza di `"phase_statuses"` nell'output, o che l'output non contenga `{` di apertura del blocco finale).
2. Con `--json`: l'output deve contenere il blocco JSON completo come oggi (verificare presenza di `"phase_statuses"` nell'output catturato).
3. Il blocco di testo umano (freschezza fasi) deve comparire in entrambi i casi.

---

## B. Campo "argomenti" davvero opzionale

### Fix 1: rimuovere il ciclo forzato in `rt/pipeline/setup.py`
Righe 344-351 attuali:
```python
    # Argomenti
    argomenti_val = argomenti.strip() if argomenti else ""
    while not argomenti_val:
        if interactive and sys.stdin.isatty():
            argomenti_val = prompt_clean("Argomenti trattati (es. 'Sinapsi e neurotrasmettitori')")
        else:
            argomenti_val = "Argomenti generali"
    argomenti_val = sanitize_filename_part(argomenti_val)
```
Sostituire con (un solo tentativo, nessun placeholder finto, vuoto è un valore legittimo):
```python
    # Argomenti (opzionale: se lasciato vuoto, nessun argomento viene registrato né mostrato all'LLM)
    argomenti_val = argomenti.strip() if argomenti else ""
    if not argomenti_val and interactive and sys.stdin.isatty():
        argomenti_val = prompt_clean("Argomenti trattati (opzionale, invio per lasciare vuoto, es. 'Sinapsi e neurotrasmettitori')")
    argomenti_val = sanitize_filename_part(argomenti_val) if argomenti_val else ""
```
(`prompt_clean`, definita più sopra nello stesso file righe 75-89, già gestisce nativamente Ctrl+C/EOF con uscita pulita e già restituisce stringa vuota se l'utente preme Invio senza scrivere nulla — nessuna modifica necessaria lì).

### Fix 2: gestire il caso vuoto SOLO dove serve, senza propagare `None` su disco

**Decisione importante presa dopo aver verificato l'intero raggio d'impatto**: `info.yaml` deve continuare a memorizzare SEMPRE una stringa vera per `argomenti` (vuota `''` quando non fornito), MAI un `null` YAML letterale. Motivo verificato: `rt/pipeline/build.py` (righe 31-46 e 128-142, e la lettura a riga 349 `topics_val = info.get("argomenti", "Argomenti")`) fa `topics.split(",")` assumendo sempre una stringa reale — se `info.yaml` contenesse `argomenti: null`, `.get("argomenti", "Argomenti")` restituirebbe `None` (il default si applica solo se la CHIAVE è assente, non se il suo valore è `null`), e `None.split(",")` andrebbe in crash **alla fase build**, non solo all'outline. Stessa lettura non protetta in `rt/pipeline/rewrite.py` (righe 310, 336) e `rt/pipeline/prepare.py` (riga 46). Nessuno di questi altri file va toccato in questo task: continuano a leggere `info.get("argomenti", "Argomenti")` esattamente come oggi, ricevendo `''` (stringa vuota, seppur poco significativa) invece di `None` — nessun crash, comportamento invariato salvo un bullet vuoto nell'elenco argomenti del documento finale quando non forniti (accettabile, cosmetico, fuori scope).

Con questa decisione, il Fix 1 già basta per tutti i punti che scrivono su disco: `argomenti_val` sarà semplicemente `''` quando non fornito, e va lasciato interpolato ESATTAMENTE come oggi nei 3 blocchi frontmatter (righe 508, 536, 559) e nel nome cartella — **tranne** il nome cartella, dove il separatore `" - "` va comunque omesso quando vuoto per evitare `"[data] MATERIA - "` con nulla dopo:
```python
    folder_name = f"[{date_val}] {materia_val}" + (f" - {argomenti_val}" if argomenti_val else "")
```
(circa riga 373 — unica modifica di questo Fix 2).

**`generate_deterministic_mock_asr`** (riga 193, usata solo con `--mock`): `argomenti_val.lower()` interpolato nel testo del segmento fittizio — se `argomenti_val` è vuoto produce una frase tronca ("...trattando ."). Sostituire con una variabile locale di fallback SOLO per il testo mock (nessun impatto sul valore reale salvato altrove):
```python
    argomenti_text_mock = argomenti_val if argomenti_val else "argomenti da definire"
    ...
    "text": f"Buongiorno a tutti. Oggi iniziamo la lezione di {materia_val.lower()} trattando {argomenti_text_mock.lower()}."
```

### Fix 3: omettere il suffisso SOLO nel prompt LLM di outline (unico punto realmente sensibile)
In `rt/pipeline/outline.py` (circa riga 60), la conversione da stringa vuota a `None` avviene **localmente, solo qui** — non tocca `info.yaml` né altri file:
```python
    topics_val = info.get("argomenti", "Argomenti")
```
→
```python
    topics_val = info.get("argomenti") or None
```
In `rt/llm/prompts.py`, aggiungere `Optional` all'import `typing` esistente (riga 10, oggi `from typing import List`), e modificare `build_outline_user_prompt` (righe 64-65):
```python
def build_outline_user_prompt(date: str, subject: str, topics: str, segments_summary: str) -> str:
    return f"""Lezione: [{date}] {subject.upper()} - {topics}
```
→
```python
def build_outline_user_prompt(date: str, subject: str, topics: Optional[str], segments_summary: str) -> str:
    topic_suffix = f" - {topics}" if topics else ""
    return f"""Lezione: [{date}] {subject.upper()}{topic_suffix}
```
Nessun'altra occorrenza di `topics` nel corpo della funzione da modificare (verificato, è l'unico punto in cui compare).

### Fix 4: `Manifest.topics` reso Optional (necessario SOLO per la chiamata di `outline.py`)
`rt/pipeline/outline.py` (riga ~121) passa `topics=topics_val` a `init_or_update_manifest`: con il Fix 3, `topics_val` può ora essere `None`. **Verificato**: `rt/core/manifest.py`, `init_or_update_manifest(..., topics: str, ...)` (riga 44) passa il valore direttamente al costruttore di `Manifest` (riga 86); `rt/core/models.py`, classe `Manifest` (riga 182), campo `topics: str` (riga 189) è oggi **obbligatorio, non `Optional`** — senza questo fix, la fase `outline` fallirebbe con un `ValidationError` Pydantic ogni volta che gli argomenti sono vuoti.

Modifiche (puramente additive, retrocompatibili — tutti gli altri 4 chiamanti di `init_or_update_manifest` in `rt/pipeline/build.py`, `rt/pipeline/rewrite.py`, `rt/pipeline/prepare.py` continuano a passare stringhe reali come oggi, `Optional[str]` le accetta comunque senza alcun cambiamento di comportamento per loro):
- `rt/core/models.py`, riga 189: `topics: str` → `topics: Optional[str] = None`.
- `rt/core/manifest.py`, riga 44: `topics: str,` → `topics: Optional[str] = None,`.
Nessun'altra modifica necessaria in `manifest.py` (righe 62 e 86 assegnano semplicemente il valore, già compatibili con `None`).

### Edge case e invarianti
- **Nessuna modifica a `rt/pipeline/build.py`, `rt/pipeline/rewrite.py`, `rt/pipeline/prepare.py`** — continuano a leggere `info.get("argomenti", "Argomenti")` esattamente come oggi, senza alcun rischio di ricevere `None` (perché `info.yaml` non memorizzerà mai `null` per questo campo).
- Quando `argomenti` è fornito esplicitamente (via `-a`/`--argomenti` da riga di comando, o risposta non vuota al prompt), il comportamento resta identico ad oggi in ogni punto (nome cartella, frontmatter, prompt LLM, manifest).
- Il messaggio del prompt cambia leggermente ("opzionale, invio per lasciare vuoto") per comunicare chiaramente la nuova possibilità.

### Test di accettazione
1. In `tests/test_setup.py`: un test che chiama `run_setup(..., argomenti="", interactive=False, ...)` (o senza passare `argomenti`) e verifica che `folder_name` NON contenga il separatore `" - "` finale (es. `folder_name == f"[{date}] {materia.upper()}"`, senza suffisso), e che `info.yaml` contenga `argomenti: ''` (stringa vuota, NON `null`) — leggerlo con `read_info_yaml` e verificare `info.get("argomenti") == ""`.
2. Un test che verifica il comportamento invariato quando `argomenti` è fornito esplicitamente (non vuoto): nome cartella con suffisso, `info.yaml` con la stringa reale.
3. Un test per `run_outline`/`build_outline_user_prompt`: con `info.yaml` avente `argomenti: ''`, verificare che `topics_val` risolto in `outline.py` sia `None` e che il prompt generato NON contenga un trattino finale vuoto (es. non deve produrre `"MATERIA - "` con nulla dopo); con un valore reale invariato rispetto a oggi.
4. Un test che chiama `init_or_update_manifest(..., topics=None, ...)` direttamente e verifica che non sollevi `ValidationError` (copre il Fix 4).
5. Un test che verifica che `rt/pipeline/build.py`/`rewrite.py`/`prepare.py` continuino a funzionare senza eccezioni con un `info.yaml` avente `argomenti: ''` (es. rieseguire un test end-to-end esistente della pipeline con argomenti vuoto, se già presente uno scenario simile, altrimenti aggiungerne uno minimo).
6. Rieseguire l'intera suite e confermare zero regressioni sui test esistenti (184 attuali + i nuovi).

## Verifica finale
Rieseguire `python3 -m pytest tests/ -q` e confermare l'esito. Verificare che la CI (`.github/workflows/tests.yml`) passi su entrambe le versioni Python della matrice per il commit di questo task.
