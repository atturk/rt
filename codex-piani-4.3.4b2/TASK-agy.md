# Task agy — 4.3.4b2

Leggi `codex-piani-4.3.4b2/piano-4.3.4b2-agy.md` e implementa **tutte** le voci presenti.

1. `git fetch origin && git checkout -b agy/4.3.4b2 origin/claude/rt-4.3.4-beta`
2. Una voce = un commit, con messaggio «4.3.4b2: <voce>».
3. Prima di aprire la PR: `cd frontend && npm run lint && npx tsc -b && npm test`; per modifiche Python `pytest -n 4`.
4. PR verso `claude/rt-4.3.4-beta`, titolo «4.3.4b2 (agy)». Non toccare VERSION né CHANGELOG: li aggiorna Claude.
