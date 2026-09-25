"""
rt.db
Database di RT 4.0 (SQLAlchemy 2 + Alembic): indice delle lezioni, stato delle fasi, issue,
decisioni di review, chiamate LLM, impostazioni e stato del daemon Telegram.

I file nella cartella della lezione restano gli artefatti (audio, JSON, Markdown). Il DB è
opzionale: senza DB, o con un DB rotto, RT funziona come prima leggendo e scrivendo i file.
"""
