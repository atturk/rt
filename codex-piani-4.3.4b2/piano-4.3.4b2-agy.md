# Piano 4.3.4b2 — agy

Lista dei lavori della beta 4.3.4b2. Si aggiunge una voce per volta, quando Attilio la chiede.
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

<!-- Le prossime voci vanno qui sotto (## 2, ## 3, …). -->
