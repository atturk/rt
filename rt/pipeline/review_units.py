"""Registro delle verifiche per unità; non partecipa alle impronte della pipeline."""
from rt.core.lesson_lock import lesson_locked
import json
from datetime import datetime
from rt.core.lesson_paths import lesson_path
from rt.storage import fs


def load_review_units(lesson_dir: str) -> dict:
    path = lesson_path(lesson_dir, 'review_units.json')
    if not fs.isfile(path):
        return {}
    with fs.open(path, encoding='utf-8') as file:
        data = json.load(file)
    return data.get('units', {})


@lesson_locked
def save_review_units(lesson_dir: str, units: dict) -> None:
    path = lesson_path(lesson_dir, 'review_units.json')
    with fs.open(path + '.tmp', 'w', encoding='utf-8') as file:
        json.dump({'schema_version': '1.0', 'units': units}, file, ensure_ascii=False, indent=2)
    fs.replace(path + '.tmp', path)


@lesson_locked
def record_review_unit(lesson_dir: str, unit, cfg, client, issues: int, result: str,
                       message: str = None, text_hash: str = None) -> None:
    from rt.pipeline.review import _unit_hashes
    units = load_review_units(lesson_dir)
    job_cfg = cfg.jobs.get('review') or cfg.llm.get('review')
    model = getattr(client, 'last_response_model', None)
    if not isinstance(model, str):
        model = 'mock-deterministic' if client.force_mock else job_cfg.primary.model if job_cfg and job_cfg.primary else None
    units[unit.unit_id] = {'reviewed_at': datetime.now().isoformat(), 'model': model,
                          'issues': issues, 'text_hash': text_hash or _unit_hashes([unit])[unit.unit_id],
                          'result': result, **({'message': message} if message else {})}
    save_review_units(lesson_dir, units)
