"""
tests/test_db_storage.py
Lezioni nel database (rt/storage): file testuali in lesson_files, media nella cartella
media/, migrazione una tantum delle cartelle esistenti ed export su richiesta.
Il run completo in mock con il DB attivo (nessuna cartella, file identici ai golden) è in
tests/test_db_sync.py::test_full_mock_run_with_database_is_unchanged_and_in_sync.
"""
import io
import json
import os
import zipfile

import pytest

from rt.core.lesson_paths import lesson_path
from rt.db.models import Lesson, StateDocument
from rt.db.session import session_scope
from rt.storage import fs
from tests.api_support import add_audio, isolated_workspace, make_lesson, run_mock_pipeline
from tests.golden_support import AUDIO_FIXTURE, LESSON_NAME


@pytest.fixture
def db_lesson(rt_db, tmp_path):
    root = tmp_path / "lessons"
    root.mkdir()
    return fs.create_db_lesson(str(root / LESSON_NAME))


def _tree(path):
    """File della cartella, senza il lock di lavorazione (.rt.job.lock) che la migrazione prende."""
    return sorted(os.path.relpath(os.path.join(b, n), path) for b, _, names in os.walk(path) for n in names
                  if n != ".rt.job.lock")


# ---------------------------------------------------------------- rt.storage.fs

def test_db_lesson_files_never_touch_disk(db_lesson, rt_db):
    info = lesson_path(db_lesson, "info.yaml")
    assert info == os.path.join(db_lesson, "info.yaml")  # niente _state/ per le lezioni nel DB
    tmp = info + ".tmp"
    with fs.open(tmp, "w", encoding="utf-8") as f:
        f.write("materia: BIOCHIMICA\n")
    fs.replace(tmp, info)
    with fs.open(info, "a", encoding="utf-8") as f:
        f.write("data: '2026-09-05'\n")
    with fs.open(info, encoding="utf-8") as f:
        assert f.read() == "materia: BIOCHIMICA\ndata: '2026-09-05'\n"
    with fs.open(os.path.join(db_lesson, "outline.json"), "w", encoding="utf-8") as f:
        json.dump({"units": []}, f)
    fs.makedirs(os.path.join(db_lesson, "assets", "images"), exist_ok=True)

    assert not os.path.exists(db_lesson)
    assert fs.isdir(db_lesson) and fs.isfile(info) and not fs.exists(tmp)
    assert fs.listdir(db_lesson) == ["info.yaml", "outline.json"]
    assert fs.getsize(info) == len("materia: BIOCHIMICA\ndata: '2026-09-05'\n")
    assert fs.sha256(info) and fs.real_path(info) is None
    fs.remove(os.path.join(db_lesson, "outline.json"))
    assert fs.listdir(db_lesson) == ["info.yaml"]
    with pytest.raises(FileNotFoundError):
        fs.open(os.path.join(db_lesson, "outline.json"))


def test_media_go_to_the_media_folder(db_lesson, rt_db):
    audio = os.path.join(db_lesson, "lezione.wav")
    fs.copy2(AUDIO_FIXTURE, audio)
    image = os.path.join(db_lesson, "assets", "images", "a1.png")
    with fs.open(image, "wb") as f:
        f.write(b"\x89PNG fake")

    media = fs.media_dir(rt_db)
    assert sorted(os.listdir(media)) == ["L1_a1.png", "L1_lezione.wav"]
    assert fs.real_path(audio) == os.path.join(media, "L1_lezione.wav")
    assert fs.isdir(os.path.join(db_lesson, "assets")) and fs.listdir(os.path.join(db_lesson, "assets", "images")) == ["a1.png"]
    with fs.open(image, "rb") as f:
        assert f.read() == b"\x89PNG fake"
    fs.rmtree(os.path.join(db_lesson, "assets"))
    assert os.listdir(media) == ["L1_lezione.wav"]
    with fs.external_output(os.path.join(db_lesson, "recall_audio_clips", "u1.wav")) as real:
        with open(real, "wb") as f:
            f.write(b"clip")
    assert fs.isfile(os.path.join(db_lesson, "recall_audio_clips", "u1.wav"))
    assert "L1_u1.wav" in os.listdir(media)


def test_lessons_root_lists_db_lessons_and_rename_moves_the_id(db_lesson, rt_db):
    from rt.core.lesson_index import scan_lessons
    with fs.open(lesson_path(db_lesson, "info.yaml"), "w", encoding="utf-8") as f:
        f.write("data: '2026-09-05'\nmateria: BIOCHIMICA\n")
    root = os.path.dirname(db_lesson)
    assert [e.folder_name for e in scan_lessons(root)] == [LESSON_NAME]

    renamed = os.path.join(root, "[2026-09-05] BIOCHIMICA - Titolo")
    fs.rename(db_lesson, renamed)
    assert fs.isfile(os.path.join(renamed, "info.yaml")) and not fs.exists(db_lesson)
    with session_scope(rt_db) as s:
        assert [l.folder_name for l in s.query(Lesson)] == ["[2026-09-05] BIOCHIMICA - Titolo"]


def test_lock_files_live_in_the_data_folder(db_lesson, rt_db):
    from rt.core.process_lock import lesson_lock_path, lesson_work_lock
    lock = lesson_lock_path(db_lesson)
    assert os.path.dirname(lock) == os.path.join(fs.data_dir(rt_db), "locks")
    with lesson_work_lock(db_lesson):
        pass
    assert not os.path.exists(db_lesson)


def test_read_snapshot_reads_each_lesson_once_and_sees_its_own_writes(db_lesson, rt_db, monkeypatch):
    with fs.open(os.path.join(db_lesson, "info.yaml"), "w") as f:
        f.write("materia: A\n")
    queries = []
    real_reader = fs._reader
    monkeypatch.setattr(fs, "_reader", lambda t: queries.append(t.rel) or real_reader(t))
    with fs.read_snapshot():
        for _ in range(3):
            assert fs.isfile(os.path.join(db_lesson, "info.yaml"))
            assert not fs.isfile(os.path.join(db_lesson, "manca.md"))
            assert fs.open(os.path.join(db_lesson, "info.yaml")).read() == "materia: A\n"
        assert len(queries) == 1
        with fs.open(os.path.join(db_lesson, "_state", "nuovo.json"), "w") as f:
            f.write("{}")
        fs.remove(os.path.join(db_lesson, "info.yaml"))
        assert fs.isfile(os.path.join(db_lesson, "_state", "nuovo.json"))
        assert not fs.isfile(os.path.join(db_lesson, "info.yaml"))
    assert fs.isfile(os.path.join(db_lesson, "nuovo.json"))


def test_new_lessons_can_stay_in_folders(rt_db, tmp_path):
    """storage.new_lessons = folder (settings) riporta al layout a cartelle."""
    from rt.db.repositories import SettingRepository
    assert fs.new_lessons_use_db()
    with session_scope(rt_db) as s:
        SettingRepository(s).set("storage.new_lessons", "folder")
    assert not fs.new_lessons_use_db()


# ---------------------------------------------------------------- migrazione ed export

@pytest.fixture
def folder_lesson(rt_db, tmp_path, monkeypatch):
    """Lezione in cartella completata (pipeline mock) con audio, immagine e stato Telegram."""
    root = isolated_workspace(tmp_path, monkeypatch)
    lesson_dir = make_lesson(root)
    add_audio(lesson_dir)
    run_mock_pipeline(lesson_dir)
    os.makedirs(os.path.join(lesson_dir, "assets", "images"))
    with open(os.path.join(lesson_dir, "assets", "images", "a1.png"), "wb") as f:
        f.write(b"\x89PNG fake")
    titled = [n for n in os.listdir(lesson_dir) if n.startswith("[2026-09-05]") and n.endswith(".md")]
    assert len(titled) == 1
    with open(os.path.join(lesson_dir, titled[0]), "a", encoding="utf-8") as f:
        f.write("\n![slide](assets/images/a1.png)\n")
    for junk in (".DS_Store", "info.yaml.tmp"):
        open(os.path.join(lesson_dir, junk), "w").close()
    key = os.path.join(os.path.realpath(lesson_dir), "_state", "telegram_audio_sent.json")
    with session_scope(rt_db) as s:
        s.add(StateDocument(key=key, payload={"x": 1}))
    return root, lesson_dir


def _contents(lesson_dir, names):
    out = {}
    for name in names:
        with fs.open(os.path.join(lesson_dir, name), "rb") as f:
            out[name] = f.read()
    return out


def test_migrate_storage_dry_run_changes_nothing(folder_lesson, rt_db):
    from rt.storage.migrate import migrate_storage
    root, lesson_dir = folder_lesson
    before = _tree(lesson_dir)
    report = migrate_storage(root, dry_run=True)
    assert [p.lesson_dir for p in report.plans] == [os.path.realpath(lesson_dir)]
    plan = report.plans[0]
    assert "info.yaml" in plan.files and "manifest.json" in plan.files  # _state/ appiattito
    assert "lezione.m4a" in plan.files and plan.media_bytes > 0
    assert set(plan.skipped) >= {".DS_Store", "info.yaml.tmp"}
    assert _tree(lesson_dir) == before and not fs.is_db_lesson(lesson_dir)
    assert not os.path.exists(fs.media_dir(rt_db))


def test_migrate_storage_moves_lessons_into_the_database(folder_lesson, rt_db):
    from rt.storage.migrate import migrate_storage, plan_lesson
    root, lesson_dir = folder_lesson
    plan = plan_lesson(lesson_dir)
    originals = {}
    for name, real in plan.files.items():
        with open(real, "rb") as f:
            originals[name] = f.read()

    report = migrate_storage(root)
    assert report.errors == [] and report.migrated == [os.path.realpath(lesson_dir)]
    assert not os.path.exists(lesson_dir)  # spostata, non cancellata:
    backup = os.path.join(report.backup_dir, "lezioni", LESSON_NAME)
    assert os.path.isfile(os.path.join(backup, "_state", "manifest.json"))
    assert os.path.isfile(report.database_backup)

    assert fs.is_db_lesson(lesson_dir)
    assert _contents(lesson_dir, originals) == originals
    assert sorted(os.listdir(fs.media_dir(rt_db))) == ["L1_a1.png", "L1_lezione.m4a"]
    with session_scope(rt_db) as s:
        keys = [d.key for d in s.query(StateDocument)]
    assert keys == [os.path.join(os.path.realpath(lesson_dir), "telegram_audio_sent.json")]

    # la pipeline continua a funzionare sulla lezione migrata (tutto già valido)
    result = run_mock_pipeline(lesson_dir)
    assert not os.path.exists(lesson_dir)
    assert migrate_storage(root).plans == []  # seconda esecuzione: niente da fare
    assert result is not None


def test_migrate_storage_keeps_the_folder_when_verification_fails(folder_lesson, rt_db, monkeypatch):
    from rt.storage import migrate
    root, lesson_dir = folder_lesson
    before = _tree(lesson_dir)
    monkeypatch.setattr(migrate.fs, "sha256", lambda path: "0" * 64)
    report = migrate.migrate_storage(root)
    assert report.migrated == [] and report.errors
    assert _tree(lesson_dir) == before and not fs.is_db_lesson(lesson_dir)
    assert fs.lesson_files(lesson_dir) == [] and os.listdir(fs.media_dir(rt_db)) == []


def test_export_final_markdown_with_images(folder_lesson, rt_db, tmp_path):
    from rt.storage.export import export_to_dir, export_zip
    from rt.storage.migrate import migrate_storage
    root, lesson_dir = folder_lesson
    folder_export = export_to_dir(lesson_dir, str(tmp_path / "prima"))
    migrate_storage(root)
    written = export_to_dir(lesson_dir, str(tmp_path / "dopo"))
    rel = lambda paths, base: sorted(os.path.relpath(p, base) for p in paths)
    assert rel(written, tmp_path / "dopo") == rel(folder_export, tmp_path / "prima")
    names = rel(written, tmp_path / "dopo" / LESSON_NAME)
    assert names[0] == "Errori concettuali.md" and names[1].startswith("[2026-09-05] BIOCHIMICA - ")
    assert names[2:] == ["assets/images/a1.png"]
    for a, b in zip(sorted(folder_export), sorted(written)):
        with open(a, "rb") as fa, open(b, "rb") as fb:
            assert fa.read() == fb.read()

    with zipfile.ZipFile(io.BytesIO(export_zip(lesson_dir, "all"))) as zf:
        members = zf.namelist()
    assert f"{LESSON_NAME}/info.yaml" in members and f"{LESSON_NAME}/lezione.m4a" in members
    assert f"{LESSON_NAME}/draft.json" in members


def test_cli_export_writes_the_files(folder_lesson, rt_db, tmp_path, capsys):
    from rt.cli import main
    from rt.storage.migrate import migrate_storage
    root, lesson_dir = folder_lesson
    migrate_storage(root)
    main(["export", LESSON_NAME, "-o", str(tmp_path / "out")])  # nome sotto lessons_root
    assert "Esportati 3 file" in capsys.readouterr().out
    main(["export", lesson_dir, "-o", str(tmp_path / "zip"), "--zip", "--all"])
    assert os.listdir(tmp_path / "zip") == [f"{LESSON_NAME}.zip"]


def test_api_export_endpoint(folder_lesson, rt_db, api_client):
    from rt.services.lesson_service import lesson_id_for_dir
    from rt.storage.migrate import migrate_storage
    root, lesson_dir = folder_lesson
    migrate_storage(root)
    lesson_id = lesson_id_for_dir(lesson_dir)
    res = api_client.get(f"/api/v1/lessons/{lesson_id}/export")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/markdown")
    assert "attachment" in res.headers["content-disposition"]
    assert "![slide](assets/images/a1.png)" in res.text
    res = api_client.get(f"/api/v1/lessons/{lesson_id}/export", params={"format": "zip", "scope": "final"})
    assert res.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
        assert f"{LESSON_NAME}/assets/images/a1.png" in zf.namelist()
    # le altre risposte dell'API non cambiano forma per una lezione nel DB
    detail = api_client.get(f"/api/v1/lessons/{lesson_id}").json()
    assert detail["id"] == lesson_id and detail["has_audio"] is True
    assert api_client.get(f"/api/v1/lessons/{lesson_id}/audio").status_code == 200
    assert api_client.get(f"/api/v1/lessons/{lesson_id}/document").json()["final"] is True


def test_migrate_storage_skips_a_lesson_being_worked_on(folder_lesson, rt_db):
    from rt.core.process_lock import lesson_work_lock
    from rt.storage.migrate import migrate_storage
    root, lesson_dir = folder_lesson
    with lesson_work_lock(lesson_dir):
        report = migrate_storage(root)
    assert report.migrated == [] and "in lavorazione" in report.errors[0]
    assert os.path.isdir(lesson_dir) and not fs.is_db_lesson(lesson_dir)
