# Fonti e materiali

Le fonti sono i documenti didattici associati alla lezione che arricchiscono il testo rielaborato e consentono la verifica automatica dei contenuti.

## Tipi di fonte

Puoi aggiungere diverse tipologie di documenti dal pannello **Dettagli → Fonti**:
- **Slide e dispense (materiale)**: presentazioni PDF o documenti ufficiali distribuiti dal docente.
- **Appunti dello studente**: appunti presi a mano o note digitali.
- **Audio e registrazioni**: tracce audio registrate durante la lezione.

Durante l'importazione di PDF, RT estrae il testo e, se richiesto, le immagini e gli schemi per inserirli direttamente nelle unità di studio pertinenti.

## Presentazioni (.pptx)

Per mostrare le slide delle presentazioni `.pptx` come immagini, RT usa i convertitori nell'ordine seguente:

1. **Microsoft PowerPoint** (su Windows) o **Keynote** (su macOS), se installati e autorizzati.
2. **LibreOffice**: se hai scaricato il componente **Convertitore delle presentazioni** in **Impostazioni → Lavorazione delle lezioni → Componenti** (~300 MB), RT usa quello con un profilo dedicato (ha la precedenza); altrimenti usa l'eventuale **LibreOffice** già installato sul computer.
3. Senza nessun convertitore disponibile, alla prima presentazione `.pptx` elaborata RT avvia in background il download del componente **Convertitore delle presentazioni** e intanto importa subito testo e immagini delle slide, senza bloccare la lezione.

> [!NOTE]
> Su macOS, se Keynote non risponde o non ha il permesso di **Automazione** in **Impostazioni di Sistema → Privacy e sicurezza → Automazione**, RT passa automaticamente a LibreOffice (o scarica il componente se manca).

## Affidabilità

A ogni fonte viene assegnato un livello di affidabilità che guida l'algoritmo di verifica e conciliazione:
- **Alta**: materiali ufficiali del docente, testi d'esame e slide. RT dà la precedenza assoluta a queste fonti in caso di discordanza con le parole pronunciate, a meno di errori palesi.
- **Normale**: materiale standard di supporto, approfondimenti o bibliografia consigliata.
- **Bassa**: appunti personali o riassunti di terzi. RT consulta queste fonti con cautela: possono contenere refusi o interpretazioni errate e non vengono usate da sole per convalidare le definizioni ufficiali del corso.

Puoi modificare il livello di affidabilità di ogni documento in qualunque momento cliccando sulla relativa icona nel pannello **Fonti**.
