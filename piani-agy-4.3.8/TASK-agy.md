# Compito per agy
Le voci 1-6 sono già fatte. Prima di tutto `git checkout agy/4.3.8b5 && git pull --rebase origin agy/4.3.8b5`.
1. Implementa le voci 7, 8 e 9 di `piani-agy-4.3.8/piano-4.3.8b5.md` sul branch `agy/4.3.8b5`, un commit per voce.
   Aggiungi le righe delle voci 7-9 in `piani-agy-4.3.8/esito-b5.md` e fai push su `agy/4.3.8b5`.
2. Poi passa a `agy/4.3.8-arricchimento` (`git fetch && git checkout agy/4.3.8-arricchimento && git pull`) ed esegui il
   `piani-agy-4.3.8/TASK-agy.md` di quel branch.
Prima di ogni push: `cd frontend && npm run -s typecheck && npm run -s lint && npx vitest run`. Niente Playwright.
