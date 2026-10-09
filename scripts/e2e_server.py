"""
Server per i test end-to-end della SPA (Playwright, fase F): API vera + worker + build della
SPA su una cartella lezioni di prova, isolata in una directory temporanea.

Uso (lo lancia frontend/playwright.config.ts):
    python scripts/e2e_server.py --port 8766 [--dir /tmp/rt-e2e]

Scrive frontend/e2e/.state/server.json con base_url e token API, che i test usano per
chiedere un link di accesso monouso (POST /api/v1/auth/login-link) e per rileggere dall'API.
Ogni avvio riparte da zero: lezioni, DB e configurazione vengono ricreati. Il worker gira con
--mock (LLM, risposte vocali e immagini dal web finti), il bot Telegram è finto
(RT_TELEGRAM_FAKE=1: esegue le richieste della web app) e il Bot API anche
(tests/api_support.fake_telegram_server), la "Prova" dei modelli è in mock (RT_API_MOCK=1),
SearXNG è un server finto (searxng_url in server.json); niente finestra di Finder per la scelta
cartella.
"""
import argparse
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_FILE = os.path.join(ROOT, "frontend", "e2e", ".state", "server.json")


def _workspace(base: str, telegram: bool = False) -> str:
    """cwd con config/ (da config.example) e lessons_root dentro base (chiave 3.x
    ancora rispettata, non più configurabile dalla SPA); HOME isolata."""
    import yaml
    if os.path.isdir(base):
        shutil.rmtree(base)
    work, lessons, home = (os.path.join(base, d) for d in ("work", "lessons", "home"))
    os.makedirs(lessons)
    os.makedirs(home)
    shutil.copytree(os.path.join(ROOT, "config.example"), os.path.join(work, "config"))
    with open(os.path.join(work, ".env"), "w", encoding="utf-8"):
        pass
    general_path = os.path.join(work, "config", "general.yaml")
    with open(general_path, encoding="utf-8") as f:
        general = yaml.safe_load(f) or {}
    general.setdefault("telegram", {})["lessons_root"] = lessons
    # Telegram è spento di predefinito; gli e2e del bot finto lo accendono (e lo provano a spegnere)
    general["telegram"]["enabled"] = telegram
    # la ricerca web delle immagini richiede SearXNG configurato; il worker --mock non lo chiama
    general.setdefault("jev", {}).update(relevance_model="typesafe/jev-1.13", relevance_mode="shadow")
    general["searxng_base_url"] = "http://127.0.0.1:9"
    # nessuna connessione nel config di esempio: senza questo ogni pagina porterebbe alla
    # configurazione guidata (la si prova in settings.spec.ts e nel job CI 'installer')
    general.setdefault("ui", {})["dismissed_notices"] = ["setup_wizard"]
    with open(general_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(general, f, sort_keys=False, allow_unicode=True)
    os.environ["HOME"] = home
    os.environ["RT_NATIVE_FOLDER_PICKER"] = "0"
    os.environ["RT_TELEGRAM_FAKE"] = "1"
    os.environ["PYTHONPATH"] = os.pathsep.join(filter(None, [ROOT, os.environ.get("PYTHONPATH")]))
    os.environ.pop("RT_DATABASE_URL", None)
    os.environ.pop("RT_DATA_DIR", None)  # anche nell'ambiente cloud i dati degli e2e restano isolati
    os.environ["RT_SECRETS_FILE"] = os.path.join(work, "config", "secrets.enc")
    os.chdir(work)
    return lessons


def _plain_lesson(root: str, date: str, materia: str, argomenti: str) -> str:
    """Cartella con info.yaml e trascritto, come dopo 'rt setup'."""
    from tests.golden_support import INFO_YAML, TRANSCRIPT_MD
    folder = os.path.join(root, f"[{date}] {materia} - {argomenti}")
    os.makedirs(folder)
    with open(os.path.join(folder, "info.yaml"), "w", encoding="utf-8") as f:
        f.write(INFO_YAML.replace("2026-09-05", date).replace("BIOCHIMICA", materia).replace("Lipidi", argomenti))
    with open(os.path.join(folder, "trascritto grezzo.md"), "w", encoding="utf-8") as f:
        f.write(TRANSCRIPT_MD.replace("2026-09-05", date).replace("BIOCHIMICA", materia))
    return folder


def _stale_review(lesson: str) -> None:
    """Review come nelle lezioni revisionate prima di RT 3.3.2: impronta calcolata con
    review_v1.1, quindi STALE (il caso di Patologia del primo test reale, RT4-FA2)."""
    from rt.core.manifest import load_manifest, save_manifest
    manifest = load_manifest(lesson)
    record = manifest.phase_records["review"]
    record["processor_version"] = "review_v1.1"
    record["source_fingerprint"] = "0" * 64
    record.pop("input_hashes", None)
    save_manifest(manifest, lesson)


def _lessons(root: str) -> None:
    """BIOCHIMICA completa con audio; FISIOLOGIA solo setup; FARMACOLOGIA e PATOLOGIA con
    l'outline approvata e 10 issue della review da decidere (per la review contestuale);
    ANATOMIA come PATOLOGIA ma con la review non aggiornata e senza documento finale (build
    con conferma, recall e immagini prima del build); CHIRURGIA completa come BIOCHIMICA, solo
    per la modifica dell'anteprima (RT4-FA3), che rende il documento da ricreare."""
    from rt.services.outline_service import approve_outline
    from tests.api_support import add_audio, make_lesson, run_mock_pipeline
    done = make_lesson(root)
    add_audio(done)
    run_mock_pipeline(done, with_review=True, auto_accept=True)
    _plain_lesson(root, "2026-09-12", "FISIOLOGIA", "Il rene")
    for date, materia, argomenti in (("2026-09-19", "FARMACOLOGIA", "Recettori"),
                                     ("2026-09-20", "PATOLOGIA", "Infiammazione"),
                                     ("2026-09-03", "REVISIONE", "Verifica di prova")):
        lesson = _plain_lesson(root, date, materia, argomenti)
        add_audio(lesson)
        run_mock_pipeline(lesson, with_review=True, auto_accept=False)  # si ferma sull'outline
        approve_outline(lesson, channel="api")
        run_mock_pipeline(lesson, with_review=True, auto_accept=False)  # si ferma sulle issue
        if materia == "REVISIONE":
            from rt.pipeline.review import load_science_issues, save_science_issues
            from rt.core.models import ScienceIssue, ScienceType, ScienceSeverity
            from rt.services.phase_validation_service import validate_phase
            issues = load_science_issues(lesson)
            issues.append(ScienceIssue(id="sci_asr_test", type=ScienceType.ERR_ASR_ST,
                                      severity=ScienceSeverity.MEDIUM, unit_id=issues[0].unit_id,
                                      claim="Qualità dell’intera unità", reason="Issue ASR di prova"))
            save_science_issues(issues, lesson)
            validate_phase(lesson, "review", channel="api")
    anatomia = _plain_lesson(root, "2026-09-21", "ANATOMIA", "Cuore")
    run_mock_pipeline(anatomia, with_review=True, auto_accept=False)
    approve_outline(anatomia, channel="api")
    run_mock_pipeline(anatomia, with_review=True, auto_accept=False)
    _stale_review(anatomia)
    chirurgia = _plain_lesson(root, "2026-09-01", "CHIRURGIA", "Suture")
    add_audio(chirurgia)
    run_mock_pipeline(chirurgia, with_review=True, auto_accept=True)
    # Lezione con due unità reali per navigazione e stato di studio, senza mock delle API.
    _study_lesson(root)
    # Vicina pronta e indipendente dalle prove che modificano CHIRURGIA.
    _study_lesson(root, materia="STUDIO_NAV", argomenti="Navigazione di prova")
    # Come le lezioni reali da RT 4.0: testi nel DB, media in media/ (le cartelle vanno nel backup).
    from rt.storage.migrate import migrate_storage
    report = migrate_storage(root)
    if report.errors:
        raise RuntimeError("; ".join(report.errors))


def _study_lesson(root: str, *, materia: str = "STUDIO", argomenti: str = "Unità di prova") -> None:
    from rt.core.lesson_paths import lesson_path
    from rt.core.segments import load_segments_json
    from rt.pipeline.outline import load_outline, save_outline
    from rt.services.outline_service import approve_outline
    from rt.services.phase_validation_service import validate_phase
    from tests.api_support import run_mock_pipeline
    path = _plain_lesson(root, "2026-09-02", materia, argomenti)
    run_mock_pipeline(path, with_review=False, auto_accept=False)
    segments = load_segments_json(lesson_path(path, "segments.json")).segments
    middle = len(segments) // 2
    outline = load_outline(path)
    first = outline.macro_sections[0].units[0]
    outline.macro_sections = outline.macro_sections[:1]
    outline.macro_sections[0].units = [
        first.model_copy(update={"id": "1.1", "title": "Prima unità", "end_segment_id": segments[middle - 1].id}),
        first.model_copy(update={"id": "1.2", "title": "Seconda unità", "start_segment_id": segments[middle].id}),
    ]
    save_outline(outline, path)
    validate_phase(path, "outline", channel="api")
    approve_outline(path, channel="api")
    result = run_mock_pipeline(path, with_review=False, auto_accept=True)
    if result.error:
        raise RuntimeError(result.error)

    from rt.pipeline.rewrite import load_draft, save_draft
    draft = load_draft(path)
    draft.units[0].content = "Formula $z$. un’impostazione un'impostazione. " + draft.units[0].content
    draft.units[1].content += '\n\n' + r'$$\sum_{i=1}^{6} x_i$$'
    save_draft(draft, path, manual=True)
    validate_phase(path, "rewrite", channel="api")
    result = run_mock_pipeline(path, with_review=False, auto_accept=True)
    if result.error:
        raise RuntimeError(result.error)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--dir", default=os.path.join(tempfile.gettempdir(), "rt-e2e"))
    parser.add_argument("--telegram", action="store_true",
                        help="Telegram acceso (gli e2e del bot finto); senza, il predefinito: spento")
    args = parser.parse_args()
    sys.path.insert(0, ROOT)

    # realpath: su macOS la cartella temporanea è un link (/var -> /private/var) e l'API salva
    # la cartella delle lezioni risolta; i test la confrontano con quella di server.json.
    root = _workspace(os.path.realpath(args.dir), telegram=args.telegram)
    from rt.api import auth
    from rt.api.launcher import run_spa
    from rt.db.bootstrap import ensure_database
    from rt.db.engine import get_database

    ensure_database()
    _lessons(root)
    # Bot API finta per "Ascolta i topic" (RT4-F5) e per il recall su Telegram avviato dalla web
    # (RT4-FA7): API, worker e bot finto la ereditano dall'ambiente.
    from tests.api_support import fake_telegram_server
    _telegram, os.environ["RT_TELEGRAM_API_URL"] = fake_telegram_server()
    # "Prova" dei modelli in mock (nessuna chiamata LLM) e SearXNG finto per la ricerca web (RT4-FA5).
    os.environ["RT_API_MOCK"] = "1"
    from tests.api_support import fake_searxng_server
    _searxng, searxng_url = fake_searxng_server(results=3)
    token = auth.reset_token(get_database())
    base_url = f"http://127.0.0.1:{args.port}"
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"base_url": base_url, "token": token, "lessons_root": root, "searxng_url": searxng_url}, f)
    print(f"Server e2e su {base_url} (lezioni in {root})", flush=True)
    return run_spa(port=args.port, open_browser=False, worker_args=["--mock"])


if __name__ == "__main__":
    sys.exit(main())
