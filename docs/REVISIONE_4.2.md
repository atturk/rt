# Revisione dei giri (guida per la sessione che rivede)

Ruolo: rivedere le PR di Codex e Antigravity verso `claude/rt-4.2.0-beta-54bz3z`, fare le
correzioni brevi, aprire task `R<n>` per gli errori grossi, unire nel beta. Mai su `main`, niente
tag o release. Risposte e commit in italiano. Piano e regole: `docs/REWORK_4.2.md`.

## Procedura per un giro

1. `gh pr list --base claude/rt-4.2.0-beta-54bz3z` (senza `gh`: strumenti GitHub MCP) → le due PR del giro (`rt42/codex-N`, `rt42/antigravity-N`).
2. Leggi il diff commit per commit (`git diff origin/claude/rt-4.2.0-beta-54bz3z...origin/<branch>`),
   escludendo `docs/openapi.json` e `frontend/src/api/schema.d.ts`. Confronta con task, wireframe
   (`docs/wireframes-4.2/`), "Stile comune" e "Note per il giro".
3. Cose da guardare (emerse nel giro 1):
   - `docs/openapi.json` non rigenerato → fallisce `tests/test_api_auth.py::test_openapi_export_is_current`.
     Rigenera: `python scripts/export_openapi.py && (cd frontend && npm run gen:api)`.
   - colori `rgba`/esadecimali o misure `[…px]` nei componenti → variabili in `frontend/src/index.css`;
   - righe di spiegazione nell'interfaccia (hint, description) → toglierle;
   - controlli dentro link (`<input>` in `<a>`), cast `as unknown as`;
   - campi raccolti in UI ma non inviati all'API;
   - e2e non aggiornati: gli agenti non li eseguono. Vanno allineati da chi rivede;
     nel giro 2 Antigravity ha cancellato interi spec invece di adattarli (ricontrollare i `D`);
   - stati finti nell'interfaccia (esiti o stati scritti fissi invece di letti dall'API);
   - parametri dell'URL: un solo `?panel=<vista>` per aprire i pannelli della lezione.
4. Unisci prima la PR con meno conflitti (`gh pr merge N --merge`), poi porta il beta nell'altro
   branch, risolvi i conflitti tenendo entrambe le funzioni, rigenera OpenAPI/schema, applica le
   correzioni brevi in un commit "Revisione: …", push, aspetta la CI (`gh pr checks N`), unisci.
5. Test: `python -m pytest tests/ -q -n auto --dist loadfile`; frontend `npm run lint && npm run
   typecheck && npx vitest run`; poi e2e completi (`npm run build && npx playwright test`; in un
   container senza browser scaricati usare `PW_CHROMIUM_PATH=/opt/pw-browsers/chromium…` o
   l'esecutabile di Chromium presente). Correggi gli e2e rotti dal cambio di layout e i bug veri.
   Noti e non nostri: su alcuni Mac falliscono `test_data_dir.py` (2) e
   `test_parallel_jobs.py::test_launcher_passes_concurrency_to_worker`.
6. Errori grossi: aggiungi `R<n> — task — agente — cosa correggere` alla sezione "Correzioni" del
   piano e prepara il prompt per l'agente (stesso schema dei prompt di giro, sul suo branch).
7. Alla fine: riepilogo per Attilio (cosa è entrato, correzioni fatte, cosa provare dal vivo con
   `cd ~/rt-dev && scripts/dev.sh` → http://localhost:5173).

## Stato

- Giro 1: unito (#48, #49) più la revisione 8ca6a3f.
- Giro 2: unito (#51 Codex, #50 Antigravity) più la revisione; R1–R3 uniti (#52).
- Release beta: i tag v4.2.0b2 e v4.2.0b3 non hanno prodotto release (CI e2e: a11y e una race del
  journey, corretti); prima di un tag eseguire gli e2e completi in locale.
- Dopo il giro 2: e2e completi, riepilogo per la prova dal vivo, poi Attilio decide su beta/tag.
