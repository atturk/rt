"""
tests/test_document_edit.py
RT4-FA3: anteprima modificabile. Markdown -> bozza -> Markdown: identico se non si cambia
nulla; testo, titoli, timecode e immagini salvati; errori con riga e motivo; issue orfane;
documento finale da ricreare. Più gli endpoint e l'avviso "Non mostrare più".
"""
import pytest

from rt.core.idempotency import PhaseStatus, check_phase_status
from rt.pipeline.build import render_lesson_documents, run_build
from rt.pipeline.document_edits import load_document_edits
from rt.pipeline.rewrite import load_draft
from rt.services.document_edit_service import DocumentEditError, parse_timecode, save_document_edit
from rt.services.lesson_service import document_sections, strip_yaml_frontmatter
from rt.services.review_service import orphan_issue_ids
from tests.api_support import isolated_workspace, make_lesson, run_mock_pipeline


def _preview(lesson_dir):
    return strip_yaml_frontmatter(render_lesson_documents(lesson_dir)["rielaborato"])


def _built_lesson(root, with_review=False):
    from rt.services.outline_service import approve_outline
    lesson_dir = make_lesson(root)
    run_mock_pipeline(lesson_dir, with_review=with_review, auto_accept=False)
    approve_outline(lesson_dir, channel="api")
    run_mock_pipeline(lesson_dir, with_review=with_review, auto_accept=False)
    if check_phase_status(lesson_dir, "build")[0] != PhaseStatus.VALID:
        run_build(lesson_dir, force=True)
    return lesson_dir


def _synthetic_lesson(root, contents=None):
    """Tre unità in due sezioni su sei segmenti di 10 s, con il documento finale creato.
    contents: testo di alcune unità al posto di quello predefinito."""
    import os
    from rt.core.idempotency import compute_source_fingerprint, record_phase_fingerprint
    from rt.core.lesson_paths import lesson_path
    from rt.core.manifest import init_or_update_manifest
    from rt.core.models import Draft, DraftUnit, Outline, OutlineMacro, OutlineUnit
    from rt.core.segments import Segment, SegmentsData
    from rt.core.timestamp import format_timestamp
    from rt.pipeline.outline import save_outline
    from rt.pipeline.rewrite import save_draft
    lesson_dir = os.path.join(root, "[2026-09-11] BIOCHIMICA - Lipidi")
    os.makedirs(os.path.join(lesson_dir, "_state"), exist_ok=True)
    with open(os.path.join(lesson_dir, "info.yaml"), "w", encoding="utf-8") as f:
        f.write("data: '2026-09-11'\nmateria: BIOCHIMICA\nargomenti: Lipidi\n")
    segs = [Segment(id=f"seg_{i:06d}", index=i, start_seconds=(i - 1) * 10.0, end_seconds=i * 10.0,
                    start_formatted=format_timestamp((i - 1) * 10), end_formatted=format_timestamp(i * 10),
                    text=f"Segmento {i}", text_raw=f"Segmento {i}") for i in range(1, 7)]
    with open(lesson_path(lesson_dir, "segments.json"), "w", encoding="utf-8") as f:
        f.write(SegmentsData(segments=segs).model_dump_json())
    with open(lesson_path(lesson_dir, "transcript_normalized.md"), "w", encoding="utf-8") as f:
        f.write("Trascritto")
    spans = {"1.1": (1, 2), "1.2": (3, 4), "2.1": (5, 6)}
    unit = lambda uid, title: OutlineUnit(id=uid, title=title, start_segment_id=f"seg_{spans[uid][0]:06d}",
                                          end_segment_id=f"seg_{spans[uid][1]:06d}", key_concepts=["lipidi"])
    save_outline(Outline(schema_version="1.0", lesson_title="Lipidi", macro_sections=[
        OutlineMacro(id="1", title="Struttura", units=[unit("1.1", "Acidi grassi"), unit("1.2", "Trigliceridi")]),
        OutlineMacro(id="2", title="Funzioni", units=[unit("2.1", "Riserva energetica")]),
    ]), lesson_dir)
    save_draft(Draft(schema_version="1.0", units=[
        DraftUnit(unit_id=uid, title=title, start_segment_id=f"seg_{a:06d}", end_segment_id=f"seg_{b:06d}",
                  source_segment_ids=[f"seg_{i:06d}" for i in range(a, b + 1)], content=(contents or {}).get(uid, f"Testo dell'unità {uid}."))
        for uid, title, (a, b) in [("1.1", "Acidi grassi", spans["1.1"]), ("1.2", "Trigliceridi", spans["1.2"]),
                                   ("2.1", "Riserva energetica", spans["2.1"])]
    ]), lesson_dir)
    init_or_update_manifest(lesson_dir, lesson_id="lipidi", date="2026-09-11", subject="BIOCHIMICA",
                            current_state="draft_validato")
    for ph in ("prepare", "outline", "rewrite"):
        record_phase_fingerprint(lesson_dir=lesson_dir, phase_name=ph,
                                 source_fingerprint=compute_source_fingerprint(lesson_dir, ph), artifact_fingerprints={})
    run_build(lesson_dir, force=True)
    assert check_phase_status(lesson_dir, "build")[0] == PhaseStatus.VALID
    return lesson_dir


@pytest.fixture
def root(tmp_path, monkeypatch, rt_db):
    return isolated_workspace(tmp_path, monkeypatch)


def _unit_lines(markdown):
    """(indice della riga del titolo, id) delle unità."""
    lines = markdown.split("\n")
    return lines, [(i, line.split(" ", 2)[1]) for i, line in enumerate(lines) if line.startswith("### ")]


def test_parse_timecode():
    assert parse_timecode("12:34") == 754
    assert parse_timecode("1:02:03") == 3723
    assert parse_timecode("00:10") == 10
    assert parse_timecode("12:60") is None
    assert parse_timecode("1:60:00") is None
    assert parse_timecode("dodici") is None


def test_unchanged_markdown_roundtrips_and_changes_nothing(root):
    lesson_dir = _built_lesson(root)
    before = _preview(lesson_dir)
    draft_before = load_draft(lesson_dir).model_dump()
    result = save_document_edit(lesson_dir, before)
    assert result["changed"] is False and result["units_changed"] == []
    assert result["build_status"] == "VALID"
    assert _preview(lesson_dir) == before
    assert load_draft(lesson_dir).model_dump() == draft_before


@pytest.mark.parametrize("heading", ["### Approfondimento clinico", "## Nota bene", "### Caso: diabete", "#### Dettaglio"])
def test_headings_written_inside_a_unit_are_text_not_structure(root, heading):
    """Il testo di un'unità può avere titoli suoi (scritti dal modello o a mano): non sono
    sezioni né unità, quindi né il documento intatto né una modifica al testo vanno rifiutati."""
    lesson_dir = _synthetic_lesson(root, {"1.2": f"Primo paragrafo.\n\n{heading}\n\nSecondo paragrafo."})
    before = _preview(lesson_dir)
    assert heading in before
    assert save_document_edit(lesson_dir, before)["changed"] is False
    edited = before.replace("Secondo paragrafo.", "**Secondo** paragrafo.").replace("Testo dell'unità 2.1.", "*Testo* dell'unità 2.1.")
    result = save_document_edit(lesson_dir, edited)
    assert sorted(result["units_changed"]) == ["1.2", "2.1"]
    assert heading in _preview(lesson_dir) and "**Secondo** paragrafo." in _preview(lesson_dir)


def test_text_title_and_timecode_are_saved_and_the_build_goes_stale(root):
    from rt.core.segments import load_segments_json
    from rt.core.lesson_paths import lesson_path
    from rt.core.timestamp import format_timestamp
    lesson_dir = _synthetic_lesson(root)
    lines, units = _unit_lines(_preview(lesson_dir))
    assert len(units) >= 2
    (first_i, first_id), (second_i, second_id) = units[0], units[1]
    segments = load_segments_json(lesson_path(lesson_dir, "segments.json")).segments
    tc_first = lines[first_i + 1]
    tc_second = lines[second_i + 1]
    first_s, second_s = parse_timecode(tc_first), parse_timecode(tc_second)
    # un tempo fra i due timecode, su un segmento diverso da quello attuale della seconda unità
    target = next(s for s in segments if first_s < s.start_seconds < second_s)
    lines[first_i] = f"### {first_id} Titolo riscritto a mano"
    content_i = next(i for i in range(first_i + 2, len(lines)) if lines[i].strip())
    lines[content_i] = "Paragrafo scritto a mano.\n\nSecondo paragrafo scritto a mano."
    lines[second_i + 1] = format_timestamp(target.start_seconds + 5)
    result = save_document_edit(lesson_dir, "\n".join(lines))

    assert result["changed"] is True and result["units_changed"] == [first_id]
    assert result["build_status"] == "STALE"
    assert "modifiche all'anteprima" in result["build_reason"] or "bozza" in result["build_reason"]
    draft = {u.unit_id: u for u in load_draft(lesson_dir).units}
    assert draft[first_id].content == "Paragrafo scritto a mano.\n\nSecondo paragrafo scritto a mano."
    edits = load_document_edits(lesson_dir)["units"]
    assert edits[first_id] == {"title": "Titolo riscritto a mano", "edited": True}

    after = _preview(lesson_dir)
    assert f"### {first_id} Titolo riscritto a mano" in after
    assert "Paragrafo scritto a mano.\n\nSecondo paragrafo scritto a mano." in after
    sections = {s["unit_id"]: s for s in document_sections(lesson_dir)}
    assert sections[first_id]["title"] == "Titolo riscritto a mano"
    assert edits[second_id] == {"start_segment_id": target.id}
    assert sections[second_id]["start_seconds"] == target.start_seconds
    assert f"### {second_id} Trigliceridi\n{format_timestamp(target.start_seconds)}\n" in after
    # il Markdown salvato si rilegge identico
    assert save_document_edit(lesson_dir, after)["changed"] is False

    # il documento ricreato contiene le modifiche
    build = run_build(lesson_dir)
    with open(build["rielaborato"], encoding="utf-8") as f:
        final = f.read()
    assert "Titolo riscritto a mano" in final and "Secondo paragrafo scritto a mano." in final
    assert check_phase_status(lesson_dir, "build")[0] == PhaseStatus.VALID


def test_document_has_no_title_heading_and_a_legacy_one_is_tolerated(root):
    """Il titolo sta nel nome del file e nel frontmatter: niente H1 nel documento (Obsidian
    lo mostrerebbe due volte). Un H1 in cima, dai documenti delle versioni precedenti, si
    ignora quando si salva l'anteprima."""
    lesson_dir = _synthetic_lesson(root)
    rendered = render_lesson_documents(lesson_dir)["rielaborato"]
    assert not any(line.startswith("# ") for line in rendered.split("\n"))
    assert rendered.startswith("---\ntitolo: ")
    assert strip_yaml_frontmatter(rendered).startswith("## ")

    legacy = "# [2026-09-28] MATERIA - Titolo\n\n" + _preview(lesson_dir)
    save_document_edit(lesson_dir, legacy)


def test_errors_carry_line_and_reason_and_nothing_is_saved(root):
    lesson_dir = _synthetic_lesson(root)
    original = _preview(lesson_dir)
    lines, units = _unit_lines(original)
    (first_i, first_id), (second_i, _second_id) = units[0], units[1]

    bad = list(lines)
    bad[second_i + 1] = "99:59:59"
    with pytest.raises(DocumentEditError) as exc:
        save_document_edit(lesson_dir, "\n".join(bad))
    assert exc.value.errors[0]["line"] == second_i + 2
    assert "oltre la fine dell'audio" in exc.value.errors[0]["message"]

    bad = list(lines)
    bad[second_i + 1] = "00:00"
    bad[first_i + 1] = "00:05"
    with pytest.raises(DocumentEditError) as exc:
        save_document_edit(lesson_dir, "\n".join(bad))
    assert any("deve venire dopo" in e["message"] for e in exc.value.errors)

    bad = list(lines)
    bad[first_i + 1] = "adesso"
    with pytest.raises(DocumentEditError) as exc:
        save_document_edit(lesson_dir, "\n".join(bad))
    assert exc.value.errors[0]["line"] == first_i + 2 and "timecode" in exc.value.errors[0]["message"]

    bad = [line for i, line in enumerate(lines) if i != second_i]
    with pytest.raises(DocumentEditError) as exc:
        save_document_edit(lesson_dir, "\n".join(bad))
    assert any("non si" in e["message"] for e in exc.value.errors)

    bad = list(lines)
    bad.insert(first_i, "![foto](assets/images/inesistente.png)")
    bad.insert(first_i, "")
    with pytest.raises(DocumentEditError) as exc:
        save_document_edit(lesson_dir, "\n".join(bad))
    assert any("Immagine non trovata" in e["message"] for e in exc.value.errors)

    bad = list(lines)
    bad.insert(first_i, "# Un titolo in mezzo")
    with pytest.raises(DocumentEditError) as exc:
        save_document_edit(lesson_dir, "\n".join(bad))
    assert exc.value.errors[0]["line"] == first_i + 1 and "primo livello" in exc.value.errors[0]["message"]

    assert _preview(lesson_dir) == original
    assert check_phase_status(lesson_dir, "build")[0] == PhaseStatus.VALID


def test_removed_claim_makes_the_issue_orphan_not_deleted(root):
    from rt.pipeline.review import load_science_issues
    lesson_dir = _built_lesson(root, with_review=True)
    issues = load_science_issues(lesson_dir)
    issue = next(i for i in issues if i.claim and i.unit_id)
    assert issue.id not in orphan_issue_ids(lesson_dir)
    markdown = _preview(lesson_dir)
    assert issue.claim in markdown
    result = save_document_edit(lesson_dir, markdown.replace(issue.claim, "frase riscritta a mano"))
    assert issue.id in result["orphan_issues"]
    assert issue.id in {i.id for i in load_science_issues(lesson_dir)}  # non cancellata


def test_accepted_fix_written_in_the_preview_is_not_reapplied_nor_orphan(root):
    from rt.pipeline.review import load_science_issues
    from rt.services.review_service import record_review_decision
    lesson_dir = _built_lesson(root, with_review=True)
    issue = next(i for i in load_science_issues(lesson_dir) if i.claim and i.unit_id and i.suggested_fix)
    record_review_decision(lesson_dir, issue.id, "edited", "CORREZIONE DECISA", channel="api", actor="test")
    markdown = _preview(lesson_dir)
    assert markdown.count("CORREZIONE DECISA") == 1
    lines, units = _unit_lines(markdown)
    unit_i = next(i for i, uid in units if uid == issue.unit_id)
    content_i = next(i for i in range(unit_i + 2, len(lines)) if lines[i].strip())
    lines[content_i] = lines[content_i] + " Aggiunta a mano."
    result = save_document_edit(lesson_dir, "\n".join(lines))
    assert result["units_changed"] == [issue.unit_id]
    after = _preview(lesson_dir)
    assert after.count("CORREZIONE DECISA") == 1 and "Aggiunta a mano." in after
    assert issue.id not in result["orphan_issues"]


# ---------------------------------------------------------------- API

def test_api_check_and_save(root, api_client):
    lesson_dir = _built_lesson(root)
    lesson_id = api_client.get("/api/v1/lessons").json()[0]["id"]
    markdown = api_client.get(f"/api/v1/lessons/{lesson_id}/document").json()["markdown"]

    check = api_client.post(f"/api/v1/lessons/{lesson_id}/document/check", json={"markdown": markdown + "\n\n## 99. Nuova"})
    assert check.status_code == 200
    body = check.json()
    assert "<h2>" in body["html"] and body["errors"] and body["errors"][0]["line"]

    bad = api_client.put(f"/api/v1/lessons/{lesson_id}/document/draft", json={"markdown": markdown.replace("\n### ", "\n#### ", 1)})
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "document_invalid"
    assert bad.json()["error"]["details"]["errors"]

    lines, units = _unit_lines(markdown)
    first_i = units[0][0]
    content_i = next(i for i in range(first_i + 2, len(lines)) if lines[i].strip())
    lines[content_i] = "Testo salvato dall'API."
    ok = api_client.put(f"/api/v1/lessons/{lesson_id}/document/draft", json={"markdown": "\n".join(lines)})
    assert ok.status_code == 200, ok.text
    assert ok.json()["build_status"] == "STALE" and ok.json()["units_changed"] == [units[0][1]]
    doc = api_client.get(f"/api/v1/lessons/{lesson_id}/document").json()
    assert doc["final"] is False and "Testo salvato dall'API." in doc["markdown"]
    assert check_phase_status(lesson_dir, "build")[0] == PhaseStatus.STALE


def test_api_notices_dismissed_server_side(root, api_client):
    assert api_client.get("/api/v1/settings").json()["notices"]["dismissed"] == []
    res = api_client.put("/api/v1/settings/notices", json={"notice": "preview_edit_beta"})
    assert res.status_code == 200 and res.json()["notices"]["dismissed"] == ["preview_edit_beta"]
    api_client.put("/api/v1/settings/notices", json={"notice": "preview_edit_issues", "dismissed": True})
    assert api_client.get("/api/v1/settings").json()["notices"]["dismissed"] == ["preview_edit_beta", "preview_edit_issues"]
    api_client.put("/api/v1/settings/notices", json={"notice": "preview_edit_beta", "dismissed": False})
    assert api_client.get("/api/v1/settings").json()["notices"]["dismissed"] == ["preview_edit_issues"]
    assert api_client.put("/api/v1/settings/notices", json={"notice": "altro"}).status_code == 422
