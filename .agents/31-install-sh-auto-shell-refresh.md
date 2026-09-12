# Task 31 — `install.sh`: rinfresco automatico della shell a fine installazione

Dipende dallo stato attuale di `install.sh` (Task 28-30 — leggi il file per intero prima di
procedere). Indipendente dagli altri task. Nel progetto RT (/Users/attilioturco/Desktop/trt),
implementa direttamente, senza produrre un piano preliminare.

## Contesto

Il Task 29 ha reso automatica l'aggiunta della riga PATH al profilo shell (`~/.zshrc` o
equivalente), ma il terminale IN CUI GIRA `install.sh` non la vede finché non si apre un nuovo
terminale o si esegue `source` a mano — una limitazione strutturale: un processo figlio (lo
script) non può modificare l'ambiente del processo padre (la shell interattiva dell'utente) che
lo ha lanciato. L'utente ha notato inoltre un'incoerenza nel riepilogo finale: il passo 1
("Esegui `./bin/rt config`") usa ancora il percorso relativo, anche se il passo 2 dichiara che
`rt` è già disponibile da ovunque.

**Soluzione verificata empiricamente in questa sessione** (con un test reale via
pseudo-terminale, non solo teoria): alla fine dello script, se l'esecuzione è interattiva,
sostituire il processo della shell corrente con una shell di login fresca dello stesso tipo
tramite `exec`. Verificato che: (a) la nuova shell legge davvero il profilo aggiornato (test con
un marcatore in un `.zshrc` di prova, confermato presente nella shell dopo l'`exec`); (b) `exec`
NON fa scattare il trap `EXIT` già presente nello script (verificato con un test dedicato) — non
c'è quindi conflitto con il cleanup del download in background già gestito prima di questo punto
del flusso; (c) tutto ciò che lo script ha già stampato prima dell'`exec` resta visibile nello
scrollback del terminale, la nuova shell si presenta subito dopo con un prompt pulito.

## Modifiche

### 1. Rinfresco automatico della shell, come ultimissimo passo dello script

Dopo l'intero riepilogo finale (dopo l'ultima riga di "Prossimi passi"), aggiungi:

```bash
if [ -t 0 ] && [ -t 1 ]; then
    exec_shell="${SHELL:-/bin/zsh}"
    echo ""
    echo "🔄 Aggiorno questa sessione di terminale (rt sarà subito disponibile)..."
    exec "$exec_shell" -l
fi
```

Esegui questo SOLO se lo script gira in un vero terminale interattivo sia in input sia in output
(`[ -t 0 ] && [ -t 1 ]`) — se `install.sh` viene lanciato in modo non interattivo (pipe, CI,
`install.sh < /dev/null`, output rediretto su file), **non fare l'`exec`**: lascerebbe un
processo interattivo sospeso senza terminale reale dietro, o comunque non ha senso in quel
contesto. In quel caso lo script deve terminare normalmente come fa oggi.

Usa lo stesso fallback già presente nella logica di rilevazione `SHELL_PROFILE` del Task 29 per
determinare quale shell eseguire (`$SHELL`, default `/bin/zsh` se non impostata) — non introdurre
una seconda logica di rilevazione separata, riusa quella coerenza.

### 2. Aggiorna il riepilogo "Prossimi passi" per riflettere che funzionerà davvero

Dato che dopo l'`exec` la sessione corrente avrà `rt` disponibile globalmente, sostituisci OGNI
riferimento a `./bin/rt` nel riepilogo finale con il comando bare `rt` (senza percorso relativo):
- "1. Esegui `./bin/rt config`" → "1. Esegui `rt config`"
- "3. Verifica con: `./bin/rt -h`" → "3. Verifica con: `rt -h`"
- "4. Prova una pipeline di test... `./bin/rt run <cartella_lezione> --mock`" → "4. ... `rt run
  <cartella_lezione> --mock`"

Aggiorna anche il testo del passo 2 (quello che oggi dice "apri un nuovo terminale o esegui
`source ~/.zshrc`") per riflettere che il rinfresco avviene automaticamente subito dopo, quindi
non serve più chiedere all'utente di farlo — es. "2. ✅ 'rt' è disponibile da qualunque cartella
(riga aggiunta a ~/.zshrc)." (rimuovi la parte su aprire un nuovo terminale/fare source, dato che
lo step 1 di questo task lo fa già in automatico subito dopo il riepilogo).

**Caso non interattivo**: se lo script termina SENZA fare l'`exec` (perché non interattivo),
mantieni invece il testo attuale che chiede esplicitamente di aprire un nuovo terminale o fare
`source` — in quel contesto è ancora l'informazione corretta, dato che il rinfresco automatico
non è avvenuto. Puoi determinare quale versione del riepilogo stampare controllando la stessa
condizione `[ -t 0 ] && [ -t 1 ]` usata al punto 1, PRIMA di decidere il testo (struttura logica
a tua discrezione, l'importante è che il messaggio stampato sia sempre coerente con cosa succede
davvero subito dopo).

## Vincoli

- Lo script deve restare valido bash (`bash -n install.sh`) e conservare `set -euo pipefail`.
- Non introdurre una seconda variabile/logica per determinare la shell dell'utente — riusa
  quella già presente dal Task 29 per `SHELL_PROFILE`.
- Non chiedere conferma prima di fare l'`exec` (coerente con le altre scelte automatiche già
  prese in questo script, es. l'installazione automatica di `micro` senza prompt).

## Test

Nessuna suite automatizzata per script shell in questo progetto — verifica manualmente in una
copia temporanea del repo e riporta l'esito nel resoconto finale:
1. Esegui `./install.sh` da un vero terminale interattivo: verifica che al termine appaia il
   messaggio di rinfresco e che la shell venga davvero sostituita (es. controlla che `echo $$`
   prima e dopo mostri un PID diverso, o più semplicemente che digitando `rt -h` subito dopo,
   senza aprire nulla di nuovo, funzioni immediatamente).
2. Verifica che il riepilogo finale stampato usi `rt` (non `./bin/rt`) in tutti i punti elencati
   sopra, nel caso interattivo.
3. Esegui lo script in modo non interattivo (es. `./install.sh < /dev/null` o rediretto su file)
   e verifica che NON tenti alcun `exec`, termini normalmente, e stampi la versione del
   riepilogo che invita ancora ad aprire un nuovo terminale/fare `source` a mano.
4. Verifica che il download del modello in background (se `INSTALL_PARAKEET=true`) sia già
   completato e ripulito correttamente PRIMA che si arrivi a questo punto finale (comportamento
   già garantito dalle fasi precedenti — conferma solo che l'aggiunta di questo task non cambi
   nulla lì).
5. Esegui `python3 -m pytest tests/ -q` per assicurarti che questo task (che non tocca codice
   della pipeline RT) non abbia comunque introdotto regressioni.
6. Pulisci ogni cartella/file temporaneo di test alla fine.
