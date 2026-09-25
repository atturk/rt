"""
rt.api
API REST di RT 4.0 (FastAPI, router versionati sotto /api/v1, eventi live con SSE).
Usa solo il service layer (rt/services) e i repository del DB (rt/db): nessuna logica di
dominio vive qui. Avvio: 'rt api' (loopback per default). Documentazione interattiva su
/docs, schema su /openapi.json (copia in docs/openapi.json, scripts/export_openapi.py).
"""
from rt.api.app import create_app  # noqa: F401
