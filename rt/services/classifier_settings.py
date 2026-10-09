"""Salvataggio della configurazione nuova senza le chiavi decisionali storiche."""
LEGACY_JEV = ("enabled", "shadow", "model", "credential", "base_url", "timeout_seconds", "relevance_mode", "relevance_model")


def write_classifier(data, classifier):
    data["classifier"] = classifier.model_dump(exclude_unset=False)
    data["jev"] = {k: v for k, v in (data.get("jev") or {}).items() if k not in LEGACY_JEV}
    data["enrichment"] = {k: v for k, v in (data.get("enrichment") or {}).items()
                          if not k.startswith("decision_") and k not in ("mode", "automatic")}
