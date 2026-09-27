from unittest.mock import patch

import pytest

from rt.services.telegram_topics import TopicListenError, recreate_topic
from tests.api_support import isolated_workspace


def test_recreation_updates_mapping_only_after_success(rt_db, tmp_path, monkeypatch):
    isolated_workspace(tmp_path, monkeypatch)
    from rt.services.settings_service import save_telegram
    from pathlib import Path
    from rt.core.config import _default_project_root, load_config
    save_telegram(Path(_default_project_root()), "", "", [["BIOCHIMICA", 42]], "", {42: "BIOCHIMICA"})
    monkeypatch.setenv("RT_TELEGRAM_BOT_TOKEN", "testing-token")
    monkeypatch.setenv("RT_TELEGRAM_CHAT_ID", "-1001")

    def telegram(_token, method, _payload):
        if method == "getMe": return {"ok": True, "result": {"id": 3}}
        if method == "getChatMember": return {"ok": True, "result": {"status": "administrator", "can_manage_topics": True}}
        if method == "deleteForumTopic": return {"ok": True}
        if method == "createForumTopic": return {"ok": True, "result": {"message_thread_id": 77}}
        raise AssertionError(method)

    with patch("rt.services.telegram_topics._post", side_effect=telegram) as call:
        with pytest.raises(TopicListenError):
            recreate_topic(42, "BIOCHIMICA", "wrong")
        assert call.call_count == 0
        assert recreate_topic(42, "BIOCHIMICA", "confermo") == 77
    assert load_config().telegram.topics["BIOCHIMICA"] == 77
