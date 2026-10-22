# Piano 7 · Lettura veloce: rumore con dissolvenza e timer

Agente: da assegnare all'avvio della b3. Richieste di Attilio (22/10/2026):
1. Il rumore di fondo entra ed esce con una dissolvenza di **1 secondo**.
2. Nelle impostazioni della lettura veloce, **sotto il rumore di fondo**, un timer attivabile con una
   durata scelta. Parte quando si avvia la lettura veloce; numeri con un'animazione semplice e carina.

## Dove

- `frontend/src/components/study/rsvpSound.ts`: `noise()` oggi sale in 0,3 s (`exponentialRampToValueAtTime`),
  `stopNoise()` ferma subito la sorgente.
- `frontend/src/components/study/SpeedReader.tsx`: effetto che avvia/ferma il rumore con
  `playing`; `SettingsPanel` con `Toggle "Rumore di fondo"`, `Segments` del tipo e lo slider del volume.
- `frontend/src/lib/studyPrefs.ts`: `RsvpPreference` e i valori predefiniti.

## 1 · Dissolvenza

- `FADE_S = 1`. In `noise()` la rampa di salita dura 1 s (da `0.0001` al volume; con volume 0
  nessuna rampa esponenziale verso 0: usare `linearRampToValueAtTime` o un minimo).
- `stopNoise({ fade = true })`: `cancelScheduledValues`, rampa a `0.0001` in 1 s partendo dal valore
  corrente (`setValueAtTime(gain.value, t)`), poi `source.stop(t + FADE_S)`. Sorgente e gain vecchi
  si staccano dopo lo stop; se nel frattempo riparte il rumore, si crea una sorgente nuova (le due
  si incrociano per un istante: va bene).
- Senza dissolvenza solo dove serve fermare all'istante: `close()`/smontaggio del componente.
  L'anteprima di 2 s delle impostazioni usa la dissolvenza in entrata e in uscita.
- Cambio del volume con lo slider: rampa breve (0,1 s) invece di un salto, così non scatta.
- Rispettare `prefers-reduced-motion`? No: è audio, la dissolvenza resta.

## 2 · Timer

Preferenze nuove in `RsvpPreference`: `timer: boolean` (predefinito `false`) e `timerMinutes: number`
(predefinito 25; 1–120).

Impostazioni (sotto il blocco del rumore, stesso stile): `Toggle "Timer"`; se acceso, la durata con
lo stesso tipo di controllo già usato per i valori numerici del pannello (es. slider con il valore
accanto, o − / +), in minuti. Niente testo descrittivo.

Comportamento (scelte da confermare con Attilio, ma da implementare così se non cambia idea):
- Parte con la prima riproduzione dopo l'apertura della lettura veloce; conta **solo mentre la
  lettura scorre** (in pausa si ferma) e si azzera chiudendo la lettura veloce.
- Mostrato in piccolo in un angolo alto dell'area di lettura (`mm:ss`, cifre tabulari), discreto, che
  non sposta la parola al centro; si nasconde in modalità zen solo se si nascondono gli altri
  controlli.
- Animazione: a ogni cambio la cifra che cambia scorre verso l'alto con dissolvenza (~250 ms,
  solo la cifra che cambia); disattivata con `prefers-reduced-motion`.
- A zero: la lettura va in pausa, il rumore si spegne con la dissolvenza, suona un rintocco breve con
  i suoni già presenti in `rsvpSound` (se i suoni sono attivi) e il timer pulsa due volte. Riprendendo
  la lettura il timer riparte dalla durata scelta.
- Cambiare la durata nelle impostazioni a timer in corso lo riporta alla nuova durata.

## Test

- Vitest su `rsvpSound` con un `AudioContext` finto: `noise()` programma una rampa di 1 s;
  `stopNoise()` programma la rampa di discesa e `stop(t + 1)`; senza dissolvenza `stop()` immediato.
- Vitest su `SpeedReader` con timer finti (`vi.useFakeTimers`): con `timer` spento nessun
  conto alla rovescia; acceso con 1 minuto conta solo in riproduzione, a zero mette in pausa;
  le preferenze nuove si salvano e si rileggono.
- E2e: attivare il timer nelle impostazioni, avviare la lettura, vedere il conto alla rovescia.
