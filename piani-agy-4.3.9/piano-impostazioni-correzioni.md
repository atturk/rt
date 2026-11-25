# Piano B2: correzioni visive delle nuove Impostazioni

Branch: `agy/4.3.9-impostazioni` (continua da qui). Prima di tutto: `git pull` del branch. Solo codice e test,
niente verifiche nell'app. Correggi nel **sistema** (`components/settings/ui.tsx` e i suoi usi), non con
eccezioni per pagina. Un commit, push sul branch.

1. **Modelli e connessioni**: il campo Modello è più basso di ~8 px e alto ~36 px contro i 44 della Connessione.
   Tutti i controlli di una riga (select, input, pulsanti) hanno la stessa altezza (`h-9`) e sono allineati al
   centro della riga; l'etichetta allineata in verticale con il controllo. Le righe senza «Prova» (Arricchitore,
   Visualizzazioni, Generazione immagini) tengono le stesse colonne delle altre: griglia a colonne fisse
   (es. `grid-cols-[minmax(0,1fr)_14rem_14rem_5.5rem]`) con una cella vuota dove manca il pulsante.
2. Stessa pagina: con un nome su due righe («Descrizione immagine…») l'icona «i» resta subito dopo l'ultima parola
   (inline, non in una colonna a parte).
3. **Lavorazione › Fonti**: intestazioni della matrice tagliate («Pagi…», «Imm…», «Cont…», «Coll…»), anche su
   telefono. Usa intestazioni che vanno a capo (niente `truncate`/`whitespace-nowrap`), oppure icone con tooltip
   più testo breve; nessuna intestazione troncata a 1280, 820 e 390 px.
4. **Lavorazione**: i menu vanno a capo («Procedi sempre in / automatico», «macparakeet (sul Mac) · / consigliato»).
   Il controllo non va mai a capo: larghezza adatta al testo più lungo (`w-64` o `min-w-max`), testo dell'opzione
   più corto se serve (es. «Procedi da sola», «macparakeet · consigliato»), su telefono il controllo va sotto
   l'etichetta a tutta larghezza.
5. **Una sola misura per le righe**: le etichette delle righe tutte a `text-body` (15 px) con `font-medium`; le
   descrizioni sotto a `text-meta`. Oggi ci sono etichette da 12 px accanto a nomi da 15 («Slide», «Orario del
   calendario», «Outline»).
6. **Interruttori accesi in chiaro**: oggi il verde è quasi invisibile. `SettingsSwitch` acceso = `bg-[--acc]`
   pieno (verde RT #155f52) con pallino bianco; spento = `bg-muted` con bordo. In scuro acceso = verde chiaro
   leggibile. Contrasto minimo 3:1 con lo sfondo in entrambi i temi.
7. **Telegram**: titolo di pagina e di gruppo entrambi «Telegram», descrizione ripetuta. Il primo gruppo si chiama
   «Collegamento», la descrizione compare una volta sola (sotto il titolo di pagina).
8. **Accesso su telefono**: la pagina scorre di 4 px in orizzontale a 390 px. Trova l'elemento che sfora (codice o
   URL lunghi: `break-all`/`min-w-0`) e correggilo; aggiungi al test Playwright delle Impostazioni un controllo che
   a 390 px nessuna pagina abbia `scrollWidth > clientWidth`.

Test: vitest dei componenti (altezze/classi dei controlli, switch acceso con la classe dell'accento), Playwright
settings come prima. Esegui `npx vitest run`, `npx oxlint --deny-warnings`, `npx tsc -b`, `npm run build`,
`npm run -s check:bundle`, Playwright settings. Non cambiare `CHANGELOG.md` né `VERSION`.
