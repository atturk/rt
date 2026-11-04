# Installazione

RT è disponibile come applicazione desktop per macOS e Windows. Essendo distribuita indipendentemente al di fuori degli store commerciali, al primo avvio il sistema operativo potrebbe richiedere una conferma esplicita per autorizzare l'esecuzione.

## macOS

Dopo aver scaricato il file `.dmg` e trascinato RT nella cartella **Applicazioni**:

1. Al primo avvio, se compare l'avviso che l'applicazione non può essere aperta perché lo sviluppatore non è verificato, apri **Impostazioni di Sistema → Privacy e sicurezza**.
2. Scorri verso il basso fino alla sezione **Sicurezza** e clicca su **Apri comunque** accanto al messaggio relativo a RT.
3. In alternativa, se usi il Terminale, puoi rimuovere l'attributo di quarantena con il comando:
   ```bash
   xattr -dr com.apple.quarantine /Applications/RT.app
   ```

## Windows

Dopo aver scaricato ed eseguito il programma di installazione:

1. Se compare la schermata blu di Windows SmartScreen ("PC protetto da Windows"), clicca sul collegamento **Ulteriori informazioni**.
2. Clicca quindi sul pulsante **Esegui comunque** per avviare l'installazione o l'applicazione.

## Aggiornamenti

RT controlla automaticamente la disponibilità di nuove versioni all'avvio. Prima di applicare qualsiasi aggiornamento, l'applicazione esegue un backup leggero di sicurezza dei tuoi dati.
