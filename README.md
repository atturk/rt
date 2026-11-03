# RT

RT è un sistema per la rielaborazione delle lezioni universitarie e per lo studio basato sull'IA.

<table>
  <tr>
    <td width="33%"><img alt="Screenshot 1" src="https://github.com/user-attachments/assets/05c719aa-de39-4d7a-8cfe-39a65e87420f" /></td>
    <td width="33%"><img alt="Screenshot 2" src="https://github.com/user-attachments/assets/6fe70cd5-17a5-42fd-981c-3f8178b1f469" /></td>
    <td width="33%"><img alt="Screenshot 3" src="https://github.com/user-attachments/assets/d448e03d-b5c7-4497-b55a-20983dccdb99" /></td>
  </tr>
</table>

## Installazione
In fondo a [questa pagina](https://github.com/atturk/rt/releases/latest) trovi l'ultima versione. Attualmente disponibile per Windows e MacOS.

## A cosa serve RT
RT è un rielaboratore di lezioni universitarie. Il nome (RT, rt o rt.) significa *Rielaborazione Trascritti* perché nasce come rielaboratore di lezioni registrate. 

**Rielaborare una lezione universitaria con RT significa trasformare una registrazione vocale lunga, piena di digressioni, interruzioni e inefficienze del parlato in un file di testo chiaro, ben organizzato, comprensibile e leggibile in poco tempo.**

Oltre a rielaborare le lezioni, RT offre diverse feature tra cui
- possibilità di testare le conoscenze tramite quiz, domande mirate, domande vaste e *modelli di domanda personalizzata*
- strumenti organizzativi, come un calendario delle lezioni, con time blocks ai quali collegare le singole lezioni
- strumenti di studio, come una modalità lettura in cui viene visualizzata una singola sezione della rielaborazione e una modalità lettura veloce

### Perché dovrei usare RT quando posso semplicemente dare il trascritto a un LLM?
RT offre diversi vantaggi rispetto a una rielaborazione "one shot" da parte di un LLM, tra cui
1. il motore di trascrizione associa a ogni singola parola un timestamp e un punteggio di confidence (quanto è sicuro il modello che si stata detta quella parola)
2. 

## Licenza
Copyright (C) 2026 Attilio Turco

RT è software libero: puoi ridistribuirlo e/o modificarlo secondo i termini della [GNU Affero General Public License v3.0](LICENSE) (`AGPL-3.0-only`). Se modifichi RT e lo offri ad altri come servizio in rete, devi rendere disponibile il codice sorgente delle tue modifiche alle stesse condizioni.

Il nome e il logo di RT non sono coperti dalla licenza del codice. Per usi non compatibili con la AGPL (per esempio integrare RT in un prodotto closed source) puoi chiedere una licenza commerciale scrivendo a [@atturk](https://github.com/atturk).

## Firma del codice (Code signing policy)

Gli installer per Windows sono firmati gratuitamente: *Free code signing provided by [SignPath.io](https://about.signpath.io), certificate by [SignPath Foundation](https://signpath.org).*

- **Chi firma:** solo gli installer prodotti dal workflow `release.yml` di questo repository, a partire dal codice in `main`, vengono inviati alla firma.
- **Ruoli:** autore, revisore e approvatore delle release è [@atturk](https://github.com/atturk). Ogni firma va approvata a mano.
- **App per Mac:** non è firmata con un ID sviluppatore Apple. Al primo avvio si apre da Impostazioni di Sistema › Privacy e sicurezza › «Apri comunque».

### Privacy

RT gira sul tuo computer e i dati delle lezioni restano lì. Non raccoglie statistiche d'uso e non invia niente al progetto. Si collega a servizi esterni solo per quello che chiedi tu:

- il fornitore di modelli che configuri, per esempio OpenRouter, con la tua chiave: riceve i testi da elaborare;
- GitHub, per controllare e scaricare gli aggiornamenti;
- Telegram, solo se attivi il ripasso via Telegram;
- i server dei componenti necessari, come la trascrizione e il browser per l'arricchimento, quando li installi.

*This program will not transfer any information to other networked systems unless specifically requested by the user or the person installing or operating it.*
