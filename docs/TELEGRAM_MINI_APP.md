# Mini App Telegram di RT

Il frontend dedicato è `frontend/mini-app.html`. Riprende il design esportato da OpenDesign: lezioni, filtri per materia, dettaglio/indice unità, preparazione recall, domanda/feedback, riepilogo e lettore delle unità. Non contiene amministrazione, importazioni, revisione editoriale o impostazioni del motore.

La Mini App usa esclusivamente `/api/v1/mini-app/*`. Il router riusa i servizi RT: stesso database, banca domande, storico, voti, sessioni web/per materia, code e worker. Quiz: esito immediato; risposte aperte e vocali: valutazione asincrona tramite il worker esistente. I ritagli audio e l'invio nel topic usano le funzioni già presenti nel bot. L'audio inviato nei topic usa il bot principale e la chat configurati in RT.

## Configurazione

Nel file `.env` della directory dati di RT, mantenere il bot principale esistente e aggiungere:

```dotenv
RT_TELEGRAM_MINI_APP_USER_IDS=ID_NUMERICO_DEL_PROPRIETARIO
# Solo se si usa un bot dedicato per la Mini App:
RT_TELEGRAM_MINI_APP_BOT_TOKEN=TOKEN_PRIVATO_DEL_BOT_DEDICATO
```

L'ID è quello dell'account Telegram che apre la Mini App, non l'ID della chat/gruppo. Più ID si separano con virgole. RT resta un'applicazione per un unico proprietario: gli account autorizzati condividono lezioni, storico e sessioni, senza isolamento per studente.

Se il token dedicato non è impostato, la verifica usa `RT_TELEGRAM_BOT_TOKEN`. Con un bot dedicato si può collaudare il launcher senza sostituire il bot che gestisce le notifiche e le revisioni di RT. Non mettere i token in variabili `VITE_*`, nel JavaScript, nei log o nel repository.

Il backend verifica l'HMAC di `Telegram.WebApp.initData`, la data (massimo cinque minuti) e l'allowlist. Emette un bearer di un'ora valido soltanto per il router di studio. Il frontend conserva questo bearer in memoria; `sessionStorage` conserva solo i riferimenti necessari a riprendere il recall. Revocare un ID dall'allowlist revoca anche le sessioni già emesse. Alla scadenza riaprire la Mini App.

## Sviluppo e build

```sh
cd frontend
npm ci
npm run dev
# Aprire /mini-app.html, con rt api avviato su 127.0.0.1:8765.
```

Per la preview locale, autenticarsi prima tramite il normale link monouso di RT sulla stessa origine. Il proxy Vite include `/login?code=...`; successivamente aprire `/mini-app.html`. L'accesso locale riusa cookie e CSRF di RT. Non disabilitare l'autenticazione per pubblicare l'app.

```sh
cd frontend
npm run build
```

La build mantiene l'app desktop (`index.html`) e aggiunge `mini-app.html`. L'API RT serve entrambe dalla sua build statica tramite il router già presente. La distribuzione delle release, che include `frontend/dist`, comprende anche la nuova pagina.

Per un host statico/serverless separato:

```sh
cd frontend
VITE_RT_MINI_API_URL=https://rt-api.example npm run build:mini
```

Pubblicare `dist/mini-app.html` e gli asset che richiama. `build:mini` produce solo il frontend di studio; per la build da servire con l'API RT usare `build`, che include anche la webapp desktop. Sul backend impostare `RT_API_CORS_ORIGINS=https://study.example` con l'origine effettiva del frontend. L'URL è fissato al momento della build; cambiandolo bisogna ricompilare. Le richieste tra origini usano il bearer di studio, senza cookie dell'app desktop.

Il backend Python, il worker, SQLite, media e ffmpeg restano sull'host RT attuale. Deve essere raggiungibile dal dispositivo tramite HTTPS. Un reverse proxy/tunnel può esporre solo `/api/v1/mini-app/*`, lasciando privata l'amministrazione. Se l'host RT è spento, lo studio non è disponibile; il frontend mostra l'errore, senza sostituire i dati con demo o risposte simulate.

## Launcher Telegram Serverless

`telegram-mini-app/` contiene un launcher separato e minimo per il bot di prova. `/start`, `/app`, `/list` e `/recall` aprono il frontend in chat privata tramite un pulsante `web_app`. Nei gruppi/topic il bot invita ad aprire la chat privata. Il launcher non conserva lezioni o risposte su Telegram.

Impostare l'URL HTTPS pubblico in `telegram-mini-app/lib/config.js`. Poi, sul **bot dedicato**, abilitare Serverless in BotFather e usare il CLI ufficiale:

```sh
cd telegram-mini-app
npm install --save-dev @tgcloud/cli
npx tgcloud login
npx tgcloud diff
npx tgcloud push
```

Il CLI richiede il token di **Serverless → CLI Access**, distinto dal token della Bot API. Nessuna tabella è necessaria, quindi non serve una migrazione. Sono distribuiti soltanto i moduli JavaScript di `handlers/`, `lib/` e `schema.js`; l'HTML/CSS del frontend va ospitato separatamente. Configurare in BotFather anche la Main Mini App o il pulsante del menu con lo stesso URL.

Non distribuire questo launcher sul bot principale mentre il daemon lo usa in polling: non implementa i callback di conferma/revisione del bot esistente. Il bot dedicato evita questa interferenza. Questo branch non cambia webhook, BotFather o hosting remoto.

Riferimenti: [Telegram Mini Apps](https://core.telegram.org/bots/webapps), [Telegram Serverless](https://core.telegram.org/bots/serverless).

## Test di regressione senza credenziali reali

```sh
python -m pytest tests/test_api_mini_app.py tests/test_api_recall_subject.py tests/test_api_recall_sessions.py -q
cd frontend
npm run test -- src/miniApp.test.ts
npm run build
cd ../telegram-mini-app
npm test
```

| Livello | Verifiche |
| --- | --- |
| API + database/worker reali, provider mock | Firma, allowlist, token scaduti/manomessi, accesso negato alle API amministrative, lezioni/unità, consumo e storico recall, feedback, voti, salto/non lo so, risposte vocali, proprietà dei job, ripresa/chiusura e round robin per materia |
| Riconnessione | Ripetere `next` restituisce la domanda in attesa, senza consumarne un'altra; un job di generazione già accodato viene riusato |
| DOM del frontend, rete simulata | Consultazione autonoma, scelta e feedback conservati durante la lettura, voto/riepilogo, ripresa del job dopo il riavvio del worker senza una seconda risposta, trascrizione vocale recuperata dopo reload |
| Launcher locale | Comandi ammessi, URL HTTPS, pulsante in privato e comportamento nei topic |

I provider LLM/STT dei test sono mock per evitare costi e dipendenze esterne, mentre servizi, storage e ciclo della coda sono quelli di produzione. Non affermano qualità linguistica della valutazione né compatibilità del microfono su tutti i client Telegram.

Un controllo remoto di sola lettura è disponibile in `scripts/check_mini_app_bot.py`:

```sh
RT_MINI_TEST_TOKEN_FILE=/percorso/privato/token python scripts/check_mini_app_bot.py
```

Il file contiene solo il token del bot di prova (permessi 0600). Il comando esegue `getMe` e `getWebhookInfo`, non stampa il token e non cambia impostazioni. Non invia messaggi e non rimuove webhook.

## Collaudo dentro Telegram

Usare il bot dedicato, un account in allowlist e una copia dei dati RT di prova; il recall modifica banca/storico e può accodare operazioni LLM. L'invio audio va verificato in una chat/topic di prova configurati nella copia di RT.

1. Aprire da pulsante del bot: identità valida, lista reale; account fuori allowlist negato.
2. Cercare/filtrare lezioni; consultare unità, formule e immagini senza avviare un recall.
3. Quiz corretto, errato, non lo so e salto; consultare le unità prima della risposta e dal feedback, conservando scelta e domanda; votare e chiudere la sessione.
4. Recall di materia con almeno due lezioni: alternanza, riferimenti alla lezione corretta e riepilogo persistito.
5. Risposta aperta e registrazione vocale su iOS/Android/Desktop: permesso negato, arresto microfono, trascrizione ed effettiva valutazione. Nessun vocale deve essere inviato prima di premere il pulsante di invio.
6. Ascoltare il ritaglio dell'unità; cambiarla/chiudere il lettore arresta l'audio. Inviare l'audio nel topic di prova e verificare il file ricevuto.
7. Fermare il worker dopo l'accodamento: errore esplicito; riavviarlo e premere Riprova senza duplicare la risposta. Ricaricare la Mini App e riprendere domanda/feedback/job.
8. Verificare tema, pulsante Indietro nativo, safe area, tastiera, dialogo e focus. Confrontare il design alle dimensioni 360×800, 390×844, 430×932, 600×960, 820×1180, 1024×768, 1366×768, 1440×900, 1920×1080, senza scorrimento orizzontale.

### Verifiche eseguite durante l'implementazione

Test API Mini App, recall per materia e sessioni: **28 superati**, incluse le fixture HTTP del bot esistente. Test DOM frontend: **3 superati**. Test launcher: **2 superati**. Build desktop + Mini App e build dedicata `build:mini` completate; controllo lint del nuovo frontend e `git diff --check` senza errori.

Preview nel browser contro FastAPI reale con SQLite e lezioni sintetiche isolati: lista, dettaglio, lettore autonomo, quiz, consultazione durante la domanda conservando la scelta, feedback e chiusura/riepilogo verificati. Le nove dimensioni elencate sopra non presentano overflow orizzontale nella schermata recall; contenuto e pulsante di invio restano entro il viewport. La verifica visiva include il lettore e il feedback a 390×844. Non sono stati usati dati di produzione né provider a pagamento. Il collaudo sui client Telegram, l'audio remoto e il microfono su dispositivi reali restano da eseguire; un precedente controllo remoto di sola lettura non aveva raggiunto Telegram per restrizioni di rete.

La build è stata verificata con dipendenze locali compatibili. `npm ci --offline` non ha potuto ricostruire tutto il lockfile perché mancava Temml nella cache; è stata usata la versione Temml 0.13.5 dichiarata dal progetto, dal repository ufficiale. Prima del collaudo completo eseguire `npm ci` con rete disponibile. I warning sui bundle desktop sopra 500 kB preesistono e non riguardano il bundle della Mini App.
