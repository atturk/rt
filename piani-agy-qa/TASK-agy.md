# Task agy: 4.3.6b2 (correzioni dal QA del 2 novembre)

Leggi `piani-agy-qa/piano-qa-agy.md` (sul branch `origin/claude/piani-agy-qa`) e implementa **tutte** le voci, dalla 1 alla 11, nell'ordine. Il piano è definitivo: le scelte sono già state prese. Se una voce non si può fare come scritto, fermati su quella voce e spiega perché nella PR. Non improvvisare un'alternativa.

1. Crea il branch dalla beta 4.3.6b1:
   `git fetch origin && git checkout -b agy/4.3.6b2 origin/claude/project-thread-tk54yz`.
   Se la PR #154 è già in main, porta anche quella: `git merge origin/main`.
2. Ogni voce è un commit, con messaggio «4.3.6b2: <numero>. <titolo della voce>».
3. Prima di aprire la PR:
   - Python: `python -m pytest tests/ -q -n auto --dist loadfile`;
   - frontend: `cd frontend && npm run lint && npm run typecheck && npm test`.
   - Se cambi un modello delle API, rigenera `docs/openapi.json` (`python scripts/export_openapi.py`) e `frontend/src/api/schema.d.ts` (`npm run gen:api`).
4. Apri una sola PR verso `claude/project-thread-tk54yz`, con titolo «4.3.6b2 (agy)». Nel corpo metti una riga per voce: fatto o non fatto, e perché.
5. Non toccare VERSION né CHANGELOG: li aggiorna Claude.
