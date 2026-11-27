#!/usr/bin/env python3
"""
Crea l'archivio di esempio rt/assets/esempio/lezione-esempio.rt.

La lezione si costruisce con la pipeline vera in modalità mock, ma con risposte "scritte a
mano" al posto di quelle generiche del mock: così i file (scaletta, draft, verifica,
domande) hanno sempre lo schema attuale di RT. Se lo schema cambia basta rilanciare lo
script (il test tests/test_sample_lesson.py controlla che l'archivio incluso sia valido).
"""
import os
import shutil
import sys
import tempfile
from unittest import mock

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

FOLDER_NAME = "[2026-10-01] ESEMPIO - Introduzione a RT"
LESSON_TITLE = "Introduzione a RT"

INFO_YAML = """data: '2026-10-01'
materia: ESEMPIO
titolo: Introduzione a RT
docente: Team RT
anno: 2026
"""

TRANSCRIPT_MD = """---
data: '2026-10-01'
materia: ESEMPIO
titolo: Introduzione a RT
---

*00:00*
Benvenuti a questa lezione dimostrativa di RT. Oggi vediamo i principi fondamentali dello studio attivo.

*00:15*
RT suddivide automaticamente la lezione in unità logiche per facilitare la comprensione e il ripasso.

*00:30*
Ogni unità viene verificata rispetto alle fonti ufficiali fornite dal docente per correggere eventuali imprecisioni.
"""

# (macro, titolo macro, unità, titolo unità, testo rielaborato)
UNITS = [
    ("1", "Principi di RT", "1.1", "Benvenuto e studio attivo",
     "Benvenuti a questa lezione dimostrativa di RT. In questa sessione introduttiva esploriamo i "
     "principi fondamentali dello studio attivo, pensato per ottimizzare l'apprendimento e la "
     "memorizzazione a lungo termine."),
    ("1", "Principi di RT", "1.2", "Struttura a unità logiche",
     "RT suddivide la trascrizione in unità logiche di studio. Ogni unità raccoglie un singolo "
     "concetto chiave o argomento trattato durante la spiegazione orale."),
    ("2", "Verifica e memorizzazione", "2.1", "Verifica con le fonti",
     "Il testo rielaborato viene confrontato automaticamente con le slide e i documenti del docente. "
     "Questo processo individua discrepanze ed errori prima che vengano memorizzati dallo studente."),
]
TOPICS = ["Studio attivo", "Unità logiche", "Verifica con le fonti"]
ISSUE = {
    "unit": "2.1", "citazione": "le slide e i documenti del docente",
    "sostituzione": "le slide, le dispense e i documenti del docente",
    "motivazione": "Il docente cita anche le dispense tra le fonti ufficiali da usare per la verifica.",
}
QUESTIONS = {
    "1.2": ("In che modo RT organizza i contenuti della lezione per facilitare lo studio?",
            ["In unità logiche, ciascuna dedicata a un concetto chiave",
             "In capitoli di lunghezza fissa",
             "In ordine alfabetico per argomento",
             "In un unico testo continuo"], 0),
    "2.1": ("A cosa serve il confronto con le fonti del docente?",
            ["A trovare discrepanze ed errori prima di memorizzarli",
             "A tradurre la lezione in inglese",
             "A ridurre la durata dell'audio",
             "A generare le immagini della lezione"], 0),
}


def _scripted_response(original):
    """Risposte del mock sostituite con il contenuto della lezione di esempio."""
    import re
    from rt.core.models import DraftUnit, LessonTopics, Outline, OutlineMacro, OutlineUnit, RecallQuestion

    def unit_segments(prompt):
        return list(dict.fromkeys(re.findall(r"seg_\d{6,}", prompt)))

    def fake(self, job_name, prompt, response_model):
        name = response_model.__name__
        if name == "Outline":
            segs = unit_segments(prompt) or ["seg_000001", "seg_000002", "seg_000003"]
            while len(segs) < len(UNITS):
                segs.append(segs[-1])
            groups = {}
            for i, (mid, mtitle, uid, utitle, _text) in enumerate(UNITS):
                groups.setdefault((mid, mtitle), []).append(OutlineUnit(
                    id=uid, title=utitle, start_segment_id=segs[i], end_segment_id=segs[i], key_concepts=[utitle]))
            macros = [OutlineMacro(id=mid, title=mtitle, units=units) for (mid, mtitle), units in groups.items()]
            return Outline(lesson_title=LESSON_TITLE, macro_sections=macros)
        if name == "LessonTopics":
            return LessonTopics(argomenti=TOPICS)
        if name == "DraftUnit":
            match = re.search(r"ID:\s*([0-9.]+)", prompt)
            uid = match.group(1) if match else UNITS[0][2]
            unit = next(u for u in UNITS if u[2] == uid)
            segs = unit_segments(prompt) or ["seg_000001"]
            return DraftUnit(unit_id=uid, title=unit[3], start_segment_id=segs[0], end_segment_id=segs[-1],
                             source_segment_ids=segs, content=unit[4])
        if name == "ReviewFindingList":
            match = re.search(r"UNITÀ:\s*([0-9.]+)", prompt)
            if match and match.group(1) == ISSUE["unit"] and ISSUE["citazione"] in prompt:
                return response_model(issues=[{"tipo": "concettuale", "gravita": "bassa",
                                               "citazione": ISSUE["citazione"],
                                               "motivazione": ISSUE["motivazione"],
                                               "sostituzione": ISSUE["sostituzione"]}])
            return response_model(issues=[])
        if name == "RecallQuestion":
            match = re.search(r"UNIT[ÀA]:\s*([\w.]+)", prompt)
            uid = match.group(1) if match else ""
            if uid in QUESTIONS:
                text, options, correct = QUESTIONS[uid]
                return RecallQuestion(id="recall_mock", type="quiz", unit_ids=[uid], question_text=text,
                                      options=options, correct_index=correct)
        return original(self, job_name, prompt, response_model)
    return fake


def _rewrite_questions(path: str) -> None:
    """Il mock del recall scrive domande generiche: tiene una domanda per le unità di QUESTIONS
    e le dà testo e opzioni veri."""
    import json
    with open(path, encoding="utf-8") as f:
        bank = json.load(f)
    kept, seen = [], set()
    for question in bank.get("questions", []):
        uid = (question.get("unit_ids") or [""])[0]
        if uid in QUESTIONS and uid not in seen:
            seen.add(uid)
            text, options, correct = QUESTIONS[uid]
            question.update(question_text=text, options=options, correct_index=correct,
                            pregenerated_material=f"La risposta corretta è «{options[correct]}».")
            kept.append(question)
    bank["questions"] = kept
    with open(path, "w", encoding="utf-8") as f:
        json.dump(bank, f, ensure_ascii=False, indent=2)


def build_sample_lesson(output_path: str) -> str:
    from rt.llm.client import LLMClient
    from rt.services.context import RunContext
    from rt.services.pipeline_service import PipelineOptions, run_pipeline
    from rt.storage.export import export_zip

    temp_root = tempfile.mkdtemp(prefix="rt-sample-lesson-")
    lesson_dir = os.path.join(temp_root, FOLDER_NAME)
    os.makedirs(lesson_dir)
    try:
        with open(os.path.join(lesson_dir, "info.yaml"), "w", encoding="utf-8") as f:
            f.write(INFO_YAML)
        with open(os.path.join(lesson_dir, "trascritto grezzo.md"), "w", encoding="utf-8") as f:
            f.write(TRANSCRIPT_MD)
        original = LLMClient._generate_mock_response
        with mock.patch.object(LLMClient, "_generate_mock_response", _scripted_response(original)):
            options = PipelineOptions(mock=True, with_review=True, auto_accept=True, rename=False)
            result = run_pipeline([lesson_dir], options, RunContext())
            if result.error:
                raise RuntimeError(f"Pipeline della lezione di esempio fallita: {result.error}")
            try:
                from rt.services.recall_service import generate_pool
                generate_pool(lesson_dir, force_mock=True, qtypes=["quiz"])
                _rewrite_questions(os.path.join(lesson_dir, "_state", "recall_questions.json"))
            except Exception as exc:  # noqa: BLE001 - le domande sono un di più
                print(f"⚠️  Domande di esempio non generate: {exc}")

        for noise in ("llm_debug.log", "telemetry_summary.json"):
            path = os.path.join(lesson_dir, "_state", noise)
            if os.path.exists(path):
                os.remove(path)
        archive_bytes = export_zip(lesson_dir, scope="all")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(archive_bytes)
        size_kb = os.path.getsize(output_path) / 1024
        print(f"✅ Lezione di esempio creata in {output_path} ({size_kb:.1f} KB)")
        if size_kb > 1024:
            raise ValueError(f"L'archivio supera 1 MB: {size_kb:.1f} KB")
        return output_path
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    os.environ.setdefault("RT_DATABASE_URL", "off")
    build_sample_lesson(os.path.join(ROOT_DIR, "rt", "assets", "esempio", "lezione-esempio.rt"))
