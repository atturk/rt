"""Compatibilità: le connessioni vivono in rt.services.connections_service (RT4-E4)."""
from rt.services.connections_service import (  # noqa: F401
    PHASES, PROVIDERS, add_model, assign_phase, connection_names, find_connection,
    list_connections, model_names, phase_selection, save_connection,
)
