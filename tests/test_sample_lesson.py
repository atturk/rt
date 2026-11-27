"""La lezione di esempio inclusa in RT deve aprirsi senza errori (bug: outline.json nel
vecchio formato dava «Errore interno del server» al primo clic dell'utente)."""
import io
import json
import zipfile

import pytest

from rt.core import paths
from rt.core.models import Draft, Outline

PAGES = ["", "/outline", "/document", "/phases", "/issues", "/decisions", "/sections", "/sources",
         "/study", "/review/units", "/recall/questions", "/recall/units", "/recall", "/versions",
         "/highlights", "/relevance", "/classifier", "/images", "/enrichment"]


def _archive_json(name):
    with zipfile.ZipFile(paths.sample_lesson_path()) as archive:
        member = next(n for n in archive.namelist() if n.endswith("/" + name) and "/history/" not in n)
        return json.loads(archive.read(member))


def test_bundled_sample_uses_current_schema():
    Outline.model_validate(_archive_json("outline.json"))
    draft = Draft.model_validate(_archive_json("draft.json"))
    assert [u.unit_id for u in draft.units] == ["1.1", "1.2", "2.1"]
    questions = _archive_json("recall_questions.json")["questions"]
    assert questions and all("mock" not in q["question_text"].lower() for q in questions)


@pytest.mark.parametrize("page", PAGES)
def test_sample_lesson_pages_open(api_client, rt_db, page):
    lesson_id = api_client.post("/api/v1/lessons/sample").json()["lesson_id"]
    res = api_client.get(f"/api/v1/lessons/{lesson_id}{page}")
    assert res.status_code < 500, (page, res.status_code, res.text[:300])


def test_sample_outline_and_document(api_client, rt_db):
    lesson_id = api_client.post("/api/v1/lessons/sample").json()["lesson_id"]
    outline = api_client.get(f"/api/v1/lessons/{lesson_id}/outline")
    assert outline.status_code == 200
    assert "Principi di RT" in outline.text
    document = api_client.get(f"/api/v1/lessons/{lesson_id}/document")
    assert document.status_code == 200
    assert "unità logiche" in document.text
