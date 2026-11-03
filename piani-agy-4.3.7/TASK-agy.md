# Task agy: 4.3.7 (correzioni dal QA del frontend 4.3.6)

Leggi `piani-agy-4.3.7/piano-4.3.7-agy.md` (sul branch `origin/claude/piani-agy-4.3.7`) e implementa **tutte** le voci, dalla 1 alla 13, nell'ordine. Il piano è definitivo: le scelte sono già state prese. Se una voce non si può fare come scritto, fermati su quella voce e spiega perché nella PR. Non improvvisare un'alternativa.

1. Lavora in `~/rt-antigravity`. Crea il branch dalla base:
   `git fetch origin && git checkout -b agy/4.3.7 origin/claude/rt-4.3.7`.
2. Ogni voce è un commit, con messaggio «4.3.7: <numero>. <titolo della voce>».
3. Prima di aprire la PR:
   - Python: `python -m pytest tests/ -q -n auto --dist loadfile`;
   - frontend: `cd frontend && npm run lint && npm run typecheck && npm test`.
   - Se cambi un modello delle API, rigenera `docs/openapi.json` (`python scripts/export_openapi.py`) e `frontend/src/api/schema.d.ts` (`npm run gen:api`).
4. Apri una sola PR verso `claude/rt-4.3.7`, con titolo «4.3.7 (agy)». Nel corpo metti una riga per voce: fatto o non fatto, e perché.
5. Non toccare VERSION né CHANGELOG: li aggiorna Claude.
6. Ambiente: non scrivere fuori da `~/rt-antigravity` (niente file in `~/.local/bin`, niente modifiche a Python di Homebrew). Non lanciare comandi `rt` o script contro la cartella dati vera `~/.rt`: per le prove usa `RT_DATA_DIR` in una cartella temporanea.
