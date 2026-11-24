"""Test per il promemoria periodico delle donazioni (support_prompt)."""
from datetime import date, timedelta

from rt.core import donazioni
from rt.services import support_prompt


def test_first_seven_days_visibility():
    state = support_prompt.initial_state()
    start = date(2026, 11, 1)
    for i in range(6):
        state = support_prompt.register_day(state, start + timedelta(days=i))
        assert state["used_days"] == i + 1
        assert support_prompt.is_visible(state, start + timedelta(days=i)) is False

    day7 = start + timedelta(days=6)
    state = support_prompt.register_day(state, day7)
    assert state["used_days"] == 7
    assert support_prompt.is_visible(state, day7) is True


def test_same_day_counted_once():
    state = support_prompt.initial_state()
    today = date(2026, 11, 1)
    state = support_prompt.register_day(state, today)
    state = support_prompt.register_day(state, today)
    state = support_prompt.register_day(state, today)
    assert state["used_days"] == 1
    assert state["last_day"] == today.isoformat()


def test_opened_reappears_after_five_used_days():
    state = support_prompt.initial_state()
    day = date(2026, 11, 1)
    for i in range(7):
        day_i = day + timedelta(days=i)
        state = support_prompt.register_day(state, day_i)

    assert support_prompt.is_visible(state, day + timedelta(days=6)) is True
    state = support_prompt.on_opened(state)
    assert state["next_at"] == 12
    assert state["hide_streak"] == 0
    assert support_prompt.is_visible(state, day + timedelta(days=6)) is False

    for i in range(7, 11):
        day_i = day + timedelta(days=i)
        state = support_prompt.register_day(state, day_i)
        assert support_prompt.is_visible(state, day_i) is False

    day12 = day + timedelta(days=11)
    state = support_prompt.register_day(state, day12)
    assert state["used_days"] == 12
    assert support_prompt.is_visible(state, day12) is True


def test_hidden_exponential_backoff_capped_at_30():
    state = {"used_days": 10, "last_day": "2026-11-10", "next_at": 10, "hide_streak": 0, "paused_until": None}
    expected_delays = [10, 20, 30, 30]
    for idx, delay in enumerate(expected_delays, start=1):
        before = state["used_days"]
        state = support_prompt.on_hidden(state)
        assert state["hide_streak"] == idx
        assert state["next_at"] == before + delay
        assert support_prompt.is_visible(state, date(2026, 11, 10)) is False

    # opened resets hide_streak
    state = support_prompt.on_opened(state)
    assert state["hide_streak"] == 0


def test_donated_pauses_for_182_calendar_days():
    day = date(2026, 1, 1)
    state = {"used_days": 10, "last_day": day.isoformat(), "next_at": 7, "hide_streak": 2, "paused_until": None}
    state = support_prompt.on_donated(state, day)
    assert state["hide_streak"] == 0
    assert state["paused_until"] == (day + timedelta(days=182)).isoformat()

    # Many usage days within the 182-day calendar window still stay invisible
    for offset in range(1, 182):
        current = day + timedelta(days=offset)
        state = support_prompt.register_day(state, current)
        assert support_prompt.is_visible(state, current) is False

    # After 182 calendar days (and >= next_at used days), it becomes visible again
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
