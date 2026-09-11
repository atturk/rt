# Task 18 — `install.sh`: installazione automatica in un comando

Indipendente dagli altri task in questa cartella (non tocca codice Python, solo un nuovo
script shell + `README.md`).

Nel progetto RT (/Users/attilioturco/Desktop/trt), implementa direttamente, senza produrre un
piano preliminare.

## Contesto

RT oggi si installa con una sequenza manuale di passi (documentata in `README.md`): installare
ffmpeg/Python via Homebrew, clonare, creare un venv, `pip install -r requirements.txt`, copiare
`config.example/`→`config/` e `.env.example`→`.env`, rendere eseguibile `bin/rt`. Decisione
presa con l'utente: RT resta un **checkout git auto-contenuto** (codice + venv + config nella
stessa cartella clonata) — NON un pacchetto pip installabile globalmente — perché la cartella
delle lezioni (che cambia posizione ogni semestre, es. `.../ANNO 3/S1/_RT Lezioni`) è già oggi
un argomento posizionale indipendente da dove vive RT stesso, quindi non serve l'installazione
globale per gestirla. L'obiettivo di questo task è automatizzare la sequenza manuale in un unico
script `install.sh` da lanciare dopo il clone: `git clone ... && cd rt && ./install.sh`.

## Requisiti dello script (`install.sh`, nuovo file, root del repo)

Bash, target macOS (RT è già macOS-only per via di `afplay`/MacWhisper — non serve supporto
Linux/Windows). Deve essere **idempotente**: rilanciarlo una seconda volta non deve rompere né
duplicare nulla, e non deve MAI sovrascrivere una configurazione esistente dell'utente.

1. **Controllo prerequisiti di sistema**:
   - Verifica se `brew` è nel PATH. Se manca, stampa le istruzioni ufficiali per installare
     Homebrew (`https://brew.sh`) e **esci** (non lanciare tu stesso l'installer di Homebrew
     via `curl | bash` — è un'azione a livello di sistema che l'utente deve scegliere di
     eseguire esplicitamente, non qualcosa che uno script di progetto deve fare per conto suo).
   - Se `brew` è presente, installa (idempotente: `brew install` salta già se presente)
     `ffmpeg` e una versione recente di Python 3 (`python@3.13` o l'ultima disponibile — verifica
     prima se un `python3` di versione >= 3.10 è già raggiungibile nel PATH senza dover forzare
     brew a installarne un altro se non necessario). Chiedi interattivamente (`read -p`, default
     "no") se installare anche `micro` (editor consigliato ma opzionale — `rt/core/editor_edit.py`
     ha già un fallback funzionante a `nano` se `$EDITOR` non è impostata, quindi non è
     bloccante saltarlo).
   - Verifica la versione di Python effettivamente disponibile (`python3 --version` o
     `python3.13 --version` a seconda di cosa hai installato/trovato) e fallisci con un
     messaggio chiaro se risulta < 3.10 (RT ne ha bisogno — verificato in questa sessione: il
     codice usa `match`/`case`, sintassi 3.10+, nessuna sintassi più recente).

2. **Ambiente virtuale**: crea `.venv/` nella root del repo (già in `.gitignore`, verificato)
   SOLO se non esiste già (idempotente — se esiste, riusala senza ricrearla, magari con un
   messaggio "venv già presente, riuso"). Attiva il venv e fai
   `pip install --upgrade pip && pip install -r requirements.txt` (basta `requirements.txt`,
   non `requirements-dev.txt` — questo è un setup per l'uso, non per lo sviluppo/test).

3. **Configurazione**: copia `config.example/` → `config/` SOLO se `config/` non esiste già
   (mai sovrascrivere una configurazione esistente dell'utente — se esiste già, stampa un
   messaggio "config/ già presente, non toccata"). Stessa logica per `.env.example` → `.env`.

4. **Permessi ed eseguibilità**: `chmod +x bin/rt` (idempotente, non fa danni se già eseguibile).

5. **PATH**: NON modificare automaticamente `~/.zshrc`/`~/.bash_profile` dell'utente (è un file
   personale, una modifica automatica e silenziosa è invasiva). Stampa invece chiaramente la
   riga da aggiungere manualmente, con il percorso assoluto reale della cartella corrente:
   ```
   export PATH="$(pwd)/bin:$PATH"
   ```
   (calcola `$(pwd)` davvero al momento dell'esecuzione dello script, non un placeholder).

6. **Verifica finale**: esegui `./bin/rt -h` all'interno del venv appena creato/riusato e
   controlla che vada a buon fine (exit code 0) — se fallisce, lo script deve terminare con un
   messaggio d'errore chiaro invece di dichiarare successo.

7. **Riepilogo finale a schermo**, con Next Steps chiari e in ordine, es.:
   ```
   ✅ Installazione completata.

   Prossimi passi:
   1. Apri config/general.yaml e .env, inserisci le tue credenziali/API key
      (vedi docs/CONFIGURATION_REFERENCE.md per la sintassi).
   2. Per usare 'rt' da qualunque cartella, aggiungi questa riga al tuo ~/.zshrc:
        export PATH="<percorso_reale>/bin:$PATH"
   3. Verifica con: ./bin/rt -h
   4. Prova una pipeline di test senza costi con: ./bin/rt run <cartella_lezione> --mock
   ```

## Aggiornamento `README.md`

Nella sezione "Guida Rapida" → "1. Requisiti e Configurazione", presenta `./install.sh` come
il percorso PRINCIPALE/consigliato in cima (una singola code fence con
`git clone ... && cd rt && ./install.sh`), mantenendo i passi manuali esistenti SUBITO SOTTO
come alternativa esplicita per chi preferisce/deve installare a mano (non-macOS, controllo
granulare, debug) — non cancellare la documentazione manuale, è ancora corretta e utile come
riferimento e fallback.

## Test

Non è possibile scrivere un test pytest per uno script shell interattivo di sistema in questo
progetto (non c'è un precedente per testare script shell nella suite esistente — verificalo
con un grep, non inventare un framework di test shell da zero per questo task). Verifica invece
manualmente, e riporta l'esito testuale nel resoconto finale:
1. Esegui `./install.sh` da zero in una copia del repo in una cartella temporanea (es.
   `/tmp/rt-install-test/`, clona `git clone /Users/attilioturco/Desktop/trt /tmp/rt-install-test`
   per non toccare il repo di sviluppo reale) e verifica che completi senza errori.
2. Rilancialo una seconda volta sulla STESSA cartella e verifica che sia davvero idempotente
   (nessun errore, non ricrea/sovrascrive `config/`/`.env`/`.venv` già esistenti, lo segnala
   chiaramente a schermo).
3. Verifica che `config/`/`.env` prodotti da uno dei due run NON vengano mai sovrascritti se
   l'utente li ha nel frattempo modificati a mano (es. modifica un valore in
   `/tmp/rt-install-test/config/general.yaml` tra il primo e il secondo run, rilancia
   `install.sh`, verifica che la modifica sia ancora lì dopo).
4. Pulisci la cartella temporanea di test alla fine (non lasciare residui).

Esegui anche `python3 -m pytest tests/ -q` per assicurarti che questo task (che non tocca
codice Python) non abbia comunque introdotto regressioni.
