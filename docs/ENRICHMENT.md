# Arricchimento

La pagina `/arricchimento` sostituisce Immagini. I vecchi URL restano utilizzabili. Nella pagina si possono avviare analisi per una lezione o un gruppo di lezioni filtrate e raggruppate. Le lezioni senza rielaborazione pronta vengono saltate. La schermata Lezioni non contiene nuovi comandi di analisi.

## Immagini delle lezioni

PDF, foto e immagini cercate sul web conservano il flusso di acquisizione e descrizione Vision. Il posizionamento usa ora la Decision API: **una descrizione d'immagine per richiesta**, insieme al testo completo della lezione, suddiviso nelle macro unità. Le etichette `macro_0`, `macro_1`, ecc. sono associate deterministicamente agli ID delle macro unità; `none` lascia l'immagine non assegnata. Più immagini possono ricevere la stessa etichetta. La cache si invalida quando cambiano descrizione, testo o modello.

Il testo usato include correzioni approvate e modifiche manuali. Non viene troncato: una lezione oltre il contesto del modello produce un errore visibile, da risolvere scegliendo un modello decisionale con contesto maggiore. Sono supportate fino a 254 macro unità più `none`. La ricerca web può ancora essere selezionata per subunità: la destinazione finale dell'immagine è una macro unità.

## Idee e generazione

Jev valuta separatamente l'utilità di una **visualizzazione** e di un'**infografica**, usando una sola subunità alla volta. Sono possibili entrambi i tipi o nessuno. L'arricchitore prepara titolo, descrizione e prompt strutturati. La modalità statica o interattiva della visualizzazione è scelta dall'arricchitore; può essere modificata dall'utente.

La soglia iniziale di utilità è `0.65`, configurabile. Il QC sulla matrice ha restituito `0.69` per la visualizzazione e `0.46` per l'infografica; questo è un primo riferimento, non una calibrazione statistica. Il tetto globale può essere proporzionale al numero di subunità (default), un numero fisso, oppure disattivato. Ogni lezione può ereditare o sostituire la scelta. Un tetto è sempre un massimo, mai una quantità da raggiungere. I contenuti manuali non sono soggetti al tetto dei suggerimenti.

Per default l'analisi si avvia dalla pagina Arricchimento. Con **Impostazioni → Arricchimento → Analizza anche nella pipeline** (`enrichment.automatic: true`) la pipeline analizza il testo prima del documento, anche dopo rielaborazione/revisione eseguite separatamente. Se i modelli non sono configurati, l'analisi viene saltata con un avviso; se fallisce, la produzione del documento può proseguire. Si possono rilanciare le analisi dalla pagina Arricchimento. Le valutazioni già completate sono in cache; testi cambiati vengono riconsiderati. Idee ignorate, prompt modificati e contenuti generati vengono conservati.

Nell'anteprima le idee compaiono sotto il testo della subunità:

- **Aggiungi** accoda la generazione e mostra subito un frame in caricamento.
- **Modifica** apre il form della lezione con tipo, subunità e prompt precompilati.
- **×** nasconde l'idea nell'anteprima; si recupera mostrando le idee ignorate nella pagina della lezione.

La pagina della lezione consente anche la generazione manuale, la rigenerazione e l'eliminazione dei risultati. Una rigenerazione conserva il risultato precedente fino al successo. I job interrotti possono essere riprovati. Se cambia la fonte, il contenuto precedente resta disponibile con un avviso. L'analisi non genera mai elementi grafici.

## Modelli e browser

In **Impostazioni → Modelli** configurare:

| Ruolo | API | Funzione |
|---|---|---|
| Descrizione immagine | Chat con Vision | Descrive immagini importate |
| Classificatore di arricchimento | Decision API | Macro unità e utilità delle idee |
| Arricchitore | Chat con JSON | Titolo, descrizione, prompt, modalità |
| Visualizzazioni HTML | Chat con JSON | HTML/SVG/canvas/JavaScript autonomi |
| Generazione infografiche | Images API | Immagine raster |

Il generatore di infografiche supporta OpenRouter `/api/v1/images` e connessioni OpenAI-compatible `/images/generations` che restituiscono `b64_json`. Non usa i modelli Vision per generare immagini. Il modello deve supportare output immagine e l'endpoint scelto.

Le visualizzazioni riprendono l'approccio del [plugin inline-visualizer-v2](https://github.com/Classic298/open-webui-plugins/tree/main/inline-visualizer-v2), senza dipendere da OpenWebUI né copiarne il runtime di estrazione del DOM. HTML, SVG, canvas e JavaScript nativi consentono grafici, matrici, diagrammi e simulazioni. Non è una copia di tutte le librerie e integrazioni del plugin: non carica Chart.js/D3/Plotly da CDN. I risultati sono autonomi, con CSP che blocca la rete e un iframe `sandbox="allow-scripts"` senza accesso same-origin. Il frame comunica solo la propria altezza tramite un messaggio validato per sorgente e dimensioni, così il documento si adatta allo spazio occupato dal risultato.

Per le catture statiche serve Chromium:

```sh
python -m playwright install chromium
```

L'installer tenta l'installazione; Docker include Chromium. Si può usare un browser già installato tramite `RT_ENRICHMENT_CHROMIUM=/percorso/al/browser`. I job delle visualizzazioni falliscono con un errore recuperabile se il browser manca. Il modello è chiamato solo dopo un comando esplicito di generazione.

## Documento ed esportazione

Le idee non entrano nel Markdown. Gli asset pubblicati sono aggiunti dopo la subunità, con marcatori riservati. L'editor li esclude dal testo canonico: modificare un documento non reinserisce gli elementi nella fonte dei generatori. Solo il manifesto degli asset pubblicati modifica l'impronta del documento; analizzare o ignorare idee non richiede un nuovo build.

L'export ZIP include il PNG statico e il file HTML autonomo collegato dal Markdown. In-app le visualizzazioni interattive vengono mostrate nel frame. La revisione delle incoerenze tra subunità non fa parte di questo intervento.

## Verifiche

Test offline mirati:

```sh
python -m pytest tests/test_enrichment.py tests/test_api_enrichment.py -q
npm test --prefix frontend -- src/components/lesson/Enrichment.test.tsx
```

I test reali sono separati e disabilitati per default:

```sh
RT_RUN_LIVE_ENRICHMENT=1 OPENROUTER_API_KEY=... \
  python -m pytest tests/test_enrichment_live.py -q
```

La suite usa esclusivamente `openai/gpt-6-luna` (2 richieste), `inclusionai/ming-image-0.1-design` (1) e `typesafe/jev-1.13` (2). Un controllo sul trasporto impedisce retry o modelli diversi. Le credenziali vengono dall'ambiente e non sono incluse negli artefatti. Gli output del QC reale su estratti delle lezioni allegate sono conservati separatamente e non pubblicati nel repository. Le fixture pubbliche sono esempi sintetici.
