# Piano 17 · Microfono nell'app e "Controlla permessi"

## Il problema

Nell'app (RT.app, finestra pywebview) "Registra" è grigio e RT non compare in Impostazioni di
Sistema › Privacy › Microfono: il permesso non è mai stato chiesto.

Cause trovate (pywebview 6.2.1, `webview/platforms/cocoa.py`):

- la finestra è un `WKWebView` creato con una `WKWebViewConfiguration` di default. Senza le
  preferenze dei media, `navigator.mediaDevices` (e forse `MediaRecorder`) non esistono, quindi
  `VoiceRecorder.tsx` calcola `supported = false` e disattiva il pulsante;
- `BrowserView.BrowserDelegate` non implementa
  `webView:requestMediaCapturePermissionForOrigin:initiatedByFrame:type:decisionHandler:`, quindi
  nessuno chiede ad AVFoundation l'accesso al microfono e macOS non mostra mai il suo prompt.

`Info.plist` ha già `NSMicrophoneUsageDescription` (`scripts/build_app.py`). La finestra gira nel
processo lanciato da RT.app (`exec` nel launcher), quindi il permesso viene attribuito a RT.

File: nessun'altra parte di RT ha bisogno di permessi. I file entrano dai selettori del sistema
(`<input type=file>`, pannelli di salvataggio) e i dati stanno in `~/.rt`, che non è protetta.
"Controlla permessi" quindi riguarda solo il microfono.

## Cosa fare

### 1. Dipendenza (Mac)

In `packaging/requirements-app.txt` aggiungi:

```
pyobjc-framework-AVFoundation; sys_platform == "darwin"
```

Niente versione fissa: pip la allinea a `pyobjc-core` già installato da pywebview, e `pip check` in
`build_app.py` lo verifica.

### 2. `rt/window.py`: preferenze e delegato (Mac)

Prima di `webview.start`, solo su `sys.platform == "darwin"`, una funzione `_enable_media()` che
sostituisce due classi di `webview.platforms.cocoa.BrowserView`, come fa già
`rt/_window_smoke.py` con `DownloadDelegate`:

- `BrowserView.WebKitHost` con una sottoclasse che in `initWithFrame_configuration_` imposta sulle
  preferenze della configurazione, prima di chiamare `super`:
  - `mediaDevicesEnabled = True`
  - `mediaRecorderEnabled = True`
  - `mediaCaptureRequiresSecureConnection = False` (la pagina è `http://127.0.0.1`, che di norma
    conta già come sicura: questa è solo una garanzia)

  Ogni `setValue_forKey_` va in un `try/except Exception` (alcune chiavi sono private e possono
  mancare): registra con `_log` quali chiavi sono state accettate.
- `BrowserView.BrowserDelegate` con una sottoclasse che aggiunge
  `webView_requestMediaCapturePermissionForOrigin_initiatedByFrame_type_decisionHandler_`:
  - origine diversa da `127.0.0.1`/`localhost` → `decisionHandler(WKPermissionDecisionDeny)`;
  - altrimenti guarda `AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeAudio)`:
    - autorizzato → `Grant`;
    - non ancora deciso → `AVCaptureDevice.requestAccessForMediaType_completionHandler_`, e nella
      completion `Grant` o `Deny` (chiama `decisionHandler` sul thread principale, ad esempio con
      `AppHelper.callAfter`);
    - negato o limitato → `Deny`.

  Così il prompt di macOS compare al primo clic su Registra e da lì in poi RT sta nell'elenco del
  Microfono. Il prompt di WebKit non compare, perché decidiamo noi.

Verifica che pyobjc conosca la firma del blocco `decisionHandler` (metadata di
`pyobjc-framework-WebKit`). Se non la conosce, registrala con `objc.registerMetaDataForSelector`.

Dopo il caricamento della pagina (dentro `loaded`) scrivi una riga in `desktop.log` con
`window.evaluate_js("[!!navigator.mediaDevices, 'MediaRecorder' in window]")`, per capire dai
registri se manca ancora qualcosa.

### 3. `rt/window.py`: Windows

WebView2 ha già un suo prompt, ma pywebview non gestisce `PermissionRequested`. Nell'hook
`initialized`/`loaded`, come fa `_window_smoke.py` con `DownloadStarting`, aggiungi un gestore su
`browser.webview.CoreWebView2.PermissionRequested`: per l'origine di `base_url` e il tipo
`Microphone` imposta `State = Allow`. Il consenso vero resta quello di Windows (Privacy ›
Microfono).

### 4. Menu "Controlla permessi"

In `_menu`, una voce `Controlla permessi`, subito dopo "Diagnostica":

- Mac:
  - non ancora deciso → `requestAccessForMediaType_` (compare il prompt), poi `_notice` con l'esito;
  - negato o limitato → apre
    `x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone` con `_open_path`
    e mostra `_notice(window, "Attiva RT in Microfono, poi riapri RT.")`;
  - autorizzato → `_notice(window, "Microfono consentito.")` e ricarica la pagina.
- Windows: apre `ms-settings:privacy-microphone` e mostra lo stesso avviso.
- Linux o finestra senza pywebview: la voce non c'è.

macOS non rimostra il prompt dopo un rifiuto: la voce apre l'impostazione giusta. È l'unico modo.

### 5. Messaggio nel registratore

In `frontend/src/components/VoiceRecorder.tsx`, se `getUserMedia` dà `NotAllowedError`, il messaggio
diventa `Microfono non consentito. Menu RT › Controlla permessi.` quando la pagina gira nell'app,
altrimenti resta quello attuale. Per sapere se si è nell'app usa quello che il frontend usa già (cerca
`pywebview` o il flag della finestra in `frontend/src/lib`). Non aggiungere altro testo.

## Test

- `tests/test_window.py` (o il file che testa `_menu`): la voce "Controlla permessi" c'è su Mac e
  Windows (con `sys.platform` simulato) e chiama le funzioni giuste (AVFoundation simulato con un
  oggetto finto, per stato `0`, `2` e `3`).
- Il delegato: con `decisionHandler` finto, l'origine `127.0.0.1` autorizzata dà Grant, un'altra
  origine dà Deny.
- Vitest per il messaggio di `VoiceRecorder` se esiste già un test del componente.
- Il test di fumo dell'app (`app.yml`) deve restare verde.

Prova a mano (Attilio, sul Mac): primo clic su Registra → prompt di macOS → RT compare in
Privacy › Microfono; dopo un rifiuto, "Controlla permessi" apre quella pagina.

## Note per il changelog

- Nell'app la registrazione vocale funziona: RT chiede il permesso del microfono al primo uso.
- Nuova voce di menu "Controlla permessi" che richiede il microfono o apre l'impostazione di sistema
  se era stato negato.
