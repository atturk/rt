# Interfaccia futura: valutazione sul codice del 24 settembre 2026

## Risultato dell'analisi

La raccomandazione è una web UI locale in Gradio come primo incremento, mantenendo
la CLI e il backend Python. Docker va considerato una modalità opzionale successiva,
non il prerequisito della nuova interfaccia. Questo documento è una proposta;
nessuna migrazione funzionale a Gradio o Docker è stata implementata.

## Cosa mostra davvero il progetto

- `rt/tui/app.py::_run_cli` sospende Textual ed esegue i comandi interattivi.
  `_run_cli_quiet` e `command_output.py` gestiscono sottoprocessi con stdout/stderr.
  Il motivo esplicitato nel codice è anche l'isolamento degli event loop.
- `rt/tui/data.py` importa direttamente pipeline e modelli: la dashboard legge stato,
  costi e contenuti strutturati. Non è soltanto un terminale dentro un terminale.
- `issue_review.py`, `outline_review.py`, `configure.py`, `recall_session.py`
  contengono direttamente app Textual; `setup.py` contiene input e `sys.exit`.
  Esiste già `rt/core/`, ma non tutto il motore è indipendente dall'interfaccia.
- `rt/core/recall_stt.py` usa macparakeet; il ramo API solleva `NotImplementedError`.
  Cambiare contenitore non crea un'alternativa di trascrizione funzionante.
- Lezioni, manifest, decision ledger, checkpoint e contabilità sono già persistenti.
  Vanno riusati, senza sostituirli con lo stato temporaneo di una pagina web.

Non è necessario sostituire argparse con Typer per ottenere questa separazione.
I sottoprocessi sono legittimi per isolamento e cancellazione: il confine utile è un
protocollo strutturato (eventi/risultati), anziché usare testo console come API.
Anche una GUI Swift con backend Python potrebbe usare IPC; una GUI Qt non evita da
sola i problemi di stato, concorrenza o interattività del backend.

## Direzione emersa da storia e note locali

Il nucleo iniziale privilegia timestamp deterministici, provenienza, idempotenza e
revisione umana. Seguono routing LLM e configurazione per fase, integrazione Telegram,
active recall, contabilità e ripresa. Il Task 40 rimuove review-asr e rinomina la
review scientifica; i Task 64–68 sostituiscono input ANSI/Rich manuale con Textual.
Dal Task 82 la TUI evolve in dashboard; i Task 93–97 correggono diff, ricerca,
TOC e feedback dei comandi. Il Task 92 passa alle release senza Git lato utente.

La storia mostra una crescita incrementale del prodotto e molto costo nella gestione
delle interfacce interattive. Non dimostra che Textual sia intrinsecamente inadatto,
né che il progetto debba essere riscritto. Le decisioni utili del core restano valide.

## Gradio locale

Gradio Blocks offre componenti per audio, immagini, file, Markdown, eventi e code.
È adatto per validare il flusso: elenco lezioni → esecuzione fase → progresso →
review con audio e decisione → documento e costo. La UI gira nel browser; il server
Python può girare direttamente sul Mac, accedere ai file e usare macparakeet.
Non serve Docker per avere un'app web.

Limiti progettuali da verificare con un prototipo: editor/diff complesso, navigazione
molto personalizzata e app con molti utenti possono richiedere componenti custom o
un frontend dedicato. La queue Gradio non sostituisce un job runner persistente;
lo stato della sessione non sostituisce manifest e ledger. Chiusura pagina e restart
non devono perdere né approvare implicitamente una review.

Primo incremento proposto, ancora da realizzare:

1. Estrarre una sola fase non interattiva in un servizio condiviso da CLI e UI, con
   eventi tipizzati di avanzamento, errori e cancellazione. Preservare `force_mock`.
2. Modellare una richiesta di decisione separata dalla sua presentazione. Nessun
   input terminale o `sys.exit` nel servizio; nessuna approvazione implicita alla chiusura.
3. Collegare dashboard e un workflow verticale a Gradio Blocks. Una sola mutazione
   per lezione alla volta, con lock condiviso anche con CLI e daemon Telegram.
4. Persistenza nel modello attuale; rilettura dello stato quando si riapre il browser.
5. Default locale su loopback, senza link pubblico. Esporre solo gli artefatti
   necessari, mai tutta la radice contenente `.env`, configurazione e stato Telegram.

Criteri di accettazione: stessi output CLI/UI, progresso leggibile, annullamento
coerente, ripresa dopo chiusura, review non approvata per errore, nessuna duplicazione
di chiamate a pagamento e separazione dei dati tra sessioni.

## Docker

Docker uniforma un ambiente Linux e può includere Python, librerie e ffmpeg.
Non risolve automaticamente compatibilità dei binari macOS, accelerazione Apple,
permessi dei volumi o gestione dei percorsi. Docker Desktop esegue i container Linux
in una VM: l'attuale macparakeet nativo non si trasferisce lì come una dipendenza pip.
Il requisito riguarda anche la trascrizione delle risposte vocali Telegram.

Una distribuzione container completa richiede prima un backend STT supportato su
Linux, oppure un servizio host macOS esplicito. La seconda opzione introduce due
componenti da installare e coordinare: per l'utente Mac attuale può essere meno semplice.

Dopo il prototipo: immagine opzionale con runtime fissato, volumi separati per lezioni,
configurazione e stato, processi web/Telegram coordinati, checkpoint e arresto pulito.
La portabilità effettiva si misura con una matrice di test, non dalla presenza di un Dockerfile.

## Fonti

- [Gradio: gestione delle code](https://www.gradio.app/guides/queuing)
- [Gradio: streaming degli output](https://www.gradio.app/guides/streaming-outputs)
- [Gradio: stato delle interfacce](https://www.gradio.app/guides/interface-state)
- [Gradio: accesso ai file](https://www.gradio.app/guides/file-access)
- [Docker Desktop: VM Linux](https://docs.docker.com/desktop/features/vmm/)

Le osservazioni sul progetto derivano dalla lettura del codice e della storia Git;
la scelta Gradio-first è una valutazione progettuale, non un requisito delle librerie.
