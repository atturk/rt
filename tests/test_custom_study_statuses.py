import pytest

from rt.db.engine import get_database
from rt.db.session import session_scope
from rt.services import study_progress_service as service
from tests.test_study_progress import ready  # noqa: F401


def test_status_valido_e_invalido(ready, monkeypatch):
    path, lid, units = ready
    uid = units[0]["id"]

    # Default validi
    service.set_status(lid, path, uid, "da-imparare")
    assert service.list_units(lid)[0]["status"] == "da-imparare"

    service.set_status(lid, path, uid, "appreso")
    assert service.list_units(lid)[0]["status"] == "appreso"

    # Stato sconosciuto fallisce
    with pytest.raises(ValueError, match="Stato di studio non valido"):
        service.set_status(lid, path, uid, "sconosciuto")

    # Stato personalizzato presente nei settings è valido
    monkeypatch.setattr(service, "custom_statuses", lambda: [
        {"id": "c1", "nome": "Da approfondire", "colore": "text-amber-500", "icona": "Star"}
    ])
    service.set_status(lid, path, uid, "c1")
    assert service.list_units(lid)[0]["status"] == "c1"


def test_eliminazione_stato_con_unita_in_uso(ready, monkeypatch):
    path, lid, units = ready
    u1 = units[0]["id"]

    monkeypatch.setattr(service, "custom_statuses", lambda: [
        {"id": "c1", "nome": "Da approfondire", "colore": "text-amber-500", "icona": "Star"}
    ])

    service.set_status(lid, path, u1, "c1")
    assert service.count_units_with_status("c1") == 1

    # Eliminazione dello stato c1: le unità tornano a in-apprendimento
    reassigned = service.delete_status_and_reassign("c1")
    assert reassigned == 1

    unit_map = {u["unit_id"]: u["status"] for u in service.list_units(lid)}
    assert unit_map[u1] == "in-apprendimento"
    assert service.count_units_with_status("c1") == 0


def test_import_con_stato_sconosciuto(ready):
    path, lid, units = ready
    db = get_database()
    u1 = units[0]["id"]

    # Import/restore con uno stato inesistente
    entries = [
        {"unit_id": u1, "status": "stato_inesistente_xyz"},
    ]

    with session_scope(db) as session:
        service.restore_units(session, lid, entries)

    unit_map = {u["unit_id"]: u["status"] for u in service.list_units(lid)}
    # Lo stato sconosciuto diventa in-apprendimento
    assert unit_map[u1] == "in-apprendimento"
