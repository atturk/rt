# Piano agy: nuova configurazione guidata (3 passi) dai wireframe

Base: main (104f9d1). Prima di tutto: `git pull` di questo branch. Solo codice e test unitari (vitest/pytest), niente Playwright.

Wireframe approvati da Attilio: https://claude.ai/artifact/MSSWwtvcprkVENUsUYiCMr (tavole «1 · Connessione»,
«2 · Modello», «3 · Pronto», «Collega Telegram»). Qui sotto c'è tutto quello che serve, senza aprirli.

File principali: `frontend/src/components/settings/wizard.tsx` (+ test), `NewConnectionForm` (dove è definito),
`frontend/src/components/settings/telegram.tsx`, `rt/api/routers/settings.py`, `rt/services/settings_service.py`.
Stile: quello delle pagine Impostazioni (Card, SettingsRow, Button). Pulsanti principali alti 44 px (`h-11`).

## 1. Passi: da 4 a 3

`STEPS = ['Connessione', 'Modello', 'Pronto']`. Telegram esce dalla guida (vedi §4). `?passo=` vecchi
(4) vanno su 3. In alto a destra, su ogni passo tranne l'ultimo, il link «Configura dopo» (porta all'elenco lezioni).
I passi fatti mostrano la spunta nel cerchio.

## 2. Passo «Connessione» (P2)

- Titolo «Collega un servizio di IA», sottotitolo: «RT usa un servizio di intelligenza artificiale per rielaborare e verificare
  le lezioni. Lo paghi tu, a consumo, con la tua chiave.»
- Riquadro verde chiaro di spiegazione: «**Connessione** = il servizio che usi, per esempio OpenRouter. **Chiave API** = il codice
  personale che quel servizio ti dà. Una connessione può avere più chiavi: RT le usa a turno e passa alla successiva se una
  finisce il credito o raggiunge i limiti.»
- «Servizio»: 4 schede in griglia (altezza 64 px): OpenRouter con etichetta verde «Consigliato», Google AI Studio, DeepSeek,
  Altro con etichetta ambra «Per esperti». Altro mostra i campi URL base/nome come oggi.
- Campo «Chiave API» (poi «Chiave API 2», «Chiave API 3»… per le chiavi aggiunte), con occhio per mostrare e pulsante cestino
  44×44 accanto; il cestino su un campo pieno chiede conferma. Link «+ Aggiungi un'altra chiave».
- Accanto all'etichetta «Chiave API» un pulsante tondo «?» (non per Altro) che apre un popup (role=dialog, chiudi con ✕ ed Esc)
  con la guida del servizio scelto. Testi esatti:
  - OpenRouter — «Come ottenere una chiave OpenRouter»: 1) Accedi o registrati su openrouter.ai. 2) Apri la pagina Keys e premi
    «Create API key». 3) Dai un nome alla chiave (es. «RT») e, se vuoi, un limite di spesa: è consigliato. 4) Copia la chiave (inizia
    con sk-or-v1-) e incollala qui. Conservala: non la rivedrai per intero. Nota: «Per i modelli a pagamento serve aggiungere credito al
    tuo account (pagina Credits). Con un limite sulla chiave non spendi mai più di quanto decidi.» Link «Apri openrouter.ai/keys ↗»
    → https://openrouter.ai/keys
  - Google AI Studio — 1) Vai su aistudio.google.com/apikey e accedi con il tuo account Google. 2) Accetta i Termini di servizio: al
    primo accesso Google crea un progetto per te. 3) Premi «Create API key». 4) Copia la chiave e incollala qui. Nota: «C'è un livello
    gratuito con limiti di uso; per usi intensi si collega la fatturazione dal progetto Google.» Link → https://aistudio.google.com/apikey
  - DeepSeek — 1) Registrati su platform.deepseek.com con email o telefono. 2) Apri «Top up» e ricarica il credito: senza credito la
    chiave non funziona. 3) Nel menu a sinistra apri «API keys» e premi «Create new API key». 4) Dai un nome e copia subito la chiave:
    DeepSeek la mostra una volta sola. Nota: «Si paga a consumo dal credito ricaricato.» Link → https://platform.deepseek.com/api_keys
  I link si aprono nel browser di sistema (come gli altri link esterni dell'app desktop).
- Validazione: quando la chiave è incollata si verifica (endpoint esistente di test/creazione connessione) e sotto compare
  «✓ Chiave valida · elenco dei modelli scaricato» oppure l'errore umano. Si salva solo con «Continua», mai a ogni tasto (P4).
- In fondo: «Avanzate» (apre le opzioni di oggi) e «Continua». Con connessioni già presenti resta il comportamento di oggi
  («Connessioni già configurate…», Continua, disclosure «Aggiungi un'altra connessione»).

## 3. Passo «Modello» (P3, P5)

- Titolo «Scegli il modello», sottotitolo «Ne basta uno: RT lo usa per tutte le fasi di elaborazione. Puoi cambiarlo quando vuoi dalle Impostazioni.»
- **Un solo campo obbligatorio** «Modello principale *», con autocompletamento a tendina (combobox ARIA, non `<datalist>`):
  - elenco dei modelli **del servizio**: nuovo endpoint `GET /settings/connections/{name}/catalog` che chiama `GET {base_url}/models`
    (OpenAI-compatibile; per OpenRouter `https://openrouter.ai/api/v1/models`) con la chiave della connessione, cache in memoria 10 min,
    timeout 6 s. Risposta: `[{id, name, prompt_price, completion_price, recommended}]`. Se fallisce: lista = modelli già noti della connessione
    e un campo libero (come oggi).
  - filtra mentre si scrive (sottostringa, case-insensitive), max 50 voci, ↑↓ Invio Esc; ogni voce mostra nome e prezzo «$x / M token»
    se noto; il modello consigliato (quello di default di RT per quel provider, se esiste già una costante; altrimenti nessuno) in cima con
    l'etichetta «Consigliato».
  - **si salva solo un modello scelto dall'elenco** (Invio, clic o «Continua»), mai a ogni lettera; `autoComplete="off"` sul campo, così
    niente cronologia del browser (bug P4 del collaudo: il campo salvava a ogni tasto).
- Sotto: «Costo stimato per una lezione di 2 ore: **…**» da `/settings/estimate`; se il prezzo manca la riga non si mostra.
- Spunta «Usa questo modello per tutte le fasi» (spuntata di default; una sola richiesta `useAssignAllPhases`) e link «Personalizza per fase»
  che mostra le righe per fase di oggi (`PhaseRows`).
- Riquadro «FACOLTATIVI · puoi aggiungerli anche dopo» con due righe: «Descrizione immagini» e «Generazione immagini», ognuna con icona ⓘ
  e tooltip (descrizione: «Serve solo per leggere foto e pagine dei PDF. Se non lo imposti, quando caricherai immagini RT ti porterà qui per
  sceglierlo.»; generazione: «Serve solo per creare immagini nell'arricchimento. Se non lo imposti, RT te lo chiederà quando serve.») e a destra
  «Non impostato · Aggiungi» (Aggiungi apre lo stesso combobox in linea). Non bloccano «Continua».
- **Redirect quando servono (P5)**: se un job ha bisogno della descrizione immagini (o generazione) e il modello non c'è, oggi fallisce. Il
  messaggio d'errore umano diventa «Per leggere le immagini serve un modello di descrizione immagini. Sceglilo in Impostazioni › Modelli.» con
  azione che porta a `/impostazioni/modelli` (stesso meccanismo dei link negli errori esistenti). Cercare dove si solleva oggi l'errore di
  modello mancante (`grep image_description` in `rt/services`, `rt/pipeline`).
- In fondo «Indietro» e «Continua» (disabilitato finché il modello principale non è scelto).

## 4. Telegram fuori dalla guida

- Nuovo componente `TelegramConnectScreen` (route dedicata, es. `/impostazioni/telegram/collega`), usato dalla scheda della schermata finale e da
  Impostazioni › Telegram al posto del form di oggi per il primo collegamento.
- Contenuto: «← Indietro»; titolo «Usa RT anche da Telegram», sotto il titolo l'etichetta «FACOLTATIVO»; testo «Se usi Telegram, RT può scriverti
  tramite un tuo bot personale. Non serve per usare RT.»; due vantaggi con icona: «Avvisi sul telefono — Ti avvisa quando una lezione è pronta o se
  qualcosa si blocca.» e «Ripasso con domande — Ricevi le domande di ripasso delle tue lezioni e rispondi in chat.»; riquadro «Come si collega · circa
  2 minuti»: 1) In Telegram apri @BotFather e crea un bot con /newbot. 2) Copia il token che ti dà e incollalo qui sotto. 3) Scrivi un messaggio
  qualsiasi al tuo bot, poi premi «Collega». Campo «Token del bot». Pulsanti «Annulla» e «Collega»; nota «Puoi collegarlo o scollegarlo quando vuoi
  da Impostazioni › Telegram.»
- «Collega» salva il token e chiama l'endpoint esistente `POST /settings/telegram/chat` (rileva la chat dal primo messaggio). Se la chat non si
  trova: messaggio «Non trovo il tuo messaggio: scrivi qualcosa al bot e riprova» e, dietro un link «Inserisci l'ID a mano», il campo chat ID di oggi.
- «Annulla», «Collega» riuscito e «← Indietro» tornano da dove si è arrivati (`location.state.from` o history back).

## 5. Passo «Pronto» (P8)

- Icona tonda con spunta, titolo «RT è pronto», sottotitolo «Ora prova a creare la tua prima lezione.»
- Due grandi schede affiancate: «Prova la lezione di esempio» (piena, colore primario; «Una guida rapida a RT dentro una lezione vera. Gratis,
  nessuna elaborazione.» → importa/apre la lezione di esempio come fa oggi la WelcomeBox) e «Crea la tua prima lezione» (bordo; «Carica la registrazione
  e, se li hai, slide, PDF o foto della lavagna.» → apre la creazione lezione).
- Scheda compatta tratteggiata: «Usi Telegram? FACOLTATIVO — Ricevi avvisi e domande di ripasso sul telefono.» + pulsante «Collega Telegram →».
- Riepilogo piccolo: «✓ Connessione — OpenRouter · 1 chiave», «✓ Modello — <id>», «– Immagini (facoltativo) — Aggiungi» (→ Impostazioni › Modelli).
- Riga finale: «Hai dubbi? La guida è sempre nel menu Aiuto (⌘?). Puoi rifare questa configurazione da Impostazioni.»
- In alto a destra «Vai alle lezioni». Ogni uscita (le due schede, «Vai alle lezioni», barra laterale) segna la guida come completata, così non ricompare.

## 6. Test

vitest: 3 passi e redirect di `?passo=4`; popup «?» per i tre servizi e assente su Altro; combobox (filtro, tastiera, nessun salvataggio prima della
scelta, `autoComplete=off`); «Continua» disabilitato senza modello; facoltativi non bloccano; schermata Telegram (Annulla torna indietro, Collega chiama
le due API, fallback chat ID); Pronto (due schede, Telegram →, riepilogo). pytest: endpoint catalog (successo, errore → fallback, cache), messaggio di
modello immagini mancante.

## Sovrapposizioni
Tocca `wizard.tsx`, `telegram.tsx`, `settings.py`/`settings_service.py`. Il piano «lezione di esempio» tocca come la si apre: qui si chiama solo
la funzione esistente usata dalla WelcomeBox, senza cambiarla.
