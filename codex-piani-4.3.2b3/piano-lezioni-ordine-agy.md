# Piano 2 · Lezioni: nessun raggruppamento e ordine "(Ri)create di recente"

## Com'è oggi

- Il gruppo di pulsanti Raggruppa (`frontend/src/components/lessons/LessonsView.tsx:96-118`) ha
  Data/Mese, Materia e Docente, e uno è sempre attivo. `LessonsGrouping`
  (`frontend/src/lib/lessonsPage.ts:12`) non ha "nessuno", e il valore predefinito è `data`.
- Gli ordinamenti (`SORT_OPTIONS`, `lessonsPage.ts:19-26`) valgono solo dentro ogni gruppo: con
  "Più avanti nello studio" le lezioni restano divise per giorno, quindi l'ordine vero non si vede.
- `groupLessons` (`frontend/src/lib/lessonView.ts:153`) sa già fare un gruppo unico con
  `group === 'nessuno'`.

## Cosa deve succedere

1. **Nessun raggruppamento.** Un clic sul pulsante del raggruppamento già attivo lo spegne: nessun
   pulsante attivo e le lezioni sono in un elenco unico, nell'ordine scelto, senza intestazioni di
   gruppo. Un clic su un altro pulsante lo accende come oggi.
   - `LessonsGrouping` prende `'nessuno'`. `parseLessonsPrefs` lo accetta. Il predefinito resta `data`.
   - Data/Mese: oggi il pulsante passa da Per data a Per mese (`handleDateClick`). Il giro diventa
     Per data → Per mese → nessuno → Per data. Materia e Docente: attivo → nessuno.
   - `lessonsGroups` con `nessuno` restituisce un solo gruppo con tutte le lezioni ordinate;
     `LessonsList` non mostra la sua intestazione né lo sfondo di gruppo.
   - `lessonSubtitle` con `nessuno` mostra la data (come per Materia e Docente).
   - Telefono: il pulsante che cicla i raggruppamenti (`cycleGroup`, `GROUP_CYCLE`) aggiunge
     `nessuno` in fondo, etichetta corta "Nessuno". `GROUPING_LABELS.nessuno` = "Senza gruppi".
   - Il salvataggio delle viste fissate (`LessonsView` in `lessonsPage.ts:40-70`) accetta `nessuno`.
2. **Ordine "(Ri)create di recente".** Nuova voce di `SORT_OPTIONS`, `ricreate: '(Ri)create di
   recente'` (telefono: "Create"), dopo "Dalla meno recente" anche in `SORT_CYCLE`. Ordina per
   l'ultima volta in cui la lezione è passata dalla pipeline (scaletta, rielaborazione o documento,
   contati insieme), più recente prima, non per la data della lezione. Senza valore in fondo.
   - Backend: `LessonSummary.pipeline_at: Optional[datetime]` (`rt/api/schemas.py`, accanto a
     `study_last_at`), riempito in `list_lessons` (`rt/services/lesson_service.py:279`) con il più
     recente fra gli `updated_at` di `phase_records` del manifest per `outline`, `rewrite` e `build`
     (`record_phase_fingerprint`, `rt/core/idempotency.py:619`).
   - Il documento si riscrive da solo dopo ogni decisione o modifica a mano (`run_documents`,
     `rt/services/documents_service.py:64`): quelle riscritture **non** contano, altrimenti ogni
     correzione rimetterebbe la lezione in cima. Per distinguerle, `build` registra anche
     `pipeline_at` nel suo record solo quando gira dentro la pipeline (`run_pipeline` o `run_phase`
     con `phase=build`), non dal job `documents`; scaletta e rielaborazione usano il loro `updated_at`.
   - Rigenera lo schema OpenAPI.

## Test

- Vitest (`lessonsPage.test.ts`, `LessonsView.test.tsx`):
  - un clic sul raggruppamento attivo lo spegne e l'elenco è unico, senza intestazioni;
  - giro Per data → Per mese → nessuno;
  - con nessuno e "Più avanti nello studio" l'ordine è globale (lezioni di giorni diversi mescolate);
  - "(Ri)create di recente" ordina per `pipeline_at`, quelle senza in fondo;
  - preferenze vecchie senza `nessuno` restano valide.
- Pytest: `pipeline_at` è il più recente fra scaletta, rielaborazione e build della pipeline; una
  riscrittura del documento dopo una decisione non lo cambia.

## Changelog

- Lezioni: si possono spegnere tutti i raggruppamenti per avere un elenco unico, e c'è l'ordine
  "(Ri)create di recente", per l'ultima volta in cui la lezione è passata da scaletta, rielaborazione
  o documento.
