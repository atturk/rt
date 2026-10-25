# TASK agy, 4.3.4b1

Leggi e implementa `codex-piani-4.3.4b1/piano-immagini-modello-decisionale-agy.md`.

- Base: `claude/rt-4.3.4-beta`. Lavora su `agy/4.3.4b1` e apri una PR verso `claude/rt-4.3.4-beta`.
- Fai prima il passo 0 (una sola chiamata di prova con Jev 1.14) e riporta l'esito nella PR.
- Un commit per sezione del piano (1–7), messaggi in italiano.
- Non toccare `VERSION` né `CHANGELOG.md`: li aggiorna Claude.
- Prima della PR: `pytest -q` e, in `frontend/`, `npm run lint`, `npm test`, `npm run build`.
  Se cambi le API rigenera `docs/openapi.json` e poi `npm run gen:api`.
- Se una regola del piano è impossibile o sbagliata, non aggirarla: scrivilo nella PR.
