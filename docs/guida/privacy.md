# Privacy

RT è un programma che gira sul tuo computer. Non ha un account, non ha un server del progetto e non raccoglie statistiche d'uso. Questa pagina spiega quali dati restano sul computer e quali escono, e verso chi.

## Cosa resta sul tuo computer

- Lezioni, audio, trascrizioni, testi rielaborati, segnalazioni della Verifica, domande, evidenziazioni e stato di studio.
- Il database di RT e i backup, compresi quelli leggeri fatti prima degli aggiornamenti.
- Le chiavi dei fornitori di modelli, il token di RT e la chiave per gli agenti. Stanno nell'archivio dei segreti di RT, non nel database delle lezioni, e non vengono mai mandate al progetto.
- I registri (log), nella cartella dati di RT. Li vedi solo tu, e li condividi solo se decidi di mandarli.

## Cosa esce dal computer, e solo quando serve

RT si collega a servizi esterni solo per quello che chiedi tu:

- **Il fornitore di modelli che scegli** (per esempio OpenRouter, OpenAI, Google), con la tua chiave. Riceve i testi da elaborare: trascrizione, appunti, testo delle slide e dei materiali, le tue domande con «Chiedi». Cosa ne fa lo decidono le sue condizioni: leggile prima di scegliere.
- **La trascrizione online**, solo se la scegli al posto di quella sul computer. In quel caso il fornitore riceve l'audio.
- **La ricerca di immagini**, solo se la attivi per arricchire le lezioni. Riceve le parole cercate.
- **Telegram**, solo se attivi il ripasso via Telegram. Riceve le domande e le tue risposte.
- **GitHub**, per controllare e scaricare gli aggiornamenti e la guida pubblica. GitHub vede l'indirizzo IP, come per ogni download.
- **I server dei componenti**, quando li installi (per esempio il modello di trascrizione o il browser per l'arricchimento).

## iPhone e agenti

- L'accesso da iPhone usa un QR con un link che entra una sola volta e vale 5 minuti: mostralo solo a dispositivi tuoi.
- L'API di sola lettura per gli agenti risponde solo sul computer stesso (127.0.0.1) e non può modificare niente. Un agente che la usa vede le tue lezioni: dagliela solo se ti fidi dell'agente e del fornitore di modelli che usa.

## File che condividi

I file `.rt` (lezioni), `.rtdb` (collezione) e `.rtcal` (orario) contengono i tuoi dati. La collezione esportata con «Esporta tutto» non contiene le chiavi. Condividili come condivideresti i tuoi appunti.

## Cancellare i dati

Per togliere tutto basta disinstallare RT e cancellare la cartella dati (menu RT → «Apri cartella dati»). Le chiavi si revocano anche dal sito di ogni fornitore.

## Contatti

Domande o segnalazioni sulla privacy: apri una issue su GitHub nel repository di RT.

*This program will not transfer any information to other networked systems unless specifically requested by the user or the person installing or operating it.*
