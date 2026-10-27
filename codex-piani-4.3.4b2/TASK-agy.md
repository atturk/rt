# Task agy — 4.3.4b2

Leggi `codex-piani-4.3.4b2/piano-4.3.4b2-agy.md` (sul branch `origin/claude/project-thread-fuiy55`) e implementa **tutte** le voci, dalla 1 alla 4. Il piano è definitivo.

1. `git fetch origin && git checkout -b agy/4.3.4b2 origin/claude/rt-4.3.4-beta`
2. Una voce = un commit, con messaggio «4.3.4b2: <voce>».
3. Prima di aprire la PR: `cd frontend && npm run lint && npx tsc -b && npm test`; per modifiche Python `pytest -n 4` (l'unico fallimento noto è `test_setup.py::test_rt_setup_clean_initialization`). Se cambi un modello delle API, rigenera `docs/openapi.json` (`python scripts/export_openapi.py`) e `frontend/src/api/schema.d.ts` (`npm run gen:api`).
4. PR verso `claude/rt-4.3.4-beta`, titolo «4.3.4b2 (agy)». Non toccare VERSION né CHANGELOG: li aggiorna Claude.
