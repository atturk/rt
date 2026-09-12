# Task 30 — `install.sh`: prompt Apple Silicon/STT con `questionary` invece di `read`

Dipende dallo stato attuale di `install.sh` (Task 28-29 già completati — leggi il file per
intero prima di procedere). Indipendente dagli altri task. Nel progetto RT
(/Users/attilioturco/Desktop/trt), implementa direttamente, senza produrre un piano preliminare.

## Contesto

Il prompt attuale per decidere se installare `macparakeet-cli`/Parakeet (introdotto nel Task 29)
usa un semplice `read -rp "...[S/n] "`. L'utente vuole lo stesso stile di `questionary` già usato
ovunque in `rt config` (`rt/pipeline/configure.py`) — un menu con frecce, non testo grezzo.

**Vincolo tecnico da rispettare**: questo prompt avviene OGGI nella fase `[1/5]`, PRIMA che il
venv Python esista (`.venv` viene creato solo nella fase `[3/5]`) — `questionary` non è quindi
ancora installato al momento in cui serve. Per non perdere il parallelismo introdotto nel Task 28
(il download del modello, ~100s osservati, sovrapposto alla creazione venv + `pip install -r
requirements.txt`), **non spostare l'intera fase venv prima del prompt**: crea invece un piccolo
bootstrap anticipato che installa SOLO `questionary` (pacchetto piccolo e veloce), fai la domanda
con quello, poi prosegui esattamente come oggi — la fase `[3/5]` esistente continuerà a fare
`pip install -r requirements.txt` sul venv già creato (che includerà di nuovo `questionary` nella
lista, operazione istantanea perché già soddisfatta) mentre il download gira ancora in
background, esattamente come oggi.

## Modifiche

### 1. Bootstrap anticipato del venv (subito dopo aver trovato `PYTHON_BIN`, prima del blocco
   di rilevazione architettura/domanda)

```bash
VENV_DIR="${REPO_DIR}/.venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "⚙️ Creazione dell'ambiente virtuale .venv..."
    "$PYTHON_BIN" -m venv "$VENV_DIR" >>"$LOG_FILE" 2>&1
fi
"${VENV_DIR}/bin/pip" install --quiet questionary >>"$LOG_FILE" 2>&1
```
(sposta qui la dichiarazione di `VENV_DIR` se oggi è dichiarata più avanti nella fase `[3/5]` —
deve restare la STESSA variabile, non crearne una seconda. La fase `[3/5]` esistente, quando ci
arriva più avanti nello script, troverà `.venv` già presente e stamperà correttamente "venv già
presente, riuso" come già fa oggi per il caso idempotente — nessuna modifica lì necessaria oltre
a verificare che non si rompa nulla con questo riordino).

Se questo bootstrap fallisce per qualunque motivo (raro, es. problema di rete durante
`pip install questionary`), non bloccare l'intera installazione: cattura l'errore e ricadi sul
prompt testuale `read -rp` esistente come fallback (vedi punto 2), stampando un avviso breve tipo
"⚠️ Prompt interattivo avanzato non disponibile, uso il prompt testuale semplice."

### 2. Il prompt vero e proprio, con fallback

Sostituisci il blocco `read -rp "...[S/n]"` (introdotto nel Task 29) con un'invocazione di
`questionary.select` tramite il Python del venv appena bootstrappato. **Attenzione a
un'insidia tecnica reale**: passare il codice Python via heredoc su stdin
(`"${VENV_DIR}/bin/python" - <<'PYEOF' ... PYEOF`) CONSUMA lo stdin dello script Python per
leggere il codice sorgente stesso, lasciando `questionary` senza stdin libero per l'input
interattivo dell'utente — il prompt non riceverebbe mai la risposta. Scrivi invece il codice
Python in un file temporaneo ed eseguilo passando il PERCORSO come argomento (stdin resta
collegato al terminale reale):

```bash
ask_stt_choice() {
    local script
    script="$(mktemp "${TMPDIR:-/tmp}/rt_install_ask.XXXXXX.py")"
    cat > "$script" <<'PYEOF'
import questionary

RECOMMENDED = "🎙️  Sì, installa macparakeet-cli e Parakeet v3 (consigliato: gratuito, locale, veloce su Apple Silicon)"
ALTERNATIVE = "🔧 No, configurerò un motore ASR alternativo"

answer = questionary.select(
    "Motore ASR per la trascrizione delle lezioni:",
    choices=[RECOMMENDED, ALTERNATIVE],
    default=RECOMMENDED,
).ask()

print("yes" if answer == RECOMMENDED else "no")
PYEOF
    local result
    result="$("${VENV_DIR}/bin/python" "$script" | tail -n 1)"
    rm -f "$script"
    echo "$result"
}
```
(usa `tail -n 1` sull'output catturato: se in futuro `questionary`/`prompt_toolkit` dovessero
scrivere qualcosa anche su stdout oltre alla riga esplicita stampata da `print(...)`, prendi
comunque solo l'ultima riga, quella che stampiamo noi esplicitamente).

Nel punto in cui oggi c'è il blocco `read -rp`, sostituiscilo con:
```bash
if [ "$IS_APPLE_SILICON" = true ]; then
    if [ ! -t 0 ]; then
        INSTALL_PARAKEET=true
    else
        choice="$(ask_stt_choice 2>>"$LOG_FILE")"
        if [ "$choice" = "no" ]; then
            INSTALL_PARAKEET=false
        else
            INSTALL_PARAKEET=true
        fi
    fi
else
    INSTALL_PARAKEET=false
fi
```
(se `ask_stt_choice` fallisce/produce output vuoto per qualunque motivo — es. il bootstrap di
`questionary` al punto 1 è fallito — ricadi sul vecchio prompt testuale `read -rp "...[S/n] "`
invece di trattarlo come "no" implicito: un fallimento del prompt bello non deve mai tradursi
silenziosamente in "non installare Parakeet" senza che l'utente abbia scelto consapevolmente).

## Vincoli

- Mantieni intatta la logica di rilevazione `IS_APPLE_SILICON` (via `sysctl -n
  hw.optional.arm64`) e il comportamento non interattivo (default "sì" via `[ ! -t 0 ]`) già
  presenti dal Task 29 — questo task cambia SOLO come viene posta la domanda in modalità
  interattiva, non la logica di decisione attorno ad essa.
- Non duplicare la dichiarazione/creazione di `VENV_DIR`/`.venv` — un solo punto nello script
  deve deciderne l'esistenza e crearla se assente, riusato sia dal bootstrap anticipato sia dalla
  fase `[3/5]` esistente.
- Lo script deve restare valido bash (`bash -n install.sh`) e conservare `set -euo pipefail`.
- Verifica il bug di portabilità ricorrente sulle annotazioni `typing` non si applica qui (codice
  bash e un piccolo script Python standalone senza tipizzazione) — nessuna azione necessaria su
  questo punto specifico.

## Test

Nessuna suite automatizzata per script shell in questo progetto (come già per i task 28-29) —
verifica manualmente in una copia temporanea del repo e riporta l'esito nel resoconto finale:
1. Installazione da zero: verifica che il menu `questionary` compaia correttamente (frecce/
   evidenziazione, non testo grezzo `[S/n]`), che scegliendo l'opzione consigliata
   `INSTALL_PARAKEET` risulti vero e il flusso prosegua come nel Task 29, e che scegliendo
   l'alternativa venga saltata sia l'installazione di macparakeet-cli sia il download.
2. Verifica che il parallelismo introdotto dal Task 28 sia ancora effettivo: misura il tempo
   totale (`${SECONDS}s` nel riepilogo finale) e conferma che sia comparabile a quello osservato
   nei test del Task 28/29 (non un ritorno al tempo sommato in sequenza pura).
3. Simula il fallimento del bootstrap `questionary` (es. temporaneamente rinomina/rendi
   irraggiungibile l'indice PyPI per quella singola chiamata, o testa con una rete disconnessa
   per quel passo) e verifica il fallback corretto al prompt testuale `read -rp`, non un "no"
   silenzioso.
4. Verifica il comportamento non interattivo (`install.sh < /dev/null`): deve continuare a
   applicare il default "sì" senza mai provare a invocare il prompt `questionary` (che
   bloccherebbe senza terminale).
5. Esegui `python3 -m pytest tests/ -q` per assicurarti che questo task (che non tocca codice
   della pipeline RT) non abbia comunque introdotto regressioni.
6. Pulisci ogni cartella/file temporaneo di test alla fine (incluso ogni `/tmp/rt_install_ask.*`
   residuo in caso di interruzione a metà test).
