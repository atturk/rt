import json
from pathlib import Path
import yaml

from rt.recall.migration import LEGACY_ESERCIZIO_CHIEDI, current_esercizio_chiedi, migrate_exercise_prompt
from rt.llm.prompts import RECALL_VARIANT_SYSTEM_PROMPT, RECALL_TEXT_VARIANT_SYSTEM_PROMPT


def test_exercise_template_prompt():
    templates = json.loads((Path("rt/recall/question_type_templates.json")).read_text(encoding="utf-8"))
    esercizio = next(t for t in templates if t["id"] == "esercizio")
    chiedi = esercizio["chiedi"]

    assert "La traccia riporta solo la situazione, i dati necessari e che cosa determinare" in chiedi
    assert "chiede il risultato e/o i passaggi chiave" not in chiedi
    assert "Non indica il metodo, le formule, le leggi o i passaggi da usare" in chiedi


def test_variant_prompts_rule():
    for prompt in (RECALL_VARIANT_SYSTEM_PROMPT, RECALL_TEXT_VARIANT_SYSTEM_PROMPT):
        assert "La traccia riporta solo la situazione, i dati necessari e che cosa determinare" in prompt
        assert "non indica il metodo, le formule o i passaggi da usare" in prompt
        assert "non suggerisce come impostare il problema" in prompt


def test_exercise_prompt_migration(tmp_path):
    config_file = tmp_path / "general.yaml"

    # 1. Tipo con testo vecchio -> viene aggiornato
    old_data = {
        "recall": {
            "custom_types": [
                {"id": "esercizio", "nome": "Esercizio", "chiedi": LEGACY_ESERCIZIO_CHIEDI},
                {"id": "altro", "nome": "Altro", "chiedi": "Testo generico"},
            ]
        }
    }
    config_file.write_text(yaml.safe_dump(old_data), encoding="utf-8")

    res = migrate_exercise_prompt(config_file, old_data)
    assert res["recall"]["custom_types"][0]["chiedi"] == current_esercizio_chiedi()
    assert res["recall"]["custom_types"][1]["chiedi"] == "Testo generico"

    # Verifica persistenza su file
    saved = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    assert saved["recall"]["custom_types"][0]["chiedi"] == current_esercizio_chiedi()

    # 2. Seconda esecuzione -> idempotente, niente cambia
    mtime_before = config_file.stat().st_mtime_ns
    res2 = migrate_exercise_prompt(config_file, saved)
    assert res2["recall"]["custom_types"][0]["chiedi"] == current_esercizio_chiedi()

    # 3. Tipo modificato a mano -> resta uguale
    custom_text = "Testo personalizzato dall'utente per l'esercizio."
    user_modified_data = {
        "recall": {
            "custom_types": [
                {"id": "esercizio", "nome": "Esercizio", "chiedi": custom_text},
            ]
        }
    }
    config_file.write_text(yaml.safe_dump(user_modified_data), encoding="utf-8")
    res3 = migrate_exercise_prompt(config_file, user_modified_data)
    assert res3["recall"]["custom_types"][0]["chiedi"] == custom_text
