# Piano 9 · Inizio del periodo accademico e lezioni mancanti per materia

Agente: **Codex**. Richiesta di Attilio (22/10/2026).

## Cosa vuole

1. Nel popup ⓘ di una settimana del calendario (`calendar-week-popup`, `CalendarPopups.tsx`), sotto la
   riga "Settimana tipo", una scritta cliccabile **"Inizio del periodo"** imposta quella settimana come
   inizio del periodo accademico (es. semestre). Se è già l'inizio, la riga dice "Inizio del periodo ✓"
   e un clic la toglie.
2. Da quella settimana a oggi RT confronta, **per materia**, le lezioni realmente tenute secondo il
   calendario con le lezioni elaborate presenti in RT.
3. Se ne mancano, nell'elenco delle lezioni raggruppato per materia (intestazione del gruppo, es.
   "DATA MINING", `GroupHeader` in `LessonsView.tsx`) compare accanto al nome una piccola **icona di
   avviso**, alta quanto il testo (lucide `TriangleAlert`, colore warning).
4. Clic sull'icona → scheda popup con il riepilogo delle lezioni mancanti di quella materia: una riga
   per lezione con giorno e data (stesso stile della lista "Da recuperare" del popup ⓘ).
5. Clic sulla data → si va al calendario su quella settimana con il blocco orario evidenziato.
6. Impostazioni › Calendario: interruttore **"Avviso lezioni mancanti"** (acceso di default) che
   nasconde l'icona.

## Regole del conteggio

- Si parte dal lunedì della settimana scelta e si arriva a ora; solo blocchi già finiti
  (`_event_end(ev) < now`, come per "Da recuperare").
- Gli eventi si risolvono con `_resolve_dates` (`rt/services/calendar_service.py`), che applica già
  settimana tipo, modifiche degli orari (override, ore spostate o aggiunte) e stati dei giorni: così
  le variazioni d'orario sono considerate.
- Non contano: blocchi `annullata` e giorni senza lezione. Neppure `saltare` (deciso da Attilio).
- Una lezione è **mancante** se il blocco non ha una lezione collegata (`ev.lesson is None`, la stessa
  associazione di `_find_lesson_for_event`).
- Materia con `normalize_subject`, come nel resto del calendario; le materie del calendario che non
  hanno ancora nessuna lezione in RT non hanno un gruppo nell'elenco: si ignorano.

## Dati e API

- Dove salvare l'inizio del periodo: nello stesso archivio delle impostazioni del calendario (come i
  docenti per materia o le preferenze del calendario). Una sola data `academic_start` (lunedì, ISO) o
  nulla.
- `PUT /calendar/period-start` con `{ date: "YYYY-MM-DD" | null }`; `CalendarWeekSummary` riceve
  `is_period_start: bool` per il popup.
- `GET /calendar/missing` → `{ start: string | null, subjects: { materia, missing: [{ key, date,
  day_name, day_number, month_number, start_time, end_time }] }[] }`, solo le materie con almeno una
  mancante. Senza inizio impostato: `start: null`, `subjects: []`.
- Rigenerare lo schema OpenAPI e i tipi del frontend.

## Frontend

- Hook `useMissingLessons()` (react-query, invalidato da modifiche al calendario, collegamenti di
  lezioni, nuove lezioni) usato da `GroupHeader` solo con raggruppamento `materia` e con l'avviso
  attivo.
- Icona: `IconButton` piccolo con suggerimento "N lezioni mancanti"; il popup riusa lo stile delle
  schede del calendario. Niente testo descrittivo.
- Calendario: parametri `/calendario?data=YYYY-MM-DD&evento=<key>`: apre la settimana di quella data e
  fa lampeggiare brevemente il blocco con quel `key` (stessa animazione d'evidenza usata altrove, es.
  `rt-media-flash`). Serve anche per i clic dalla lista "Da recuperare" se è comodo, ma non è
  richiesto.

## Anche qui (dal piano 4)

In `CalendarPopups.tsx` togliere `focus:ring-1 focus:ring-primary` dai campi di testo: il piano 4
(agy) non tocca questo file.

## Test

- Pytest su `calendar_service`: con inizio impostato, blocchi passati senza lezione contano, quelli
  con lezione no, `annullata` e `saltare` no, gli override contano con l'orario modificato, i blocchi
  futuri no; senza inizio la lista è vuota. API `PUT`/`GET`.
- Vitest: icona solo col raggruppamento per materia e con mancanti; nascosta con l'impostazione
  spenta; popup con le date; link al calendario con i parametri giusti; riga "Inizio del periodo" nel
  popup ⓘ.
- E2e: imposta l'inizio da una settimana, vedi l'avviso su una materia, apri il popup, clic sulla
  data → calendario sulla settimana giusta con il blocco evidenziato.
