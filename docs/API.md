# API REST di RT (RT 4.0, fase E)

L'API espone a una web app (la SPA della fase F) e a script tutto quello che oggi si fa
dalla CLI. Usa solo il service layer (`rt/services`) e il database (`rt/db`): nessuna
logica di dominio vive in `rt/api`.

## Avvio

```bash
rt api                 # http://127.0.0.1:8765/api/v1, documentazione su /docs
rt api --reset-token   # genera e mostra un nuovo token
rt api --port 9000
rt api --dev-cors      # consente le richieste della SPA in sviluppo (localhost:5173)
```

- Ascolta solo su `127.0.0.1` per default; `--host` diverso stampa un avviso.
- Al primo avvio stampa un **token** (una sola volta). Nel DB resta solo l'hash
  (tabella `settings`, chiave `api.auth`).
- Autenticazione: `Authorization: Bearer <token>`; nella pagina `/docs` il pulsante
  **Authorize**. La SPA apre una sessione con `POST /api/v1/auth/session` (cookie HttpOnly,
  SameSite=Strict) e ripete il cookie `rt_csrf` nell'header `X-CSRF-Token` per le scritture.
- `--no-auth` disattiva l'autenticazione, solo su loopback.
- CORS: nessuna origine per default; `--dev-cors` o `RT_API_CORS_ORIGINS=origine1,origine2`.

## Errori

Ogni errore ha la forma `{"error": {"code": "...", "message": "...", "details": ...}}`.
I messaggi passano dal sanificatore delle credenziali; un errore inatteso è un 500 generico.

## Schema

`docs/openapi.json` è lo schema esportato da `python scripts/export_openapi.py` (un test
verifica che sia aggiornato). La SPA ne genera il client TypeScript.
