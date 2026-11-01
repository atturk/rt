#!/usr/bin/env python3
"""Valutazione della qualità dei risultati AI di una lezione con un modello giudice.

Legge lo zip completo di una lezione ('rt export --all --zip', o rt_export_lesson con scope
all) e fa giudicare a un modello più forte di quello che ha generato, su un campione di unità:

- rielaborazione: ogni unità confrontata con i segmenti del trascritto da cui deriva
  (fedeltà, completezza, chiarezza, formule), con le affermazioni inventate e le omissioni;
- verifica: le segnalazioni del revisore scientifico (errore vero, falso allarme, correzione);
- domande: le domande di recall con il testo delle loro unità (pertinenza, correttezza,
  risposta giusta del quiz, difficoltà adatta).

Il giudice è sempre lo stesso e la temperatura è 0, così due versioni di RT sulla stessa
lezione si confrontano. Ogni chiamata riporta il costo di OpenRouter; --budget ferma la
valutazione prima di superarlo.

Uso:
  OPENROUTER_API_KEY=... python scripts/eval_quality.py lezione.zip [altra.zip ...] \\
      [--units 5] [--issues 5] [--questions 6] [--budget 0.06] [--out rapporto.json]
La chiave si legge solo dall'ambiente e non viene mai scritta.
"""
import argparse
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

JUDGE_MODEL = "openai/gpt-6-sol"
API_URL = "https://openrouter.ai/api/v1/chat/completions"

SYSTEM = (
    "Sei un docente universitario esperto e un revisore severo ma equo. Valuti il lavoro di "
    "un sistema che trasforma la trascrizione automatica (ASR, con errori di riconoscimento) "
    "di una lezione universitaria italiana in testo di studio. Giudica solo su quanto ti viene "
    "dato: il trascritto è la fonte di verità per ciò che il docente ha detto, ma può contenere "
    "parole storpiate dall'ASR, che una buona rielaborazione corregge. Rispondi in italiano, "
    "solo con il JSON richiesto."
)

SCORE = {"type": "integer", "minimum": 1, "maximum": 5}

UNIT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["fedelta", "completezza", "chiarezza", "formule_e_termini", "inventato", "omesso", "nota"],
    "properties": {
        "fedelta": SCORE, "completezza": SCORE, "chiarezza": SCORE, "formule_e_termini": SCORE,
        "inventato": {"type": "array", "items": {"type": "string"},
                      "description": "Affermazioni del testo senza riscontro nel trascritto né corrette per conoscenza comune della materia"},
        "omesso": {"type": "array", "items": {"type": "string"},
                   "description": "Concetti didattici del trascritto mancanti nel testo"},
        "nota": {"type": "string"},
    },
}

ISSUE_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["esito", "correzione_giusta", "nota"],
    "properties": {
        "esito": {"type": "string", "enum": ["errore_vero", "falso_allarme", "dubbio"]},
        "correzione_giusta": {"type": "boolean"},
        "nota": {"type": "string"},
    },
}

QUESTION_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["pertinenza", "correttezza", "chiarezza", "risposta_quiz_giusta", "nota"],
    "properties": {
        "pertinenza": SCORE, "correttezza": SCORE, "chiarezza": SCORE,
        "risposta_quiz_giusta": {"type": ["boolean", "null"], "description": "null se non è un quiz"},
        "nota": {"type": "string"},
    },
}


class Budget:
    def __init__(self, limit):
        self.limit, self.spent, self.calls = limit, 0.0, 0

    def left(self):
        return self.limit - self.spent


def judge(key, budget, prompt, name, schema):
    body = {
        "model": JUDGE_MODEL, "temperature": 0,
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
        "response_format": {"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}},
        "usage": {"include": True},
    }
    request = urllib.request.Request(API_URL, json.dumps(body).encode(), {
        "Authorization": f"Bearer {key}", "Content-Type": "application/json",
        "X-Title": "RT eval qualità"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                data = json.load(response)
            break
        except urllib.error.HTTPError as exc:
            if exc.code < 500 and exc.code != 429 or attempt == 2:
                raise RuntimeError(f"OpenRouter {exc.code}: {exc.read()[:300]!r}") from exc
            time.sleep(5 * (attempt + 1))
    usage = data.get("usage") or {}
    budget.spent += float(usage.get("cost") or 0)
    budget.calls += 1
    return json.loads(data["choices"][0]["message"]["content"]), usage


def read_lesson(zip_path):
    """File della lezione dallo zip completo (nomi senza _state/, eventuale cartella radice)."""
    files = {}
    with zipfile.ZipFile(zip_path) as archive:
        for name in archive.namelist():
            # history/ver_*/ tiene le versioni precedenti con gli stessi nomi: vale solo la corrente
            if "history/" in name:
                continue
            if name.endswith(".json") or name.endswith(".yaml"):
                files[Path(name).name] = archive.read(name).decode("utf-8")
    def load(name, default):
        return json.loads(files[name]) if name in files else default
    segments = {s["id"]: s for s in load("segments.json", {}).get("segments", [])}
    issues = load("science_issues.json", [])
    if isinstance(issues, dict):
        issues = issues.get("issues", [])
    return {
        "info": files.get("info.yaml", ""),
        "units": load("draft.json", {}).get("units", []),
        "segments": segments,
        "issues": issues,
        "questions": load("recall_questions.json", {}).get("questions", []),
    }


def sample(items, count, seed):
    if len(items) <= count:
        return list(items)
    # campione sparso su tutta la lezione, uguale a ogni esecuzione
    rng = random.Random(seed)
    step = len(items) / count
    return [items[min(len(items) - 1, int(i * step + rng.random() * step))] for i in range(count)]


def source_text(lesson, unit):
    return "\n".join(f"[{lesson['segments'][s]['start_formatted']}] {lesson['segments'][s]['text_raw']}"
                     for s in unit.get("source_segment_ids", []) if s in lesson["segments"])


def evaluate(zip_path, key, args):
    lesson = read_lesson(zip_path)
    budget = Budget(args.budget)
    report = {"lezione": Path(zip_path).name, "giudice": JUDGE_MODEL, "unita": [], "verifica": [], "domande": []}
    units_by_id = {u["unit_id"]: u for u in lesson["units"]}
    header = f"Metadati della lezione:\n{lesson['info'][:600]}\n\n"

    for unit in sample(lesson["units"], args.units, zip_path.name):
        if budget.left() <= 0:
            break
        prompt = (header + f"TRASCRITTO (fonte) dell'unità {unit['unit_id']}:\n{source_text(lesson, unit)}\n\n"
                  f"TESTO RIELABORATO dell'unità \"{unit['title']}\":\n{unit['content']}\n\n"
                  "Valuta da 1 a 5: fedelta (nessuna informazione inventata o distorta), completezza "
                  "(tutti i concetti didattici del trascritto, escluse digressioni organizzative), "
                  "chiarezza (testo di studio ben organizzato), formule_e_termini (formule, unità, "
                  "nomi tecnici corretti, anche dove l'ASR li ha storpiati). Elenca le affermazioni "
                  "inventate e i concetti omessi, brevi.")
        verdict, usage = judge(key, budget, prompt, "unita", UNIT_SCHEMA)
        report["unita"].append({"unit_id": unit["unit_id"], "titolo": unit["title"], **verdict,
                                "token_in": usage.get("prompt_tokens")})

    for issue in sample(lesson["issues"], args.issues, zip_path.name + "/issues"):
        unit = units_by_id.get(issue.get("unit_id"))
        if budget.left() <= 0 or unit is None:
            continue
        prompt = (header + f"TRASCRITTO dell'unità:\n{source_text(lesson, unit)}\n\n"
                  f"TESTO RIELABORATO:\n{unit['content']}\n\n"
                  f"SEGNALAZIONE del revisore scientifico ({issue.get('type')}, gravità {issue.get('severity')}):\n"
                  f"Affermazione: {issue.get('claim')}\nMotivo: {issue.get('reason')}\n"
                  f"Correzione proposta: {issue.get('suggested_fix')}\n\n"
                  "È un errore vero (del docente o della rielaborazione) o un falso allarme? "
                  "La correzione proposta è giusta?")
        verdict, _ = judge(key, budget, prompt, "verifica", ISSUE_SCHEMA)
        report["verifica"].append({"id": issue.get("id"), "tipo": issue.get("type"), **verdict})

    live = [q for q in lesson["questions"] if q.get("status") != "discarded"]
    for question in sample(live, args.questions, zip_path.name + "/recall"):
        units = [units_by_id[u] for u in question.get("unit_ids", []) if u in units_by_id]
        if budget.left() <= 0 or not units:
            continue
        options = ""
        if question.get("options"):
            options = "\nOpzioni: " + " | ".join(f"{i}) {o}" for i, o in enumerate(question["options"])) + \
                f"\nIndice indicato come corretto: {question.get('correct_index')}"
        prompt = (header + "TESTO DI STUDIO:\n" + "\n\n".join(u["content"] for u in units) +
                  f"\n\nDOMANDA ({question.get('type')}): {question.get('question_text')}{options}\n\n"
                  "Valuta da 1 a 5 pertinenza (verifica un concetto importante del testo), "
                  "correttezza (domanda e risposta attesa corrette nella materia), chiarezza. "
                  "Per un quiz di' se l'indice corretto è davvero l'unica risposta giusta.")
        verdict, _ = judge(key, budget, prompt, "domanda", QUESTION_SCHEMA)
        report["domande"].append({"id": question.get("id"), "tipo": question.get("type"), **verdict})

    report["costo_usd"] = round(budget.spent, 4)
    report["chiamate"] = budget.calls
    report["sintesi"] = summary(report)
    return report


def mean(rows, field):
    values = [r[field] for r in rows if isinstance(r.get(field), (int, float)) and not isinstance(r.get(field), bool)]
    return round(sum(values) / len(values), 2) if values else None


def summary(report):
    units, issues, questions = report["unita"], report["verifica"], report["domande"]
    quiz = [q for q in questions if q.get("risposta_quiz_giusta") is not None]
    return {
        "unita": {f: mean(units, f) for f in ("fedelta", "completezza", "chiarezza", "formule_e_termini")},
        "affermazioni_inventate": sum(len(u["inventato"]) for u in units),
        "verifica_errori_veri": sum(i["esito"] == "errore_vero" for i in issues),
        "verifica_falsi_allarmi": sum(i["esito"] == "falso_allarme" for i in issues),
        "domande": {f: mean(questions, f) for f in ("pertinenza", "correttezza", "chiarezza")},
        "quiz_con_risposta_sbagliata": sum(not q["risposta_quiz_giusta"] for q in quiz),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("zips", nargs="+", type=Path)
    parser.add_argument("--units", type=int, default=5, help="Unità giudicate per lezione")
    parser.add_argument("--issues", type=int, default=4, help="Segnalazioni della verifica giudicate")
    parser.add_argument("--questions", type=int, default=5, help="Domande di recall giudicate")
    parser.add_argument("--budget", type=float, default=0.06, help="Spesa massima per lezione in dollari")
    parser.add_argument("--out", type=Path, help="Rapporto JSON (default: stampa)")
    args = parser.parse_args()
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        sys.exit("Imposta OPENROUTER_API_KEY nell'ambiente.")
    reports = []
    for path in args.zips:
        report = evaluate(path, key, args)
        print(f"{path.name}: {json.dumps(report['sintesi'], ensure_ascii=False)} · ${report['costo_usd']}",
              file=sys.stderr)
        reports.append(report)
    text = json.dumps(reports, ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    main()
