# Piano B: nuove Impostazioni (rework della UI, non correzioni singole)

Branch: `agy/4.3.9-impostazioni`, che parte dalla punta di `agy/4.3.9-notifiche` (piano A, già finito).
Prima di tutto `git pull` del branch. Solo codice e test unitari, niente verifiche nell'app (le faccio io in
chiaro e scuro). Commit piccoli, push sul branch.

## Obiettivo
Le Impostazioni oggi sembrano un modulo cresciuto a pezzi: righe e linee doppie, «Salva» sparsi fra due
linee, campi disallineati, sezioni quasi vuote o duplicate, frecce ▼ nude, intestazioni MAIUSCOLE ovunque.
Va rifatto il **sistema**, non le singole pagine: un solo set di componenti, una sola griglia, salvataggio
automatico, spiegazioni nei tooltip. Stile: quello di RT (font, colori e token di `frontend/src/index.css`,
raggio 8px, verde RT come accento), più moderno, minimale e preciso, sul modello delle impostazioni di
macOS / Linear / Raycast: gruppi a "lista inserita", molta aria, nessun bordo superfluo.
Font: esattamente quello del resto di RT (`font-sans` di `index.css` e le dimensioni `text-meta`/`text-body`/
`text-heading`): nessun font, peso o dimensione nuova, così il cambio non è brusco. Riferimento visivo approvato da
Attilio: il prototipo https://claude.ai/artifact/KzUcDv4KRW8u4SZyhkVTwZ (struttura e stile; i contenuti seguono questo piano).

## 1. Componenti (nuovo `frontend/src/components/settings/ui.tsx`, sostituiscono quelli di `common.tsx`)
- `SettingsPage({ title, description, children })`: titolo della sezione + una riga di descrizione muted.
  Contenuto `max-w-3xl`, gruppi distanziati `gap-8`.
- `SettingsGroup({ title?, description?, footer?, children })`: titolo piccolo in sentence case
  (`text-meta font-medium text-muted-foreground`, niente uppercase), sotto un riquadro `rounded-lg border
  bg-card` con le righe separate da `divide-y divide-border/60`. Mai linee fuori dai riquadri, mai due
  linee una sopra l'altra. `footer` = testo muted sotto il riquadro.
- `SettingsRow({ label, description?, info?, control, htmlFor?, stacked? })`: griglia
  `grid-cols-[1fr_auto]`, `px-4 py-3`, `min-h-12`, allineamento verticale al centro. Etichetta
  `text-body`, descrizione su una riga `text-meta text-muted-foreground`. `info` → icona `Info` (lucide,
  `size-3.5`) accanto all'etichetta che apre il `Tooltip` esistente (`components/ui/tooltip.tsx`) con la
  spiegazione lunga: le spiegazioni lunghe NON stanno più sotto l'etichetta. Il controllo a destra ha larghezze
  fisse coerenti: select/input `w-60` (testo) o `w-24` (numeri), switch e pulsanti icona allineati a destra.
  `stacked` (o schermo stretto, `@container`) → controllo sotto l'etichetta a tutta larghezza (per URL, prompt,
  textarea).
- `SettingsSwitch` (usa `components/ui/switch.tsx`) per tutti i sì/no: niente più badge «Sì» cliccabili né
  checkbox con paragrafi.
- `SettingsDisclosure({ label, summary?, children, defaultOpen=false })`: riga cliccabile con chevron che
  ruota (`ChevronRight` → 90°), `summary` muted a destra (es. «1 voto», «3 modelli»); contenuto dentro lo
  stesso riquadro. Sostituisce `<details>` e le frecce ▼.
- `SettingsMatrix` per le tabelle di scelte (vedi Fonti): intestazione delle colonne UNA volta, righe con
  etichetta a sinistra e celle a icona; ogni icona ha tooltip.
- Salvataggio automatico (`useAutoSave(mutation, value, { delay })`): switch/select salvano subito; testi e
  numeri al blur o dopo 600 ms senza digitare. Stato discreto nella riga stessa: spinner piccolo mentre salva,
  poi «Salvato» muted che sparisce dopo 1,5 s; errore in rosso nella riga con «Riprova». **Niente più pulsanti
  «Salva …»**, tranne dove serve un'azione esplicita: chiavi/segreti (campo + «Salva chiave» nella riga),
  connessioni nuove, import/export.
- Tutto con token (`bg-card`, `border`, `muted`, `foreground`…): nessun colore fisso, così chiaro e scuro
  vengono giusti. Focus visibile ovunque (`focus-visible:ring-2 ring-ring`).

## 2. Struttura (navigazione e contenuti)
- Barra sinistra: stesse voci con un'icona lucide piccola per ciascuna, voce attiva con `bg-muted` e testo
  `font-medium` (non bold pesante). «Calendario» e «Materie» diventano una voce sola **«Materie e
  calendario»** (redirect da entrambi i vecchi path): gruppo Materie (elenco, nuova materia, docenti), gruppo
  Calendario (avviso lezioni mancanti, orario con importa/esporta UNA volta sola).
- **Aspetto e lettura**: gruppi Tema, Lettura, Evidenziatore, Chiusura della finestra (tasto X).
- **Domande**: gruppo «Regole imparate dai tuoi voti» con descrizione chiara: righe «Usa i voti per migliorare
  le domande» e «Controlla le domande prima di salvarle» (con `info` che spiega cosa fanno; oggi «Voti» e
  «Controllo prima di salvare» non si capiscono). Le regole per tipo/materia (oggi textarea sempre aperte, es.
  «Mirata · ELETTROMAGNETISMO · 1 voti») diventano `SettingsDisclosure` chiuse con summary «N voti», dentro la
  textarea e «Rigenera». Gruppo «Tipi personalizzati» come oggi ma nei componenti nuovi. «Galleria dei modelli
  pronti»: gruppo con titolo chiaro e card compatte, sempre visibile (non nascosta dietro ▼).
- **Lavorazione delle lezioni**: gruppo Trascrizione (motore; URL server, modello e chiave compaiono solo per i
  motori che li usano, come righe allineate); gruppo Scaletta (la scelta del piano A «Approvazione della
  scaletta» + secondi solo per la modalità a tempo); gruppo Fonti con `SettingsMatrix`: righe Slide / Testi /
  Immagini, colonne raggruppate «Cosa usare» (testo, pagina, immagini) e «Come usarla» (guida, contesto,
  collegamenti) con l'intestazione una volta sola e tooltip per ogni icona (oggi sembra triplicato e la parola
  «Contesto» si ripete su ogni riga); gruppo Arricchimento; gruppo Velocità (switch «Lavora in parallelo» con
  `info` che elenca cosa va in parallelo).
- **Modelli e connessioni**, **Telegram** (inclusi interruttori e storico del piano A), **Accesso da altri
  dispositivi**, **Info e aggiornamenti**: stessi contenuti nei componenti nuovi. Le pagine lunghe (modelli)
  usano disclosure per le parti avanzate (editor dei prompt, route).
- Telefono: la lista delle sezioni resta come oggi (voce + descrizione + chevron); dentro una sezione i gruppi
  vanno a tutta larghezza e le righe passano in `stacked` quando serve.

## 3. Regole di qualità
- Nessuna sezione quasi vuota: se una pagina ha meno di due righe, va accorpata.
- Nessun duplicato (es. «Orario del calendario» oggi compare in Calendario e in Materie).
- Testi brevi, in italiano semplice, sentence case; spiegazioni nei tooltip `info`.
- Tooltip SEMPRE interi e in primo piano: solo il `Tooltip` di `components/ui/tooltip.tsx` (portale in
  `document.body`, posizione fissa con `placeTooltip`), mai tooltip CSS dentro i riquadri. Niente `overflow-hidden`
  che li tagli, niente z-index più bassi di riquadri, intestazioni fisse o pannello laterale; vicino ai bordi della
  finestra si girano (sopra/sotto, sinistra/destra) invece di uscire. Vitest: il testo del tooltip di una riga
  sta in `document.body` fuori dal gruppo e non dentro un elemento con overflow nascosto.
- Mantieni i `data-testid` esistenti dove possibile (sui controlli, non sui contenitori) per non rompere e2e.
  Aggiorna i test vitest delle impostazioni (`components/settings/*.test.tsx`): le asserzioni su «Salva …»
  diventano asserzioni sul salvataggio automatico (mutation chiamata dopo change/blur).
- Bundle: il budget iniziale è quasi pieno (487,7/490 kB). Le pagine delle impostazioni devono restare lazy
  (controlla `React.lazy` delle route) e non aggiungere dipendenze.
- `docs/guida/` se cita «Salva scaletta», «Calendario» come voce separata o simili: aggiorna i testi.

## Chiusura
- `CHANGELOG.md` sezione `4.3.9b9`: Novità «Impostazioni ridisegnate: gruppi più chiari, salvataggio
  automatico, spiegazioni nei suggerimenti; Materie e calendario in un'unica pagina».
- Esegui: `npx vitest run`, `npx oxlint --deny-warnings`, `npx tsc -b`, `npm run build`,
  `npm run -s check:bundle`, e la parte e2e delle impostazioni se c'è (`npx playwright test e2e/settings*
  --trace off`, con `RT_PYTHON` puntato al python del repo) se riesci a lanciarla; altrimenti scrivilo.
- Push su `agy/4.3.9-impostazioni`.
