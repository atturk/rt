# Piano 4.3.4b2 — agy

Lista dei lavori della beta 4.3.4b2: quattro voci, piano definitivo.
Base: branch `claude/rt-4.3.4-beta` (contiene già la PR #135, errore leggibile nel popup di aggiornamento).
Lavora su `agy/4.3.4b2`, una PR verso `claude/rt-4.3.4-beta`, un commit per voce.
Regole UI: minimalismo, pulsanti a icona con suggerimento, niente testo superfluo.

## 1. Impostazioni: togliere la sezione «Studio»

In Impostazioni > Aspetto la sezione **Studio** (riga «Colori dell'evidenziatore» con
«Giallo, verde, azzurro, rosa, arancio» e l'interruttore «Frecce per cambiare unità») va tolta.

- `frontend/src/components/settings/preferences.tsx`, `AppearanceSection`: elimina il blocco
  `<Section id="studio" title="Studio">…</Section>` e la riga `const [highlighter, setHighlighter] = useHighlighterPrefs()`;
  togli `useHighlighterPrefs` dall'import di `@/lib/studyPrefs` (restano `useRsvpPrefs`, `RsvpPreference`).
- **Non** toccare `lib/studyPrefs.ts` né lo Studio: la preferenza `study.highlighter` resta (colore usato e
  `arrows`, default `true`), solo che non si cambia più dalle impostazioni. Le frecce ← → nello Studio continuano a funzionare.
- Collegamenti: cerca `#studio` / `impostazioni/aspetto#studio` nel frontend e nei test; se ci sono, toglili o puntali a `#aspetto`.
- Test:
  - `frontend/e2e/settings.spec.ts`, test «tema, lettura, audio e sfondo…»: togli i passaggi su
    «Frecce per cambiare unità» (click, controllo dopo il reload e il click che le riaccende); il resto del test resta.
  - `frontend/src/components/settings/preferences.test.tsx`: aggiungi un controllo che in `AppearanceSection`
    non ci siano più il titolo «Studio» né «Colori dell'evidenziatore».
- Verifica: `cd frontend && npm run lint && npx tsc -b && npm test`, e l'e2e `settings.spec.ts` se riesci a lanciarlo.

## 2. Studio: font e dimensione del testo dalle impostazioni

Nello Studio si sceglie il font e la dimensione del testo dell'unità (titolo e testo), da una sezione
delle impostazioni. Tra i font c'è **Seravek**.

**Preferenze**
- Nuovo file `frontend/src/lib/studyText.ts`:
  - `STUDY_FONTS`: `[valore, etichetta, stack CSS]`:
    - `sistema` · «Sistema» · `var(--font-sans)` (default, cioè come oggi);
    - `seravek` · «Seravek» · `Seravek, 'Gill Sans Nova', 'Avenir Next', var(--font-sans)`;
    - `avenir` · «Avenir Next» · `'Avenir Next', Avenir, var(--font-sans)`;
    - `georgia` · «Georgia» · `Georgia, 'Iowan Old Style', serif`;
    - `dislessia` · «OpenDyslexic» · `'OpenDyslexic', var(--font-sans)` (il font è già in `/fonts`, dichiarato in index.css).
  - Font: preferenza condivisa `study.text-font` (nome valido per il server: minuscole, punto, trattino), con `usePreference(name, 'sistema')`.
  - Dimensione: è lo stesso `textScale` che oggi lo Studio cambia con + e −, salvato per dispositivo in
    `localStorage['rt-device:study-text-scale']`, da 0,8 a 2,0 a passi di 0,1. Sposta `getSavedStudyTextScale`
    e il salvataggio da `Study.tsx` a un hook `useStudyTextScale()` in `studyText.ts`. Lo usano sia lo Studio
    sia le impostazioni: cambiando da una parte si vede dall'altra (evento `storage` o un piccolo store in memoria).
  - Font non installati: Seravek e Avenir ci sono solo sul Mac. In `studyText.ts` scrivi una funzione
    `fontAvailable(name)` che confronta su un canvas la larghezza di un testo col font e con il solo
    fallback. Nelle impostazioni mostra solo i font disponibili, più quello salvato. Se il font salvato
    non c'è, lo stack CSS ripiega da solo.

**Studio** (`frontend/src/components/study/Study.tsx`)
- Sulla `<section>` di `UnitText` (titolo `h2` e testo) imposta `style={{ fontFamily: stack }}`, con lo stack del font scelto.
  La dimensione resta com'è (`--study-text-scale`).
- Non applicarlo alla lettura veloce, che ha già il suo «Font per dislessia», né alle formule (`.rt-math` resta com'è).

**Impostazioni** (`frontend/src/components/settings/preferences.tsx`, `AppearanceSection`)
- Al posto della sezione tolta alla voce 1, nuova `<Section id="testo-studio" title="Testo dello Studio">` con due campi:
  - «Font»: `Select` (`SettingsSelect`) con i font disponibili. Ogni opzione è scritta nel suo font, se il Select lo permette.
  - «Dimensione»: `Select` da 80% a 200% a passi di 10%, che legge e scrive la stessa scala dello Studio.
- Niente frasi di spiegazione né anteprime lunghe. Al massimo una riga d'anteprima («Aa»
  o il titolo di esempio) nel font scelto, solo se resta discreta.

**Test**
- `studyText.test.ts`:
  - default `sistema`;
  - lo stack di `seravek` contiene `Seravek`;
  - la scala viene limitata fra 0,8 e 2,0.
- `preferences.test.tsx`: scegliendo «Seravek» si salva `study.text-font = 'seravek'`; con la dimensione a 120% la scala vale 1,2.
- `Study.test.tsx`: con `study.text-font = 'seravek'` la section del testo ha `font-family` con Seravek. Il test esistente dello zoom (+/−) deve restare verde.
- In jsdom il canvas non misura: falsifica `fontAvailable` (vi.mock) o fallo tornare `true` quando non può misurare.

## 3. PDF: timecode duplicato sotto il titolo dell'unità

Nel PDF ogni titolo di sottounità mostra il timecode due volte: accanto al titolo (`.print-timecode`, voluto) e, sotto, come paragrafo a sé («00:22»).

**Causa.** L'HTML del documento contiene dopo ogni titolo il paragrafo `[data-unit-timecode]` (`rt/services/lesson_service.py`). Nell'app lo nasconde `index.css` con `.rt-document [data-unit-timecode] { display: none }`, ma la pagina di stampa (`components/lesson/PrintLessonPage.tsx`) usa `.print-content`, non `.rt-document`, quindi il paragrafo resta visibile.

**Cosa fare**
- In `PrintLessonPage.tsx`, subito dopo `root.innerHTML = rawHtml`, rimuovi i paragrafi: `root.querySelectorAll('[data-unit-timecode]').forEach((el) => el.remove())`.
- Lascia com'è `lib/printDocument.ts` (la riga che salta `[data-unit-timecode]` è coperta da un test e non dà fastidio).
- Non toccare il backend né `index.css`.

**Test**
- `PrintLessonPage.test.tsx` (nuovo; mocka `useLesson` e `useLessonDocument`): con un documento `<h3 data-unit-id="u1">Titolo</h3><p data-unit-timecode="u1">00:22</p><p>Testo</p>` e una sezione `{unit_id: 'u1', start_formatted: '00:22'}`, il testo «00:22» compare una sola volta (dentro `.print-timecode`) e non c'è nessun `[data-unit-timecode]`.
- `printDocument.test.ts` resta verde senza modifiche.

## 4. Classificatore: pagine delle fonti lette come descrizione o come immagine

Oggi una pagina di una fonte in «Testo e immagini» (né guida né Integra) si colloca solo sul testo: `place_page_in_outline` passa a Jev `mapping_text`, che per le pagine con figure e poche parole è la descrizione del modello visivo. L'immagine non arriva mai al classificatore. Serve un'impostazione per passargli l'immagine anche quando la pagina è stata descritta. **Il default resta il comportamento di oggi.**

**Config** (`rt/core/config.py`, `ClassifierConfig`)
- Nuovo campo `material_pages_reader: Literal["description", "image"] = "description"`, con un commento di una riga come quello di `images_reader`.
- In `rt/pipeline/image_decision.py` aggiungi `uses_image_for_material_pages(cfg=None) -> bool`: vale `True` solo se `material_pages_reader == "image"` e il job `images` non è `off` (stessa forma di `uses_decision_reader`). Non leggere `RT_IMAGES_READER`.

**Pipeline** (`rt/pipeline/material_mapping.py`, `assign_material_pages`, solo nel ramo `else`, cioè fonti non principali e non Integra)
- Calcola il flag una volta prima del ciclo sulle fonti. Riusa `image_cache` (`load_cache`) come fa il ramo `solo_immagini`.
- Per ogni pagina, con il flag attivo e `page.get("has_figures")`, `page.get("immagini")` e `not page.get("mapping_skip")`:
  - per la prima immagine della pagina chiama `decide_image(lesson_dir, outline, h, data, page["testo"], image_cache, mock=mock, ctx=ctx)`. Il testo passato è quello completo, descrizione compresa;
  - le unità e le macro restituite prendono il posto di quelle di `place_page_in_outline`. Se il ruolo non è `contenuto`, la pagina non va da nessuna parte;
  - salva il ruolo in `descriptions[h]["ruolo"]`, come nel ramo `solo_immagini`;
  - se `decide_image` solleva un errore (tranne `RunCancelled`), ricadi su `place_page_in_outline` per quella pagina.
- Le altre pagine (senza figure, o con il flag spento) restano su `place_page_in_outline`.
- Il resto non cambia: `page_info` va in `pages_by_unit` / `pages_by_macro` con le unità scelte, quindi il testo continua a fare da contesto, e le immagini si collocano come oggi.
- La descrizione delle pagine in `rt/core/materials.py` resta com'è: serve al contesto e alla ricerca in archivio.
- Non toccare `place_page_in_outline`, che usa anche l'Arricchimento.

**API e tipi**
- Il campo passa da GET/PUT delle impostazioni del classificatore come `images_reader`. Rigenera `docs/openapi.json` con `scripts/export_openapi.py` e `frontend/src/api/schema.d.ts` con `npm run gen:api`.

**UI** (`frontend/src/components/settings/classifier.tsx`, riga del job `images`)
- Accanto al Select «Lettura immagini», visibile alle stesse condizioni, aggiungi un Select con `aria-label="Lettura pagine delle fonti"` e le opzioni `description` «Descrizione» (default) e `image` «Immagine». Nessun testo in più.
- Nella probe, `with_image` vale `true` anche quando `material_pages_reader === 'image'`.

**Test**
- `tests/test_material_mapping.py`:
  - con il default, una pagina con figure passa da `place_page_in_outline` e `decide_image` non viene chiamato;
  - con `material_pages_reader="image"` e job images non `off`, `decide_image` riceve i byte dell'immagine e il testo della pagina, e la sua scelta finisce in `units` e in `pages_by_unit`;
  - con il ruolo diverso da `contenuto`, la pagina non viene collocata;
  - se `decide_image` solleva un errore, si usa il risultato di `place_page_in_outline`;
  - una pagina senza figure usa sempre il testo.
  - Se un test richiede il marker `decision_reader` (vedi `tests/conftest.py` / `pytest.ini`), usalo.
- `classifier.test.tsx` (o il test delle impostazioni del classificatore): il nuovo Select salva `material_pages_reader: 'image'`.
