# Far usare RT a Claude (server MCP)

Due server MCP permettono a Claude Code di usare un RT già installato e avviato, per
verifiche automatiche: chiamate all'API, import, pipeline, Studio, Recall, log con i tempi e
interfaccia web con la console del browser.

- **rt** (`scripts/rt_mcp.py`): solo libreria standard di Python, nessuna installazione.
- **playwright** (`@playwright/mcp`): un browser che Claude guida per provare la web app.

Si usano sul Mac di prova, mai su quello con le lezioni principali.

## Installazione (una volta)

Nella cartella del repository sul Mac di prova:

```bash
git pull
scripts/setup_mcp.sh
```

Registra i due server in Claude Code solo per questa cartella. Per `playwright` serve Node.js
(`brew install node`). Poi si apre Claude Code (o una sessione Remote Control) in questa cartella.

## Accesso all'API

Non serve copiare il token: `rt_mcp.py` chiede un link monouso all'app installata (lo stesso
comando dei servizi launchd, `rt web --no-browser`) e apre una sessione come la web app. Il
token dell'utente non cambia.

In alternativa, o se RT non è installato come app: `RT_API_TOKEN=<token>` oppure il token in
`~/.rt/config/mcp-token`. Altre variabili: `RT_MCP_BASE_URL`, `RT_DATA_DIR`,
`RT_MCP_RT_COMMAND` (comando `rt` da usare), `RT_MCP_MODE=readonly` (solo letture).

## Strumenti

| Strumento | Cosa fa |
|---|---|
| `rt_status` | Salute dell'API, versione, cartelle, worker, job attivi, costi LLM |
| `rt_endpoints` | Cerca negli endpoint (schema OpenAPI dell'app); con `detail` mostra parametri e corpo |
| `rt_request` | Qualsiasi chiamata sotto `/api/v1`; file binari salvati in `~/.rt/mcp/downloads` |
| `rt_upload` | POST multipart con file locali: import audio (`/lessons`), ZIP, fonti, immagini |
| `rt_wait_job` | Aspetta la fine di un job e riporta durata, errore ed eventi |
| `rt_logs` | Ultime righe di api, worker, desktop e browser-install, filtrabili per testo e ora |
| `rt_export_lesson` | ZIP di una lezione in `~/.rt/mcp/exports` |
| `rt_browser_login` | Link monouso per aprire la web app autenticata nel browser di Playwright |

## Protezioni

- **Sempre bloccati**: uscita da RT, aggiornamenti e canale, finestra del Finder, rivelare il
  token Telegram, chiusura della sessione.
- **Con `confirm=true`**: ogni DELETE, le eliminazioni via POST, Aggiorna/Ricostruisci,
  ripristini di versioni e del testo, modifica dei metadati, compattazione audio, chiavi e
  connessioni, import di calendario e tipi di domanda.
- **Eliminare una lezione** ne salva prima lo ZIP completo; se l'export fallisce la lezione non
  si elimina.

Quello che non copre: la finestra nativa dell'app, la scelta cartella del Finder, la
registrazione dal microfono.
