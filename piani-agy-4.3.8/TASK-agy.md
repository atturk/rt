# Compito per agy
Implementa `piani-agy-4.3.8/piano-4.3.8b6.md` (voci 1, 2 e 3; non la sezione «In coda») sul branch `agy/4.3.8b6`.
Un commit per voce, poi `piani-agy-4.3.8/esito-b6.md` con una riga per voce e push su `agy/4.3.8b6`.
Non toccare le modifiche già fatte da Claude su questo branch (posizione dell'anteprima di trascinamento, «Accesso da altri dispositivi»).
Prima del push: `cd frontend && npm run -s typecheck && npm run -s lint && npx vitest run`, e `pytest` sui test Python toccati. Niente Playwright.
