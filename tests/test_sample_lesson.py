"""Test completi per la lezione di esempio (guida rapida P12 + isolamento e pulizia P17)."""
import io
import json
import zipfile

import pytest

from rt.core import paths
from rt.core.models import Draft, Outline
from rt.db.models import (
    Lesson,
    LessonFile,
    LessonSummaryCache,
    PhaseRun,
    Subject,
    SubjectTeacher,
)
from rt.db.session import session_scope

PAGES = [
    "",
    "/outline",
    "/document",
    "/phases",
    "/issues",
    "/decisions",
    "/sections",
    "/sources",
    "/study",
    "/review/units",
    "/recall/questions",
    "/recall/units",
    "/recall",
    "/versions",
    "/highlights",
    "/relevance",
    "/classifier",
    "/images",
    "/enrichment",
]


def _archive_json(name):
    with zipfile.ZipFile(paths.sample_lesson_path()) as archive:
        member = next(n for n in archive.namelist() if n.endswith("/" + name) and "/history/" not in n)
        return json.loads(archive.read(member))


def test_bundled_sample_uses_current_schema_and_quickstart_content():
    outline = Outline.model_validate(_archive_json("outline.json"))
    assert len(outline.macro_sections) == 4
    assert [m.title for m in outline.macro_sections] == [
        "Cos'è RT",
        "Creare una lezione",
        "Verificare e correggere",
        "Studiare",
    ]

    draft = Draft.model_validate(_archive_json("draft.json"))
    assert [u.unit_id for u in draft.units] == ["1.1", "1.2", "2.1", "2.2", "3.1", "3.2", "4.1", "4.2"]
    for unit in draft.units:
        words = len(unit.content.split())
        assert 80 <= words <= 150, (unit.unit_id, words)

    questions = _archive_json("recall_questions.json")["questions"]
    assert 4 <= len(questions) <= 6
    assert all("mock" not in q["question_text"].lower() for q in questions)
    sections_covered = {q["unit_ids"][0].split(".")[0] for q in questions}
    assert sections_covered == {"1", "2", "3", "4"}


@pytest.mark.parametrize("page", PAGES)
def test_sample_lesson_pages_open(api_client, rt_db, page):
    lesson_id = api_client.post("/api/v1/lessons/sample").json()["lesson_id"]
    res = api_client.get(f"/api/v1/lessons/{lesson_id}{page}")
    assert res.status_code < 500, (page, res.status_code, res.text[:300])


def test_sample_outline_and_document(api_client, rt_db):
    lesson_id = api_client.post("/api/v1/lessons/sample").json()["lesson_id"]
    outline = api_client.get(f"/api/v1/lessons/{lesson_id}/outline")
    assert outline.status_code == 200
    macros = outline.json()["macro_sections"]
    assert len(macros) == 4
    assert sum(len(m["units"]) for m in macros) == 8
    document = api_client.get(f"/api/v1/lessons/{lesson_id}/document")
    assert document.status_code == 200
    assert "Dalla registrazione al testo" in document.text
    assert "Stati di studio e calendario" in document.text


def test_sample_leaves_no_trace_in_subjects_calendar_recall_or_telegram(api_client, rt_db, monkeypatch):
    from rt.services.lesson_service import resolve_lesson_dir
    from rt.telegram import notify

    res = api_client.post("/api/v1/lessons/sample")
    assert res.status_code == 201
    lesson_id = res.json()["lesson_id"]

    # Nell'elenco lezioni è marcata come esempio e non espone materia/docente fittizi
    lessons = api_client.get("/api/v1/lessons").json()
    sample_row = next(row for row in lessons if row["id"] == lesson_id)
    assert sample_row["is_sample"] is True
    assert sample_row["materia"] == ""
    assert sample_row["docente"] == ""
    assert api_client.get("/api/v1/lessons", params={"materia": "ESEMPIO"}).json() == []

    # Niente ESEMPIO o Team RT in materie, calendario e recall globale
    assert api_client.get("/api/v1/subjects").json() == []
    assert api_client.get("/api/v1/recall/subjects").json() == []
    cal = api_client.get("/api/v1/calendar/week", params={"date": "2026-10-01"}).json()
    assert all(ev.get("materia") != "ESEMPIO" for day in cal["days"] for ev in day["events"])
    assert api_client.get("/api/v1/calendar/missing").json()["subjects"] == []

    # Nessuna notifica Telegram per la lezione di esempio
    sent = []
    monkeypatch.setattr(notify, "send_notification", lambda *args, **kwargs: sent.append((args, kwargs)) or True)
    lesson_dir = resolve_lesson_dir(lesson_id)
    assert notify.notify_build_completed(lesson_dir, {}, "Introduzione a RT") is False
    assert notify.notify_review_completed(lesson_dir, 1, "Introduzione a RT") is False
    assert notify.notify_decision_needed("science_issue", lesson_dir, "Introduzione a RT", 1) is False
    assert notify.notify_job_failed(lesson_dir, "Introduzione a RT", "errore") is False
    assert sent == []


def test_delete_sample_removes_all_rows_and_legacy_residues_and_allows_reimport(api_client, rt_db):
    lesson_id = api_client.post("/api/v1/lessons/sample").json()["lesson_id"]

    # Simula eventuali residui lasciati da una 4.3.9 prima dell'eliminazione
    with session_scope(rt_db) as s:
        s.add(Subject(nome="ESEMPIO"))
        s.add(SubjectTeacher(materia="ESEMPIO", nome="Team RT"))

    deleted = api_client.delete(f"/api/v1/lessons/{lesson_id}")
    assert deleted.status_code == 204

    with session_scope(rt_db) as s:
        assert s.query(Lesson).count() == 0
        assert s.query(LessonFile).count() == 0
        assert s.query(PhaseRun).count() == 0
        assert s.query(LessonSummaryCache).count() == 0
        assert s.query(Subject).count() == 0
        assert s.query(SubjectTeacher).count() == 0

    # Reimportazione immediata dopo la cancellazione
    reimported = api_client.post("/api/v1/lessons/sample")
    assert reimported.status_code == 201, reimported.text
    new_id = reimported.json()["lesson_id"]
    assert api_client.get(f"/api/v1/lessons/{new_id}/outline").status_code == 200


def test_sample_generation_without_and_with_dummy_screenshot(api_client, rt_db, tmp_path, monkeypatch):
    from PIL import Image
    from scripts.make_sample_lesson import build_sample_lesson
    from rt.core import paths as rt_paths

    # 1. Senza screenshot la generazione riesce senza immagini
    no_shots_archive = tmp_path / "no-shots.rt"
    build_sample_lesson(str(no_shots_archive), screenshot_dir=str(tmp_path / "missing"))
    with zipfile.ZipFile(no_shots_archive) as zf:
        assert not any("/assets/images/" in name for name in zf.namelist())

    # 2. Con uno screenshot finto per 1.1 l'unità ha l'immagine nel documento e nell'API
    shots_dir = tmp_path / "shots"
    shots_dir.mkdir()
    buf = io.BytesIO()
    Image.new("RGB", (64, 40), color=(40, 110, 200)).save(buf, format="WEBP")
    (shots_dir / "1.1.webp").write_bytes(buf.getvalue())

    with_shot_archive = tmp_path / "with-shot.rt"
    build_sample_lesson(str(with_shot_archive), screenshot_dir=str(shots_dir))

    monkeypatch.setattr(rt_paths, "sample_lesson_path", lambda: str(with_shot_archive))
    res = api_client.post("/api/v1/lessons/sample")
    assert res.status_code == 201
    lesson_id = res.json()["lesson_id"]

    doc = api_client.get(f"/api/v1/lessons/{lesson_id}/document").json()
    unit_1_1 = next(s for s in doc["sections"] if s["unit_id"] == "1.1")
    assert len(unit_1_1["immagini_sezione"]) == 1
    assert unit_1_1["immagini_sezione"][0].endswith(".webp")
    assert unit_1_1["immagini_sezione"][0] in doc["markdown"]

    imgs = api_client.get(f"/api/v1/lessons/{lesson_id}/images").json()["images"]
    assert any(img["in_assets"] and "1.1" in img["units"] for img in imgs)
