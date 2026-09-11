# Task 06 — Conferma outline da terminale: fix HTML, vista ad albero espandibile, diff tra revisioni

Indipendente dai task 07-10 (nessun file condiviso). Consolida anche il polish con `questionary`
che era stato rimandato durante il Task 02 (vedi nota in fondo a `rt/pipeline/outline_review.py`
"il polish con questionary è un task separato, non toccarlo qui" — questo è quel task).

Nel progetto RT (/Users/attilioturco/Desktop/trt), implementa direttamente, senza produrre un
piano preliminare:

## Bug 1 — HTML grezzo mostrato nel terminale

`rt/telegram/formatting.py:17-29`, `render_outline_summary_text(outline)`, costruisce testo con
markup HTML (`<b>...</b>`) pensato per `parse_mode="HTML"` di Telegram, e
`rt/pipeline/outline_review.py:34-56` (`_confirm_via_terminal`) lo stampa a schermo verbatim,
mostrando letteralmente `<b>1. Titolo</b>` invece di formattarlo.

Aggiungi un parametro `for_telegram: bool = True` a `render_outline_summary_text`: quando
`False`, ometti i tag `<b>`/`</b>` (titolo lezione e header macro-sezione restano testo semplice,
`escape_html` non serve più in quel ramo dato che non stai costruendo HTML). Aggiorna l'unico
altro chiamante (nel percorso Telegram, se ancora presente altrove — verifica con grep
`render_outline_summary_text` in tutto `rt/`) perché continui a passare `for_telegram=True`
esplicitamente o lasci il default invariato.

## Bug 2 — troncamento a 3800 caratteri applicato anche al terminale

Stesso file, riga 10 e 27-28: `MAX_MESSAGE_CHARS = 3800` è un margine di sicurezza sotto il
limite di 4096 caratteri di un messaggio Telegram — non ha senso applicarlo al terminale, dove
l'utente perde la vista completa dell'outline con lezioni che hanno molte macro-sezioni/unità.
Il troncamento deve applicarsi SOLO quando `for_telegram=True`.

## Vista interattiva ad albero per il terminale (sostituisce il rendering statico + `input()`)

Il terminale oggi mostra l'outline come testo statico e chiede `input()` con scelta A/M
(`rt/pipeline/outline_review.py:34-56`). Sostituiscila con una vista interattiva navigabile,
sullo stesso modello già usato in `rt/pipeline/issue_review.py` per la review ASR/scienza
(vedi `raw_mode()`/`read_single_key` da `rt/core/keyboard.py`, e `rich.live.Live` per il
redraw) — NON serve `questionary` per l'albero (non ha un widget ad albero: solo
select/checkbox/text/confirm; verificato, non usarlo per questa parte), ma resta utile per il
prompt finale di modifica testuale (vedi sotto).

Costruisci la vista con `rich.tree.Tree` (già dipendenza, `rich>=13.0`):
- Un nodo radice col titolo della lezione.
- Un nodo figlio per ogni macro-sezione (`macro.id`. `macro.title`).
- Un nodo figlio per ogni unità didattica sotto la sua macro-sezione (`unit.id` `unit.title`
  più i primi `key_concepts`).
- Naviga con le frecce (già supportate da `read_single_key`, vedi come le usa `issue_review.py`
  per gli spostamenti) tra i nodi macro-sezione; Invio/Spazio espande/collassa la macro-sezione
  evidenziata (mostra/nasconde le sue unità); le unità partono collassate di default se la
  lezione ha più di, diciamo, 4 macro-sezioni (soglia ragionevole, non serve renderla
  configurabile), altrimenti tutte espanse di default.
- In fondo alla schermata, un prompt sempre visibile: `[A]pprova / [M]odifica / [↑↓] Naviga /
  [Invio] Espandi-Collassa`.
- Premendo `A`: esci dal loop, approva (comportamento identico a oggi).
- Premendo `M`: esci dalla modalità raw/albero, chiedi il feedback testuale libero con
  `questionary.text("Descrivi le modifiche desiderate:").ask()` (qui sì, per il testo libero,
  `questionary` va benissimo — coerente con quanto già usato altrove nel progetto, es.
  `rt/pipeline/setup.py::_prompt_materia_select`), poi chiama `run_outline_revision(...)` come
  già avviene oggi.

## Vista diff dopo una revisione

Quando l'utente ha chiesto una modifica e `run_outline_revision` ha prodotto una nuova outline,
mostra un confronto tra la vecchia e la nuova invece di ripartire da una vista pulita: prima
della chiamata a `run_outline_revision`, salva l'outline corrente in una variabile locale
(es. `previous_outline = load_outline(lesson_dir)` PRIMA di invocare la revisione — oggi
`_confirm_via_terminal` ricarica sempre l'outline da disco a ogni iterazione del loop, quindi
la versione precedente va catturata esplicitamente altrimenti si perde, dato che
`run_outline_revision` sovrascrive `outline.json` e non ritorna né persiste la versione
precedente).

Confronta le due `Outline` (schema esatto in `rt/core/models.py`: `Outline{lesson_title,
macro_sections: List[OutlineMacro]}`, `OutlineMacro{id, title, units: List[OutlineUnit]}`,
`OutlineUnit{id, title, start_segment_id, end_segment_id, key_concepts}` — i nomi delle classi
sono `Outline`/`OutlineMacro`/`OutlineUnit`, non `MacroSection`/`Unit`) confrontando gli `id`
(stringhe gerarchiche stabili tipo "1", "1.1" — i titoli possono cambiare tra le revisioni,
quindi la chiave del confronto deve essere l'id, non il titolo):
- Macro-sezione/unità presente solo nella nuova outline → prefisso `+` (verde se il terminale
  supporta colore, usa `rich` per questo).
- Macro-sezione/unità presente solo nella vecchia → prefisso `-` (rosso).
- Presente in entrambe con titolo/contenuto invariato → nessun prefisso, testo normale
  (eventualmente attenuato/dim).
- Presente in entrambe ma con titolo cambiato → mostra entrambe le versioni o un prefisso `~`
  a tua scelta implementativa, purché sia chiaro all'occhio cos'è cambiato.

Poi torna alla stessa vista ad albero navigabile (ora sulla outline nuova, con i marcatori diff
sovrapposti) per un nuovo giro di Approva/Modifica.

## Test

Aggiorna/aggiungi test in `tests/test_outline_review.py` per: `render_outline_summary_text`
con `for_telegram=False` (nessun tag HTML, nessun troncamento anche oltre 3800 caratteri) e
`for_telegram=True` (comportamento invariato rispetto a oggi). Per la parte interattiva, se è
difficile testare l'intera navigazione a schermo, testa almeno la logica pura di costruzione
dell'albero e del diff (funzioni separate, non l'intero loop I/O) in isolamento. Esegui
`python3 -m pytest tests/ -q` e assicurati che passi, correggendo eventuali fallimenti tu
stesso prima di considerare il task concluso.
