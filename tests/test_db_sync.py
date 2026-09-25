"""
tests/test_db_sync.py
RT4-B2: import delle lezioni nel DB (rt db sync), dual-write dalle scritture di info.yaml,
manifest e ledger, confronto DB/file (rt db check) e funzionamento senza DB o con DB rotto.
"""
import json
import os

import pytest

from rt.core.manifest import init_or_update_manifest
from rt.core.state import WorkflowState, transition_to
from rt.db.engine import get_database, reset_database_cache
from rt.db.repositories import DecisionRepository, IssueRepository, LessonRepository, PhaseRunRepository
from rt.db.session import session_scope
from rt.db.sync import check_all, sync_all
from rt.pipeline.ledger import get_ledger_path, record_decision
from tests.golden_support import LESSON_NAME, load_golden, scenario_audio_full


def _make_lesson(root, name, materia="BIOCHIMICA", decisions=0, issues=0):
    lesson_dir = os.path.join(root, name)
    state = os.path.join(lesson_dir, "_state")
    os.makedirs(state)
    with open(os.path.join(state, "info.yaml"), "w", encoding="utf-8") as f:
        f.write(f"data: '2026-09-0{len(name) % 9 + 1}'\nmateria: {materia.lower()}\ntitolo: '{name}'\n"
                f"argomenti: Lipidi\nfase_corrente: preparato\nstato: preparato\n")
    with open(os.path.join(state, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"lesson_id": name, "lesson_dir": lesson_dir, "date": "2026-09-01", "subject": materia,
                   "current_state": "preparato", "created_at": "x", "updated_at": "x",
                   "phase_records": {"prepare": {"status": "VALID", "source_fingerprint": "abc",
                                                 "processor_version": "prepare_v1.0", "updated_at": "t1"},
                                     "outline": {"status": "STALE", "stale_reason": "input cambiato"}}}, f)
    if issues:
        with open(os.path.join(state, "science_issues.json"), "w", encoding="utf-8") as f:
            json.dump([{"id": f"sci_{i:06d}", "type": "ERR_CONCETTUALE", "severity": "high", "unit_id": "u1",
                        "claim": "c", "reason": "r"} for i in range(issues)], f)
    if decisions:
        with open(os.path.join(state, "review_decisions.json"), "w", encoding="utf-8") as f:
            json.dump({"schema_version": "1.0", "decisions": [
                {"issue_id": f"sci_{i:06d}", "decision": "accepted", "resolved_text": "t",
                 "resolved_by": "user", "timestamp": f"2026-09-01T10:00:0{i}"} for i in range(decisions)]}, f)
    return lesson_dir


@pytest.fixture
def lessons(tmp_path):
    root = tmp_path / "lezioni"
    root.mkdir()
    dirs = [
        _make_lesson(str(root), "[2026-09-01] BIOCHIMICA - Lipidi", issues=3, decisions=2),
        _make_lesson(str(root), "[2026-09-02] FISIOLOGIA - Rene", materia="Fisiologia"),
        _make_lesson(str(root), "[2026-09-03] ANATOMIA - Cuore", issues=1),
    ]
    (root / "non una lezione").mkdir()
    return str(root), dirs


def _file_snapshot(dirs):
    snap = {}
    for d in dirs:
        for dirpath, _, files in os.walk(d):
            for name in files:
                path = os.path.join(dirpath, name)
                with open(path, "rb") as f:
                    snap[path] = f.read()
    return snap


def test_sync_imports_all_lessons_without_touching_files(rt_db, lessons):
    root, dirs = lessons
    before = _file_snapshot(dirs)
    assert sync_all(rt_db, root) == {"synced": 3, "errors": []}
    assert _file_snapshot(dirs) == before
    with session_scope(rt_db) as s:
        rows = LessonRepository(s).list_all(under_root=root)
        assert [r.folder_name for r in rows] == sorted(os.path.basename(d) for d in dirs)
        lipidi = LessonRepository(s).get_by_path(dirs[0])
        assert lipidi.materia == "BIOCHIMICA" and lipidi.workflow_state == "preparato"
        runs = PhaseRunRepository(s).for_lesson(lipidi)
        assert runs["prepare"].status == "VALID" and runs["prepare"].source_fingerprint == "abc"
        assert runs["outline"].stale_reason == "input cambiato"
        assert len(IssueRepository(s).for_lesson(lipidi)) == 3
        assert [d.issue_id for d in DecisionRepository(s).active(lipidi)] == ["sci_000000", "sci_000001"]
    assert check_all(rt_db, root) == []


def test_sync_is_idempotent(rt_db, lessons):
    root, dirs = lessons
    sync_all(rt_db, root)
    sync_all(rt_db, root)
    with session_scope(rt_db) as s:
        lesson = LessonRepository(s).get_by_path(dirs[0])
        assert len(DecisionRepository(s).active(lesson)) == 2
        assert len(LessonRepository(s).list_all()) == 3
    assert check_all(rt_db, root) == []


def test_check_reports_differences(rt_db, lessons):
    root, dirs = lessons
    sync_all(rt_db, root)
    # modifiche fatte a mano, senza passare da RT (quindi senza dual-write)
    with open(os.path.join(dirs[1], "_state", "info.yaml"), "a", encoding="utf-8") as f:
        f.write("titolo_extra: x\n")
    path = os.path.join(dirs[1], "_state", "info.yaml")
    text = open(path, encoding="utf-8").read().replace("fase_corrente: preparato", "fase_corrente: completato")
    open(path, "w", encoding="utf-8").write(text)
    os.remove(get_ledger_path(dirs[0]))
    new = _make_lesson(root, "[2026-09-04] CHIMICA - Acidi")
    diffs = check_all(rt_db, root)
    joined = "\n".join(diffs)
    assert "workflow_state" in joined
    assert "decisioni diverse" in joined
    assert os.path.basename(new) + ": lezione assente dal database" in joined
    sync_all(rt_db, root)
    assert check_all(rt_db, root) == []


def test_dual_write_follows_state_manifest_and_ledger(rt_db, lessons):
    root, dirs = lessons
    lesson_dir = dirs[1]
    transition_to(os.path.join(lesson_dir, "_state", "info.yaml"), WorkflowState.OUTLINE_VALIDATED, allow_force=True)
    with session_scope(rt_db) as s:
        assert LessonRepository(s).get_by_path(lesson_dir).workflow_state == "outline_validata"
    init_or_update_manifest(lesson_dir, "x", "2026-09-02", "FISIOLOGIA", "outline_validata",
                            phase_records={"outline": {"status": "VALID", "source_fingerprint": "f2"}})
    record_decision(lesson_dir, "sci_000009", "rejected", resolved_text="claim", channel="cli", actor="user")
    with session_scope(rt_db) as s:
        lesson = LessonRepository(s).get_by_path(lesson_dir)
        assert PhaseRunRepository(s).for_lesson(lesson)["outline"].status == "VALID"
        assert [(d.issue_id, d.channel) for d in DecisionRepository(s).active(lesson)] == [("sci_000009", "cli")]
    # la lezione mai sincronizzata a mano risulta comunque allineata grazie al dual-write
    assert not [d for d in check_all(rt_db, root) if os.path.basename(lesson_dir) in d]


def test_without_database_nothing_changes(lessons, monkeypatch, tmp_path):
    root, dirs = lessons
    path = tmp_path / "assente" / "rt.db"
    monkeypatch.setenv("RT_DATABASE_URL", f"sqlite:///{path}")
    reset_database_cache()
    record_decision(dirs[1], "sci_1", "accepted", resolved_text="t")
    transition_to(os.path.join(dirs[1], "_state", "info.yaml"), WorkflowState.OUTLINE_VALIDATED, allow_force=True)
    assert not path.exists()


def test_broken_database_does_not_break_writes(lessons, monkeypatch, tmp_path, caplog):
    root, dirs = lessons
    path = tmp_path / "rt.db"
    path.write_bytes(b"garbage" * 1000)
    monkeypatch.setenv("RT_DATABASE_URL", f"sqlite:///{path}")
    reset_database_cache()
    record_decision(dirs[1], "sci_1", "accepted", resolved_text="t")
    with open(get_ledger_path(dirs[1]), encoding="utf-8") as f:
        assert json.load(f)["decisions"][0]["issue_id"] == "sci_1"
    assert "Database non disponibile" in caplog.text


def test_cli_db_sync_and_check(rt_db, lessons, capsys):
    from rt.cli import main
    root, dirs = lessons
    with pytest.raises(SystemExit):
        main(["db", "check", "--lessons-root", root])
    assert "lezione assente dal database" in capsys.readouterr().out
    main(["db", "sync", "--lessons-root", root])
    assert "Lezioni sincronizzate: 3" in capsys.readouterr().out
    main(["db", "check", "--lessons-root", root])
    assert "allineato" in capsys.readouterr().out


def test_full_mock_run_with_database_is_unchanged_and_in_sync(rt_db, tmp_path):
    """Run mock completo (sottoprocessi CLI) con il DB attivo: stessi file e output dei golden,
    e 'rt db check' pulito senza aver mai lanciato 'rt db sync'."""
    work = tmp_path / "run"
    work.mkdir()
    actual = scenario_audio_full(str(work))
    expected = load_golden("audio_full")
    for rel in sorted(expected):
        assert actual[rel] == expected[rel], rel
    out_dir = str(work / "out")
    assert check_all(rt_db, out_dir) == []
    with session_scope(rt_db) as s:
        lesson = LessonRepository(s).get_by_path(os.path.join(out_dir, LESSON_NAME))
        assert lesson.workflow_state == "pronto_per_build"  # come info.yaml nel golden
        assert PhaseRunRepository(s).for_lesson(lesson)["build"].status == "VALID"
        assert DecisionRepository(s).active(lesson)
