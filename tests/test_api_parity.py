"""
tests/test_api_parity.py
RT4-E5: parità CLI ↔ API (tabella di docs/RT4_PARITY.md, dal piano, sezione 9-bis). Per ogni
riga la stessa operazione gira via CLI (sottoprocesso 'rt ...', come i golden test) e via API
(TestClient + worker in processo) su due copie della stessa fixture in mock; poi si
confrontano file della lezione, stato delle fasi, ledger delle decisioni e costi.

Le differenze attese e ignorate: percorsi temporanei, timestamp e hash (normalize_text), e
nel ledger chi ha deciso e da dove (channel, actor, resolved_by: 'api' contro 'cli').
"""
import json
import os
import shutil

import pytest

from rt.storage import fs

from rt.services.jobs import DbJobQueue
from rt.services.worker import Worker
from tests.api_support import isolated_workspace, make_lesson
from tests.golden_support import (
    AUDIO_FIXTURE, COMPARED_FILES, LESSON_NAME, _run_cli, normalize_text,
)

# Chi ha preso la decisione e da quale canale: diverso per costruzione tra CLI e API.
WHO_KEYS = {"channel", "actor", "resolved_by", "approved_by", "timestamp", "decided_at", "approved_at"}


# ---------------------------------------------------------------- le due parti

class ApiSide:
    def __init__(self, client, root, worker):
        self.client, self.root, self.worker = client, root, worker

    def lesson_id(self, name=LESSON_NAME):
        lessons = self.client.get("/api/v1/lessons").json()
        return next(item["id"] for item in lessons if item["folder_name"] == name)

    def drain(self, limit=10):
        for _ in range(limit):
            if self.worker.run_once() is None:
                return
        raise AssertionError("troppi job in coda")

    def job(self, job_id):
        return self.client.get(f"/api/v1/jobs/{job_id}").json()

    def post(self, path, expected=(200, 202), **kwargs):
        res = self.client.post(f"/api/v1{path}", **kwargs)
        assert res.status_code in expected, res.text
        return res.json()

    def run(self, path, **kwargs):
        """Accoda un job, lo esegue col worker e restituisce lo stato finale del job."""
        accepted = self.post(path, expected=(202,), **kwargs)
        self.drain()
        return self.job(accepted["job_id"])

    def decide_pending(self, lesson_id, decide):
        for item in self.client.get(f"/api/v1/lessons/{lesson_id}/issues").json()["items"]:
            issue = item["issue"]
            self.post(f"/lessons/{lesson_id}/issues/{issue['id']}/decision",
                      json={"decision": decide(issue)})


class CliSide:
    def __init__(self, root):
        self.root = root

    def rt(self, *argv, stdin=""):
        code, out, err = _run_cli(list(argv), cwd=self.root, stdin=stdin)
        assert code == 0, f"rt {' '.join(argv)} → {code}\n{out}\n{err}"
        return out

    def json_out(self, *argv, stdin=""):
        """L'ultimo blocco JSON stampato dal comando (--json lo mette in fondo)."""
        out = self.rt(*argv, stdin=stdin)
        start = 0 if out.lstrip().startswith("{") else out.rindex("\n{") + 1
        return json.loads(out[start:])


@pytest.fixture
def api(api_client, tmp_path, monkeypatch, rt_db):
    root = isolated_workspace(tmp_path, monkeypatch)
    return ApiSide(api_client, root, Worker(DbJobQueue(rt_db), worker_id="parity-worker"))


@pytest.fixture
def cli(tmp_path):
    root = tmp_path / "cli"
    root.mkdir()
    return CliSide(str(root))


@pytest.fixture
def pair(api, cli):
    """La stessa lezione (trascritto Markdown) in una copia per parte."""
    return make_lesson(cli.root), make_lesson(api.root)


# ---------------------------------------------------------------- confronto

def _strip_who(value):
    if isinstance(value, dict):
        return {k: _strip_who(v) for k, v in value.items() if k not in WHO_KEYS}
    if isinstance(value, list):
        return [_strip_who(v) for v in value]
    return value


def lesson_files(lesson_dir, extra=()):
    root = os.path.dirname(lesson_dir)
    out = {}
    for rel in list(COMPARED_FILES) + list(extra):
        path = os.path.join(lesson_dir, rel)
        if not fs.isfile(path):
            out[rel] = "<MISSING>"
            continue
        with fs.open(path, encoding="utf-8") as f:
            text = normalize_text(f.read(), root)
        if rel.endswith(".json"):
            text = json.dumps(_strip_who(json.loads(text)), ensure_ascii=False, indent=1, sort_keys=True)
        out[rel] = text
    return out


def all_files(lesson_dir):
    """Percorsi relativi di tutti i file della lezione (le cartelle vuote non contano).
    Passa da rt.storage.fs: CLI e API creano le lezioni nel database (nessuna cartella)."""
    return sorted(os.path.relpath(os.path.join(base, name), lesson_dir)
                  for base, _, names in fs.walk(lesson_dir) for name in names
                  if not name.startswith(".rt."))  # lock del worker (.rt.job.lock)


def lesson_state(lesson_dir):
    """Stato confrontabile: fasi, validazioni, ledger, costi per fase."""
    from rt.pipeline.cost import compute_lesson_cost
    from rt.services.lesson_service import phase_report
    report = phase_report(lesson_dir)
    cost = compute_lesson_cost(lesson_dir) or {}
    by_job = {job: int(info.get("total_calls") or 0) for job, info in (cost.get("by_job") or {}).items()}
    return {
        "phases": [(p["phase"], p["status"]) for p in report["phases"]],
        "outline_validation": report["outline_validation"],
        "draft_validation": report["draft_validation"],
        "calls_by_job": by_job,
        "total_cost_usd": cost.get("total_estimated_cost_usd"),
    }


def assert_same_lesson(cli_dir, api_dir, extra=()):
    cli_files, api_files = lesson_files(cli_dir, extra), lesson_files(api_dir, extra)
    for rel in cli_files:
        assert cli_files[rel] == api_files[rel], f"{rel} diverso tra CLI e API"
    assert lesson_state(cli_dir) == lesson_state(api_dir)


def is_asr(issue_type: str) -> bool:
    return issue_type.startswith("ERR_ASR") or issue_type == "ERR_REWRITE_DRIFT"


# ---------------------------------------------------------------- righe della tabella

def test_row_run_folder_pipeline(api, cli, pair):
    """rt run <cartella> --mock --auto-accept ⇔ POST /lessons/{id}/jobs run_pipeline."""
    cli_dir, api_dir = pair
    cli.rt("run", cli_dir, "--mock", "--auto-accept", "--with-review", "--channel", "terminal", "--no-rename",
           stdin="a\n")
    lesson_id = api.lesson_id()
    job = api.run(f"/lessons/{lesson_id}/jobs", json={"type": "run_pipeline", "mock": True, "auto_accept": True,
                                                       "with_review": True, "rename": False})
    assert job["state"] == "succeeded", job  # con auto_accept outline e issue non chiedono nulla
    assert_same_lesson(cli_dir, api_dir)
    assert all(status == "VALID" for _, status in lesson_state(api_dir)["phases"])


def test_row_setup_audio(api, cli):
    """rt setup <audio> -d -m -a --mock ⇔ POST /lessons (upload) → job ingest_audio."""
    shutil.copy(AUDIO_FIXTURE, os.path.join(cli.root, "lezione.wav"))
    out_dir = os.path.join(cli.root, "out")
    cli.rt("setup", "lezione.wav", "-d", "2026-09-05", "-m", "BIOCHIMICA", "-a", "Lipidi", "-o", out_dir, "--mock")
    with open(AUDIO_FIXTURE, "rb") as f:
        job = api.run("/lessons", files={"audio": ("lezione.wav", f, "audio/wav")},
                      data={"date": "2026-09-05", "materia": "BIOCHIMICA", "argomenti": "Lipidi", "mock": "true"})
    assert job["state"] == "succeeded", job
    cli_dir, api_dir = os.path.join(out_dir, LESSON_NAME), os.path.join(api.root, LESSON_NAME)
    assert fs.is_db_lesson(cli_dir) and fs.is_db_lesson(api_dir)
    assert not os.path.exists(cli_dir) and not os.path.exists(api_dir)  # nessuna cartella di lavoro
    assert all_files(cli_dir) == all_files(api_dir)
    assert_same_lesson(cli_dir, api_dir)
    assert lesson_files(api_dir)["trascritto grezzo.md"] != "<MISSING>"


def test_row_single_phases(api, cli, pair):
    """rt prepare/outline/rewrite/review/build ⇔ POST /lessons/{id}/jobs run_phase (+ decisioni)."""
    cli_dir, api_dir = pair
    lesson_id = api.lesson_id()
    cli.rt("prepare", cli_dir)
    cli.rt("outline", cli_dir, "--mock", stdin="a\n")  # 'rt outline' chiede subito l'approvazione
    for phase in ("prepare", "outline"):
        job = api.run(f"/lessons/{lesson_id}/jobs", json={"type": "run_phase", "phase": phase, "mock": True})
        assert job["state"] == "succeeded", job
    api.post(f"/lessons/{lesson_id}/outline/approve")
    assert_same_lesson(cli_dir, api_dir)

    cli.rt("rewrite", cli_dir, "--mock")
    cli.rt("review", cli_dir, "--mock", "--auto-accept", "all", "--channel", "terminal")
    for phase in ("rewrite", "review"):
        job = api.run(f"/lessons/{lesson_id}/jobs", json={"type": "run_phase", "phase": phase, "mock": True})
        assert job["state"] == "succeeded", job
    api.decide_pending(lesson_id, lambda issue: "accepted")  # come --auto-accept all
    assert_same_lesson(cli_dir, api_dir)

    cli.rt("build", cli_dir, "--no-rename")
    job = api.run(f"/lessons/{lesson_id}/jobs", json={"type": "run_phase", "phase": "build", "mock": True,
                                                       "rename": False})
    assert job["state"] == "succeeded", job
    assert_same_lesson(cli_dir, api_dir)
    assert all(status == "VALID" for _, status in lesson_state(api_dir)["phases"])


def test_row_rewrite_single_unit(api, cli, pair):
    """rt rewrite --unit U1 ⇔ run_phase rewrite con unit (job rewrite_unit)."""
    from tests.api_support import run_mock_pipeline
    cli_dir, api_dir = pair
    for lesson_dir in pair:
        run_mock_pipeline(lesson_dir)
    lesson_id = api.lesson_id()
    unit = api.client.get(f"/api/v1/lessons/{lesson_id}/outline").json()["macro_sections"][0]["units"][0]["id"]
    cli.rt("rewrite", cli_dir, "--mock", "--force", "--unit", unit)
    job = api.run(f"/lessons/{lesson_id}/jobs", json={"type": "run_phase", "phase": "rewrite", "unit": unit,
                                                       "force": True, "mock": True})
    assert job["state"] == "succeeded" and job["type"] == "rewrite_unit", job
    assert_same_lesson(cli_dir, api_dir)


def test_row_validate_outline_and_draft(api, cli, pair):
    """rt validate-outline / validate-draft ⇔ GET /lessons/{id}/phases."""
    from tests.api_support import run_mock_pipeline
    cli_dir, _ = pair
    for lesson_dir in pair:
        run_mock_pipeline(lesson_dir)
    report = api.client.get(f"/api/v1/lessons/{api.lesson_id()}/phases").json()
    assert report["outline_validation"] == cli.json_out("validate-outline", cli_dir)
    assert report["draft_validation"] == cli.json_out("validate-draft", cli_dir)


def test_row_outline_revise_and_approve(api, cli, pair):
    """Revisione e approvazione dell'outline in 'rt run' ⇔ /outline/revise + /outline/approve."""
    cli_dir, api_dir = pair
    feedback = "Dividi in due unità"
    cli.rt("run", cli_dir, "--mock", "--channel", "terminal", "--no-rename", stdin=f"m\n{feedback}\na\n")
    lesson_id = api.lesson_id()
    job = api.run(f"/lessons/{lesson_id}/jobs", json={"type": "run_pipeline", "mock": True, "with_review": False,
                                                       "rename": False})
    assert job["state"] == "waiting_for_decision" and job["decision"]["kind"] == "outline_approval"
    outline = api.client.get(f"/api/v1/lessons/{lesson_id}/outline").json()
    assert outline["approved"] is False
    revision = api.run(f"/lessons/{lesson_id}/outline/revise", json={"feedback": feedback, "mock": True})
    assert revision["state"] == "succeeded", revision
    api.post(f"/lessons/{lesson_id}/outline/approve")
    api.drain()
    assert api.job(job["id"])["state"] == "succeeded"
    assert_same_lesson(cli_dir, api_dir)


def _pending_review_pair(cli, pair):
    """Le due copie ferme sulla review: outline approvata, issue non ASR pendenti."""
    for lesson_dir in pair:
        cli.rt("run", lesson_dir, "--mock", "--with-review", "--channel", "terminal", "--no-rename", stdin="a\n")
    from rt.pipeline.ledger import get_pending_issues
    pending = [list(get_pending_issues(d)[1]) for d in pair]
    assert pending[0] and [i.id for i in pending[0]] == [i.id for i in pending[1]]
    return pending[0]


@pytest.mark.anyio
async def test_row_interactive_review(api, cli, pair):
    """Review interattiva da terminale (Textual) ⇔ /issues/{id}/decision e /decisions/undo."""
    from rt.tui.issue_review import IssueReviewApp
    cli_dir, api_dir = pair
    to_review = _pending_review_pair(cli, pair)
    plan = {issue.id: ("accepted" if n % 2 == 0 else "rejected") for n, issue in enumerate(to_review)}

    app = IssueReviewApp(lesson_dir=cli_dir, to_review=to_review, issue_type="science")
    async with app.run_test() as pilot:
        # prima risposta sbagliata, poi "indietro" e correzione, come l'annullamento dell'API
        await pilot.press("r" if plan[to_review[0].id] == "accepted" else "a")
        await pilot.press("b")
        for issue in to_review:
            await pilot.press("a" if plan[issue.id] == "accepted" else "r")
    assert app.return_value is True

    lesson_id = api.lesson_id()
    first = to_review[0].id
    wrong = "rejected" if plan[first] == "accepted" else "accepted"
    api.post(f"/lessons/{lesson_id}/issues/{first}/decision", json={"decision": wrong})
    api.post(f"/lessons/{lesson_id}/decisions/undo", json={"issue_id": first})
    for issue in to_review:
        api.post(f"/lessons/{lesson_id}/issues/{issue.id}/decision", json={"decision": plan[issue.id]})
    assert api.client.get(f"/api/v1/lessons/{lesson_id}/issues").json()["items"] == []

    cli.rt("build", cli_dir, "--no-rename")
    job = api.run(f"/lessons/{lesson_id}/jobs", json={"type": "run_phase", "phase": "build", "rename": False})
    assert job["state"] == "succeeded", job
    assert_same_lesson(cli_dir, api_dir)


def _built_pair(pair):
    from tests.api_support import run_mock_pipeline
    for lesson_dir in pair:
        run_mock_pipeline(lesson_dir)


def _png(path):
    from PIL import Image
    Image.new("RGB", (64, 48), (200, 30, 30)).save(path, format="PNG")
    return path


def test_row_add_images(api, cli, pair, tmp_path):
    """rt add-images -i <file> --mock ⇔ POST /lessons/{id}/images (upload) → job add_images."""
    cli_dir, api_dir = pair
    _built_pair(pair)
    photos = tmp_path / "foto"
    photos.mkdir()
    slide = _png(str(photos / "slide.png"))
    cli.rt("add-images", cli_dir, "-i", str(photos), "--mock")
    with open(slide, "rb") as f:
        job = api.run(f"/lessons/{api.lesson_id()}/images", files={"files": ("slide.png", f, "image/png")},
                      data={"mock": "true"})
    assert job["state"] == "succeeded", job
    assert all_files(cli_dir) == all_files(api_dir)
    assert any(path.startswith("assets") for path in all_files(api_dir))
    assert_same_lesson(cli_dir, api_dir)


def _recall_files(lesson_dir):
    from rt.pipeline.recall import get_recall_bank_path
    with open(get_recall_bank_path(lesson_dir), encoding="utf-8") as f:
        bank = _strip_who(json.loads(normalize_text(f.read(), os.path.dirname(lesson_dir))))
    return bank


def _cli_recall_session(monkeypatch, lesson_dir, style, keys, editor_text=""):
    """Il recall da terminale di 'rt recall' (serve un TTY: stdin e input simulati)."""
    import builtins
    import sys
    import rt.core.editor_edit as editor_edit
    from rt.tui.recall import run_recall_terminal_session
    replies = iter(keys)

    def fake_input(prompt=""):
        try:
            return next(replies)
        except StopIteration:
            raise EOFError
    with monkeypatch.context() as mp:
        mp.setattr(sys.stdin, "isatty", lambda: True, raising=False)
        mp.setattr(builtins, "input", fake_input)
        mp.setattr(editor_edit, "edit_text_in_editor", lambda initial: initial + editor_text)
        run_recall_terminal_session(lesson_dir, order="alternato", style=style, force_mock=True)


def test_row_recall_quiz_and_open_answer(api, cli, pair, monkeypatch):
    """rt recall (quiz: scelta e salto; mirata: risposta scritta) ⇔ /recall/generate, /next,
    /answer, /skip."""
    cli_dir, api_dir = pair
    _built_pair(pair)
    lesson_id = api.lesson_id()
    answer_text = "Le lipasi idrolizzano i trigliceridi."

    _cli_recall_session(monkeypatch, cli_dir, "quiz", ["a", "s", "q"])
    _cli_recall_session(monkeypatch, cli_dir, "mirata", ["r", "q"], editor_text=answer_text)

    assert api.run(f"/lessons/{lesson_id}/recall/generate", json={"mock": True})["state"] == "succeeded"

    def shown(qtype, exclude=""):
        """Domanda mostrata; il rifornimento (job recall_refill) gira prima della successiva,
        come nel terminale dopo ogni domanda."""
        return api.post(f"/lessons/{lesson_id}/recall/next?mock=true&qtype={qtype}"
                        + (f"&exclude_id={exclude}" if exclude else ""))

    first = shown("quiz")
    api.post(f"/lessons/{lesson_id}/recall/answer", json={"question_id": first["id"], "choice": 0})
    api.drain()
    second = shown("quiz")
    api.post(f"/lessons/{lesson_id}/recall/skip", json={"question_id": second["id"]})
    api.drain()
    shown("quiz", exclude=second["id"])  # mostrata, poi "esci"
    api.drain()
    open_q = shown("mirata")
    job = api.run(f"/lessons/{lesson_id}/recall/answer", json={"question_id": open_q["id"], "answer": answer_text,
                                                                "mock": True})
    assert job["state"] == "succeeded", job
    shown("mirata")  # mostrata, poi "esci"
    api.drain()
    cli_bank, api_bank = _recall_files(cli_dir), _recall_files(api_dir)
    for cq, aq in zip(cli_bank["questions"], api_bank["questions"]):
        assert cq == aq, (cq["id"], {k: (cq.get(k), aq.get(k)) for k in set(cq) | set(aq) if cq.get(k) != aq.get(k)})
    assert [(q["id"], q["type"], q["status"]) for q in cli_bank["questions"]] == [
        (q["id"], q["type"], q["status"]) for q in api_bank["questions"]]
    assert cli_bank == api_bank


def test_row_status_and_cost(api, cli, pair):
    """rt status --json e rt cost --json ⇔ GET /lessons/{id} e GET /lessons/{id}/costs."""
    cli_dir, api_dir = pair
    cli.rt("run", cli_dir, "--mock", "--with-review", "--channel", "terminal", "--no-rename", stdin="a\n")
    cli.rt("run", api_dir, "--mock", "--with-review", "--channel", "terminal", "--no-rename", stdin="a\n")
    status = cli.json_out("status", cli_dir, "--json")
    cost = cli.json_out("cost", cli_dir, "--json")
    detail = api.client.get(f"/api/v1/lessons/{api.lesson_id()}").json()
    assert detail["phases"] == {ph: info["status"] for ph, info in status["phase_statuses"].items()}
    assert [(p["phase"], p["status"], p["reason"]) for p in detail["phase_report"]] == [
        (ph, info["status"], info["reason"].replace(cli_dir, api_dir)) for ph, info in status["phase_statuses"].items()]
    assert detail["pending_issues"] == status["pending_issues_total"] > 0
    assert detail["state"] == status["stato_effettivo"]
    assert detail["segment_count"] == status["segment_count"]
    assert (detail["materia"], detail["data"]) == (status["materia"], status["data"])
    api_cost = detail["cost"]
    for key in ("total_calls", "total_estimated_cost_usd", "has_unknown_cost"):
        assert api_cost[key] == cost[key], key
    assert {j: v["total_calls"] for j, v in api_cost["by_job"].items()} == {
        j: v["total_calls"] for j, v in cost["by_job"].items()}


def test_row_config_written_by_api_is_read_by_cli(api_client, tmp_path, monkeypatch, rt_db):
    """rt config (provider, modelli delle sei fasi, pricing, Telegram, trascrizione,
    lessons_root) ⇔ endpoint di RT4-E4: quello che scrive l'API lo legge la CLI."""
    import subprocess
    import sys
    from tests.api_support import workspace_with_example_config
    workspace_with_example_config(tmp_path, monkeypatch)  # config/ completa con i sei job
    monkeypatch.setenv("RT_TELEGRAM_BOT_TOKEN", "test-disabled-token")
    client = api_client
    res = client.post("/api/v1/settings/connections",
                      json={"name": "Parita", "provider": "openrouter", "api_keys": ["sk-or-v1-parita-0123456789"]})
    assert res.status_code == 201, res.text
    jobs = [p["job"] for p in res.json()["phases"]]
    assert len(jobs) == 6
    for n, job_name in enumerate(jobs):
        res = client.put(f"/api/v1/settings/phases/{job_name}", json={"connection": "Parita", "model": f"vendor/model-{n}"})
        assert res.status_code == 200, res.text
    new_root = str(tmp_path / "altra_radice")
    os.makedirs(new_root)
    assert client.put("/api/v1/settings/lessons-root", json={"path": new_root}).status_code == 200
    res = client.put("/api/v1/settings/transcription", json={"engine": "custom", "base_url": "http://127.0.0.1:9000/v1",
                                                               "model": "whisper-parita"})
    assert res.status_code == 200, res.text
    res = client.put("/api/v1/settings/telegram", json={"chat_id": "424242", "topics": {"BIOCHIMICA": 7}})
    assert res.status_code == 200, res.text

    # la CLI in un processo nuovo, nella stessa cartella di lavoro
    script = ("import json; from rt.core.config import load_config; c = load_config(); "
              "print(json.dumps({'root': c.telegram.lessons_root, 'engine': c.transcription.engine, "
              "'stt_model': c.transcription.model, 'topics': c.telegram.topics, "
              f"'models': {{j: c.jobs[j].primary.model for j in {jobs!r}}}}}))")
    env = dict(os.environ, PYTHONPATH=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    out = subprocess.run([sys.executable, "-c", script], cwd=os.getcwd(), env=env, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    seen = json.loads(out.stdout.strip().splitlines()[-1])
    assert seen["root"] == new_root
    assert (seen["engine"], seen["stt_model"]) == ("custom", "whisper-parita")
    assert seen["topics"] == {"BIOCHIMICA": 7}
    assert seen["models"] == {j: f"vendor/model-{n}" for n, j in enumerate(jobs)}


def test_row_telegram_daemon_status(api, monkeypatch, tmp_path):
    """Stato del demone Telegram: GET /telegram/daemon ⇔ il PID file che legge 'rt telegram-daemon'."""
    import rt.telegram.daemon_status as ds
    pid_path = str(tmp_path / "tg.pid")
    monkeypatch.setattr(ds, "DEFAULT_PID_PATH", pid_path)
    assert api.client.get("/api/v1/telegram/daemon").json() == {"running": False, "pid": None}
    ds.write_daemon_pid(pid_path)  # come fa il demone all'avvio
    assert api.client.get("/api/v1/telegram/daemon").json() == {"running": True, "pid": ds.get_daemon_pid(pid_path)}
    ds.remove_daemon_pid(pid_path)
    assert api.client.get("/api/v1/telegram/daemon").json()["running"] is False
