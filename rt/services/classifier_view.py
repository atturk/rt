"""Snapshot dei job e correzioni del pannello Classificatore."""
from datetime import datetime, timezone

from rt.core.config import load_config, classifier_job, classifier_jev
from rt.pipeline.rewrite import load_draft
from rt.pipeline.ledger import load_resolved_draft
from rt.services import unit_relevance as rel, question_types as qt, section_labels as sl, unit_prefilter as pf
from rt.services.recall_context import digest, lesson_context
from rt.storage import fs

JOBS = {"relevance": "relevance", "question_types": "question_types", "exercises": "section_labels",
        "cases": "section_labels", "prefilter": "prefilter", "drift": "drift", "enrichment": "enrichment"}


def units_view(lesson_dir):
    view = "resolved" if fs.isfile(rel._path(lesson_dir,"resolved")) else "draft"
    try:
        return (load_resolved_draft(lesson_dir) if view == "resolved" else load_draft(lesson_dir)).units, view
    except (OSError, ValueError):
        return [], view


def overview(lesson_dir):
    cfg = load_config()
    units, view = units_view(lesson_dir)
    sections = sl.sections(lesson_dir, units)
    owner = {u.unit_id: s["id"] for s in sections for u in s["units"]}
    relevance, types, labels, prefilter = rel._load(lesson_dir, view), qt._load(lesson_dir), sl._load(lesson_dir), pf.load(lesson_dir)
    section_hashes = {s["id"]: sl._section_hash(lesson_dir, s) for s in sections}
    effective_labels = {s["id"]: {kind: sl.effective(labels.get(s["id"], {}), kind) for kind in sl.KINDS}
                        for s in sections if labels.get(s["id"], {}).get("text_hash") == section_hashes[s["id"]]}
    allowed = rel.included_ids(lesson_dir, units, view=view, records=relevance, cfg=classifier_jev(cfg,"relevance"))
    from rt.services import enrichment_service as es
    enrichment = es.load(lesson_dir)
    out = {"units": [{"id": u.unit_id, "title": u.title, "section_id": owner[u.unit_id]} for u in units], "jobs": {}, "pending": 0}
    pending = set()
    for name, config_name in JOBS.items():
        job = classifier_job(cfg, config_name)
        cells, stamps = [], []
        for item in sections if name in ("exercises", "cases") else units:
            sid = item["id"] if isinstance(item, dict) else None
            uid = None if sid else item.unit_id
            row, value, manual, fresh, skipped, options, confidence = {}, None, False, False, False, [], None
            if name == "relevance":
                row = relevance.get(uid,{})
                fresh = row.get("text_hash") == rel._unit_hash(item,lesson_dir) and row.get("config_hash") == rel._config_hash(classifier_jev(cfg,"relevance"))
                value = row.get("override") or row.get("prediction")
                manual = row.get("override") is not None
                options = list(rel.CLASSES)
            elif name == "question_types":
                row = types.get(uid,{})
                fresh = row.get("text_hash") == qt._text_hash(item,lesson_dir) and (row.get("override") is not None or row.get("config_hash") == qt._config_hash(classifier_jev(cfg,"question_types")))
                value = row.get("override") or qt._compatible(row, owner.get(uid), effective_labels)
                manual = row.get("override") is not None
                skipped = uid not in allowed and not manual
                options = list(qt.CRITERIA)
            elif name in ("exercises", "cases"):
                kind = "esercizio" if name == "exercises" else "caso"
                row = labels.get(sid,{})
                fresh = row.get("text_hash") == section_hashes[sid] and (row.get("override_"+kind) is not None or row.get("config_hash") in ("mock",sl._config_hash(classifier_jev(cfg,"section_labels"))))
                value, manual = sl.effective(row,kind), row.get("override_"+kind) is not None
                confidence = row.get(kind+"_confidence")
                options = list(sl.ESERCIZIO_CRITERIA if kind == "esercizio" else sl.CASO_CRITERIA)
            elif name in ("prefilter", "drift"):
                task = "task_a" if name == "prefilter" else "task_b"
                record = prefilter.get(uid,{})
                row = record.get(task) or {}
                fresh = record.get("text_hash") == digest([item.title,item.content,lesson_context(lesson_dir)]) and row.get("config_hash") == pf.configuration(classifier_jev(cfg,name),task)
                verdict = row.get("verdict") or {}
                if verdict:
                    value = verdict.get("outcome") if name == "prefilter" else "drift" if verdict.get("is_high_confidence_drift") else "coherent"
                confidence = verdict.get("confidence",verdict.get("noul_probability"))
                skipped = uid not in allowed
            else:
                policy = es.analysis_policy(cfg, cfg.mock_llm)
                unit = {"id": uid, "title": item.title, "content": item.content}
                assessment = enrichment.assessments.get(uid)
                expected = digest([es.source_hash(unit),policy])
                fresh = assessment == expected
                row = enrichment.assessment_metadata.get(uid, {}) or ({"at": None} if assessment else {})
                fresh = fresh or row.get("key") == expected
                confidence = max(row.get("utilities", {}).values(), default=None)
                elements = [e for e in enrichment.elements if e.unit_id == uid and not e.manual and e.utility >= cfg.enrichment.utility_threshold]
                value = ", ".join(sorted({e.kind for e in elements})) or ("none" if assessment else None)
                skipped = uid not in allowed
            confidence = confidence if confidence is not None else row.get("confidence")
            state = "skipped" if skipped else "error" if row.get("error") and fresh else "stale" if row and not fresh else "fresh" if fresh and (value is not None or manual) else "missing"
            cell = {"unit_id":uid,"section_id":sid,"value": value if fresh and not skipped else None,"source":"manual" if manual and fresh else "classifier","state":state,"confidence":confidence if fresh else None,"options":options}
            cells.append(cell)
            stamp = row.get("classified_at") or row.get("at")
            if stamp:
                stamps.append(stamp)
            if job.mode != "off" and state in ("error","missing","stale"):
                pending.update(u.unit_id for u in item["units"]) if sid else pending.add(uid)
        states = {c["state"] for c in cells}
        state = "off" if job.mode == "off" else "stale" if "stale" in states else "never" if not cells or states <= {"missing","skipped"} else "partial" if states & {"error","missing"} else "done"
        out["jobs"][name] = {"mode":job.mode,"state":state,"last_run_at":max(stamps) if stamps else None,"errors":sum(c["state"] == "error" for c in cells),"cells":cells}
    out["pending"] = len(pending)
    return out


def correct(lesson_dir, job, cell_id, value, actor="utente"):
    if job == "relevance":
        _, view = units_view(lesson_dir)
        rel.set_override(lesson_dir,cell_id,value,view=view,actor=actor)
    elif job == "question_types":
        qt.set_override(lesson_dir,cell_id,value)
    elif job in ("exercises","cases"):
        sl.set_override(lesson_dir,cell_id,"esercizio" if job == "exercises" else "caso",value)
    else:
        raise ValueError("Job non correggibile")
    return overview(lesson_dir)


def run(lesson_dir, job, *, force=False, unit_ids=None, ctx=None):
    cfg = load_config()
    names = [job] if job else list(JOBS)
    completed = set()
    for name in names:
        if name not in JOBS:
            raise ValueError("Job non valido")
        config_name = JOBS[name]
        if config_name in completed or classifier_job(cfg,config_name).mode == "off":
            continue
        completed.add(config_name)
        mock = cfg.mock_llm or bool(ctx and ctx.force_mock)
        if name == "relevance":
            _, view = units_view(lesson_dir)
            rel.refresh(lesson_dir,force_mock=mock,force=force,unit_ids=unit_ids,ctx=ctx,view=view)
        elif name == "question_types":
            qt.refresh(lesson_dir,force_mock=mock,force=force,unit_ids=unit_ids,ctx=ctx,view=units_view(lesson_dir)[1])
        elif name in ("exercises","cases"):
            sl.refresh(lesson_dir,force_mock=mock,force=force,unit_ids=unit_ids,explicit=True)
        elif name in ("prefilter","drift"):
            pf.refresh_prefilter(lesson_dir,unit_ids,force,jobs=(name,))
        else:
            from rt.services.enrichment_service import analyze
            analyze(lesson_dir,mock=mock,ctx=ctx,force=force,unit_ids=unit_ids)
    return overview(lesson_dir)
