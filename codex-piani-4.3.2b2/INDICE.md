# Piani per la 4.3.2b2

Base: `claude/rt-4.3.2-beta` (dopo la 4.3.2b1). Ogni PR va verso quel branch.

1. `piano-aggiornamenti-app-codex.md`: aggiornamenti in un popup della finestra dell'app, download separato dall'installazione e conservato su disco, Installa e riavvia, canale beta anche dall'app.
2. `piano-notifiche-dock-codex.md`: notifica di sistema quando un job finisce o aspetta una decisione con la finestra in secondo piano; numero dei job sull'icona nel Dock.
3. `piano-apri-con-codex.md`: file aperti con RT ("Apri con", icona nel Dock, doppio clic su Windows) che aprono Nuova lezione.
4. `piano-risposte-codex.md`: ogni risposta è un tentativo nello storico; le domande riposte non mostrano la vecchia risposta; pagina Risposte dal pannello Domande.
5. `piano-dmg-apri-comunque-codex.md`: firma ad-hoc di RT.app e sfondo del DMG con le istruzioni per Apri comunque.

"Salva con nome" per gli export non serve: nell'app pywebview mostra già la finestra di salvataggio per ogni download (Mac e Windows).

La divisione fra Codex e agy si decide quando il batch è completo.
