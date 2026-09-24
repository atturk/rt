# Gestione del progetto e delle release

## Confini delle cartelle

Il checkout contiene `rt/` (pacchetto Python), `bin/` (launcher), `tests/`,
`config.example/`, `docs/`, `scripts/` e `.github/`. Il nome del checkout e quello
del pacchetto possono essere entrambi `rt`: non sono duplicati.

| Contenuto | Git | Archivio runtime | Backup personale |
| --- | --- | --- | --- |
| Codice, launcher, template, VERSION, dipendenze | Sì | Sì | Tramite Git |
| Test sintetici, CI, strumenti di manutenzione | Sì | No | Tramite Git |
| Documenti per sviluppatori | Sì | No | Tramite Git |
| `.env`, `config/`, `.rt_telegram/` | No | No | Sì |
| `.agents/`, `.agent/`, `.claude/` | No | No | Sì, se utili |
| Lezioni, registrazioni, output e fixture reali | No | No | Sì, fuori dal checkout |
| `.venv/`, cache, log ricreabili | No | No | Non necessario |

Gli esperimenti vanno fuori dal checkout oppure temporaneamente in `scratch/`,
ignorata da Git. Un test con nome `test_taskNN.py` non è obsoleto per il solo nome:
si elimina solo quando viene eliminato il comportamento coperto o quando una
copertura equivalente lo sostituisce. Non spostare il pacchetto in `src/` senza
aggiornare e testare launcher, configurazione e updater, che oggi dipendono dalla radice.

## Dipendenze e Python

Python minimo: 3.11. La matrice CI verifica 3.11, 3.12 e 3.14 su macOS e Linux.
Questo non rende disponibile la trascrizione nativa Mac su Linux.
`requirements.txt` descrive le dipendenze dirette; `constraints.txt` blocca le
versioni dirette e transitive del set verificato. I vincoli includono pytest, ma
non lo installano negli ambienti runtime: è richiesto solo da `requirements-dev.txt`.

Il set iniziale è quello dell'ambiente macOS/Python 3.14 del 24 settembre 2026.
Per aggiornare: risolvere in un ambiente pulito, aggiornare consapevolmente i vincoli,
eseguire `pip check`, la suite e la matrice CI, poi pubblicare una nuova versione.
Non rigenerare i vincoli da un ambiente con pacchetti estranei. I vincoli fissano
versioni, non gli hash di tutte le wheel: non sono un lock universale con verifica
crittografica dei pacchetti. Python e dipendenze Homebrew rimangono esterni.

Dopo aver spostato un checkout, ricreare `.venv/`: gli eseguibili contengono
percorsi assoluti. Non committare né distribuire il virtualenv.

## Aggiornamenti e dati

Usare Git nei checkout di sviluppo; `rt -u` li rifiuta prima di accedere alla rete.
Le installazioni da archivio usano `rt -u`. L'updater conserva `.env`, `config/`,
`.rt_telegram/` e note degli assistenti. La rimozione del codice obsoleto è limitata
alle directory possedute dalla distribuzione: `rt/`, `bin/`, `config.example/`, `docs/`.
Non salvare dati personali in queste directory. File sconosciuti alla radice e
altre cartelle vengono conservati; eventuali vecchi file alla radice si rimuovono
con una migrazione esplicita, non con una cancellazione generica.

Il backup delle lezioni deve includere sorgenti, `_state/`, decision ledger e
metadati: gli output sono ricreabili solo parzialmente e possono comportare costi API.
Il backup del repository non sostituisce quello dei dati ignorati da Git.

## Procedura di release

1. Eseguire `.venv/bin/python -m pytest tests/ -q` e `pip check`.
2. Aggiornare `VERSION` a `major.minor.patch` nello stesso commit della release.
3. Committare e verificare `python scripts/check_release.py --tag vX.Y.Z --output dist`.
   Il comando verifica **HEAD**, non modifiche non committate.
4. Pubblicare commit e un nuovo tag `vX.Y.Z`. Non riscrivere tag già distribuiti.
5. Il workflow riusa la matrice dei test; solo al successo verifica tag, VERSION,
   contenuti ed eseguibilità dell'archivio e crea la release con tarball e SHA256SUMS.
6. Fare uno smoke test dell'installazione in una cartella separata, senza credenziali
   reali o dati attivi. Gli archivi non includono test, note private e configurazioni utente.

Bootstrap e updater restano compatibili con gli archivi sorgente GitHub del tag.
Il tarball allegato è un artefatto controllato aggiuntivo, con checksum verificabile;
gli installer attuali **non verificano quel checksum**. Il workflow controlla lo
stesso contenuto prodotto da `git archive`, con le esclusioni di `.gitattributes`.

## Limiti ancora aperti

L'updater non è ancora una transazione completa: copia codice in place e il controllo
delle dipendenze dopo la copia non gestisce un rollback. Una futura evoluzione può
usare installazioni versionate e cambio atomico del percorso attivo. L'attuale lavoro
protegge i confini dei file senza riscrivere l'intero sistema di installazione.

Configurazione e stato sono ancora relativi all'installazione; spostarli in directory
utente standard richiede una migrazione dedicata. Non basta cambiare il nome di una
cartella. Anche un eventuale pacchetto wheel richiede prima di separare risorse,
configurazione e percorsi dal checkout. La scelta della licenza è del titolare: non
aggiungere automaticamente una licenza permissiva se non è stata decisa.
