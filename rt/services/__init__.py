"""
rt.services
Service layer di RT 4.0: il motore (rt/pipeline, rt/core) esposto a CLI, Telegram, web,
API e worker senza dipendere da nessuna interfaccia. I moduli di questo pacchetto non
stampano, non leggono da stdin e non chiamano sys.exit(): comunicano con eventi tipizzati
(events.py) e ricevono un contesto di esecuzione (context.py).
"""
