# Piano: fissare la vista della pagina Lezioni

Base: `claude/rt-4.3.2-beta`. Ramo suggerito: `codex/lezioni-vista-fissata`. PR verso `claude/rt-4.3.2-beta`.

## Richiesta

Un pulsante a icona a sinistra del campo Cerca salva lo stato corrente della pagina Lezioni:
raggruppamento, ordinamento, testo cercato e filtri. Quando l'utente torna su Lezioni ritrova quello
stato. Se lo stato è fissato e l'utente cambia qualcosa (testo, raggruppamento, ordine, filtri), lo
può fare liberamente, ma lo stato smette di essere fissato. L'icona cambia tra fissato e non fissato.

## Com'è oggi

- `frontend/src/lib/lessonsPage.ts::useLessonsPrefs`: raggruppamento (`group`) e ordinamento
  (`sort`) in `localStorage` (`rt-lessons-page`), quindi già ricordati sempre.
- `frontend/src/lib/lessonFilters.ts::useLessonFilters`: `q`, `materia`, `stato` nell'URL
  (`?q=&materia=&stato=`), persi quando si torna a `/` dalla barra laterale.
- `frontend/src/components/lessons/LessonsView.tsx::LessonsHeaderActions`: gruppo di pulsanti
  Raggruppa, menu Ordina, campo Cerca (`<form role="search">`), pulsante Seleziona. Sul telefono
  pillole al posto dei pulsanti e una lente che apre il campo.
- `frontend/src/lib/preferences.ts::usePreference`: preferenze salvate in RT (`/api/v1/preferences`)
  con copia locale. Usala, così la vista fissata vale sia nell'app sia nel browser.

## Modifiche

### 1. Stato fissato

In `frontend/src/lib/lessonsPage.ts`:

```ts
export type LessonsView = { group: LessonsGrouping; sort: LessonsSort; q: string; materia: string; stato: string }
export const PINNED_VIEW_PREF = 'lessons.pinned'
export function parsePinnedView(raw: unknown): LessonsView | null  // valida come parseLessonsPrefs, null se non valido
export function sameView(a: LessonsView, b: LessonsView): boolean   // q confrontato dopo trim
```

Hook `usePinnedLessonsView()`, con dentro `usePreference<LessonsView | undefined>(PINNED_VIEW_PREF, undefined)`,
che restituisce `{ pinned: LessonsView | null, pin(view), unpin() }`. `unpin` salva `undefined`, che
cancella la preferenza.

### 2. Ripristino all'ingresso

In `frontend/src/routes/lessons.tsx`, una volta sola al montaggio della pagina (ref di guardia):

- se c'è una vista fissata e l'URL **non** ha `q`, `materia` o `stato`, applica la vista:
  `setPrefs({ group, sort })` e un solo aggiornamento dell'URL con `q/materia/stato` (aggiungi a
  `useLessonFilters` una funzione `applyFilters(values)` che fa un solo `setParams` con
  `replace: true`, come `resetFilters`, e allinea anche lo stato locale `q` e `pending`);
- se l'URL ha già dei filtri (un link da un'altra pagina, per esempio "Solo <materia>"), vince l'URL
  e la vista fissata resta salvata per la volta dopo. L'icona mostra "non fissato" perché lo stato
  corrente è diverso.

Attendi che la preferenza sia caricata prima di applicarla: la copia locale di `usePreference` dà
già il valore al primo render; se la query di `/api/v1/preferences` porta un valore diverso dopo il
montaggio, non riapplicare (si applica solo all'ingresso).

### 3. Una modifica dell'utente toglie il fissaggio

Sempre in `lessons.tsx`, incapsula i gestori che arrivano da un gesto dell'utente:
`setFilter`, `resetFilters` (anche il pulsante "Azzera" e "Mostra tutte") e `setPrefs`. Se c'è una
vista fissata e il nuovo stato è diverso da quella vista, chiama `unpin()` e poi applica la modifica.
La modifica non viene mai bloccata. Il ripristino del punto 2 usa le funzioni originali, non quelle
incapsulate, così non toglie il fissaggio da solo.

`fixed = pinned !== null && sameView(pinned, current)` è ciò che decide l'icona.

### 4. Il pulsante

In `LessonsHeaderActions` aggiungi le prop `fixed: boolean` e `onToggleFixed: () => void`, e un
`IconButton` subito prima del `<form role="search">`:

- non fissato: icona `Pin` di lucide, etichetta "Fissa questa vista";
- fissato: la stessa icona `Pin` riempita (`fill-current`), con `active` e `aria-pressed={true}`,
  etichetta "Vista fissata: tocca per non fissarla più" (non usare `PinOff`, che sembra un'azione);
- clic su non fissato: `pin(current)`; clic su fissato: `unpin()`.
- Sul telefono il pulsante sta accanto alla lente, con la stessa logica.
- Il suggerimento segue il componente dei pulsanti a icona già esistente; non aggiungere testo
  sotto il pulsante.

Lo stato corrente passato a `pin` è `{ ...prefs, q: filters.q.trim(), materia: filters.materia, stato: filters.state }`.

### 5. Cosa non cambia

- Senza vista fissata la pagina si comporta come oggi.
- La modalità selezione non fa parte della vista e non la toglie.

## Test

- `frontend/src/lib/lessonsPage.test.ts`: `parsePinnedView` scarta valori non validi; `sameView`
  ignora spazi ai lati della ricerca.
- `frontend/src/routes/lessons.test.tsx`:
  1. con una vista fissata salvata e URL vuoto, la pagina si apre con quel raggruppamento, ordine e
     testo nel campo, e il pulsante ha `aria-pressed="true"`;
  2. scrivere un carattere nel campo cancella la preferenza (DELETE su
     `/api/v1/preferences/lessons.pinned`) e il pulsante torna non premuto, con il testo nuovo nel
     campo;
  3. cambiare raggruppamento o ordine fa lo stesso;
  4. con una vista fissata e `?materia=X` nell'URL vince l'URL e la preferenza resta;
  5. clic sul pulsante non premuto salva la vista corrente (PUT con i valori giusti).
- Esegui i test del frontend dei file toccati e `npm run typecheck` (o il comando equivalente del
  repo).

## Nota per il changelog

"Lezioni: il pulsante con la puntina accanto a Cerca fissa raggruppamento, ordine e ricerca, che
ritrovi quando torni alla pagina; se cambi qualcosa la vista non è più fissata."
