"""Compatibilità: le impostazioni vivono in rt.services.settings_service (RT4-E4)."""
from rt.services.settings_service import (  # noqa: F401
    ROUTE_ROLES, _atomic_yaml, _env_path, _read_yaml, _save_secret, _validate_secret,
    credential_names, general_config_path, route_round_robin_keys, route_settings,
    save_credential, save_lessons_root, save_route, save_telegram, save_transcription,
)
