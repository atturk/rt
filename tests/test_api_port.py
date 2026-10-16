"""
tests/test_api_port.py
La porta dell'app: la 8765, oppure, se la occupa un altro programma, una libera che RT
ricorda nella cartella dati (così 'rt web', i servizi e le aperture successive la ritrovano).
"""
import socket

import pytest

from rt.services import service_manager as sm


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("RT_DATA_DIR", str(tmp_path))
    monkeypatch.delenv(sm.PORT_ENV, raising=False)
    return tmp_path


@pytest.fixture
def occupied():
    """Un altro programma in ascolto su una porta (non RT: niente /api/v1/health)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    yield s.getsockname()[1]
    s.close()


def test_default_port_and_override(data, monkeypatch):
    assert sm.api_port() == sm.DEFAULT_PORT
    (data / sm.PORT_FILE).write_text("8800\n")
    assert sm.api_port() == 8800
    monkeypatch.setenv(sm.PORT_ENV, "9000")
    assert sm.api_port() == 9000
    (data / sm.PORT_FILE).write_text("non-una-porta")
    monkeypatch.delenv(sm.PORT_ENV)
    assert sm.api_port() == sm.DEFAULT_PORT


def test_busy_port_is_replaced_and_remembered(data, occupied):
    (data / sm.PORT_FILE).write_text(f"{occupied}\n")
    said = []
    chosen = sm.choose_port(said.append)
    assert chosen != occupied and not sm.port_busy(chosen)
    assert sm.api_port() == chosen
    assert str(occupied) in said[0] and str(chosen) in said[0]


def test_free_port_or_running_rt_is_kept(data, occupied, monkeypatch):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        free = s.getsockname()[1]
    (data / sm.PORT_FILE).write_text(f"{free}\n")
    assert sm.choose_port() == free
    (data / sm.PORT_FILE).write_text(f"{occupied}\n")
    monkeypatch.setattr(sm, "api_is_up", lambda port=None, timeout=1.0: True)  # c'è già RT
    assert sm.choose_port() == occupied


def test_env_port_is_never_changed(data, occupied, monkeypatch):
    monkeypatch.setenv(sm.PORT_ENV, str(occupied))
    assert sm.choose_port() == occupied
    assert not (data / sm.PORT_FILE).exists()
