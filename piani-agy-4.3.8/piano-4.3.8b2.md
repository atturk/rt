# Piano 4.3.8b2: affidabilità delle fonti ed estensioni di RT (agy)

Da fare **dopo** la b1, sullo stesso branch `agy/4.3.8`. Un commit per voce. Il perché delle scelte è nel Claude Doc «RT 4.3.8: analisi… e piano», voci 5 e 6.

---

## 5. Affidabilità delle fonti

**Oggi.** `Source` (`rt/core/sources.py:34`) ha `tipo`, `uso`, `pagine`, `estrai`. Gli appunti in foto o PDF sono `materiale` e nella verifica finiscono sotto «MATERIALI DEL DOCENTE»: prima passata (`build_science_review_user_prompt`, `rt/llm/prompts.py` ~riga 323), seconda passata (`SECOND_PASS_REVIEW_SYSTEM_PROMPT` e `build_second_pass_review_prompt`, ~riga 39; pagine da `source_index.search` in `rt/pipeline/review.py` ~riga 503, etichetta `[Fonte: file, pag. N]`) e deriva JEV (`run_jev_task_b`, `review.py` ~riga 298).

**Scelta fissata:** tre categorie, **senza percentuali da nessuna parte**: `alta`, `normale`, `bassa`. Predefinito `normale`.

**Cosa fare.**
1. **Dato:** `Source.affidabilita: Literal['alta', 'normale', 'bassa'] | None = None`; `None` vale `normale`. Accettalo dove si accetta già `uso`: `rt/api/routers/lesson_sources.py` (form ~riga 76 e modello ~riga 168), `rt/api/routers/archive.py` (~riga 115, `add_to_lesson`), `add_source`/aggiornamento in `sources.py`, creazione da `materials_lesson_service.py`. Vale anche per gli appunti di testo (`tipo == 'appunti'`).
2. **Interfaccia:** accanto a «uso», un selettore a tre voci «Affidabilità: Alta · Normale · Bassa», in `SourceControls.tsx` (Dettagli → Fonti) e nelle righe dei materiali del popup Nuova lezione (`NewLessonDialog.tsx`, dove si sceglie `uso`, ~riga 287). Sulla miniatura, solo se non è normale, una piccola icona (scudo pieno / scudo vuoto) con suggerimento «Affidabilità alta/bassa».
3. **Prompt, regola d'oro:** se tutte le fonti sono `normale`, **ogni prompt resta identico byte per byte a oggi** (serve anche alla cache dei prompt).
4. **Prima passata e JEV:** le pagine delle fonti `alta` vanno sotto «SLIDE E MATERIALI DEL DOCENTE (affidabilità alta)», quelle `bassa` sotto «APPUNTI DELLO STUDENTE (affidabilità bassa: possono contenere errori)», le `normale` restano sotto «MATERIALI DEL DOCENTE». `material_context_for_unit` (`material_mapping.py:771`) deve sapere l'affidabilità di ogni pagina (dal `source_id`).
5. **Seconda passata:** ogni pagina trovata porta l'affidabilità nell'etichetta solo se non è normale: `[Fonte: file, pag. N, affidabilità alta]`. Al system prompt si aggiungono queste regole **solo se tra le pagine trovate ce n'è almeno una alta o bassa**:
   - fonte ad affidabilità alta: attieniti alla fonte, salvo errori gravi e inconfutabili; se il docente a voce contraddice una fonte alta (es. «atri» invece di «ventricoli»), è «possibile_errore_del_docente», non «definizione_del_corso»;
   - fonte ad affidabilità bassa: consultala, ma da sola non basta per «definizione_del_corso»; se è l'unica prova, la segnalazione resta e la nota dice che la conferma viene solo dagli appunti.
6. Cambiare l'affidabilità non rilancia la verifica: vale dalla verifica successiva.
7. Rigenera `docs/openapi.json` e `frontend/src/api/schema.d.ts`.

**Test** (`tests/test_source_reliability.py` nuovo, più quelli dei componenti):
- con sole fonti normali i prompt di prima passata, seconda passata e JEV sono uguali a uno snapshot preso **prima** della modifica;
- il campo si salva e si legge via API (aggiunta, modifica, archivio) e resta dopo il riordino delle fonti;
- una fonte alta e una bassa producono le etichette giuste nei tre prompt;
- seconda passata mock: con una sola pagina bassa come prova l'esito non è «definizione_del_corso»;
- `SourceControls.test.tsx` e `NewLessonDialog.test.tsx`: il selettore cambia `affidabilita` nella richiesta.

## 6. Estensioni di RT: `.rt`, `.rtdb`, `.rtcal`

**Oggi.** I file aperti dal sistema arrivano da `application:openFiles:` (`rt/window.py:677`) e da `desktop --open "%1"` (Windows, `packaging/windows/rt.iss`), e `useOpenedFiles.ts` li manda **tutti** al popup Nuova lezione. RT è solo «Apri con» secondaria (`LSHandlerRank Alternate`, `scripts/build_app.py:274`). L'orario si esporta già come `.rtcal` (`calendar.py:159`, `CalendarScheduleSettings.tsx:41`); lezioni ed «Esporta tutto» sono `.zip`.

**Cosa fare.**
1. **Esportazioni:** export di lezioni → `.rt` (`rt/api/routers/lessons.py` ~righe 312-413, `LessonsView.tsx`, `ImportConflicts.tsx`); «Esporta tutto» → `.rtdb` (`backup_service.export_backup` e `window.py`, dialogo di salvataggio); orario già `.rtcal`. Il contenuto non cambia (ZIP e JSON).
2. **Importazioni:** ovunque si accetta `.zip` si accetta anche `.rt` (`jobs.py:173`, `lesson_import_service.py:52`, `accept` dei selettori); «Importa tutto» accetta `.rtdb` e `.zip`; l'orario `.rtcal` e `.json` (c'è già).
3. **Mac:** in `Info.plist` aggiungi `UTExportedTypeDeclarations` per `it.rt.lezioni` (`rt`, conforme a `public.zip-archive`), `it.rt.collezione` (`rtdb`, `public.zip-archive`) e `it.rt.orario` (`rtcal`, `public.json`). Un `CFBundleDocumentTypes` per ciascuno con `LSHandlerRank Owner` e la sua icona `.icns` in `packaging/icons/` (`rt-lezioni.icns`, `rt-collezione.icns`, `rt-orario.icns`: l'icona di RT su un foglio, generata da `rt.png` con uno script in `scripts/`). Il tipo «File supportati da RT» resta com'è.
4. **Windows:** in `rt.iss` tre ProgID (`RT.Lezioni`, `RT.Collezione`, `RT.Orario`) con `DefaultIcon` (`.ico` corrispondenti) e comando `--open "%1"`, associati alle tre estensioni, più `ChangesAssociations=yes` in `[Setup]`.
5. **Smistamento** (`useOpenedFiles.ts`, per estensione, minuscole):
   - `.rt` e `.zip` di lezioni → l'import di lezioni esistente, con conflitti e conferme;
   - `.rtcal` → naviga a Impostazioni → Calendario e apre il popup «Importa orario» già compilato (`CalendarScheduleSettings.tsx`): niente cambia finché non premi Importa o Sostituisci;
   - `.rtdb` → lato Python, la stessa strada di `_import_collection` (`window.py:901`) con il file già scelto al posto di `_chosen_file`. Il dialogo dice «Sostituisce tutte le lezioni, il database e il calendario attuali. Quelli attuali vengono messi da parte.» con data e versione della collezione; se un lavoro è in corso rifiuta, come oggi. Il frontend non scarica mai un `.rtdb` come allegato di Nuova lezione;
   - tutto il resto → Nuova lezione, come oggi.
6. **Apertura a freddo** (RT chiusa): lo smistamento vale anche per `file_in_attesa`.

**Test:** `useOpenedFiles.test.ts` per i quattro casi; `.rtcal` aperto non chiama `/calendar/import` senza il clic; un `.rtdb` passato al gestore Python chiama la conferma e, se annullata, non tocca niente (`tests/test_window_open_files.py`); `Info.plist` generato contiene i tre tipi (`tests/test_build_app.py`); `.zip` e `.json` vecchi funzionano ancora.

---

## Prima della PR

- Python: `python -m pytest tests/ -q -n auto --dist loadfile`.
- Frontend: `cd frontend && npm run lint && npm run typecheck && npm test`.
- Se cambi un modello delle API: `python scripts/export_openapi.py` e `npm run gen:api`.
- Non toccare VERSION né CHANGELOG.
