import hashlib

from rt.db.health import check_database
from rt.db.models import Lesson, LessonFile
from rt.db.session import session_scope


def test_db_check_reports_content_checksum_and_missing_media(rt_db, tmp_path):
    with session_scope(rt_db) as session:
        lesson = Lesson(path=str(tmp_path / "lezione"), folder_name="lezione", storage="db")
        session.add(lesson)
        session.flush()
        session.add(LessonFile(lesson_id=lesson.id, name="info.yaml", content=b"abc", size=3,
                               sha256=hashlib.sha256(b"abc").hexdigest(), mtime=0))
        session.add(LessonFile(lesson_id=lesson.id, name="audio.wav", media_path="missing.wav",
                               content=None, size=10, sha256="a" * 64, mtime=0))
    assert check_database(rt_db) == ["lezione/audio.wav: file media mancante."]
    with session_scope(rt_db) as session:
        row = session.query(LessonFile).filter_by(name="info.yaml").one()
        row.sha256 = "b" * 64
    problems = check_database(rt_db)
    assert "lezione/info.yaml: checksum del contenuto incoerente." in problems
    assert "lezione/audio.wav: file media mancante." in problems


def test_db_check_reports_unreferenced_media(rt_db, tmp_path):
    from rt.storage import fs

    media_dir = fs.media_dir(rt_db)
    import os
    os.makedirs(media_dir, exist_ok=True)
    with open(os.path.join(media_dir, "unused.bin"), "wb") as stream:
        stream.write(b"unused")
    assert check_database(rt_db) == ["Media orfano non referenziato: unused.bin"]


def test_db_check_reports_folder_storage_for_explicit_conversion(rt_db, tmp_path):
    with session_scope(rt_db) as session:
        session.add(Lesson(path=str(tmp_path / "legacy"), folder_name="legacy", storage="folder"))
    assert check_database(rt_db) == [
        "1 lezioni usano ancora lo storage a cartelle; convertile con 'rt db migrate-storage'."
    ]


def test_db_check_ignores_system_files_and_quick_skips_media_checksums(rt_db, tmp_path):
    import os
    from rt.storage import fs

    media_dir = fs.media_dir(rt_db)
    os.makedirs(media_dir, exist_ok=True)
    for name in (".DS_Store", "upload.tmp"):
        with open(os.path.join(media_dir, name), "wb") as stream:
            stream.write(b"x")
    with open(os.path.join(media_dir, "audio.wav"), "wb") as stream:
        stream.write(b"0123456789")
    with session_scope(rt_db) as session:
        lesson = Lesson(path=str(tmp_path / "lezione"), folder_name="lezione", storage="db")
        session.add(lesson)
        session.flush()
        session.add(LessonFile(lesson_id=lesson.id, name="audio.wav", media_path="audio.wav",
                               content=None, size=10, sha256="a" * 64, mtime=0))
    assert check_database(rt_db) == ["lezione/audio.wav: checksum media incoerente."]
    assert check_database(rt_db, quick=True) == []


def test_db_check_reports_folder_lessons_missing_from_the_database(rt_db, tmp_path):
    import os
    root = tmp_path / "lezioni"
    lesson = root / "[2026-09-01] BIOCHIMICA"
    lesson.mkdir(parents=True)
    (lesson / "info.yaml").write_text("data: '2026-09-01'\nmateria: BIOCHIMICA\n", encoding="utf-8")
    problems = check_database(rt_db, lessons_root=str(root))
    assert len(problems) == 1 and "non sono nel database" in problems[0] and "migrate-storage" in problems[0]
