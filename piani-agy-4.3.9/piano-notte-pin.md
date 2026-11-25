# Piano notte 2 — Pin per categoria nelle Lezioni

Branch: `agy/4.3.9-notte-pin`. Solo codice e test unitari, niente verifiche nell'app. Commit e push sul branch.
File principali: `frontend/src/routes/lessons.tsx`, `frontend/src/lib/lessonsPage.ts`,
`frontend/src/components/lessons/LessonsView.tsx` (+ test).

## Oggi
Il pulsante pin nell'intestazione salva l'intera vista (raggruppamento, ordine, ricerca, filtri) in
`usePreference('lessons.pinned')` e la riapplica all'avvio.

## Nuovo comportamento
Raggruppamenti con categorie: `data` (giorno), `mese` (vista "nascosta" ma vista a tutti gli effetti: funziona
anche lì), `materia`, `docente`. `nessuno` non ha categorie.

1. **Pin di categoria** (persistente): accanto al nome di ogni gruppo (`GroupHeader`), a sinistra del nome,
   un'icona pin. Visibile al passaggio del mouse (e sempre visibile sul gruppo fissato e sui dispositivi touch,
   `@media (hover: none)`). Click: fissa quella categoria per il raggruppamento corrente; un nuovo click la
   sgancia. **Una sola categoria fissata per raggruppamento**: fissarne un'altra nello stesso raggruppamento
   sostituisce la precedente. Salvataggio in `usePreference('lessons.pins')` come
   `{ data?: string, mese?: string, materia?: string, docente?: string }` (la `key` del gruppo).
   - Il gruppo fissato è sempre il primo dell'elenco, con l'icona pin piena colorata (verde/`text-primary`,
     come l'icona dell'intestazione nello screenshot 4). L'ordinamento resta interno ai gruppi.
   - Cambiando raggruppamento il pin di un altro raggruppamento non si vede ma resta salvato; tornando a quel
     raggruppamento riappare.
   - Ricerca/filtri: funzionano come oggi. Se il gruppo fissato non ha lezioni che corrispondono, non compare
     (resta salvato); cancellata la query torna in cima.
   - Una key salvata che non esiste più (es. docente rinominato) si ignora senza errori.
2. **Icona pin nell'intestazione** (quella vicino alla ricerca):
   - Se nel raggruppamento corrente c'è una categoria fissata: icona verde (attiva). Click = sgancia quella
     categoria (non fissa la ricerca). Dopo, l'icona torna normale.
   - Se non c'è una categoria fissata nel raggruppamento corrente: click = **fissa la ricerca** (query +
     filtri materia/stato attuali). Disabilitata se la ricerca è vuota e non ci sono filtri.
3. **Pin della ricerca** (trasversale, NON persistente): salvato in `sessionStorage` (`rt.lessons.searchPin`,
   letture/scritture in try/catch), quindi dura finché l'app (o la scheda) resta aperta.
   - Mentre è attivo, la query e i filtri fissati sono applicati in tutti i raggruppamenti, l'icona
     dell'intestazione è verde e i pin di categoria sono **nascosti in tutte le viste** (non cancellati:
     tornano quando il pin della ricerca viene tolto o alla prossima apertura dell'app). Le icone pin dei
     gruppi sono nascoste mentre il pin della ricerca è attivo.
   - Click sull'icona verde = toglie il pin della ricerca.
4. **Migrazione**: la vecchia preferenza `lessons.pinned` non si applica più; al primo avvio rimuovila
   (`setPref(undefined)` o equivalente) e togli il codice che riapplicava la vista all'avvio e che sganciava
   il pin cambiando vista (`sameView`, `pin/unpin` in `lessons.tsx` righe ~53-160) se non serve più.
5. Etichette accessibili: "Fissa in cima <nome>", "Togli <nome> dalla cima", "Fissa la ricerca",
   "Togli la ricerca fissata". Tooltip uguali.
6. Mobile (telefono): stessa logica; icona dei gruppi sempre visibile.

## Test (vitest)
Ordine dei gruppi con un pin; pin per raggruppamento indipendenti (giorno, docente, materia insieme);
cambio vista e ritorno; ricerca che esclude il gruppo fissato e lo ripristina; icona intestazione verde con
pin di categoria → click sgancia; pin ricerca nasconde i pin di categoria e li ripristina quando tolto;
sessionStorage che lancia eccezioni non rompe la pagina; migrazione di `lessons.pinned`.
Fine: `cd frontend && npx vitest run src/routes/lessons.test.tsx src/lib src/components/lessons && npx tsc --noEmit`.
Riga nel CHANGELOG della prossima beta.
