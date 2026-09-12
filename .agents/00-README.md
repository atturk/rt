# Task per Antigravity — consolidamento ingest/outline/review/recall

I file numerati in questa cartella sono già il piano di implementazione completo, pronto per
essere eseguito: NON produrre un tuo piano di implementazione separato prima di iniziare.
Leggi ogni file di task e implementa direttamente quanto descritto.

**Stato**: 01-18 sono già stati implementati, revisionati (con alcuni fix di hardening
applicati direttamente in revisione) e pushati in round precedenti — non rifarli, non toccare
quel codice se non indicato esplicitamente da un task attivo. Il lavoro corrente da eseguire è
**19-22**: 19 sostituisce MacWhisper con `macparakeet-cli` (gratuito) come motore ASR; 20-21-22
costruiscono insieme il nuovo comando `rt config` (wizard interattivo di configurazione guidata:
provider LLM, Telegram con discovery live di gruppo/topic, motore STT, pricing opzionale).

## Ordine di esecuzione

19 è indipendente e può essere eseguito in qualsiasi momento rispetto a 20-22 (non tocca lo
stesso codice, a parte il nome del motore STT di default che 22 legge da 19 se già completato).
20 → 21 → 22 vanno eseguiti IN ORDINE: 21 estende la funzione creata da 20, 22 estende quella
di 20+21 — non sono indipendenti tra loro.

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

Riferimento: piano approvato per i task 01-12 in
`/Users/attilioturco/.claude/plans/ok-adesso-vorrei-fare-reactive-spark.md`; piano approvato
per i task 13-17 (feature "add-images") in
`/Users/attilioturco/.claude/plans/discutiamo-prima-il-punto-flickering-chipmunk.md` (i task
18-22 non hanno un piano separato, sono autosufficienti — decisioni prese direttamente in chat:
RT resta un checkout git auto-contenuto niente packaging pip/pipx per il 18; sostituzione
MacWhisper→macparakeet-cli e design del wizard `rt config` con discovery live Telegram invece
del link-paste, per motivazioni spiegate nei task 19-22 stessi).

Quando tutti i task sono completati (o se ti sei fermato bloccato su un task), segnalalo in
chat con un riepilogo breve per task: file toccati, output dei test, e — importante — cosa
non hai fatto o non sei sicuro sia corretto. I commit separati e il diff completo verranno
revisionati e poi pushati.

## Nota su un bug di portabilità ricorrente nei giri precedenti

Più task nei round precedenti hanno usato `Optional[...]`/`List[...]` (e simili da `typing`)
come annotazione di tipo senza il corrispondente `from typing import ...` in cima al file.
Funziona per puro caso in questo ambiente (Python 3.14 valuta le annotazioni in modo differito
di default, PEP 649) ma darebbe `NameError` all'import su Python <3.14. Quando aggiungi o
modifichi una firma di funzione con un'annotazione da `typing`, verifica sempre che sia
importata esplicitamente in quel file — non dare per scontato che "i test passano" sia una
prova sufficiente, dato che i test girano nello stesso ambiente Python 3.14 che maschera il
problema.
