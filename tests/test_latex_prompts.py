import pytest

from rt.llm import prompts
from rt.llm.prompts import REWRITE_SYSTEM_PROMPT, STUDY_NOTE_VERIFICA_SYSTEM_PROMPT

# Domande e valutazioni: senza la regola il modello scriveva «ρ_s» invece di $\rho_s$.
RECALL_PROMPTS = [getattr(prompts, f"RECALL_{name}_SYSTEM_PROMPT") for name in (
    "QUIZ", "MIRATA", "VASTA", "EVAL_MIRATA", "EVAL_VASTA", "VARIANT", "TEXT_VARIANT",
    "EVAL_RAGIONAMENTO", "EVAL_TEXT")]


@pytest.mark.parametrize("prompt", [REWRITE_SYSTEM_PROMPT, STUDY_NOTE_VERIFICA_SYSTEM_PROMPT, *RECALL_PROMPTS])
def test_latex_instructions_include_math_and_temml_compatible_chemistry(prompt):
    for instruction in ("$...$", "$$...$$", "indici", "frazioni", "Unicode", "<sub>/<sup>",
                        r"$$\mathrm{...}$$", r"\rightarrow", r"\rightleftharpoons",
                        r"$\mathrm{CO_2}$", r"mai \ce", "sigle non chimiche restano testo"):
        assert instruction in prompt


def test_custom_recall_types_get_the_latex_rule():
    from types import SimpleNamespace
    from rt.pipeline.recall_special import system_for
    assert prompts.LATEX_WRITING_RULE in system_for(SimpleNamespace(chiedi="Chiedi un caso clinico.", correzione="testo"))
