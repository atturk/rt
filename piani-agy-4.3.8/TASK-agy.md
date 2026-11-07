# Compito per agy
1. Sul branch `agy/4.3.8b5`: se le voci 7-8 non sono ancora sul remoto, fai `git pull --rebase origin agy/4.3.8b5` e `git push`.
   Poi implementa la voce 9 di `piani-agy-4.3.8/piano-4.3.8b5.md` (un commit), aggiungi la sua riga in `piani-agy-4.3.8/esito-b5.md`
   e push su `agy/4.3.8b5`.
2. Poi passa a `agy/4.3.8-arricchimento` (`git fetch && git checkout agy/4.3.8-arricchimento && git pull`) ed esegui il
   `piani-agy-4.3.8/TASK-agy.md` di quel branch.
Prima di ogni push: `cd frontend && npm run -s typecheck && npm run -s lint && npx vitest run`. Niente Playwright.
