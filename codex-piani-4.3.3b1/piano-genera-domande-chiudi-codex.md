# Piano 5 · Genera domande: il popup si chiude e la generazione continua

Agente: **Codex**. Nello Studio, popup "Genera domande · <unità>": dopo Genera la X non fa niente
finché il job non finisce.

## Causa

`frontend/src/components/study/Study.tsx`, componente del popup (circa riga 1380):
`<Modal open={open} onClose={running ? () => undefined : onClose} …>`. Mentre il job gira la
chiusura è disattivata di proposito, perché l'aggiornamento dello Studio a fine job
(`invalidateQueries(recallKeys.all(lessonId))`) sta in un `useEffect` del popup stesso: chiudendolo
si perderebbe.

## Cosa fare

1. La X, Esc e il clic fuori chiudono sempre il popup. Il job `recall_generate` è già nella coda dei
   job e continua da solo; resta visibile nel pannello dei job come gli altri.
2. Il controllo di fine job si sposta fuori dal popup, in un punto che resta montato: il componente
   dello Studio che apre il popup tiene l'elenco dei job di generazione avviati
   (`pendingJobs: string[]`, il popup lo riceve con `onStarted(jobId)`). Un piccolo componente o hook
   per job (`useJobStatus`) quando il job finisce:
   - riuscito: `invalidateQueries(recallKeys.all(lessonId))`, toglie il job dall'elenco;
   - fallito: toast/avviso breve con l'errore del job (stesso stile degli altri avvisi dello Studio),
     toglie il job dall'elenco.
3. Popup ancora aperto a fine job: si chiude da solo come oggi (riuscito) o mostra l'errore (fallito).
4. Riaprendo il popup della stessa unità mentre la generazione gira: mostra lo stato "Genero le
   domande su 1.3…" con i campi disattivati (non far partire un secondo job per sbaglio).
5. Controlla `frontend/src/components/lesson/panels/QuestionsPanel.tsx` (pulsante "Generazione…" nel
   pannello Domande della lezione): se ha lo stesso blocco, stessa correzione.

## Test

vitest `Study`: con un job in corso la X chiude il popup; quando il job finisce le domande vengono
ricaricate anche a popup chiuso; un job fallito a popup chiuso mostra l'errore; riaprendo il popup
durante il job i campi sono disattivati.
