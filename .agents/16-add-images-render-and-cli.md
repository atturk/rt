# Task 16 — `rt add-images`: inserimento nel documento finale + comando CLI (chiude il flusso end-to-end)

Quarto di 5 task sequenziali (13→17). **Richiede che i Task 13, 14, 15 siano già completati**
(usa `describe_new_images`/`judge_images_by_macro`/le funzioni di cache — se mancano, fermati
e segnala che le precondizioni non sono soddisfatte). Dopo questo task, `rt add-images` è
completo e funzionante per `-i <pdf_o_cartella>` (senza `--web-search`, che arriva nel Task
17). Non eseguire in parallelo con gli altri task di questa serie.

Nel progetto RT (/Users/attilioturco/Desktop/trt), leggi per intero `rt/pipeline/build.py`
(in particolare `render_rielaborato_md` e `run_build`) prima di modificarlo — non indovinare
la forma delle funzioni esistenti. Implementa direttamente, senza produrre un piano
preliminare.

## Contesto e vincoli confermati sulla struttura esistente

`render_rielaborato_md` genera per ogni macro-sezione una riga `## {macro.id}. {macro.title}`
(H2) seguita, per ciascuna unità, da `### {unit.id} {unit.title}` (H3) più il contenuto. Le
immagini vanno inserite SUBITO DOPO la riga dell'heading di macro-sezione (`##`) e PRIMA della
prima riga di heading di unità (`###`) di quella stessa macro-sezione.

**Importante**: il file che l'utente legge/apre NON è `rielaborato.md` — `run_build` scrive
`rielaborato.md` come intermedio interno (usato solo per il fingerprint di idempotenza), poi
ne scrive una COPIA con nome formale a livello di root della lezione (`[{data}] {MATERIA} -
{titolo_formale}.md`, tramite lo stesso helper `_atomic_write_text` usato per tutti gli altri
file). Questo comando deve riscrivere ENTRAMBI i file (stesso contenuto), non solo uno.
Decisione presa con l'utente: le immagini vanno SOLO in `rielaborato.md`/il deliverable
finale, MAI in `pre-elaborato.md` o negli altri file diagnostici (Revisioni ASR, Errori
concettuali, Problemi scientifici) — non toccare quelle funzioni di rendering.

## Parte 1 — Estensione di `render_rielaborato_md`

Aggiungi un parametro opzionale `images_by_macro: Optional[Dict[str, List[dict]]] = None`
(macro_id → lista di entry `descriptions.json`, cioè dict con almeno `filename` e `alt_text`)
e un parametro `carousel: bool = False`. Subito dopo la riga dell'heading `##` di ciascuna
macro-sezione (trova il punto esatto nel loop esistente), se `images_by_macro` contiene
immagini per quella `macro.id`:

- **Formato normale** (`carousel=False`, default): una riga per immagine,
  `f"![{img['alt_text']}]({img['filename']})\n"` (nota: `img['filename']` è già il path
  relativo `assets/images/<hash>.png` salvato dal Task 13/14 — non ri-derivarlo).
- **Formato carosello** (`carousel=True`): raggruppa tutte le immagini della macro-sezione in
  un blocco fenced, formato ESATTO richiesto dall'utente:
  ```
  ```napkin-notes
  [[assets/images/<hash1>.png]]

  [[assets/images/<hash2>.png]]
  ```
  ```
  (righe `[[path]]` separate da una riga vuota, senza il prefisso `![]()` markdown — sono
  wikilink in stile Obsidian dentro un blocco di codice fenced `napkin-notes`, per un plugin
  Obsidian che li renderizza come carosello. Nessuna descrizione testuale per riga a meno che
  tu non trovi comodo aggiungerla come testo libero dopo il wikilink sulla stessa riga logica,
  ma NON è richiesto esplicitamente — l'elemento essenziale è il formato del blocco fenced con
  i wikilink).

## Parte 2 — Orchestratore `run_add_images` (`rt/pipeline/add_images.py`)

```python
def run_add_images(
    lesson_dir: str,
    input_path: Optional[str] = None,
    carousel: bool = False,
    force_mock: bool = False,
) -> Dict[str, Any]:
    """Orchestratore principale di 'rt add-images' (senza --web-search, aggiunto nel Task 17).
    1. Verifica che la lezione sia già stata buildata (check_phase_status(lesson_dir, "build")
       == PhaseStatus.VALID, da rt.core.idempotency — vedi come altri comandi supplementari
       fanno un controllo di prerequisito analogo, es. cmd_recall in rt/cli.py verifica la
       fase 'rewrite'). Se non VALID, solleva un errore chiaro che invita a fare prima 'rt build'.
    2. Se input_path è fornito: estrae le immagini grezze (rt.core.image_extract.extract_images),
       separa nuove/cachate (partition_new_vs_cached_images, Task 13), descrive le nuove
       (describe_new_images, Task 14, con il contesto lezione = materia+titolo da info.yaml
       per sorgenti pdf:/folder:).
    3. Carica l'outline (rt.pipeline.outline.load_outline) e chiama judge_images_by_macro
       (Task 15) sull'INTERO descriptions.json (nuove + già cachate insieme — un'immagine già
       descritta in un run precedente deve poter essere comunque rivalutata per l'assegnazione
       alle macro-sezioni di QUESTO run, l'assegnazione non viene mai cachata, solo la
       descrizione).
    4. Ricostruisce images_by_macro nel formato atteso da render_rielaborato_md: per ogni
       macro_id -> [entry completa da descriptions.json per ogni hash assegnato].
    5. Ricarica outline/draft/segments/ledger esattamente come fa run_build (leggi
       run_build in rt/pipeline/build.py per il pattern esatto di caricamento) e richiama
       render_rielaborato_md(..., images_by_macro=images_by_macro, carousel=carousel).
    6. Riscrive SIA rielaborato.md SIA la copia con nome formale (stesso identico pattern di
       run_build — il nome formale si ricava dallo stesso modo in cui run_build lo fa, non
       reinventarlo: leggi come run_build costruisce 'named_filepath' e riusalo identico).
    7. NON tocca pre-elaborato.md né gli altri file diagnostici.
    Ritorna un dict di riepilogo: {"images_added": N, "macros_with_images": [...], "rielaborato_md": path, "deliverable_md": path}.
    """
```
Se né `input_path` è passato (questo task) né `--web-search` (Task 17) sono forniti a livello
di CLI, il comando deve fallire con un messaggio chiaro — quel controllo va nel comando CLI
(Parte 3), non qui dentro (questa funzione può essere chiamata anche con solo `input_path` da
un test, indipendentemente dal Task 17).

## Parte 3 — Comando CLI `rt add-images`

In `rt/cli.py`, nuovo subparser (stesso stile/posizione di `recall`/`review-asr` — leggi
`cmd_recall`/il subparser `p_recall` come modello diretto da imitare per il pattern di
controllo prerequisiti + `_ensure_config_ready`):
```python
p_addimg = subparsers.add_parser("add-images", help="Integra slide/foto (o immagini trovate sul web) nel documento finale, per macro-sezione")
p_addimg.add_argument("lesson_dir", help="Directory della lezione")
p_addimg.add_argument("-i", "--input", default=None, help="Percorso a un file PDF di slide o una cartella di foto")
p_addimg.add_argument("--carousel", action="store_true", help="Raggruppa le immagini di ogni sezione in un blocco carosello (plugin Obsidian napkin-notes) invece di righe immagine singole")
p_addimg.add_argument("--mock", action="store_true", help="Usa mock deterministico (nessuna chiamata LLM/vision reale)")
p_addimg.set_defaults(func=cmd_add_images)
```
(il flag `--web-search` verrà aggiunto dal Task 17 su questo stesso subparser — non lasciare
spazio incompatibile, ma non implementarlo qui).

```python
def cmd_add_images(args):
    if not getattr(args, "input", None):
        print("❌ Nessuna sorgente di immagini indicata. Usa -i <pdf_o_cartella>.", file=sys.stderr)
        sys.exit(1)
    if not getattr(args, "mock", False):
        _ensure_config_ready(["image_description", "image_unit_judge"])
    from rt.pipeline.add_images import run_add_images
    try:
        res = run_add_images(args.lesson_dir, input_path=args.input, carousel=args.carousel, force_mock=args.mock)
    except Exception as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)
    print(f"✔ {res['images_added']} immagini aggiunte, {len(res['macros_with_images'])} sezioni coinvolte.")
    print(f"  - {res['deliverable_md']}")
```
(la condizione "nessuna sorgente" nel task 17 dovrà diventare "né -i né --web-search" —
lascia un commento `# TODO Task 17: includere --web-search in questo controllo` se preferisci,
o semplicemente aggiorna tu stesso questa condizione quando arrivi al Task 17 in sequenza).

## Test

Aggiungi test end-to-end (mock) in `tests/test_add_images.py`: una lezione di test già
buildata (fixture con outline/draft/segments minimi, 2 macro-sezioni), esegui `run_add_images`
con un PDF/cartella di test e `force_mock=True`, verifica che `rielaborato.md` e il file con
nome formale contengano le righe `![...](assets/images/...)` sotto la macro-sezione giusta e
che `pre-elaborato.md` resti invariato. Test separato per `--carousel` che verifica il blocco
fenced esatto. Test per il rifiuto quando la lezione non è ancora buildata. Esegui
`python3 -m pytest tests/ -q` e correggi eventuali fallimenti tu stesso prima di considerare il
task concluso.

## Attenzione — bug di portabilità ricorrente in questo progetto

Più round di task precedenti hanno usato `Optional[...]`/`List[...]`/`Dict[...]` come
annotazione di tipo senza il corrispondente `from typing import ...` in cima al file — funziona
per puro caso in questo ambiente (Python 3.14 valuta le annotazioni in modo differito di
default, PEP 649) ma darebbe `NameError` su Python <3.14. Verifica sempre che ogni nome da
`typing` che usi sia importato esplicitamente nel file che lo usa.
