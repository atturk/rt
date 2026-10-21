import re
from pathlib import Path
import rt.services.api_jobs  # noqa: F401 - registra tutti gli handler
from rt.services.worker import _HANDLERS

REPO_ROOT = Path(__file__).resolve().parent.parent
JOBS_TS = REPO_ROOT / "frontend" / "src" / "lib" / "jobs.ts"
FORMAT_TS = REPO_ROOT / "frontend" / "src" / "lib" / "format.ts"


def test_all_registered_job_types_have_labels_in_frontend():
    content = JOBS_TS.read_text(encoding="utf-8")
    for job_type in _HANDLERS:
        pattern = rf"\b{re.escape(job_type)}\s*:"
        assert re.search(pattern, content), f"Il tipo job '{job_type}' non ha un'etichetta in frontend/src/lib/jobs.ts"


def test_all_progress_phases_have_labels_in_frontend():
    jobs_content = JOBS_TS.read_text(encoding="utf-8")
    format_content = FORMAT_TS.read_text(encoding="utf-8")

    known_phases = {
        "setup",
        "archive",
        "prepare",
        "outline",
        "rewrite",
        "review",
        "build",
        "recall",
        "add_images",
        "describe_images",
        "enrichment",
        "enrichment_generate",
        "import_lesson_zips",
        "export_lessons",
    }

    # Raccogli anche dinamicamente le fasi da ctx.progress e phase_scope nel backend
    for py_file in (REPO_ROOT / "rt").rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        for m in re.finditer(r'ctx\.progress\(\s*["\']([a-zA-Z0-9_]+)["\']', text):
            known_phases.add(m.group(1))
        for m in re.finditer(r'phase_scope\([^,]+,\s*["\']([a-zA-Z0-9_]+)["\']', text):
            known_phases.add(m.group(1))

    for phase in known_phases:
        pattern = rf"\b{re.escape(phase)}\s*:"
        assert re.search(pattern, jobs_content) or re.search(pattern, format_content), (
            f"La fase '{phase}' non ha un'etichetta in jobs.ts o format.ts"
        )
