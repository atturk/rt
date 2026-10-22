# Piano 7 · Lettura veloce: rumore con dissolvenza e conto alla rovescia

Agente: **agy**. Richieste di Attilio (22/10/2026):
1. Il rumore di fondo entra ed esce con una dissolvenza di **1 secondo**.
2. Nelle impostazioni della lettura veloce, **sotto il rumore di fondo**, un **conto alla rovescia** di
   pochi secondi prima che le parole partano (non un timer di sessione tipo pomodoro), con numeri
   animati in modo semplice e carino.

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

## 2 · Conto alla rovescia prima della lettura

Preferenza nuova in `RsvpPreference`: `countdown: number`, secondi interi da **0 a 10**; **0 = spento**
(predefinito 3).

Impostazioni: sotto il blocco del rumore, una riga "Conto alla rovescia" con uno slider 0–10 e il
valore accanto (`Spento` a 0, altrimenti `3 s`). Niente testo descrittivo.

Comportamento (deciso da Attilio):
1. **Nuova unità → Play**: se `countdown > 0` parte il conto alla rovescia e **intanto parte il
   rumore di fondo** (con la sua dissolvenza); a fine conto inizia la lettura.
2. **Pausa e ripresa**:
   - ripresa entro **5 secondi** dalla pausa → nessun conto alla rovescia, si riparte subito;
   - ripresa dopo **più di 5 secondi** → il conto alla rovescia c'è di nuovo.
3. Durante il conto alla rovescia Play/Spazio lo mette in pausa come la lettura (e conta come pausa
   per la regola dei 5 secondi); frecce e cambio d'unità lo annullano. Chiudere la lettura veloce
   lo annulla.

Grafica: al posto della parola centrale, grande come la parola, il numero corrente (3, 2, 1). Ogni
numero entra scalando leggermente da 0,8 a 1 con dissolvenza ed esce svanendo (~300 ms), con un
anello sottile intorno che si svuota in quel secondo. Con `prefers-reduced-motion` solo il numero,
senza animazione. Nessun suono in più (il click della prima parola resta com'è).

Stato da tenere nel componente: `pausedAt` (ora della pausa) e "unità già avviata"; un cambio
d'unità azzera tutto, così la regola 1 vale per ogni unità nuova.

## Test

- Vitest su `rsvpSound` con un `AudioContext` finto: `noise()` programma una rampa di 1 s;
  `stopNoise()` programma la rampa di discesa e `stop(t + 1)`; senza dissolvenza `stop()` immediato.
- Vitest su `SpeedReader` con timer finti (`vi.useFakeTimers`): con `countdown` 0 la prima parola
  parte subito; con 3 compaiono 3, 2, 1 e poi la prima parola, e il rumore parte al Play (non dopo);
  pausa e ripresa dopo 4 s → niente conto; dopo 6 s → conto di nuovo; nuova unità → conto di nuovo;
  la preferenza si salva e si rilegge (0–10).
- E2e: impostare 2 s, Play, vedere il conto e poi la lettura.
