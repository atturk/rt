"""Test per il promemoria periodico delle donazioni (support_prompt)."""
from datetime import date, timedelta

from rt.core import donazioni
from rt.services import support_prompt


def test_first_twenty_days_visibility():
    state = support_prompt.initial_state()
    start = date(2026, 11, 1)
    for i in range(19):
        state = support_prompt.register_day(state, start + timedelta(days=i))
        assert support_prompt.is_visible(state, start + timedelta(days=i)) is False
    day20 = start + timedelta(days=19)
    state = support_prompt.register_day(state, day20)
    assert state["used_days"] == 20
    assert support_prompt.is_visible(state, day20) is True


def test_same_day_counted_once():
    state = support_prompt.initial_state()
    today = date(2026, 11, 1)
    state = support_prompt.register_day(state, today)
    state = support_prompt.register_day(state, today)
    state = support_prompt.register_day(state, today)
    assert state["used_days"] == 1
    assert state["last_day"] == today.isoformat()


def test_opened_and_donate_click_reappear_after_twenty_used_days():
    for event in (support_prompt.on_opened, support_prompt.on_donated):
        state = {"used_days": 20, "last_day": "2026-11-20", "next_at": 20, "hide_streak": 1, "paused_until": None}
        state = event(state)
        assert state["next_at"] == 40
        assert state["hide_streak"] == 0
        assert state["paused_until"] is None  # il clic su Dona non mette in pausa


def test_hidden_reappears_after_thirty_used_days():
    state = {"used_days": 20, "last_day": "2026-11-20", "next_at": 20, "hide_streak": 0, "paused_until": None}
    for idx in range(1, 4):
        before = state["used_days"]
        state = support_prompt.on_hidden(state)
        assert state["hide_streak"] == idx
        assert state["next_at"] == before + 30
        assert support_prompt.is_visible(state, date(2026, 11, 20)) is False


def test_already_donated_pauses_for_182_calendar_days():
    day = date(2026, 1, 1)
    state = {"used_days": 30, "last_day": day.isoformat(), "next_at": 20, "hide_streak": 2, "paused_until": None}
    state = support_prompt.on_already_donated(state, day)
    assert state["hide_streak"] == 0
    assert state["paused_until"] == (day + timedelta(days=182)).isoformat()
    for offset in range(1, 182):
        current = day + timedelta(days=offset)
        state = support_prompt.register_day(state, current)
        assert support_prompt.is_visible(state, current) is False
    after_182 = day + timedelta(days=182)
    state = support_prompt.register_day(state, after_182)
    assert support_prompt.is_visible(state, after_182) is True


def test_corrupted_file_falls_back_to_initial_state(tmp_path, monkeypatch):
    monkeypatch.setenv("RT_DATA_DIR", str(tmp_path))
    path = support_prompt.state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not valid json", encoding="utf-8")
    assert support_prompt.load_state() == support_prompt.initial_state()

    path.write_text('{"used_days": "bad", "next_at": true, "last_day": "9999-99-99"}', encoding="utf-8")
    assert support_prompt.load_state() == support_prompt.initial_state()


def test_api_empty_url_always_invisible(api_client, tmp_path, monkeypatch):
    monkeypatch.setenv("RT_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(donazioni, "DONAZIONI_URL", "")
    path = support_prompt.state_path()
    support_prompt.save_state(
        {"used_days": 20, "last_day": "2026-01-01", "next_at": 7, "hide_streak": 0, "paused_until": None},
        path,
    )
    res = api_client.get("/api/v1/system/support-prompt")
    assert res.status_code == 200
    assert res.json() == {"visible": False, "url": ""}


def test_api_endpoints_and_io_error_never_500(api_client, tmp_path, monkeypatch):
    monkeypatch.setenv("RT_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(donazioni, "DONAZIONI_URL", "https://ko-fi.com/example")
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    support_prompt.save_state(
        {"used_days": 6, "last_day": yesterday, "next_at": 7, "hide_streak": 0, "paused_until": None},
    )

    res = api_client.get("/api/v1/system/support-prompt")
    assert res.status_code == 200
    assert res.json() == {"visible": True, "url": "https://ko-fi.com/example/donate"}

    post_res = api_client.post("/api/v1/system/support-prompt", json={"event": "opened"})
    assert post_res.status_code == 200
    assert post_res.json() == {"visible": False, "url": "https://ko-fi.com/example/donate"}

    def fail_save(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(support_prompt, "save_state", fail_save)
    support_prompt.state_path().unlink()
    err_res = api_client.get("/api/v1/system/support-prompt")
    assert err_res.status_code == 200
    assert err_res.json() == {"visible": False, "url": "https://ko-fi.com/example/donate"}
