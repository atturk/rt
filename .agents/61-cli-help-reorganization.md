# Task 61 — Riorganizza `rt -h` in italiano, meno ridondante, con esempi

Indipendente dagli altri task attivi. Nel progetto RT (/Users/attilioturco/Desktop/trt),
implementa direttamente, senza produrre un piano preliminare.

## Contesto

`rt -h` oggi (`rt/cli.py`): la riga `usage:` elenca già tutti i sottocomandi, e subito sotto la
sezione "positional arguments" li rielenca con descrizione — ridondante. Tutto in inglese
("Academic Lecture Transcription & Reconstruction Workflow"). I comandi principali (config,
run, review, recall, status, telegram-daemon) sono mescolati con le sottofasi della pipeline
(setup, prepare, outline, rewrite, build, add-images) senza gerarchia visiva. I "Comandi
diagnostici" hanno "(uso avanzato)" tra parentesi nella descrizione.

## Modifica

Riscrivi l'help seguendo questa struttura (indicazioni precise dell'utente):

1. **Descrizione** in italiano: `"Workflow per Rielaborazione Trascritti e Active Recall"`
   invece di `"Academic Lecture Transcription & Reconstruction Workflow"`.
2. **Riga `usage:` compatta**, senza l'elenco esaustivo di tutti i sottocomandi (es. `rt
   <comando> [opzioni]` o simile) — evita la ridondanza con la lista sotto. Verifica come
   personalizzare `_format_usage` in `RTHelpFormatter` (già esistente, riga 602) per questo.
3. **Rinomina "positional arguments"** in **"Comandi principali"**, e mostra SOLO questi 6 in
   quella sezione, in quest'ordine: `config`, `run`, `review`, `recall`, `status`,
   `telegram-daemon` — con le descrizioni già esistenti (mantienile, sono già buone), tradotte
   in italiano se non lo sono già.
4. Sposta gli altri sottocomandi (`setup`, `prepare`, `outline`, `rewrite`, `build`,
   `add-images`) sotto una nuova intestazione breve, es. **"Fasi della pipeline"** (sono i passi
   individuali che compongono `rt run`) — verifica come ottenere una sezione separata con
   argparse: l'approccio più pulito è impostare `help=argparse.SUPPRESS` su questi
   sottocomandi (così `RTHelpFormatter`, che già filtra le action con help SUPPRESS, riga
   605-606, non li mostra nella sezione automatica) e aggiungerli manualmente in un blocco di
   testo nell'epilogo, con lo stesso stile/allineamento della sezione "Opzioni generali"
   esistente.
5. **Rimuovi "(uso avanzato)"** dalla descrizione dei comandi diagnostici — intestazione breve
   "Comandi diagnostici" senza parentesi, stesso trattamento del punto 4 (SUPPRESS +
   elencati manualmente nell'epilogo).
6. **"Opzioni generali"** resta come già implementato dal Task 54, nessuna modifica lì.
7. **Aggiungi una sezione "Esempi"** in fondo all'epilogo con 3-4 esempi reali, es.:
   ```
   Esempi:
     rt run lezione.m4a              Pipeline completa da un file audio
     rt run <cartella_lezione>       Riprende una lezione già iniziata
     rt review <cartella_lezione>    Critica scientifica indipendente
     rt recall <cartella_lezione>    Sessione di active recall da terminale
   ```
8. Evita descrizioni eccessivamente lunghe e qualunque testo tra parentesi nelle intestazioni
   di sezione — intestazioni brevi e dirette (es. "Comandi principali", "Fasi della pipeline",
   "Comandi diagnostici", "Opzioni generali", "Esempi").

I NOMI dei comandi (`config`, `run`, `setup`, ecc.) restano invariati in inglese/tecnico — sono
quello che l'utente digita, non vanno tradotti.

## Test

- Test che verifica che l'output di `rt -h` contenga l'intestazione "Comandi principali" con
  esattamente i 6 comandi nell'ordine specificato, e NON contenga più "positional arguments".
- Test che verifica che `setup`/`prepare`/`outline`/`rewrite`/`build`/`add-images` non
  compaiano più nella sezione "Comandi principali" ma in una sezione separata.
- Test che verifica l'assenza di "(uso avanzato)" nell'output.
- Test che verifica la presenza di una sezione "Esempi" con almeno 2 righe di esempio.
- Test che verifica che TUTTI i sottocomandi restino comunque funzionanti (nessuna regressione
  su `rt setup -h`, `rt validate-outline -h`, ecc. — SUPPRESS nasconde solo dalla lista
  riepilogativa, non disabilita il sottocomando).

Esegui `python3 -m pytest tests/ -q` e correggi finché l'intera suite passa.

## Vincoli

Verifica il bug di portabilità ricorrente sulle annotazioni `typing` per qualunque riga toccata
(vedi `.agents/00-README.md`).

Non cambiare il comportamento funzionale di alcun sottocomando: è un lavoro esclusivamente di
presentazione dell'help.

## Verifica finale

1. `python3 -m pytest tests/ -q`.
2. Lancia `rt -h` e verifica visivamente che l'output rispetti tutti i punti sopra.
