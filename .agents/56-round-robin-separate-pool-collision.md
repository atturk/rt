# Task 56 — CRITICO: creare un pool round-robin "separato" può sovrascrivere silenziosamente le chiavi di un altro profilo già configurato

Indipendente dagli altri task attivi, priorità alta: rischio concreto di corruzione di
configurazione già usata in produzione. Nel progetto RT (/Users/attilioturco/Desktop/trt),
implementa direttamente, senza produrre un piano preliminare.

## Contesto

Verificato nel codice attuale (`rt/pipeline/configure.py`, dentro `_create_new_model_profile`,
righe ~290-343): quando l'utente ha già un profilo Google round-robin con N chiavi (es.
`google_1`...`google_3`) per la fase "rewrite", e vuole creare un SECONDO profilo Google
round-robin con un pool di chiavi **completamente separato e indipendente** per un'altra fase
(es. "review"), le 3 opzioni disponibili oggi (`➕ Aggiungi altre chiavi` / `🔄 Sostituisci tutte
le chiavi da zero` / `⏭ Mantieni le chiavi esistenti`) non coprono questo caso:

- **"Mantieni"**: riusa esattamente le stesse credenziali esistenti (nessun pool separato).
- **"Aggiungi"**: parte da `existing_creds` e AGGIUNGE le nuove — pool condiviso/esteso, non
  separato.
- **"Sostituisci da zero"**: azzera `collected_keys` ma la generazione dei nuovi identificatori
  (`google_1`, `google_2`, ... e i relativi `GOOGLE_API_KEY_1`, ...) **riparte da indice 1**,
  quindi COLLIDE con gli identificatori già usati dal primo profilo. Il blocco di scrittura
  (circa righe 406-422) fa match per `name`/`env_var` già esistenti e li **sovrascrive
  in-place** (sia in `general_data["credentials"]` sia il valore reale nel `.env` tramite
  `_update_env_file`). Risultato: il PRIMO profilo (che referenzia `google_1`/`google_2`/... per
  nome) si ritrova silenziosamente a puntare ai valori delle NUOVE chiavi appena inserite,
  rompendo il suo round-robin originale — senza alcun avviso, senza che l'utente se ne accorga
  finché non nota errori di autenticazione o comportamento anomalo sul primo profilo.

## Modifica

**Genera sempre identificatori di credenziale univoci a livello globale per provider**, non
solo rispetto a `existing_creds` (che è scoped al contesto del profilo che si sta modificando).
Prima di generare `cn`/`ce` per una nuova chiave (righe ~338-341), calcola l'indice di partenza
guardando TUTTE le credenziali già registrate per quel provider in
`general_data.get("credentials", [])` (non solo `existing_creds`), e parti dal primo indice
libero — es. se `google_1`...`google_3` sono già usati da qualunque profilo esistente, un nuovo
pool "da zero" deve iniziare da `google_4`, non da `google_1`.

Applica questo sia al ramo "Sostituisci tutte le chiavi da zero" sia — per coerenza — a
qualunque altro punto che genera nuovi identificatori di credenziale, per evitare la stessa
classe di collisione in futuro.

**Aggiungi un'opzione esplicita per il caso "pool separato"**, distinta dalle 3 esistenti, es.
`🆕 Crea un pool separato (nuove chiavi indipendenti, non condivise con altri profili)` — che
imposta `collected_keys = []` E usa la nuova logica di indice-libero-globale sopra, così il
comportamento è esplicito e distinguibile da "Sostituisci da zero" (che l'utente potrebbe
ragionevolmente intendere come "cambia le chiavi di QUESTO STESSO pool", non "creane uno
nuovo") — valuta se rinominare "Sostituisci da zero" in qualcosa come "🔄 Sostituisci le chiavi
di questo pool con altre nuove" per chiarire che è un'operazione diversa da "crea un pool
indipendente", dato che semanticamente sono due esigenze diverse dell'utente.

## Test

- Test di regressione diretto sul bug: crea un profilo A con 3 chiavi round-robin
  (`google_1..3`), poi crea un profilo B scegliendo "crea pool separato" (o "sostituisci da
  zero" se non introduci la nuova opzione, ma verifica che segua comunque la logica di indice
  libero) con 3 nuove chiavi — verifica che il profilo A in `general.yaml`/`.env` NON sia stato
  alterato (stessi nomi di credenziale, stessi valori nel `.env`), e che il profilo B usi
  identificatori diversi (`google_4..6`).
- Test che verifica che "Aggiungi altre chiavi" continui a funzionare come oggi (pool condiviso
  esteso, comportamento INVARIATO — non toccare questo ramo).
- Test che verifica il calcolo dell'indice libero quando le credenziali esistenti per un
  provider NON sono numerate in sequenza continua (es. `google_1`, `google_3` per qualche
  motivo — buco all'indice 2): verifica che il nuovo indice scelto sia comunque univoco (va bene
  sia riempire il buco sia continuare dopo il massimo, scegli l'approccio più semplice e
  documentalo).

Esegui `python3 -m pytest tests/ -q` e correggi finché l'intera suite passa.

## Vincoli

Verifica il bug di portabilità ricorrente sulle annotazioni `typing` per qualunque riga toccata
(vedi `.agents/00-README.md`).

Non toccare il comportamento di "Mantieni" e "Aggiungi": restano invariati, il problema riguarda
solo la generazione di NUOVI identificatori quando l'intento è un pool indipendente.

## Verifica finale

1. `python3 -m pytest tests/ -q`.
2. Test funzionale diretto: riproduci lo scenario esatto del bug (due profili Google
   round-robin per due fasi diverse, il secondo creato con l'opzione per pool separato) e
   verifica manualmente che entrambi i profili funzionino correttamente e in modo indipendente
   dopo il salvataggio.
