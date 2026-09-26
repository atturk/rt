# Parità CLI ↔ web (RT 4.0)

Tabella del piano di migrazione (sezione 9-bis). Tutto quello che si fa nel terminale si fa
anche dalla web; ogni azione della web passa dall'API e viene salvata dal backend. Una riga è
"fatta" quando passano tutte e tre le verifiche:

1. **Parità backend (RT4-E5)**: `tests/test_api_parity.py` esegue la stessa operazione via CLI
   e via API su due copie della stessa lezione in mock e confronta file, stato delle fasi,
   ledger e costi.
2. **Persistenza (RT4-E5)**: `tests/test_api_persistence.py` rilegge ogni scrittura da un
   processo nuovo (app, client e connessione al DB nuovi).
3. **End-to-end della SPA (RT4-F7)**: Playwright contro l'API vera, con ricarica dopo ogni
   modifica. Arriva con la fase F.

| Processo CLI oggi | Endpoint API (fase E) | Schermata SPA (fase F) | Parità (E5) | Persistenza (E5) | SPA (F7) |
|---|---|---|---|---|---|
| `rt run` (audio o cartella, `--mock`, `--auto-accept`, `--force`) | `POST /lessons` (`run=true`), `POST /lessons/{id}/jobs` tipo `run_pipeline` | Importazione + avvio pipeline | ✅ `test_row_run_folder_pipeline` | ✅ `test_job_writes_persist` | ✅ `ingest.spec.ts` (importa, segue gli eventi, approva, arriva alla review) |
| `rt setup` / trascrizione | `POST /lessons` → job `ingest_audio` | Importazione con upload | ✅ `test_row_setup_audio` | ✅ `test_job_writes_persist` | ✅ `ingest.spec.ts` (solo trascrizione, errori di formato) |
| `rt prepare`, `outline`, `rewrite` (anche `--unit`), `review`, `build` singoli | `POST /lessons/{id}/jobs` tipo `run_phase` | Pulsanti per fase nella vista lezione | ✅ `test_row_single_phases`, `test_row_rewrite_single_unit` | ✅ `test_job_writes_persist` | ✅ `lesson-view.spec.ts` (avvio di una fase) |
| `validate-outline`, `validate-draft` | `GET /lessons/{id}/phases` | Stato fasi con errori leggibili | ✅ `test_row_validate_outline_and_draft` | lettura | ✅ `lesson-view.spec.ts` (fasi e validazioni) |
| Approvazione/revisione outline | `GET /outline`, `POST /outline/approve`, `/outline/revise` | Vista outline ad albero | ✅ `test_row_outline_revise_and_approve` | ✅ `test_outline_and_review_decisions_persist` | ✅ `ingest.spec.ts` (approva, richiedi modifiche) |
| Review interattiva delle issue (accetta, rifiuta, modifica, annulla) | `GET /issues`, `POST /issues/{id}/decision`, `POST /decisions/undo` | Review contestuale | ✅ `test_row_interactive_review` | ✅ `test_outline_and_review_decisions_persist` | ✅ `review.spec.ts` (decisioni, annulla, ripartenza della pipeline in attesa) |
| `rt add-images` | `POST /lessons/{id}/images` → job `add_images`; `GET /lessons/{id}/images`, `/assets/images/{nome}` | Immagini della lezione (`/lezioni/{id}/immagini`) | ✅ `test_row_add_images` | ✅ `test_images_job_persists` | ✅ `recall-images-bot.spec.ts` (PDF, job, anteprima) |
| `rt recall` (quiz, mirata, vasta; risposta scritta o vocale) | `GET /recall`, `/recall/history`, `POST /recall/generate`, `/next`, `/answer`, `/answer-voice`, `/vote`, `/skip` | Sessione di recall (`/lezioni/{id}/recall`) | ✅ `test_row_recall_quiz_and_open_answer` | ✅ `test_recall_writes_persist` | ✅ `recall-images-bot.spec.ts` (quiz, voto, salto, scritta, vocale) |
| `rt export` (Markdown finale con immagini, `--all`, `--zip`) | `GET /lessons/{id}/export` (`format=markdown\|zip`, `scope=final\|all`) | Download dalla vista lezione | ✅ `test_row_export` | lettura | ✅ `lesson-view.spec.ts` (Markdown e zip uguali all'API) |
| `rt status`, `rt cost` | `GET /lessons/{id}`, `GET /costs` | Dashboard e vista lezione | ✅ `test_row_status_and_cost` | lettura | ✅ `foundation.spec.ts` (dashboard), `lesson-view.spec.ts` (fasi, costi) |
| `rt config` (provider, chiavi, modelli per le sei fasi, pricing, Telegram, trascrizione, lessons_root) | endpoint di RT4-E4 (`/settings/...`, `/secrets/{name}`) | Impostazioni | ✅ `test_row_config_written_by_api_is_read_by_cli` | ✅ `test_settings_writes_persist` | — |
| `rt telegram-daemon` (avvio, stato) | `GET /telegram/daemon`, `POST /telegram/daemon/start`, `/stop` | Stato del bot (`/bot`, pannello riusabile nelle impostazioni) | ✅ `test_row_telegram_daemon_status` | PID file del demone | ✅ `recall-images-bot.spec.ts` (bot finto) |
| `rt -u` (aggiornamento) | fuori scope per la web | — | — | — | — |

Sessione del browser (login e logout): `test_browser_session_persists_and_logout_revokes`;
nella SPA (RT4-F1) accesso con link monouso o token, logout e dashboard con filtri sono in
`frontend/e2e/foundation.spec.ts`. La colonna "SPA (F7)" copre le schermate F2-F6 (test in `frontend/e2e/`).
Il percorso completo di una lezione nuova (link di accesso, importazione dell'audio, scaletta,
review di tutte le issue, build, documento con audio, recall), con ricarica dopo ogni passo, è
in `frontend/e2e/journey.spec.ts`; l'accessibilità di base (axe, regole WCAG 2 A/AA, temi chiaro
e scuro, focus da tastiera) su ogni pagina in `frontend/e2e/a11y.spec.ts`.
Job in coda e annullamento (`rt jobs`, `rt jobs cancel`) sono nella pagina Job della SPA
(RT4-F4, `frontend/e2e/ingest.spec.ts`).

## Differenze trovate e corrette con i test di parità

- `rt validate-outline` e `rt validate-draft` cercavano `segments.json` nella radice della
  lezione invece che in `_state/`: fallivano su ogni lezione attuale.
- Dopo l'ultima decisione presa via API `info.yaml` restava `in_attesa_revisione_umana`: ora
  passa a `pronto_per_build` come a fine review da terminale o da Telegram.
- Un `rt run` da audio accodato (`POST /lessons` con `run=true`) falliva alla ripresa dopo
  l'approvazione della scaletta: rifaceva il setup sulla cartella già creata. Ora riparte dalla
  lezione (trovato dal test Playwright di RT4-F4).
- `POST /lessons/{id}/images` con una sola immagine la passava come file, formato che
  `add-images` non accetta: le immagini vanno sempre come cartella (un PDF da solo resta file).
- Il recall da terminale rifornisce la riserva dopo ogni domanda mostrata; ora anche
  `POST /recall/next` accoda il rifornimento (job `recall_refill`) quando la riserva è sotto
  soglia.

## Note

- Le differenze ignorate nei confronti: percorsi temporanei, timestamp, hash, e chi ha deciso e
  da dove (`channel`, `actor`, `resolved_by`: `api` contro `cli`).
- La risposta vocale nel terminale non esiste (c'è su Telegram): via API la valuta il job
  `recall_evaluate` dopo la trascrizione, ed è coperta dal test di persistenza.
- `rt config` è un wizard interattivo: il test verifica che la configurazione scritta
  dall'API sia quella che legge la CLI (`load_config` in un processo nuovo).
