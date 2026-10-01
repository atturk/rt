#!/usr/bin/env python3
"""QC con i client RT: importa Markdown, classifica e salva domande per revisione umana.

Le credenziali si configurano in RT_DATA_DIR, mai negli input o negli output QC.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import re
import sys

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rt.core.config import load_config
from rt.core.lesson_paths import lesson_path
from rt.core.models import Draft, DraftUnit, RecallQuestionType
from rt.pipeline.recall import generate_recall_batch, load_recall_bank, _generation_policy, _generation_digest, _generation_key
from rt.services import unit_relevance
from rt.services.recall_context import lesson_context

ALLOWED_MODELS = {"stealth/space-bunny-alpha", "openrouter/free"}


def write_json(path, data):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def import_markdown(source, target):
    text = source.read_text(encoding='utf-8')
    front = re.match(r'^---\s*\n(.*?)\n---\s*\n', text, re.S)
    if not front:
        raise ValueError(f'Frontmatter mancante: {source.name}')
    info = yaml.safe_load(front.group(1))
    units = []
    for i, chunk in enumerate(re.split(r'(?m)^###\s+', text[front.end():])[1:], 1):
        header, _, content = chunk.partition('\n')
        uid, _, title = header.partition(' ')
        content = re.sub(r'^\s*\d{1,2}:\d{2}(?::\d{2})?\s*\n', '', content).strip()
        content = re.split(r'(?m)^#{1,2}\s+', content)[0].strip()
        sid = f'seg_{i:06d}'
        units.append(DraftUnit(unit_id=uid, title=title, content=content,
            start_segment_id=sid, end_segment_id=sid, source_segment_ids=[sid]))
    if not units or len({u.unit_id for u in units}) != len(units):
        raise ValueError(f'Unità mancanti o duplicate: {source.name}')
    target.mkdir(parents=True, exist_ok=True)
    Path(lesson_path(str(target), 'info.yaml')).write_text(yaml.safe_dump(info, allow_unicode=True), encoding='utf-8')
    draft = Draft(lesson_id=source.stem, units=units)
    Path(lesson_path(str(target), 'draft.json')).write_text(draft.model_dump_json(indent=2), encoding='utf-8')
    return draft


def run_lesson(source, work, sample_ids):
    full = work / source.stem
    draft = import_markdown(source, full)
    rows = unit_relevance.refresh(str(full), view='resolved')
    print(f'{source.stem}: {len(rows)} unità classificate', flush=True)
    sample = [u for u in draft.units if u.unit_id in sample_ids]
    if not sample:
        raise ValueError(f'Campione vuoto: {source.name}')
    result = {'source': source.name, 'context': lesson_context(str(full)),
        'classification': [{'unit_id': u.unit_id, 'title': u.title, 'content': u.content,
                            'record': rows.get(u.unit_id), 'assessment': unit_relevance.recall_assessment(str(full), u)} for u in draft.units],
        'sample_ids': [u.unit_id for u in sample], 'styles': {}}
    for style in RecallQuestionType:
        accumulated, attempts, errors = [], {}, []
        groups = [sample] if style == RecallQuestionType.VASTA else [[u] for u in sample]
        for group in groups:
            ids = [u.unit_id for u in group]
            step = full / ('qc_' + style.value + '_' + '_'.join(ids))
            step.mkdir(exist_ok=True)
            Path(lesson_path(str(step), 'info.yaml')).write_text(Path(lesson_path(str(full), 'info.yaml')).read_text(), encoding='utf-8')
            Path(lesson_path(str(step), 'draft.json')).write_text(draft.model_copy(update={'units': group}).model_dump_json(indent=2), encoding='utf-8')
            unit_relevance._save(str(step), {u.unit_id: rows[u.unit_id] for u in group}, 'resolved')
            fingerprint = _generation_digest(str(step), group, _generation_policy(style, []))
            output_path = step / 'qc-step.json'
            previous = json.loads(output_path.read_text()) if output_path.exists() else {}
            bank = load_recall_bank(str(step))
            checkpoint = bank.generation_attempts.get(_generation_key(style, group), {})
            if previous.get('fingerprint') == fingerprint and 'error' not in previous:
                output = previous
            elif checkpoint.get('fingerprint') == fingerprint:
                # Una risposta salvata dalla pipeline resta recuperabile anche se il runner
                # è stato interrotto prima di scrivere il proprio risultato.
                output = {'fingerprint': fingerprint, 'questions': [q.model_dump(mode='json') for q in bank.questions
                    if q.generation_fingerprint == fingerprint], 'attempts': bank.generation_attempts}
                write_json(output_path, output)
            else:
                try:
                    questions = generate_recall_batch(str(step), style, 12, [])
                    output = {'fingerprint': fingerprint, 'questions': [q.model_dump(mode='json') for q in questions],
                              'attempts': load_recall_bank(str(step)).generation_attempts}
                except Exception as exc:
                    from rt.llm.credentials import GLOBAL_CREDENTIALS
                    output = {'fingerprint': fingerprint, 'error': GLOBAL_CREDENTIALS.sanitize_secrets(str(exc))}
                write_json(output_path, output)
            accumulated.extend(output.get('questions', []))
            attempts.update(output.get('attempts', {}))
            if output.get('error'):
                errors.append({'unit_ids': ids, 'error': output['error']})
            print(f"{source.stem}: {style.value} {','.join(ids)}, {len(output.get('questions', []))} domande", flush=True)
            result['styles'][style.value] = {'questions': accumulated, 'attempts': attempts, 'errors': errors}
            write_json(full / 'qc-result.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--work-dir', type=Path, required=True)
    parser.add_argument('--sample-ids', default='1.1,1.2,2.1,2.2')
    parser.add_argument('--sample-plan', type=Path, help='JSON: filename → array degli ID da campionare')
    parser.add_argument('--workers', type=int, default=2)
    args = parser.parse_args()
    cfg = load_config()
    route = cfg.jobs.get('recall') or cfg.llm.get('recall')
    if cfg.jev.relevance_model != 'typesafe/jev-1.13' or cfg.jev.relevance_mode != 'active':
        raise ValueError('QC richiede typesafe/jev-1.13 in modalità active')
    routes = (route.effective_routes + [r for r in (route.fallback.timeout, route.fallback.rate_limit,
        route.fallback.safety, route.fallback.auth, route.fallback.generic) if r]) if route else []
    if not routes or any(r.model not in ALLOWED_MODELS or r.provider != 'openrouter' for r in routes):
        raise ValueError('Configura solo stealth/space-bunny-alpha o openrouter/free per recall')
    args.work_dir.mkdir(parents=True, exist_ok=True)
    sources = sorted(args.inputs.glob('*.md'))
    if not sources:
        raise ValueError('Nessuna rielaborazione Markdown')
    plan = json.loads(args.sample_plan.read_text()) if args.sample_plan else {}
    results = []
    with ThreadPoolExecutor(max_workers=max(1, min(args.workers, 4))) as pool:
        pending = {pool.submit(run_lesson, s, args.work_dir, plan.get(s.name, args.sample_ids.split(','))): s for s in sources}
        for future in as_completed(pending):
            results.append(future.result())
            write_json(args.work_dir / 'qc-results.json', {'requested_models': [cfg.jev.relevance_model, route.primary.model,
                [r.model for r in routes]], 'complete': len(results) == len(sources),
                'lessons': sorted(results, key=lambda x: x['source'])})
    print(f'Risultati: {args.work_dir / "qc-results.json"}')


if __name__ == '__main__':
    main()
