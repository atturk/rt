# Task 28 — `install.sh`: ristrutturazione UX (colori, log pulito, parallelismo, robustezza)

Indipendente dagli altri task. Nel progetto RT (/Users/attilioturco/Desktop/trt), implementa
direttamente, senza produrre un piano preliminare.

## Contesto

`install.sh` funziona correttamente (verificato con più installazioni reali su un MacBook Air
pulito durante questa sessione di test), ma l'output è quello di uno script grezzo: rumoroso
(ogni `brew install` stampa caveat, warning sui Command Line Tools, elenco bottle scaricate...),
senza colori, senza indicazione di avanzamento per fase, e completamente sequenziale anche dove
non serve (il download del modello Parakeet, ~100 secondi osservati, e la parte Python
venv+pip sono totalmente indipendenti tra loro ma oggi girano uno dopo l'altro). L'utente ha
chiesto esplicitamente un giro di rifinitura professionale su 4 assi: abbellire, nascondere il
rumore non essenziale, parallelizzare dove è sicuro, migliorare la robustezza generale.

**Nessuna modifica di comportamento/decisioni già prese va toccata**: nessun'installazione
automatica di Homebrew, nessuna sovrascrittura silenziosa di `config/`/`.env` esistenti,
`micro` si installa senza prompt (già così), idempotenza completa su ri-esecuzione. Questo task
è puramente sulla presentazione/velocità/robustezza dello script, non sulla sua logica di
"cosa installare quando".

## 1. Colori (coerenti con lo stile già usato nel resto del progetto)

Riusa la stessa palette ANSI già definita in `rt/pipeline/setup.py` (CYAN, GREEN, YELLOW, RED,
BOLD, RESET) invece di inventarne una nuova — stessa sensazione visiva tra CLI Python e
installer bash. Applica: verde per i successi (✅), giallo per gli avvisi (⚠️), rosso per gli
errori (❌), ciano/bold per le intestazioni di fase. Disabilita i colori automaticamente se
l'output non è un terminale (`[ -t 1 ]`), per non sporcare log/redirect.

## 2. Indicazione di avanzamento per fase

Sostituisci il flusso piatto di `echo` con un'intestazione per ciascuna delle grandi fasi
(NON per ogni singolo controllo interno, che resta idempotente/silenzioso se già soddisfatto —
l'utente deve percepire avanzamento tra blocchi larghi, non un contatore che salta se un
sotto-step viene saltato):
```
[1/5] Prerequisiti di sistema
[2/5] Download modello Parakeet (in background)
[3/5] Ambiente virtuale Python
[4/5] Configurazione
[5/5] Verifica finale
```
(adatta la numerazione se restructuri diversamente le fasi, l'importante è il concetto — poche
fasi larghe e sempre presenti, non un contatore per ogni `brew install`).

## 3. Log pulito: nascondere il rumore di `brew`/`pip`, non l'informazione

Crea `${REPO_DIR}/install.log` (nuovo, aggiungilo a `.gitignore` — non deve mai finire
versionato) e reindirizza lì l'output verboso di Homebrew (bottle scaricate, caveat, warning sui
Command Line Tools, elenco "New Formulae/Casks" se ricompare) e di `pip install`. Sul terminale
mostra solo una riga concisa per operazione, es. `🍺 Installazione di macparakeet-cli...` seguita
da `✅ macparakeet-cli installato.` (o `❌ ... fallita — vedi install.log per i dettagli.` in caso
di errore, con `exit 1` — mai fallire silenziosamente).

Fattorizza la logica ripetuta (oggi ci sono 4 punti quasi identici: `python@3.13`, `ffmpeg`,
`macparakeet-cli`, `micro`) in una funzione helper unica, es.:
```bash
brew_install_quiet() {
    local pkg="$1"
    echo "🍺 Installazione di ${pkg}..."
    if brew install "$pkg" >>"$LOG_FILE" 2>&1; then
        echo "✅ ${pkg} installato."
    else
        echo "❌ Installazione di ${pkg} fallita — vedi ${LOG_FILE} per i dettagli." >&2
        exit 1
    fi
}
```
(adatta nome/firma a piacere, l'importante è eliminare la duplicazione e garantire un
comportamento identico e loggato per tutti e 4 i casi d'uso).

**Non nascondere** invece: i messaggi che informano l'utente di cosa sta succedendo (già ben
scritti oggi), gli errori reali, e il progresso del download del modello (vedi punto 4 — quello
resta visibile, è l'unica barra di progresso reale che lo strumento offre).

## 4. Parallelismo sicuro: sovrapporre il download del modello alla parte Python

**Vincolo di sicurezza non negoziabile**: non lanciare mai due comandi `brew` (mutanti, es.
`brew install`) in parallelo tra loro — Homebrew non supporta invocazioni concorrenti e può
corrompere il proprio stato/lock. Il download del modello Parakeet (`macparakeet-cli models
download parakeet-v3`) **non è un comando brew**, è un sottoprocesso indipendente della CLI
macparakeet — può quindi girare in background in sicurezza mentre `brew install micro` e la
creazione del venv/`pip install` procedono in sequenza sul thread principale, dato che nessuna
di queste operazioni tocca lo stato di Homebrew in conflitto con l'altra.

Ristruttura così:
1. Appena `macparakeet-cli` è disponibile (già installato o appena installato), avvia il
   download del modello in background reindirizzando il suo output al log:
   ```bash
   macparakeet-cli models download parakeet-v3 >>"$LOG_FILE" 2>&1 &
   model_pid=$!
   ```
   **Attenzione**: oggi l'output del download (con le percentuali) viene mostrato DAL VIVO sul
   terminale — è l'unica vera barra di progresso disponibile e l'utente l'ha esplicitamente
   apprezzata durante i test. Non buttarla via reindirizzandola ciecamente al log: o (a) lascia
   che scriva sia su terminale che sul log con `tee -a "$LOG_FILE"` mantenendo l'output dal vivo,
   oppure (b) tienila reindirizzata al log MA stampa un heartbeat con tempo trascorso (pattern
   già presente nello script attuale, es. ogni 10s) mentre il job gira in background, così
   l'utente ha comunque un segnale di vita continuo anche se non vede le percentuali esatte
   finché non arriva al `wait` finale. Scegli l'opzione che preferisci circa a/b, ma non tornare
   al silenzio completo (`&>/dev/null`) che ha causato il problema originale.
2. **Mentre il download gira in background**, prosegui su thread principale con: installazione
   di `micro` (via `brew_install_quiet`), creazione/riuso del venv, `pip install`, copia
   `config.example/`→`config/` e `.env.example`→`.env`, `chmod +x bin/rt` — tutte operazioni
   indipendenti dal modello scaricato.
3. Solo prima della verifica finale, fai `wait "$model_pid"` (con lo stesso heartbeat/log già
   presente oggi se il job è ancora in corso a quel punto) e gestisci successo/fallimento come
   già fa lo script attuale (fallimento del download NON deve bloccare l'installazione — verrà
   ritentato alla prima trascrizione reale, comportamento già corretto oggi, mantienilo).

Verifica empiricamente (con un download reale, non mockato — es. cancellando prima il modello
con `macparakeet-cli models delete parakeet-v3 --force` come già fatto in questa sessione) che
il tempo totale dell'installazione end-to-end si riduca rispetto a prima (il download da solo
impiega ~100s osservati, la parte Python richiede un tempo comparabile — la sovrapposizione
dovrebbe portare un risparmio reale e misurabile, non solo teorico).

## 5. Robustezza: cleanup su interruzione

Aggiungi un `trap` che termina in modo pulito il job di download in background se lo script
viene interrotto (Ctrl+C) o esce per errore prima del `wait` finale, per non lasciare processi
orfani:
```bash
cleanup() {
    if [ -n "${model_pid:-}" ] && kill -0 "$model_pid" 2>/dev/null; then
        kill "$model_pid" 2>/dev/null
    fi
}
trap cleanup EXIT INT TERM
```
(adatta se la variabile o l'approccio cambia nella tua implementazione — l'importante è che
nessun processo macparakeet-cli resti a girare in background dopo che lo script stesso è
terminato per qualunque motivo).

## 6. Tempo totale di installazione nel riepilogo finale

Aggiungi `SECONDS=0` in cima allo script (builtin bash, conta i secondi trascorsi) e nel
riepilogo finale stampa qualcosa come `✅ Installazione completata in ${SECONDS}s.` — piccolo
tocco professionale, utile anche per misurare l'effetto del parallelismo introdotto al punto 4.

## Vincoli

- Nessuna modifica alle decisioni di prodotto già prese (elencate nel Contesto sopra).
- Lo script deve restare valido bash (`bash -n install.sh` senza errori) e conservare
  `set -euo pipefail` in testa.
- Aggiungi `install.log` a `.gitignore`.

## Test

Non esiste (e non va introdotta da zero per questo task, come già stabilito nel Task 18) una
suite automatizzata per script shell in questo progetto — verifica manualmente e riporta
l'esito testuale nel resoconto finale:
1. Installazione da zero in una copia temporanea del repo (es. `/tmp/rt-install-test/`, clonata
   da questo repo per non toccare il repo di sviluppo reale) con il modello Parakeet già
   cancellato (`macparakeet-cli models delete parakeet-v3 --force` prima di iniziare, così il
   download reale parte da zero e puoi verificare davvero la sovrapposizione col resto).
   Misura e riporta il tempo totale (`${SECONDS}s` stampato a fine script) confrontandolo
   idealmente con una stima di quanto impiegherebbe in sequenza pura (somma dei tempi delle fasi
   osservati separatamente).
2. Verifica che `install.log` contenga davvero l'output verboso di `brew`/`pip` (apri il file e
   controllane il contenuto) e che il terminale mostri invece solo le righe concise + le fasi
   `[N/5]` + i colori.
3. Interrompi lo script con Ctrl+C durante il download del modello (in background) e verifica
   che nessun processo `macparakeet-cli` resti a girare dopo (`ps aux | grep macparakeet-cli`
   dovrebbe non mostrare nulla di orfano).
4. Rilancia lo script una seconda volta sulla stessa cartella e verifica la piena idempotenza
   (nessuna riscrittura di `config/`/`.env`/`.venv` già presenti, come già garantito oggi).
5. Simula un fallimento del download del modello (es. disconnetti la rete per qualche secondo
   proprio in quella fase, o usa un id modello inesistente temporaneamente per il test) e
   verifica che lo script segnali chiaramente l'errore con puntatore al log, senza bloccare il
   resto dell'installazione.
6. Pulisci la cartella temporanea di test alla fine.

Esegui anche `python3 -m pytest tests/ -q` per assicurarti che questo task (che non tocca codice
Python) non abbia comunque introdotto regressioni.
