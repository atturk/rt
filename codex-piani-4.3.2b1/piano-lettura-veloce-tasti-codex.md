# Piano: lettura veloce, tasti L e S, unità con Option+frecce, controlli semitrasparenti

Base: `claude/rt-4.3.2-beta`. Ramo suggerito: `codex/lettura-veloce-tasti`. PR verso `claude/rt-4.3.2-beta`.

## Richiesta

1. Tasto **L**: passa dalla lettura normale dello Studio alla lettura veloce e viceversa. Vale in
   entrambe le schermate.
2. Durante la lettura veloce **in riproduzione**, il blocco dei controlli (velocità, pulsanti
   rotondi, conteggio parole) passa a opacità 25%.
3. Ai lati del blocco dei pulsanti rotondi, due pulsanti rotondi un po' più piccoli per andare
   all'unità precedente e successiva. Tasti: **Option+←/→** su Mac, **Alt+←/→** su Windows (le frecce
   da sole spostano già tra le frasi). Al cambio di unità compare un avviso a sola icona, come quelli
   della lettura normale in modalità zen.
4. Tasto **S** in lettura veloce: cambia lo stato di studio dell'unità e mostra l'avviso con l'icona
   dello stato, come in modalità zen.

## Codice coinvolto

- `frontend/src/components/study/Study.tsx`
  - stato `speedReading`, `readerMounted`, `closeReader`;
  - pulsante "Lettura veloce" (`data-testid="study-rsvp-btn"`);
  - `changeStatus`, `nextStudyStatus`, `goToUnit`, `navigateReading`;
  - gestore `keydown` della lettura normale (righe ~339-396): esce subito se `speedReading` o con
    `altKey`;
  - stato `notice` e il suo rendering (`data-testid="zen-notice"`), oggi mostrato **solo** se
    `zenMode`.
- `frontend/src/components/study/SpeedReader.tsx`
  - gestore `keydown` proprio (righe ~144-170), che esce con `metaKey`, `ctrlKey` o `altKey`;
  - `RoundButton` e il blocco `data-testid="speed-reader-controls"`;
  - è montato con `key={`${lesson.id}-${unit.id}`}`, quindi si rimonta a ogni cambio di unità e
    riparte in pausa dalla parola 1.

## Modifiche

### 1. Tasto L

- **Lettura normale** (`Study.tsx`, gestore esistente): `key === 'l'` senza modificatori apre la
  lettura veloce con la stessa funzione del pulsante. Estrai `openReader()` dall'`onClick` attuale:
  mette in pausa l'audio dell'unità, scrolla in alto, imposta `speedReading`/`readerMounted`, chiude
  indice e dettagli. Non fa nulla se il testo non è pronto (`!textRoot`, cioè il pulsante dice
  "attendi il testo") o se è aperto un dialogo, un menu o l'indice: le stesse condizioni che il
  gestore già controlla.
- **Lettura veloce** (`SpeedReader.tsx`): `l` chiama la prop esistente `onClose()` (che è
  `closeReader`). Rispetta le esclusioni attuali del gestore (campi, pannello impostazioni,
  `blocked`).
- Accetta `l` e `L` senza Shift (come gli altri tasti dello Studio: `e.key.toLowerCase()`, ma esci se
  `shiftKey`).

### 2. Controlli al 25% durante la riproduzione

In `SpeedReader.tsx` avvolgi il cursore della velocità, `speed-reader-controls` e
`speed-reader-count` in un contenitore con `data-testid="speed-reader-panel"`:

- `opacity-25` quando `playing`, `opacity-100` altrimenti, con `transition-opacity duration-300`;
- torna al 100% con `hover` e con `focus-within`, così il pulsante Pausa resta raggiungibile col mouse
  e da tastiera (`hover:opacity-100 focus-within:opacity-100`);
- `motion-reduce:transition-none`;
- la parola e il contesto non cambiano.

### 3. Pulsanti e tasti per cambiare unità

- `RoundButton` riceve una prop `small`: `size-11 min-w-11` (max-md `size-10 min-w-10`), icona
  `size-4`, stessa etichetta sotto (`note`) vuota per non alzare la riga, oppure senza `note` e con
  allineamento verticale al cerchio dei pulsanti grandi.
- Ordine: `[Unità precedente] [−5] [Play] [Ricomincia] [Ripassa] [Unità successiva]`. Icone
  `SkipBack` e `SkipForward` di lucide. Etichette: "Unità precedente (⌥←)" / "Unità successiva (⌥→)"
  su Mac, "(Alt+←)" / "(Alt+→)" altrove (usa l'helper Mac/Windows già usato in
  `components/settings/shortcuts.tsx`, se esportabile, altrimenti `navigator.platform`).
- Sul telefono sei pulsanti non stanno con `gap-4`: sotto `md` i due pulsanti delle unità vanno nella
  riga del cursore della velocità, ai due lati, invece che nella riga dei pulsanti.
- Nuove prop di `SpeedReader`: `onUnit(direction: -1 | 1)`, `canPrevUnit`, `canNextUnit`.
  `Study.tsx` le collega a `goToUnit(unitIndex ± 1)` **dentro la lezione**; ai bordi il pulsante è
  disattivato (con il motivo nel suggerimento, come da piano n. 11). Non usare `navigateReading`, che
  al bordo passa alla lezione seguente e ricarica tutto.
- Tasti nel gestore di `SpeedReader`: `altKey && !metaKey && !ctrlKey && (ArrowLeft|ArrowRight)` →
  `onUnit(...)`, sempre con `preventDefault()`. Il controllo iniziale che oggi esce con `altKey` va
  ristretto: esce con `altKey` solo per i tasti diversi da queste due frecce.
- **Riproduzione continua**: se `playing` era vero, la nuova unità parte da sola. `Study.tsx` tiene un
  ref `resumeReader` impostato prima di `goToUnit`; `SpeedReader` riceve `autoStart` e, se vero,
  avvia la lettura appena ha le parole (rispettando la rampa iniziale `ramp`). In pausa resta in
  pausa.
- **Avviso a icona**: estendi `notice.kind` con `'unit'` e `direction`; l'icona è `SkipBack` o
  `SkipForward` `size-6`, nessun testo visibile (l'etichetta "Unità 1.3" va solo in `aria-live`).
  Al bordo nessun avviso.

### 4. Tasto S in lettura veloce

- `SpeedReader` riceve `onStatus()`: `s` chiama `onStatus`, che in `Study.tsx` fa `changeStatus()` e
  `setNotice({ kind: 'status', status: nextStudyStatus(live?.status), label: STATUS_LABELS[...] })`,
  come la riga `key === 's'` della lettura normale. Non mette in pausa la lettura.
- Se `status.isPending`, ignora il tasto (oggi il pulsante è disattivato in quel caso).

### 5. Avviso visibile anche fuori dalla zen

Oggi l'avviso si vede solo con `zenMode && notice`. Cambia la condizione in
`(zenMode || speedReading) && notice` e la regione `aria-live` alla riga ~673 nello stesso modo.
In lettura veloce l'avviso va centrato sopra la parola, non a `top-16`, perché l'intestazione è
diversa: usa una classe alternativa quando `speedReading`, per esempio `top-1/3`.

## Conflitti con il codice attuale (da rispettare)

- **Alt+←/→ su Windows è "Indietro/Avanti"** nel browser e in WebView2: senza `preventDefault()`
  RT torna alla pagina precedente. Il gestore deve chiamarlo sempre per queste due combinazioni
  quando la lettura veloce è attiva, anche ai bordi (dove non succede nulla).
- I due gestori `keydown` escono con `altKey`: senza la modifica del punto 3 Option+frecce non
  arrivano mai.
- `SpeedReader` si rimonta a ogni unità e riparte in pausa: senza `autoStart` la riproduzione si
  ferma a ogni cambio.
- L'avviso esiste solo in zen: senza il punto 5 i tasti S e Option+frecce non mostrano nulla.
- Con i controlli al 25% il pulsante Pausa è poco visibile: per questo torna al 100% con hover e focus.
- La preferenza `study.highlighter.arrows` spegne le frecce tra le unità nella lettura normale. Non
  vale per Option+frecce in lettura veloce, che è una combinazione esplicita.
- Lo zoom del testo con `+` e `−` (piano n. 10) non tocca la lettura veloce: nessun conflitto con L
  e S.

## Test

`frontend/src/components/study/StudyTools.test.tsx` e `SpeedReader.test.tsx`:

- `l` nella lettura normale apre la lettura veloce; `l` nella lettura veloce torna allo Studio; con
  il focus in un campo non fa nulla; con Shift non fa nulla.
- Durante la riproduzione `speed-reader-panel` ha `opacity-25`; in pausa no.
- `Alt+ArrowRight` passa all'unità seguente, chiama `preventDefault`, mostra `zen-notice` con
  l'icona e continua la riproduzione se era attiva; all'ultima unità non cambia nulla e il pulsante
  "Unità successiva" è disattivato.
- `ArrowRight` senza Alt continua a spostare tra le frasi.
- `s` in lettura veloce cambia lo stato (stesso PUT del pulsante) e mostra l'avviso con l'icona dello
  stato.

## Nota per il changelog

"Lettura veloce: L la apre e la chiude, S cambia lo stato dell'unità, Option+frecce (Alt+frecce su
Windows) e due nuovi pulsanti passano all'unità vicina; durante la lettura i controlli si
attenuano."
