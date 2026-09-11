# Task per Antigravity — consolidamento ingest/outline/review/recall

I file numerati in questa cartella sono già il piano di implementazione completo, pronto per
essere eseguito: NON produrre un tuo piano di implementazione separato prima di iniziare.
Leggi ogni file di task e implementa direttamente quanto descritto.

**Stato**: 01-05 sono già stati implementati, revisionati e pushati in un round precedente —
non rifarli, non toccare quel codice se non indicato esplicitamente da uno dei task 06-10.
Il lavoro corrente da eseguire è **06 → 07 → 08 → 09 → 10**.

## Ordine di esecuzione

Esegui i task in ordine numerico sequenziale: **06 → 07 → 08 → 09 → 10**, nella stessa
sessione/working tree, uno alla volta (06 e 07 sono completamente indipendenti dal resto; 08 e
09 condividono `rt/pipeline/recall.py` su funzioni diverse — l'ordine numerico 08 prima di 09
evita qualunque necessità di merge; 10 è indipendente ma tocca file Telegram, va comunque bene
farlo per ultimo).

## Dopo OGNI task numerato (obbligatorio, non solo alla fine)

1. Esegui `python3 -m pytest tests/ -q`.
2. Se i test falliscono: diagnostica e correggi tu stesso il problema, e ripeti finché la
   suite passa — non fermarti solo perché un test fallisce al primo giro. Fermati a chiedere
   aiuto solo se dopo un paio di tentativi reali resti bloccato senza aver capito la causa.
3. Una volta che i test passano per QUESTO task: fai un `git commit` separato per QUEL task
   (messaggio tipo "Task 0N: <breve descrizione>"). **Non fare `git push`** in nessun caso —
   il push avverrà solo alla fine, dopo la revisione di tutti i task. Poi passa direttamente
   al task numerato successivo, senza fermarti a chiedere conferma.

Un commit per task completato e verificato permette di isolare subito quale task ha
introdotto un problema, invece di dover analizzare un diff enorme e indistinguibile a fine
lavoro — ma non serve fermarsi ad aspettare conferma tra un task e l'altro.

Riferimento: piano approvato in
`/Users/attilioturco/.claude/plans/ok-adesso-vorrei-fare-reactive-spark.md` (contesto
generale, i singoli file di task qui sono già autosufficienti per l'implementazione).

Quando tutti i task sono completati (o se ti sei fermato bloccato su un task), segnalalo in
chat con un riepilogo breve per task: file toccati, output dei test, e — importante — cosa
non hai fatto o non sei sicuro sia corretto. I 5 commit separati e il diff completo verranno
revisionati e poi pushati.
