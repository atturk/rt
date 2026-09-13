# Task 54 — `rt -v` (versione) e `rt -u` (aggiornamento)

Indipendente dagli altri task attivi. Nel progetto RT (/Users/attilioturco/Desktop/trt),
implementa direttamente, senza produrre un piano preliminare.

## Obiettivo (esperienza utente, non negoziabile)

L'utente non deve mai vedere né scrivere un comando `git`. Deve vedere solo questo:

```
$ rt -v
RT versione 2.4.0 — sei aggiornato ✅
```
oppure, se online e con una versione più recente disponibile:
```
$ rt -v
RT versione 2.3.0 — è disponibile la versione 2.4.0
Esegui 'rt -u' per aggiornare
```
oppure, se offline/impossibile controllare:
```
$ rt -v
RT versione 2.3.0 (impossibile verificare aggiornamenti — controlla la connessione)
```

```
$ rt -u
Aggiornamento in corso...
✅ RT aggiornato: 2.3.0 → 2.4.0
```
oppure se già aggiornato:
```
$ rt -u
Sei già aggiornato all'ultima versione (2.4.0).
```

Sotto il cofano il meccanismo è basato su git (RT è un checkout git auto-contenuto, non un
pacchetto pip/pipx — decisione presa al Task 18, non cambiarla), ma questo è un dettaglio di
implementazione: l'utente non deve mai vedere parole come "git", "pull", "tag", "commit",
"describe" nei messaggi stampati a schermo.

## Schema di versione: tag git, non un file VERSION

Le versioni sono tag git standard sul branch `main`, formato `vMAJOR.MINOR.PATCH` (es. `v3.0.0`).
Non introdurre un file `VERSION` separato da tenere sincronizzato a mano: la fonte di verità è
il tag più recente raggiungibile da `HEAD`. La creazione dei tag stessi (quando e quale numero
usare) è una decisione umana presa al momento del rilascio, non fa parte di questo task — non
serve automatizzarla né chiedertelo, assumi semplicemente che uno o più tag `vX.Y.Z` esistano o
esisteranno sul repo.

## Modifica

### 1. `rt -v` / `rt --version`

In `rt/cli.py::main()` (riga 628), PRIMA di costruire il parser con `subparsers =
parser.add_subparsers(dest="command", required=True)` (riga 643) — che essendo `required=True`
rifiuterebbe un'invocazione con solo `-v`/`-u` e nessun sottocomando — intercetta questi due
flag leggendo direttamente `sys.argv[1:]`, PRIMA di qualunque parsing con `argparse`, e gestiscili
con una funzione dedicata che poi fa `sys.exit(0)` (o `1` in caso di errore), senza proseguire
oltre nella `main()` esistente.

Implementa in un nuovo modulo, es. `rt/core/version.py`:
- `get_current_version(project_root: str) -> str`: esegue (con `subprocess`, `cwd=project_root`
  — **non** la cwd del processo, l'utente può lanciare `rt -v` da qualunque cartella, es. da
  dentro una cartella lezione) `git describe --tags --abbrev=0`. Se non ci sono tag nel repo,
  ritorna un valore di fallback chiaro (es. `"sconosciuta"` o l'hash breve del commit corrente
  con una nota) — non sollevare un'eccezione che fa crashare `rt -v` su un repo senza tag.
- `get_latest_remote_version(project_root: str, timeout: float = 5.0) -> Optional[str]`:
  esegue `git ls-remote --tags origin` (NON un `git fetch` completo — più leggero e non tocca
  lo stato locale) con un timeout ragionevole, estrae i tag `vX.Y.Z`, li ordina come VERSIONI
  SEMANTICHE (X, Y, Z numerici, non ordinamento lessicografico — altrimenti "v2.10.0" finirebbe
  prima di "v2.9.0") e ritorna il più recente. Ritorna `None` (non solleva eccezioni) se il
  comando fallisce, va in timeout, o non c'è connessione — questi sono scenari attesi (utente
  offline), non errori.
- Funzione che confronta le due versioni (stessa logica di ordinamento semantico) e stampa uno
  dei tre messaggi mostrati sopra.

`get_current_version` funziona quindi anche offline (è puramente locale); solo il controllo di
"c'è una versione più recente" richiede rete, e deve degradare in modo pulito se non disponibile.

### 2. `rt -u` / `rt --update`

Stessa intercettazione precoce in `main()`. Nuova funzione, es. `run_update(project_root: str)`:

1. Verifica che non ci siano modifiche locali non committate su file TRACCIATI da git
   (`git status --porcelain`, `cwd=project_root` — ignora `config/`, che è gitignored e quindi
   non comparirà comunque). Se ce ne sono, stampa un messaggio chiaro (es. "⚠️ Ci sono modifiche
   locali non salvate nel codice, impossibile aggiornare in sicurezza.") e interrompi senza
   toccare nulla.
2. Verifica di essere sul branch `main` (`git rev-parse --abbrev-ref HEAD`); se non lo è, stampa
   un messaggio chiaro e interrompi (non cambiare branch automaticamente al posto dell'utente).
3. `git fetch origin` (`cwd=project_root`).
4. Confronta `HEAD` con `origin/main`: se già allineati, stampa "Sei già aggiornato
   all'ultima versione (<versione corrente>)." e fermati.
5. Se `origin/main` è avanti: esegui un fast-forward (`git merge --ff-only origin/main` o
   equivalente) — se fallisce perché la storia è divergente (scenario anomalo per questo repo,
   ma va gestito senza tentare un merge automatico), stampa un messaggio chiaro che consiglia di
   contattare chi mantiene il progetto, non un traceback grezzo.
6. Dopo l'aggiornamento dei file: re-installa le dipendenze
   (`<project_root>/.venv/bin/python3 -m pip install -r requirements.txt --quiet`, verifica il
   path esatto del venv in `bin/rt` — righe 12-13, `venv_dir = os.path.join(project_root,
   ".venv")`) — operazione idempotente e veloce se nulla è cambiato, va bene farla sempre dopo
   un aggiornamento riuscito.
7. Ricalcola la versione corrente (nuovo tag raggiungibile da `HEAD` dopo il pull) e stampa
   "✅ RT aggiornato: <vecchia> → <nuova>".

Tutti i comandi `git`/`pip` vanno eseguiti con `cwd=project_root` esplicito (stesso valore già
calcolato in `bin/rt`, righe 9-13: risali la cartella `bin/` per trovare la radice del progetto,
non affidarti alla cwd del processo).

### 3. Wiring in `rt -h`

Aggiungi una riga nell'help principale (`epilog_text` o la descrizione del parser, righe
631-640) che menziona `-v`/`--version` e `-u`/`--update` — oggi non compaiono da nessuna parte
nell'help perché non sono ancora sottocomandi/flag registrati.

## Test

- Test su `get_current_version`/`get_latest_remote_version` mockando `subprocess.run` per
  simulare: repo con tag, repo senza tag, comando `git` che fallisce/va in timeout (deve
  ritornare `None`/fallback pulito, mai un'eccezione non gestita).
- Test sull'ordinamento semantico delle versioni: verifica esplicitamente che `v2.10.0` sia
  considerato più recente di `v2.9.0` (non l'inverso, che accadrebbe con un ordinamento
  lessicografico ingenuo).
- Test su `run_update` che mocka ciascuno step (`git status --porcelain` con output non vuoto →
  interrompe con messaggio, senza chiamare `git fetch`; branch diverso da `main` → interrompe;
  già aggiornato → messaggio corretto, nessun `pip install` eseguito; aggiornamento riuscito →
  verifica che `pip install -r requirements.txt` venga invocato con l'eseguibile del venv
  corretto).
- Test che verifica che `rt -v`/`rt -u` funzionino come flag di primo livello (senza dover
  passare da un sottocomando), dato il vincolo `required=True` dei subparser esistenti — verifica
  che `rt` senza argomenti e senza `-v`/`-u` continui a comportarsi come oggi (mostra errore
  argparse per sottocomando mancante, non regredire questo comportamento).

Esegui `python3 -m pytest tests/ -q` e correggi finché l'intera suite passa.

## Vincoli

Verifica il bug di portabilità ricorrente sulle annotazioni `typing` per qualunque riga toccata
(vedi `.agents/00-README.md`).

Non introdurre un file `VERSION`. Non toccare la decisione "niente pip/pipx" del Task 18. Non
costruire un sistema di migrazione automatica della configurazione tra versioni: fuori scope,
non richiesto.

## Verifica finale

1. `python3 -m pytest tests/ -q`.
2. Test funzionale diretto: se il repo locale ha almeno un tag `vX.Y.Z` (creane uno di prova se
   serve, es. `git tag v0.0.1-test` su un commit qualunque, poi rimuovilo a fine test con `git
   tag -d`), verifica che `rt -v` mostri quella versione e — se hai accesso di rete al remote —
   il confronto con l'ultima disponibile. Verifica `rt -u` su un caso "già aggiornato" (nessun
   commit nuovo da tirare) e documenta se non è stato possibile testare il caso "aggiornamento
   reale disponibile" (richiederebbe due checkout a versioni diverse).
