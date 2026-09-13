# Task 48 — Notifica Telegram "Build completata": mostra data/argomenti/materia invece del percorso file

Indipendente dagli altri task attivi. Nel progetto RT (/Users/attilioturco/Desktop/trt),
implementa direttamente, senza produrre un piano preliminare.

## Contesto

Quando la pipeline completa una lezione, Telegram manda una notifica che oggi include il
percorso assoluto del file `rielaborato.md`. L'utente vuole invece un messaggio che dica: che la
lezione è pronta, con data e argomenti; la MATERIA solo se il topic di destinazione è quello
generico/"varie" (non se è un topic dedicato a una materia specifica, dove sarebbe ridondante);
e che con `/list` si possono vedere tutte le lezioni disponibili.

**File/funzione**: `rt/telegram/notify.py::notify_build_completed(lesson_dir, build_result,
lesson_title)` (righe 9-33). Testo attuale (righe 23-27):
```python
text = (
    f"✅ &lt;b&gt;Build completata&lt;/b&gt;\n"
    f"{escape_html(lesson_title)}\n"
    f"📄 {escape_html(str(build_result.get('rielaborato', '')))}"
)
```
`build_result['rielaborato']` è il percorso assoluto (da `rt/pipeline/build.py`, righe
421-432). Chiamata da `rt/cli.py` righe 339-348 (`cmd_build`) e righe 581-583 (dentro `rt run`),
con `lesson_title` già passato (da `load_outline(lesson_dir).lesson_title`, fallback al nome
cartella — vedi `_get_lesson_title_for_notify`, righe 190-195 di `cli.py`).

## Modifica

In `notify_build_completed`, leggi `info.yaml` dalla `lesson_dir` (via
`read_info_yaml(lesson_path(lesson_dir, "info.yaml"))`, stesso helper già usato altrove — es.
`rt/core/state.py`) per ottenere `data`, `materia`, `argomenti`. Determina se il topic di
destinazione è quello generico: la funzione calcola già `message_thread_id` (righe 21-22 circa,
via `resolve_topic_id`) — confronta la materia della lezione con le chiavi di
`runtime_cfg.topics` (stessa logica già usata in `rt/core/lesson_index.py::filter_unmapped`,
righe 55-57, o l'equivalente più diretto: se `materia.strip().upper()` non è tra le chiavi
mappate in `runtime_cfg.topics`, il topic di destinazione è quello generico/varie).

Costruisci il nuovo messaggio, es.:
```
✅ Lezione pronta
📅 {data}
{argomenti se presenti}
{materia, SOLO se il topic è quello generico/varie}

Usa /list per vedere tutte le lezioni disponibili.
```
Adatta la formattazione HTML esistente (escape con `escape_html`) e lo stile del resto dei
messaggi del progetto (emoji, grassetto `<b>`). Rimuovi completamente la riga col percorso file
(`📄 ...`).

Non cambiare la firma di `notify_build_completed` se non strettamente necessario — i dati
aggiuntivi (data/materia/argomenti) vanno letti da `lesson_dir`, già disponibile come parametro,
non serve aggiungere nuovi argomenti.

## Test

- Test che verifica il nuovo testo del messaggio per una lezione con topic dedicato (materia
  mappata): il messaggio NON deve contenere la materia, deve contenere data e argomenti, deve
  menzionare `/list`, e non deve più contenere alcun percorso file.
- Test per una lezione destinata al topic generico/varie: il messaggio DEVE includere la
  materia.
- Test per una lezione senza argomenti (campo vuoto in `info.yaml`): il messaggio non deve
  mostrare una riga vuota o placeholder per gli argomenti.

Esegui `python3 -m pytest tests/ -q` e correggi finché l'intera suite passa.

## Vincoli

Verifica il bug di portabilità ricorrente sulle annotazioni `typing` per qualunque riga toccata
(vedi `.agents/00-README.md`).

## Verifica finale

1. `python3 -m pytest tests/ -q`.
2. Se hai un bot Telegram di test disponibile: verifica il messaggio reale ricevuto per una
   lezione con topic dedicato e una con topic generico. Altrimenti documenta che non è stato
   possibile e sarà l'utente a verificarlo sul proprio bot.
