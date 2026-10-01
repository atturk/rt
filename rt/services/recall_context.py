"""Contesto disciplinare deterministico condiviso da classificatore e recall."""
import hashlib
import json
import re

import yaml

from rt.core.lesson_paths import lesson_path
from rt.storage import fs

POLICY_VERSION = "recall-relevance-2"
RELEVANCE_DEFINITION = (
    "Considera rilevante una nozione, definizione, relazione, proprietà, meccanismo, metodo o applicazione "
    "che aiuti a studiare gli argomenti della lezione o a prepararsi nella materia indicata. Può essere "
    "una singola informazione breve: non è necessario che l'argomento sia sviluppato completamente in "
    "questa unità. Gli argomenti della lezione sono un riferimento tematico, non un elenco esaustivo. "
    "Conserva anche prerequisiti, analogie e chiarimenti che insegnano contenuti disciplinari pertinenti. "
    "Non basta la presenza di parole associate alla materia. Comunicazioni organizzative, ricevimento, "
    "modalità d'esame, saluti, interruzioni e dettagli incidentali non costituiscono contenuti da testare. "
    "Neppure obiettivi dichiarati del corso, organizzazione didattica, annunci di argomenti futuri o "
    "consigli generici di studio sono nozioni interrogabili. Un metodo disciplinare effettivamente "
    "descritto rimane rilevante. Nelle unità miste valuta le sole informazioni disciplinari. "
    "Un riepilogo può contenere conoscenze rilevanti."
)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def normalize_topics(value):
    values = value if isinstance(value, (list, tuple)) else re.split(r"[,;\n]", str(value or ""))
    result = []
    for item in values:
        topic = str(item).strip()
        if topic and topic not in result:
            result.append(topic)
    return result


def lesson_context(lesson_dir):
    info, outline = {}, {}
    for name, reader in [("info.yaml", yaml.safe_load), ("outline.json", json.loads)]:
        path = lesson_path(lesson_dir, name)
        if fs.isfile(path):
            try:
                with fs.open(path, "r", encoding="utf-8") as stream:
                    data = reader(stream.read()) or {}
                if isinstance(data, dict):
                    if name == "info.yaml":
                        info = data
                    else:
                        outline = data
            except (ValueError, OSError, yaml.YAMLError):
                pass
    generated = normalize_topics(outline.get("generated_topics"))
    topics = info.get("argomenti")
    # Il build copia gli argomenti generati in info.yaml uniti da ", ": rilette, le virgole dentro
    # un argomento lo spezzerebbero e le etichette del classificatore risulterebbero da rifare.
    raw = outline.get("generated_topics")
    if generated and isinstance(raw, list) and isinstance(topics, str) and topics.strip() == ", ".join(map(str, raw)).strip():
        topics = generated
    return {"materia": str(info.get("materia") or ""),
            "titolo_lezione": str(outline.get("lesson_title") or info.get("titolo") or ""),
            "argomenti_lezione": normalize_topics(topics) or generated}


def context_block(context):
    return "CONTESTO DISCIPLINARE:\n" + json.dumps(context, ensure_ascii=False, sort_keys=True)
