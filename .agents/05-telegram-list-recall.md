# Task 05 — Telegram: indice lezioni, `/list` e `/recall <query>`

**Da lanciare SOLO dopo che i task 02 e 03 sono completati** (usa campi di config e funzioni
che 03 introduce, e tocca file che 02 ripulisce prima). Non eseguire in parallelo con 02/03.

Nel progetto RT (/Users/attilioturco/Desktop/trt), implementa direttamente due nuove funzionalità
Telegram, senza produrre un piano preliminare. PRECONDIZIONE: prima di iniziare, verifica che
esistano già rt.core.config.TelegramRuntimeConfig.lessons_root, .misc_topic_id, e
rt.telegram.config.reverse_resolve_materia (aggiunti dal task 03, che deve essere già completato)
— se non esistono ancora, fermati e segnala che le precondizioni non sono soddisfatte.

CONTESTO: oggi non esiste alcuna funzione che scansiona una cartella per elencare tutte le
lezioni (ogni lezione è una sottocartella con un info.yaml contenente materia/data/argomenti/
titolo). Il comando Telegram /recall esiste ma è a zero argomenti (risolve solo tramite un
override YAML statico o "ultima lezione di questo topic"). Bisogna aggiungere: un comando /list
che elenca le lezioni della materia associata al topic corrente, e generalizzare /recall per
accettare una query testuale (data e/o parola chiave) che cerca tra le lezioni della materia del
topic corrente. rt.pipeline.setup.parse_flexible_date(raw_input) già normalizza date come
"11 marzo 2026"/"11 mar 2026"/"11-03-2026" in "YYYY-MM-DD" e solleva ValueError su testo non
riconoscibile come data (es. "catabolismo") — riusala così com'è, non riscriverla.

1. Crea rt/core/lesson_index.py (nuovo file):
   ```python
   from dataclasses import dataclass
   from typing import List
   import os
   from rt.core.state import read_info_yaml
   from rt.core.lesson_paths import lesson_path

   @dataclass
   class LessonEntry:
       lesson_dir: str
       folder_name: str
       data: str
       materia: str
       titolo: str
       argomenti: str

   def scan_lessons(lessons_root: str) -> List[LessonEntry]:
       """Enumera le sottocartelle DIRETTE di lessons_root (struttura piatta, nessun
       annidamento) con un info.yaml leggibile. Cartelle senza info.yaml valido sono
       ignorate silenziosamente."""
       entries = []
       if not lessons_root or not os.path.isdir(lessons_root):
           return entries
       for name in sorted(os.listdir(lessons_root)):
           full = os.path.join(lessons_root, name)
           if not os.path.isdir(full):
               continue
           yaml_path = lesson_path(full, "info.yaml")
           if not os.path.isfile(yaml_path):
               continue
           try:
               info = read_info_yaml(yaml_path)
           except Exception:
               continue
           entries.append(LessonEntry(
               lesson_dir=full,
               folder_name=name,
               data=str(info.get("data", "")),
               materia=str(info.get("materia", "")).strip().upper(),
               titolo=str(info.get("titolo", "")),
               argomenti=str(info.get("argomenti", "")),
           ))
       return entries

   def filter_by_materia(entries: List[LessonEntry], materia_upper: str) -> List[LessonEntry]:
       return [e for e in entries if e.materia == materia_upper]

   def filter_unmapped(entries: List[LessonEntry], topics: dict) -> List[LessonEntry]:
       mapped = set((topics or {}).keys())
       return [e for e in entries if e.materia not in mapped]

   def filter_by_date(entries: List[LessonEntry], iso_date: str) -> List[LessonEntry]:
       return [e for e in entries if e.data == iso_date]

   def filter_by_keyword(entries: List[LessonEntry], keyword: str) -> List[LessonEntry]:
       kw = keyword.strip().lower()
       if not kw:
           return list(entries)
       return [e for e in entries if kw in e.materia.lower() or kw in e.titolo.lower()
               or kw in e.argomenti.lower() or kw in e.folder_name.lower()]
   ```

2. Crea rt/telegram/lesson_query.py (nuovo file):
   ```python
   from typing import List, Tuple
   from rt.core.lesson_index import LessonEntry, filter_by_date, filter_by_keyword
   from rt.pipeline.setup import parse_flexible_date

   MAX_INLINE_DISAMBIGUATION = 4

   def resolve_recall_query(entries: List[LessonEntry], raw_query: str) -> Tuple[str, List[LessonEntry]]:
       """Ritorna (mode, matches). mode in {'date_and_keyword', 'date', 'keyword'}."""
       raw_query = raw_query.strip()
       if " - " in raw_query:
           date_part, _, keyword_part = raw_query.partition(" - ")
           date_part = date_part.strip()
           if date_part:
               try:
                   iso_date = parse_flexible_date(date_part)
                   matches = filter_by_keyword(filter_by_date(entries, iso_date), keyword_part)
                   return "date_and_keyword", matches
               except ValueError:
                   pass
           return "keyword", filter_by_keyword(entries, raw_query)

       try:
           iso_date = parse_flexible_date(raw_query)
           return "date", filter_by_date(entries, iso_date)
       except ValueError:
           return "keyword", filter_by_keyword(entries, raw_query)
   ```

3. In rt/telegram/formatting.py, aggiungi (stesso stile/posizione delle altre funzioni di
   rendering testo già presenti, es. render_outline_summary_text):
   ```python
   def render_lesson_list_text(entries, show_materia: bool) -> str:
       lines = []
       for i, e in enumerate(entries, start=1):
           label = e.titolo or e.argomenti or e.folder_name
           suffix = f" ({e.materia})" if show_materia and e.materia else ""
           lines.append(f"{i}. [{e.data}] {escape_html(label)}{suffix}")
       return "\n".join(lines)
   ```
   (usa la stessa funzione `escape_html` già usata dalle altre funzioni di formatting.py in
   questo file, per coerenza con l'HTML parse-mode dei messaggi).

4. In rt/telegram/daemon.py:
   - Aggiungi un handler `handle_list_command(update, context)`: legge
     `runtime_cfg = load_config().telegram`; se `runtime_cfg.lessons_root` non è impostato,
     rispondi con un messaggio d'errore che invita a configurarlo (menziona
     docs/CONFIGURATION_REFERENCE.md); altrimenti `entries = scan_lessons(runtime_cfg.lessons_root)`,
     risolvi `materia = reverse_resolve_materia(thread_id, runtime_cfg.topics)` (thread_id da
     `update.effective_message.message_thread_id`); se `materia` è risolta, filtra con
     `filter_by_materia` e `show_materia=False`; altrimenti filtra con `filter_unmapped` e
     `show_materia=True`; se la lista risultante è vuota, rispondi "Nessuna lezione trovata per
     questo topic."; altrimenti rispondi con `render_lesson_list_text(...)`. Registra l'handler
     con `application.add_handler(CommandHandler("list", handle_list_command))` accanto agli
     altri CommandHandler già registrati in run_daemon.
   - Generalizza `handle_recall_command` (oggi gestisce solo il caso a zero argomenti): se
     `context.args` è vuoto, mantieni ESATTAMENTE la catena di risoluzione esistente (override
     YAML → last_lesson → messaggio d'errore), aggiungendo solo una menzione di /list nel
     messaggio d'errore finale. Se `context.args` non è vuoto: unisci gli argomenti in
     `raw_query`, carica `runtime_cfg = load_config().telegram` (stesso controllo su
     `lessons_root` mancante del punto precedente), scansiona con `scan_lessons`, applica LO
     STESSO scoping per materia di /list (filter_by_materia o filter_unmapped in base al topic
     corrente) PRIMA di chiamare `resolve_recall_query(scoped_entries, raw_query)`, poi:
     - 0 match → "Nessuna lezione trovata per '{raw_query}'. Usa /list per vedere le lezioni disponibili."
     - 1 match → avvia subito la sessione: `await loop.run_in_executor(None, start_recall_via_telegram, match.lesson_dir, "alternato", None, False)` (usa lo stesso pattern già presente altrove in questo file per chiamare funzioni sincrone bloccanti da un handler async — verifica come lo fa già il resto di daemon.py per `start_recall_via_telegram` e riusa lo stesso approccio esatto).
     - 2-4 match → manda `render_lesson_list_text(matches, show_materia=True)` seguito da
       un'istruzione a scegliere, PIÙ una `InlineKeyboardMarkup` con un'unica riga di N bottoni
       affiancati (`InlineKeyboardButton(str(i+1), callback_data=f"rld:{short_id}:{i}")`),
       dove `short_id = tg_registry.register_pending(lesson_dir=matches[0].lesson_dir,
       round_=0, kind="recall_disambiguation", state_dir=runtime_cfg.state_dir,
       message_thread_id=thread_id, extra={"candidate_dirs": [m.lesson_dir for m in matches]})`
       (adatta ai parametri reali già accettati da `register_pending` in questo file — leggilo
       prima di chiamarlo).
     - >4 match (usa `MAX_INLINE_DISAMBIGUATION` da rt.telegram.lesson_query) → SOLO la lista
       testuale (nessun bottone), con un messaggio che invita a una query più specifica (data
       e/o parola chiave aggiuntiva, o "data - parola chiave").
   - Aggiungi un handler `_handle_recall_disambiguation_callback` per il nuovo prefisso di
     callback `"rld"` (registralo nel dispatch di `handle_callback` seguendo lo stesso pattern
     usato dagli altri prefissi già gestiti lì, es. quello delle issue): decodifica
     `short_id` e `idx` da `callback_data` (split su `:`), recupera la entry registrata via
     `tg_registry` (leggi come gli altri handler già fanno il lookup), prende
     `extra["candidate_dirs"][int(idx)]`, e avvia il recall su quella cartella esattamente come
     nel caso "1 match" sopra.

5. Scrivi test per le nuove funzioni pure: crea tests/test_lesson_index.py che copre
   scan_lessons/filter_by_materia/filter_unmapped/filter_by_date/filter_by_keyword con cartelle
   temporanee (pytest tmp_path) contenenti info.yaml fittizi, e un test per
   resolve_recall_query che copre i tre modi (data, keyword, "data - keyword") inclusi i casi
   limite (query che sembra una data ma non lo è, data valida senza risultati, keyword che
   contiene letteralmente " - ").

6. Esegui la test suite (pytest tests/ -q) e assicurati che passi.
