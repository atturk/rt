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

## Endpoint

Tutti sotto `/api/v1` e autenticati, salvo `GET /health` e `POST /auth/session`.
Le lezioni hanno un id numerico stabile (riga `Lesson` del DB): resta lo stesso anche quando
`rt build` rinomina o sposta la cartella.

### Lettura (RT4-E2)

| Metodo e percorso | Cosa restituisce | Equivalente CLI |
|---|---|---|
| `GET /lessons?materia=&state=&q=` | Elenco con stato fasi, issue pendenti, costo | dashboard `rt` |
| `GET /lessons/{id}` | Dettaglio: fasi con motivo, costi, outline approvata, audio | `rt status`, `rt cost` |
| `GET /lessons/{id}/phases` | Freschezza fasi e report di validazione | `rt validate-outline`, `rt validate-draft` |
| `GET /lessons/{id}/document` | Markdown, HTML sanificato, timecode per unità (da `segments.json`) | anteprima / file finale |
| `GET /lessons/{id}/audio` | Audio della lezione, con `Range`; solo file audio dentro la cartella | — |
| `GET /lessons/{id}/outline` | Albero dell'outline e approvazione | approvazione outline |
| `GET /lessons/{id}/issues?status=pending\|all` | Issue con contesto (unità, timecode, finestra audio) e decisione | `rt review` |
| `GET /lessons/{id}/decisions` | Ledger (`review_decisions.json`) | `rt status --issues` |
| `GET /costs` | Costi LLM di tutte le lezioni, per lezione e per job | `rt cost` |

### Impostazioni (RT4-E4)

La logica vive in `rt/services/settings_service.py` e `rt/services/connections_service.py`
(spostati da `rt/web/`, che li reimporta per Gradio). Nessuna risposta contiene un valore
segreto: solo `set: true/false`.

| Metodo e percorso | Cosa fa | Equivalente CLI |
|---|---|---|
| `GET /settings` | Cartella lezioni, trascrizione, Telegram, sei fasi, connessioni, credenziali, pricing | `rt config` |
| `PUT /settings/lessons-root` | Cartella delle lezioni | `rt config` |
| `PUT /settings/transcription` | Motore STT (macparakeet o server compatibile) | `rt config` |
| `PUT /settings/telegram` | Token, chat, topic per materia | `rt config --telegram` |
| `POST /settings/connections` | Nuova connessione (provider, base URL, chiavi) | `rt config --models` |
| `POST /settings/connections/{name}/models` | Aggiunge un modello | `rt config --models` |
| `PUT /settings/phases/{job}` | Connessione e modello per outline, rewrite, review, recall, image_description, image_unit_judge | `rt config --models` |
| `GET/PUT /settings/routes/{job}/{role}` | Route primaria, secondaria, fallback | file `config/*.yaml` |
| `PUT /settings/pricing` | Pricing custom per provider e modello | `rt config` |
| `PUT /secrets/{name}` | Scrive un segreto dichiarato (archivio cifrato se inizializzato, altrimenti `.env`) | `rt secrets set` |
| `GET /telegram/daemon`, `POST /telegram/daemon/start`, `/stop` | Stato, avvio e arresto del bot | `rt telegram-daemon` |

Il bot parte come processo separato in una sessione propria (sopravvive all'API) e il lock
del PID file in `~/.rt/` impedisce i duplicati; lo stop invia SIGTERM. Un servizio launchd
dedicato arriva con la fase G.
