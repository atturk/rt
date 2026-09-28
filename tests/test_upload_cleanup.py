"""La pulizia esplicita non tocca gli upload associati a job."""
import os
import uuid

import pytest

from rt.api.errors import ApiError
from rt.services.jobs import DbJobQueue
from rt.services import upload_cleanup


def test_inventory_and_delete_only_orphan(tmp_path, monkeypatch, rt_db):
    monkeypatch.setattr(upload_cleanup, "lessons_root", lambda: str(tmp_path))
    root = tmp_path / ".rt" / "uploads"
    orphan = root / uuid.uuid4().hex
    active = root / uuid.uuid4().hex
    orphan.mkdir(parents=True)
    active.mkdir()
    (orphan / "audio.wav").write_bytes(b"audio")
    queue = DbJobQueue(rt_db)
    queue.enqueue("ingest_audio", None, {"upload_dir": str(active)})

    rows = {item["id"]: item for item in upload_cleanup.list_uploads()}
    assert rows[orphan.name]["state"] == "orphan"
    assert rows[orphan.name]["files"] == 1
    assert rows[active.name]["state"] == "active"
    with pytest.raises(ApiError) as busy:
        upload_cleanup.delete_orphan(active.name)
    assert busy.value.status_code == 409
    with pytest.raises(ApiError):
        upload_cleanup.delete_orphan("../outside")
    upload_cleanup.delete_orphan(orphan.name)
    assert not os.path.exists(orphan)
    assert os.path.isdir(active)


def test_symlink_is_never_listed_or_deleted(tmp_path, monkeypatch, rt_db):
    monkeypatch.setattr(upload_cleanup, "lessons_root", lambda: str(tmp_path))
    root = tmp_path / ".rt" / "uploads"
    root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    link = root / uuid.uuid4().hex
    link.symlink_to(outside, target_is_directory=True)
    assert upload_cleanup.list_uploads() == []
    with pytest.raises(ApiError):
        upload_cleanup.delete_orphan(link.name)
    assert outside.is_dir()
