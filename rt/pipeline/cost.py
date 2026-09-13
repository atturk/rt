"""
rt.pipeline.cost
Modulo di calcolo e reportistica diagnostica dei costi cumulativi LLM per lezione.
Legge e aggrega le voci registrate in _state/llm_debug.log.
"""

import os
import json
from typing import Dict, List, Optional, Any
from rt.core.lesson_paths import lesson_path


def compute_lesson_cost(lesson_dir: str) -> Optional[Dict[str, Any]]:
    """
    Legge _state/llm_debug.log e calcola l'aggregazione dei costi LLM.
    Restituisce None se il file non esiste o non contiene record validi.
    """
    log_path = lesson_path(lesson_dir, "llm_debug.log")
    if not os.path.isfile(log_path):
        return None

    entries: List[Dict[str, Any]] = []
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if not line_str:
                    continue
                try:
                    record = json.loads(line_str)
                    if isinstance(record, dict):
                        entries.append(record)
                except Exception:
                    # Ignora silenziosamente eventuali righe JSON corrotte
                    continue
    except Exception:
        return None

    if not entries:
        return None

    total_calls = len(entries)
    total_cost = 0.0
    by_job: Dict[str, Dict[str, Any]] = {}

    for entry in entries:
        job = entry.get("job") or "unknown"
        unit_id = entry.get("unit_id")
        status = entry.get("status", "unknown")
        failure_class = entry.get("failure_class")
        attempt = entry.get("attempt", 1)
        provider = entry.get("provider", "?")
        model = entry.get("model", "?")
        resolved_model = entry.get("resolved_model")
        route_role = entry.get("route_role", "primary")
        credential_ref = entry.get("credential_ref")
        cost_val = entry.get("estimated_cost")
        timestamp = entry.get("timestamp")

        cost_numeric = float(cost_val) if (cost_val is not None and isinstance(cost_val, (int, float))) else None

        if cost_numeric is not None:
            total_cost += cost_numeric

        if job not in by_job:
            by_job[job] = {
                "total_calls": 0,
                "success_calls": 0,
                "error_calls": 0,
                "total_cost": 0.0,
                "units": {},
                "direct_entries": []
            }

        job_data = by_job[job]
        job_data["total_calls"] += 1
        if status == "success":
            job_data["success_calls"] += 1
        else:
            job_data["error_calls"] += 1

        if cost_numeric is not None:
            job_data["total_cost"] += cost_numeric

        entry_summary = {
            "timestamp": timestamp,
            "attempt": attempt,
            "status": status,
            "failure_class": failure_class,
            "provider": provider,
            "model": model,
            "resolved_model": resolved_model,
            "route_role": route_role,
            "credential_ref": credential_ref,
            "estimated_cost": cost_numeric,
        }

        if unit_id:
            if unit_id not in job_data["units"]:
                job_data["units"][unit_id] = {
                    "total_calls": 0,
                    "total_cost": 0.0,
                    "entries": []
                }
            u_data = job_data["units"][unit_id]
            u_data["total_calls"] += 1
            if cost_numeric is not None:
                u_data["total_cost"] += cost_numeric
            u_data["entries"].append(entry_summary)
        else:
            job_data["direct_entries"].append(entry_summary)

    return {
        "lesson_dir": os.path.abspath(lesson_dir),
        "total_calls": total_calls,
        "total_estimated_cost_usd": total_cost,
        "by_job": by_job,
    }


def render_cost_report(cost_data: Optional[Dict[str, Any]], split: bool = False) -> str:
    """Renderizza il report dei costi per terminale."""
    if not cost_data:
        return "Nessun dato di costo disponibile per questa lezione (nessuna chiamata LLM registrata)."

    lesson_dir = cost_data["lesson_dir"]
    total_calls = cost_data["total_calls"]
    total_cost = cost_data["total_estimated_cost_usd"]
    by_job = cost_data["by_job"]

    lines = []
    lines.append(f"\n💰 COSTO CUMULATIVO LLM: {lesson_dir}")
    lines.append("=" * 60)

    if not split:
        for job_name, j_data in by_job.items():
            calls_str = f"{j_data['total_calls']} chiamate"
            cost_str = f"${j_data['total_cost']:.6f}"
            lines.append(f"  {job_name:<18} {calls_str:>14}    {cost_str:>12}")
        lines.append("-" * 60)
        tot_calls_str = f"{total_calls} chiamate"
        tot_cost_str = f"${total_cost:.6f}"
        lines.append(f"  {'TOTALE':<18} {tot_calls_str:>14}    {tot_cost_str:>12}")
        lines.append("=" * 60 + "\n")
    else:
        for job_name, j_data in by_job.items():
            lines.append(f"\n📂 FASE/JOB: {job_name} ({j_data['total_calls']} chiamate, ${j_data['total_cost']:.6f})")

            # Se ci sono chiamate dirette (senza unit_id)
            if j_data["direct_entries"]:
                for e in j_data["direct_entries"]:
                    status_icon = "✔" if e["status"] == "success" else "❌"
                    status_desc = "Success" if e["status"] == "success" else (e["failure_class"] or e["status"])
                    cost_desc = f"${e['estimated_cost']:.6f}" if e["estimated_cost"] is not None else "N/D"
                    cred_info = f" ({e['credential_ref']})" if e["credential_ref"] else ""
                    route_info = f"{e['provider']}/{e['model']}{cred_info}"
                    lines.append(f"    [#{e['attempt']}] {status_icon} {status_desc} [{route_info}] - {cost_desc}")

            # Se ci sono unità
            if j_data["units"]:
                for unit_id, u_data in j_data["units"].items():
                    lines.append(f"  • Unità {unit_id} ({u_data['total_calls']} tentativi, ${u_data['total_cost']:.6f}):")
                    for e in u_data["entries"]:
                        status_icon = "✔" if e["status"] == "success" else "❌"
                        status_desc = "Success" if e["status"] == "success" else (e["failure_class"] or e["status"])
                        cost_desc = f"${e['estimated_cost']:.6f}" if e["estimated_cost"] is not None else "N/D"
                        cred_info = f" ({e['credential_ref']})" if e["credential_ref"] else ""
                        route_info = f"{e['provider']}/{e['model']}{cred_info}"
                        lines.append(f"      [#{e['attempt']}] {status_icon} {status_desc} [{route_info}] - {cost_desc}")

        lines.append("\n" + "=" * 60)
        tot_calls_str = f"{total_calls} chiamate"
        tot_cost_str = f"${total_cost:.6f}"
        lines.append(f"  {'TOTALE GENERALE':<18} {tot_calls_str:>14}    {tot_cost_str:>12}")
        lines.append("=" * 60 + "\n")

    return "\n".join(lines)
