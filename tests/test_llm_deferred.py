"""Test unitari per la cache batch differita (rt.llm.deferred)."""
from datetime import timedelta

from rt.db.models import Job, LlmDeferred, utcnow
from rt.db.session import session_scope
from rt.llm import deferred
from rt.llm.providers.base import NormalizedResponse


def test_request_key_is_deterministic_and_sensitive():
    msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "ciao"}]
    schema = {"type": "object", "properties": {"a": {"type": "string"}}}
    k1 = deferred.request_key("openrouter", "openai/gpt-4o:batch", msgs, schema=schema, params={"temperature": 0.2, "max_tokens": 100})
    k2 = deferred.request_key("OPENROUTER", "openai/gpt-4o:batch", msgs, schema=schema, params={"max_tokens": 100, "temperature": 0.2})
    assert k1 == k2
    assert len(k1) == 64

    # Cambiando un parametro, il modello o il messaggio cambia la chiave
    assert deferred.request_key("openrouter", "openai/gpt-4o-mini:batch", msgs, schema=schema, params={"temperature": 0.2, "max_tokens": 100}) != k1
    assert deferred.request_key("openrouter", "openai/gpt-4o:batch", msgs, schema=schema, params={"temperature": 0.5, "max_tokens": 100}) != k1
    assert deferred.request_key("openrouter", "openai/gpt-4o:batch", [{"role": "user", "content": "altro"}], schema=schema) != k1


def test_put_pending_mark_submitted_and_store_results(rt_db):
    k1 = deferred.request_key("openrouter", "m1:batch", [{"role": "user", "content": "1"}])
    k2 = deferred.request_key("openrouter", "m1:batch", [{"role": "user", "content": "2"}])

    deferred.put_pending(
        k1, job_id="job-1", lesson_path="/tmp/l1", provider="openrouter", model="m1:batch",
        credential_ref="openrouter", request={"model": "m1:batch", "messages": []},
    )
    deferred.put_pending(
        k2, job_id="job-1", lesson_path="/tmp/l1", provider="openrouter", model="m1:batch",
        credential_ref="openrouter", request={"model": "m1:batch", "messages": []},
    )

    pending = deferred.pending_for_job("job-1")
    assert {e.key for e in pending} == {k1, k2}
    assert all(e.state == "pending" for e in pending)
    assert deferred.job_has_waiting_items("job-1") is True

    updated = deferred.mark_submitted([k1, k2], "batch-123")
    assert updated == 2
    assert deferred.pending_for_job("job-1") == []
    batches = deferred.open_batches()
    assert len(batches) == 1
    assert batches[0]["batch_id"] == "batch-123"
    assert set(batches[0]["keys"]) == {k1, k2}

    norm1 = NormalizedResponse(content='{"ok": true}', provider="openrouter", model="m1:batch", usage={"prompt_tokens": 10, "completion_tokens": 5})
    touched = deferred.store_results("batch-123", {
        k1: norm1,
        k2: {"error": "Rate limit on request"},
    })
    assert touched == ["job-1"]
    assert deferred.job_has_waiting_items("job-1") is False
    assert deferred.open_batches() == []

    e1 = deferred.get(k1)
    assert e1 is not None and e1.state == "done" and e1.response["content"] == '{"ok": true}'
    e2 = deferred.get(k2)
    assert e2 is not None and e2.state == "error" and "Rate limit" in (e2.error or "")

    deferred.consume_error(k2)
    assert deferred.get(k2) is None
    assert deferred.get(k1) is not None


def test_delete_for_job_and_cleanup(rt_db):
    now = utcnow()
    old = now - timedelta(days=8)
    recent = now - timedelta(days=2)

    with session_scope(rt_db) as s:
        s.add(Job(id="j-done", type="run_phase", state="succeeded", payload={}, created_at=old, updated_at=old))
        s.add(Job(id="j-fail", type="run_phase", state="failed", payload={}, created_at=recent, updated_at=recent))
        s.add(Job(id="j-cancel", type="run_phase", state="cancelled", payload={}, created_at=recent, updated_at=recent))
        s.add(Job(id="j-wait", type="run_phase", state="waiting_for_provider", payload={}, created_at=recent, updated_at=recent))

        # Riga done vecchia (> 7 giorni): va rimossa
        s.add(LlmDeferred(key="k-old-done", job_id="j-done", provider="openrouter", model="m", request={}, state="done", response={"content": "x"}, created_at=old, updated_at=old))
        # Riga done recente di un job riuscito: resta fino a 7 giorni
        s.add(LlmDeferred(key="k-fresh-done", job_id="j-done", provider="openrouter", model="m", request={}, state="done", response={"content": "y"}, created_at=recent, updated_at=recent))
        # Riga pending di job fallito: va rimossa
        s.add(LlmDeferred(key="k-fail-pending", job_id="j-fail", provider="openrouter", model="m", request={}, state="pending", created_at=recent, updated_at=recent))
        # Riga done di job annullato: va rimossa
        s.add(LlmDeferred(key="k-cancel-done", job_id="j-cancel", provider="openrouter", model="m", request={}, state="done", response={"content": "z"}, created_at=recent, updated_at=recent))
        # Riga submitted di job in attesa: resta
        s.add(LlmDeferred(key="k-wait-sub", job_id="j-wait", batch_id="b-wait", provider="openrouter", model="m", request={}, state="submitted", created_at=recent, updated_at=recent))

    removed = deferred.cleanup(max_age_days=7, now=now)
    assert removed == 3
    assert deferred.get("k-old-done") is None
    assert deferred.get("k-fail-pending") is None
    assert deferred.get("k-cancel-done") is None
    assert deferred.get("k-fresh-done") is not None
    assert deferred.get("k-wait-sub") is not None

    deleted = deferred.delete_for_job("j-wait")
    assert len(deleted) == 1 and deleted[0].key == "k-wait-sub"
    assert deferred.get("k-wait-sub") is None
