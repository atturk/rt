# Piano: calendario, vista annuale, vai alla settimana, stampo, esporta e importa

Base: `claude/rt-4.3.2-beta`. Wireframe di riferimento (solo per l'idea, non da copiare alla lettera):
https://claude.ai/artifact/AJSnyZ9roghNQgdhH97tVx

## Regole di interfaccia (valgono per tutto il piano)

- Minimalismo: meno pulsanti possibile; pulsanti a **icona con suggerimento** (`IconButton` con
  `label`), mai pulsanti a testo nelle barre; **nessuna leggenda**, nessuna frase descrittiva o di
  stato visibile. Le informazioni stanno nei suggerimenti e nelle etichette `aria-label`.
- Testo visibile solo dove serve davvero: le conferme di sovrascrittura hanno una frase breve e due
  pulsanti con un verbo ("Annulla", "Sostituisci").
- Gli avvisi di copia e incolla sono popup a sola icona, come l'avviso della modalità zen dello
  Studio (`data-testid="zen-notice"` in `Study.tsx`): stesso aspetto, durata 1,2 s.
- La vista calendario attuale va bene: non cambiare ciò che il piano non nomina.

## Codice coinvolto

- `frontend/src/routes/calendar.tsx` (pagina, barra, gruppo matita con le modalità di modifica che
  compaiono al passaggio del mouse: `group-hover`), `components/calendar/WeekRangePopup.tsx`,
  `weekRange.ts`, `CalendarWeekGrid.tsx`, `CalendarDayList.tsx`, `CalendarPopups.tsx`,
  `subjectColor.ts`, `StatusIcon.tsx`, `api/calendar.ts`.
- Backend: `rt/api/routers/calendar.py`, `rt/services/calendar_service.py`
  (`_resolve_day_events`, `_resolve_dates`, `get_week_view`, `delete_template_entry` con `from/to`,
  `create_override`), `rt/services/calendar_models.py`.
- Impostazioni: `frontend/src/components/settings/subjects.tsx` (sezione Materie). Il piano n. 9
  (docenti per materia) tocca gli stessi file: fallo prima di questo.

## 1. Griglia delle settimane (componente condiviso)

Nuovo `components/calendar/WeekYearGrid.tsx`, usato da "Vai alla settimana" e dall'intervallo.

- **Anno accademico**: da settembre ad agosto. La settimana appartiene al mese del suo giovedì.
  Frecce per l'anno precedente e successivo; limiti 2025/26–2035/36 come oggi.
- **Una riga per mese**: a sinistra il nome breve del mese (con l'anno solo per settembre e gennaio),
  a destra fino a 5 caselle. Una riga sottile separa i mesi.
- **Casella**: numero della settimana e, sotto, il giorno del lunedì ("19 ott"); per la settimana
  corrente "oggi" al posto della data e bordo scuro di 2 px.
  - passata: sfondo grigio chiaro, testo attenuato, piccola spunta in alto a destra;
  - futura con ore: verde con intensità proporzionale alle ore (come oggi);
  - futura senza ore: bordo tratteggiato, sfondo trasparente;
  - cambio d'orario rispetto alla settimana prima: barretta ambra a sinistra (`inset 3px 0 0`), come
    l'attuale `border-l-2 border-study-learning`;
  - suggerimento: "Settimana 43 · 19–23 ott 2026 · 30,5 ore" (più "· l'orario cambia da qui" quando
    c'è la barretta).
- **Niente leggenda**: togli la riga "vuota · con ore · cambia qui".
- Tastiera: frecce tra le caselle, Invio per scegliere, Esc chiude.

## 2. Vai alla settimana

- Nella barra, subito dopo l'icona "Oggi", un `IconButton` con l'icona `CalendarSearch`, etichetta
  "Vai alla settimana".
- Apre un popup con `WeekYearGrid` (stesso posizionamento di `WeekRangePopup`), con l'icona "Oggi"
  nell'intestazione del popup.
- Un tocco su una casella porta a quella settimana e chiude il popup. In vista giorno porta al lunedì
  di quella settimana.

## 3. Intervallo (modifica in blocco)

`WeekRangePopup` usa `WeekYearGrid` in modalità intervallo: primo e ultimo tocco, le settimane
dell'intervallo con sfondo `--primary` e bordo verde, gli estremi pieni. Togli la frase di stato
visibile (resta in `aria-live` nascosto) e la leggenda. I pulsanti in basso diventano due icone:
`X` "Annulla" e `Check` "Modifica queste settimane" (disattivato finché manca l'intervallo).

## 4. Vista annuale

- Terza vista nel selettore desktop accanto a Settimana e Giorno: icona `LayoutGrid`, etichetta
  "Anno". Solo desktop, come il selettore attuale. Ricorda la vista scelta per la sessione.
- **Dati**: nuovo endpoint `GET /api/v1/calendar/year?start=YYYY-MM-DD` (lunedì della prima
  settimana di settembre). Restituisce 52 o 53 settimane in forma compatta:
  `[{start_date, week_number, days: [{date, status, events: [{start_hour, end_hour, materia,
  status, is_recorded}]}]}]`, calcolate con la stessa logica di `get_week_view` (riusa
  `_resolve_dates`/`_resolve_day_events`, con una sola lettura di modelli, override e stati per
  tutto l'anno, non 52 chiamate separate). Aggiungi lo schema e rigenera `frontend/src/api/schema.d.ts`
  con lo strumento del repo.
- **Disposizione**: una sezione per mese (titolo "Ottobre 2026"), in una griglia
  `repeat(auto-fill, minmax(290px, 1fr))`. In ogni mese una riga per settimana: numero della
  settimana e cinque mini linee del giorno (lun–ven), alte 14 px.
- **Mini linea del giorno**: l'asse va dalla prima all'ultima ora dell'orario (fallback 8:00–19:00);
  ogni ora è un segmento del colore della materia (`getSubjectColor`):
  - settimane passate: colore pieno;
  - future: colore al 42% su bianco;
  - `annullata`: grigio;
  - `nonseguita`: bordo rosso interno di 1,5 px.
- Settimana corrente con bordo scuro; barretta ambra dove cambia l'orario (stessa regola della
  griglia). Nessuna leggenda, nessun totale di ore, nessuna nota testuale.
- Suggerimento su ogni riga: "Settimana 43 · 19–23 ott · 30,5 ore".
- **Selezione**: un clic seleziona la settimana (bordo verde); un secondo clic la deseleziona; doppio
  clic o Invio apre quella settimana nella vista settimana.

## 5. Copia e incolla dello stampo

Lo stampo è una settimana copiata negli **appunti interni di RT**: nessun archivio di stampi, nessun
pannello dedicato.

- **Appunti**: un piccolo store nel frontend (`components/calendar/weekClipboard.ts`) con
  `{ sourceStart, entries: [{ day_of_week, start_time, end_time, materia, docente }] }`, salvato
  anche in `sessionStorage` così resta passando tra viste e pagine nella stessa sessione. Le voci
  sono le ore effettive della settimana (modello più override, senza quelle tolte).
- **Dentro "Modifica orario"**: il gruppo della matita oggi, al passaggio del mouse, mostra le tre
  modalità di modifica. Aggiungi in testa al gruppo due icone: `Copy` "Copia lo stampo di questa
  settimana" e `ClipboardPaste` "Incolla lo stampo della settimana N" (disattivata, con il motivo
  nel suggerimento, se gli appunti sono vuoti o contengono questa stessa settimana).
  - **iPhone e touch**: oggi il gruppo è nascosto sul telefono (`!isPhone`). Mostra la matita anche
    sul telefono; un tocco apre il gruppo (stato `open`), un secondo tocco o un tocco fuori lo chiude.
    Usa la stessa logica su qualsiasi dispositivo senza hover (`(hover: none)`).
- **Incolla nella vista settimana**: sostituisce l'orario di **questa settimana sola**. Se la
  settimana ha già ore, un piccolo popup sotto l'icona: icona di avviso, "Questa settimana ha già un
  orario. Sostituirlo?", pulsanti "Annulla" e "Sostituisci".
- **Vista annuale**: lo stesso gruppo della matita nella barra contiene "Copia" (attiva con una sola
  settimana selezionata che ha ore), "Incolla" e "Seleziona più settimane". In modalità selezione il
  clic aggiunge o toglie settimane; "Incolla" le sostituisce tutte con lo stampo; se almeno una ha
  già ore, una finestra di conferma: "N settimane hanno già un orario. Sostituirlo?" con "Annulla" e
  "Sostituisci". La spunta (`Check` "Fatto") esce dalla selezione.
- **Backend atomico**: `POST /api/v1/calendar/paste` con `{ weeks: [lunedì...], entries: [...] }`.
  In una sola transazione, per ogni settimana: le ore effettive diventano override `removed` (per le
  voci del modello) o vengono cancellate (override `added`), poi le voci dello stampo diventano
  override `added` con le date di quella settimana. Le ore collegate a una lezione registrata o con
  uno stato diverso da `seguire` **non si tolgono** e restano accanto a quelle incollate: il conteggio
  della conferma le esclude. Restituisce le settimane cambiate. Il frontend invalida `calendarKeys.all`.
- Dopo copia e incolla, l'avviso a sola icona (`Copy`, `ClipboardCheck`).

## 6. Esporta e importa l'orario (Impostazioni › Materie)

- In cima alla sezione Materie una riga "Orario del calendario" con due `IconButton`: `Download`
  "Esporta l'orario" e `Upload` "Importa un orario". Nessuna descrizione.
- **Formato**: file JSON `rt-orario-AAAA-MM-GG.rtcal` (tipo `application/json`):
  `{ "format": "rt-calendar", "version": 1, "exported_at", "subjects": [{ "name", "teachers": [] }],
  "template": [{ day_of_week, start_time, end_time, materia, docente, valid_from, valid_to }],
  "overrides": [{ date, action, start_time, end_time, materia, docente, template_index? }] }`.
  Contiene tutto l'orario esistente (modello e override); **non** contiene stati, note, giorni
  segnati, collegamenti a lezioni o percorsi: è fatto per scambiarlo tra studenti.
- `GET /api/v1/calendar/export` lo restituisce con `Content-Disposition: attachment`.
- **Import**: `POST /api/v1/calendar/import` con `{ data, from?, to?, dry_run }`.
  - Validazione: `format`/`version`, al massimo 1 MB, date e orari con i validatori esistenti,
    al massimo 2000 voci; errore 422 con messaggio breve in italiano.
  - `dry_run: true` restituisce `{ subjects, entries, conflicts }`, dove `conflicts` è il numero di
    ore attuali che verrebbero sostituite nel periodo (o in tutto il calendario).
  - Senza periodo: sostituisce tutto l'orario (modelli e override). Con periodo `[from, to]`: le
    voci importate valgono solo lì (ritagliate su `valid_from/valid_to`); le voci attuali del modello
    nel periodo si spezzano come fa già `delete_template_entry(from, to)`; gli override nel periodo si
    cancellano. Stati e collegamenti alle lezioni restano dove l'ora esiste ancora.
  - Le materie mancanti si aggiungono all'elenco; i docenti si uniscono a quelli della materia
    (piano n. 9).
- **Finestra di import** (dopo la scelta del file con un `<input type="file" accept=".rtcal,.json">`
  nascosto): titolo "Importa orario", riga con nome del file e numero di materie, casella "Solo in un
  periodo" che mostra due campi data "Dal" e "Al". Se `conflicts > 0`: icona di avviso e
  "Sostituisce l'orario attuale" (con "dal … al …" se c'è il periodo), pulsante rosso "Sostituisci";
  altrimenti pulsante "Importa". "Annulla" sempre.

## Test

- Backend (`tests/test_calendar*.py`):
  - `year` restituisce 52/53 settimane e gli stessi eventi di `week` per una settimana a caso;
  - `paste` sostituisce, conserva le ore registrate ed è atomico in caso di errore;
  - `export` → `import` produce lo stesso orario;
  - `import` con periodo tocca solo il periodo;
  - `dry_run` conta i conflitti;
  - un file non valido dà 422.
- Frontend:
  - `WeekYearGrid` mette la settimana nel mese del giovedì, segna passate, corrente e cambi, e non ha
    leggenda;
  - "Vai alla settimana" naviga;
  - la vista annuale seleziona, copia, entra in selezione multipla, incolla e mostra la conferma
    quando serve;
  - nel gruppo della matita compaiono Copia e Incolla; su un dispositivo senza hover il tocco apre
    il gruppo;
  - l'import mostra l'avviso solo con conflitti.

## Nota per il changelog

"Calendario: vista annuale, Vai alla settimana, griglia delle settimane più leggibile, copia e
incolla dell'orario di una settimana anche su più settimane, esporta e importa l'orario dalle
Impostazioni."
