# LibreOffice 26.8.3 (stable) — costanti verificate sul Pro 2026-11-28
- macOS aarch64: https://download.documentfoundation.org/libreoffice/stable/26.8.3/mac/aarch64/LibreOffice_26.8.3_MacOS_aarch64.dmg
  299927705 byte, SHA256 de943203795e5057785f65515063e2db5eb60b0bb6d8e2534fec59e5cc5fb988 (verificato sul file)
- Windows x86-64: https://download.documentfoundation.org/libreoffice/stable/26.8.3/win/x86_64/LibreOffice_26.8.3_Win_x86-64.msi
  376311808 byte, SHA256 0e6918c273eabbdbbd800ee0dacbbf130a14c13c2e4cec861b06dd59e015bf94 (dal .sha256 ufficiale)
- LibreOffice.app estratta (hdiutil attach -nobrowse -readonly + ditto): ~808 MB su disco, 7,6 s.

# Confronto qualità: NON completato
- Keynote via osascript (come materials.py): timeout 120 s su tutti i 4 pptx sintetici → probabile permesso Automazione / dialogo primo avvio senza nessuno davanti. Anche RT al primo uso resta appeso 120 s in silenzio.
- Quick Look (qlmanage -p -o): 0,1 s ma solo Preview.html, mai PDF/PNG per slide → inutile come convertitore.
- LibreOffice portabile: esecuzione bloccata dall'auto mode di Claude Code sul Pro (binario scaricato). Serve OK di Attilio scritto nel thread «Preparare la prossima beta notturna» o lancio manuale.
- pptx sintetiche (grafici, tabelle, formule/caratteri, forme) in ~/rt-stuff/pptx-confronto/pptx sul Pro.

# Confronto LibreOffice 26.8.3 portabile (2026-11-28 08:10 Rome, OK Attilio)
Tempi: 6,1 s il primo (avvio a freddo), poi 0,7-1,0 s per file da 5 slide. PNG in pptx-confronto/ (anche ramo tmp/pptx-confronto 03a1d5a1).
- FONT: usa solo i suoi (Carlito per Calibri ok; Liberation; tutto il resto → Linux Libertine G serif: Helvetica Neue, Georgia, Arial Black, Comic Sans, Avenir, Cambria Math). Da indagare: profilo portabile/headless non vede i font di macOS? Possibile fix: config font replacement o SAL_FONTPATH.
- Emoji: 3 su 4 spariscono, ⚡ in b/n.
- Grafici, tabelle (celle unite), forme, connettori, testo ruotato, lingue/simboli Unicode: corretti. Dispersione XY: marcatori piccoli e chiari.
- Non provati: SmartArt e equazioni OMML (servono pptx vere dall'Air).
