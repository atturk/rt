"""Test per avviso alla chiusura con job in corso (Extra 2)."""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from rt import window as rt_window


def test_active_jobs_quit_message_counts_active_and_ignores_terminal_and_batch_phrases():
    assert rt_window.active_jobs_quit_message([]) is None
    assert rt_window.active_jobs_quit_message([
        {"id": "1", "state": "succeeded"},
        {"id": "2", "state": "failed"},
        {"id": "3", "state": "cancelled"},
        {"id": "4", "state": "waiting_for_decision"},
    ]) is None

    one = rt_window.active_jobs_quit_message([
        {"id": "1", "state": "running"},
        {"id": "2", "state": "succeeded"},
    ])
    assert one == "C'è 1 lavoro in corso. Uscendo si interrompe e riprende alla prossima apertura di RT."

    many = rt_window.active_jobs_quit_message([
        {"id": "1", "state": "running"},
        {"id": "2", "state": "queued"},
        {"id": "3", "state": "waiting_for_provider", "batch": True},
    ])
    assert many == "Ci sono 3 lavori in corso. Uscendo si interrompono e riprendono alla prossima apertura di RT."
    assert "batch" not in many.lower()


def test_allow_quit_close_respects_close_action_api_failures_and_cancel():
    win = MagicMock()

    # In modalità background (non quit) chiude senza chiedere nulla
    with (
        patch("rt.core.config.load_config", return_value=SimpleNamespace(ui=SimpleNamespace(close_action="background"))),
        patch("rt.window._fetch_active_jobs") as fetch_mock,
    ):
        assert rt_window._allow_quit_close(win, "http://127.0.0.1:8765") is True
        fetch_mock.assert_not_called()

    quit_cfg = SimpleNamespace(ui=SimpleNamespace(close_action="quit"))

    # Se l'API non risponde salta l'avviso e lascia chiudere
    with (
        patch("rt.core.config.load_config", return_value=quit_cfg),
        patch("rt.window._fetch_active_jobs", return_value=None),
    ):
        assert rt_window._allow_quit_close(win, "http://127.0.0.1:8765") is True
        win.create_confirmation_dialog.assert_not_called()

    # Nessun job attivo: sulla X nessun dialogo
    with (
        patch("rt.core.config.load_config", return_value=quit_cfg),
        patch("rt.window._fetch_active_jobs", return_value=[{"id": "1", "state": "succeeded"}]),
    ):
        assert rt_window._allow_quit_close(win, "http://127.0.0.1:8765") is True
        win.create_confirmation_dialog.assert_not_called()

    # Con job attivi e click su Annulla -> restituisce False per impedire la chiusura
    win.create_confirmation_dialog.return_value = False
    with (
        patch("rt.core.config.load_config", return_value=quit_cfg),
        patch("rt.window._fetch_active_jobs", return_value=[{"id": "1", "state": "running"}, {"id": "2", "state": "queued"}]),
    ):
        assert rt_window._allow_quit_close(win, "http://127.0.0.1:8765") is False
        win.create_confirmation_dialog.assert_called_once_with(
            "Esci da RT",
            "Ci sono 2 lavori in corso. Uscendo si interrompono e riprendono alla prossima apertura di RT.",
        )

    # Con job attivi e conferma -> restituisce True
    win.create_confirmation_dialog.reset_mock()
    win.create_confirmation_dialog.return_value = True
    with (
        patch("rt.core.config.load_config", return_value=quit_cfg),
        patch("rt.window._fetch_active_jobs", return_value=[{"id": "1", "state": "waiting_for_provider"}]),
    ):
        assert rt_window._allow_quit_close(win, "http://127.0.0.1:8765") is True
        win.create_confirmation_dialog.assert_called_once_with(
            "Esci da RT",
            "C'è 1 lavoro in corso. Uscendo si interrompe e riprende alla prossima apertura di RT.",
        )


def test_menu_quit_rt_uses_active_jobs_warning_or_default_and_handles_http_timeout():
    # _fetch_active_jobs gestisce errori/timeout senza propagare eccezioni
    with (
        patch("rt.api.auth.create_session", return_value="tok"),
        patch("rt.api.auth.drop_session") as drop_mock,
        patch("urllib.request.urlopen", side_effect=OSError("timeout")),
    ):
        assert rt_window._fetch_active_jobs("http://127.0.0.1:8765", timeout=2.0) is None
        drop_mock.assert_called_once_with("tok")

    fake_resp = MagicMock()
    fake_resp.read.return_value = json.dumps([{"id": "1", "state": "running"}]).encode("utf-8")
    fake_resp.__enter__.return_value = fake_resp
    with (
        patch("rt.api.auth.create_session", return_value="tok"),
        patch("rt.api.auth.drop_session") as drop_mock,
        patch("urllib.request.urlopen", return_value=fake_resp) as open_mock,
    ):
        jobs = rt_window._fetch_active_jobs("http://127.0.0.1:8765", timeout=2.0)
        assert jobs == [{"id": "1", "state": "running"}]
        assert open_mock.call_args.kwargs["timeout"] == 2.0
        drop_mock.assert_called_once_with("tok")
