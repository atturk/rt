# Piano 4.3.8b1: Studio (agy)

Quattro voci, tutte nello Studio e nel solo frontend. Il piano completo della 4.3.8, con il perché di ogni scelta, è nel Claude Doc «RT 4.3.8: analisi delle note "dopo consolidamento" e piano».

- **Base:** `claude/rt-4.3.8` (4.3.7 stabile). Ci sono già i due residui della QA (PR #163): non rifarli.
- **Branch:** `agy/4.3.8`, quello di questo piano. Un commit per voce.
- **Interfaccia:** testi in italiano, minimalismo, niente testo che spiega l'interfaccia. Si aggiornano solo i suggerimenti dei pulsanti.
- **Test:** ognuna delle voci ha i suoi, nei file `*.test.tsx` accanto ai componenti.

---

## 1. Prima la selezione, poi lo strumento

**Oggi.** Verifica (V) e Chiedi (C) agiscono solo se la modalità è già accesa (`Study.tsx`, `handleMouseUp`, ~riga 1283). L'evidenziatore (E) colora la selezione solo in modalità `evidenzia` (`highlights.ts`, `onMouseUp`). Se selezioni prima e premi il tasto, la modalità si accende e la selezione resta lì senza effetto.

**Cosa fare.**
- Se c'è una selezione non vuota dentro il testo dell'unità (lo stesso controllo di `handleMouseUp`: `root.contains(range.commonAncestorContainer)`) quando premi **E, G, V o C**, o clicchi il pulsante corrispondente in `HighlightTools`, lo strumento si applica subito a quella selezione **una volta sola** e la modalità **non** resta accesa.
  - E: evidenzia nel colore corrente; Maiusc+E usa il colore successivo, come oggi.
  - G: toglie le evidenziazioni che toccano la selezione.
  - V / C: apre il popup di Verifica / Chiedi sulla quote, come `onSelection` di oggi (stessi `prefix`/`suffix`).
- Senza selezione il comportamento resta identico a oggi.
- Il clic su un pulsante della barra non deve far perdere la selezione: salva il `Range` al `pointerdown` del pulsante (o `preventDefault` sul `mousedown`) e usa quello. Su iPhone la selezione nativa resta attiva quando tocchi un pulsante: se si perde, vale il range salvato.
- Suggerimenti: «Verifica · V · seleziona il testo, prima o dopo», idem per Chiedi ed Evidenziatore.
- In zen l'avviso (`setNotice`) mostra lo strumento applicato, non «… attiva».

**Test** (`Study.test.tsx` o `StudyTools.test.tsx`): selezione e poi V apre la verifica con la quote giusta e `hlMode` resta `null`; selezione e poi E crea l'evidenziazione nel colore corrente; selezione e poi clic sul pulsante Verifica fa lo stesso; senza selezione V accende la modalità come oggi.

## 2. Colori delle evidenziazioni nella lettura veloce e avviso Irlen

**Oggi.** `rsvp.ts` segna le parole evidenziate solo con `hl: boolean` (righe ~213 e ~235, `closest('.rt-hl')`). In `index.css` `.rt-rsvp-hl` e `.rt-rsvp-word[data-hl]` usano un solo colore, `--rsvp-hl` (righe ~1003-1005 e ~1118-1124). I colori dello Studio sono `.rt-hl-0` … `.rt-hl-4` → `--hl-1` … `--hl-5`.

**Cosa fare.**
- `Word.hl` e `ContextPiece.hl` diventano `number | undefined`: l'indice del colore letto dalla classe `rt-hl-N` dell'evidenziazione più vicina (per le formule anche da `rt-hl-math` + `rt-hl-N`). Aggiorna `wordDelay` (`entry.hl` resta truthy: attenzione all'indice 0, usa `entry.hl !== undefined`).
- In `SpeedReader.tsx` la parola corrente ha `data-hl={N}` e il contesto usa la classe `rt-rsvp-hl rt-rsvp-hl-N`. In CSS ogni N usa `--hl-(N+1)` come sfondo, con il testo leggibile nel tema scuro come oggi (`--rsvp-hl-fg`). La regola Irlen (`.rt-layout[data-tint] .rt-rsvp`) **non** sostituisce più i colori con un grigio unico.
- **Avviso Irlen:** quando la modalità Irlen si accende (impostazioni della lettura veloce, `SpeedReader.tsx` ~riga 608, e della zen, `ZenHeader.tsx`), o quando apri la lettura veloce con Irlen già accesa, se l'unità ha almeno un'evidenziazione con colore diverso da 0 (giallo), compare un `Modal` con il testo «Con la modalità Irlen alcuni colori delle evidenziazioni potrebbero vedersi poco.», una casella «Non mostrare più» e il pulsante OK. La scelta si salva nelle preferenze dello Studio (`studyPrefs.ts`, nuovo campo `irlenHighlightWarning: boolean`, predefinito `true`).
- «Mostra le evidenziazioni» e «Rallenta sulle evidenziate» restano come sono.

**Test:** `rsvp.test.ts`: una parola in `rt-hl-2` ha `hl === 2`, una in `rt-hl-0` ha `hl === 0`; `SpeedReader.test.tsx`: la parola verde ha `data-hl="1"`; con Irlen accesa e un'evidenziazione rosa l'avviso compare una volta; con «Non mostrare più» non ricompare; con solo evidenziazioni gialle non compare.

## 3. Lettura veloce dalla parola selezionata

**Oggi.** Il lettore parte sempre dalla parola 0 (`useState(0)` in `SpeedReader.tsx`). L (`Study.tsx` ~riga 472) e il pulsante chiamano `openReader` senza guardare la selezione.

**Cosa fare.**
- In `readUnitWords` (`rsvp.ts`) salva per ogni parola il nodo di testo e l'offset di partenza (campo interno, non esposto nel testo).
- In `openReader` (`Study.tsx` ~riga 289), se c'è una selezione non vuota nel testo dell'unità, passa al lettore il nodo e l'offset di inizio della selezione. `SpeedReader` riceve una prop `startAt?: { node: Node; offset: number }` e inizializza `index` con la prima parola che contiene quel punto o che viene subito dopo. Il lettore si apre come oggi, fermo, con il conto alla rovescia al play.
- Dopo l'apertura la selezione si toglie (`removeAllRanges`).
- Con la voce 1: L con una selezione è «applica la lettura veloce alla selezione».

**Test** (`SpeedReader.test.tsx` / `Study.test.tsx`): seleziono una parola a metà unità, premo L → la parola corrente è quella; seleziono a metà di una parola → parte da quella parola; senza selezione parte dalla prima.

## 4. Stato dell'unità accanto al titolo, in lettura veloce e in zen

**Oggi.** In lettura veloce il titolo della barra è `${unit.id} ${unit.title}` (`Study.tsx` ~riga 711, `StudyShell title`). In zen `ZenHeader` mostra solo `title`. Lo stato si cambia con S (`changeStatus`, `handleStatusFromReader`), ma non si vede.

**Cosa fare.**
- A sinistra del titolo, in entrambe le barre, un `IconButton` piccolo con l'icona e la classe di `STUDY_ICONS[live.status ?? 'da-imparare']` (`studyProgress.ts`), la stessa del pulsante Stato della barra dello Studio. Suggerimento «Stato: <etichetta> · S», `aria-label` come il pulsante dello Studio.
- Clic o tocco = come S: in lettura veloce `handleStatusFromReader`, in zen `changeStatus` più l'avviso di oggi.
- In zen il pulsante compare con la barra (stessa logica di apertura). `ZenHeader` riceve le prop `status` e `onStatus`.

**Test:** in lettura veloce e in zen l'icona corrisponde allo stato; il clic e S la cambiano entrambi; il pulsante ha l'`aria-label` dello stato.

---

## Prima della PR

- Frontend: `cd frontend && npm run lint && npm run typecheck && npm test`.
- Python solo se tocchi il backend (non dovrebbe servire): `python -m pytest tests/ -q -n auto --dist loadfile`.
- Non toccare VERSION, CHANGELOG, `docs/openapi.json`, `schema.d.ts`.
