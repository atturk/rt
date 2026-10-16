import pytest

from rt.llm.prompts import REWRITE_SYSTEM_PROMPT, STUDY_NOTE_VERIFICA_SYSTEM_PROMPT


@pytest.mark.parametrize("prompt", [REWRITE_SYSTEM_PROMPT, STUDY_NOTE_VERIFICA_SYSTEM_PROMPT])
def test_latex_instructions_include_math_and_temml_compatible_chemistry(prompt):
    for instruction in ("$...$", "$$...$$", "indici", "frazioni", "Unicode", "<sub>/<sup>",
                        r"$$\mathrm{...}$$", r"\rightarrow", r"\rightleftharpoons",
                        r"$\mathrm{CO_2}$", r"mai \ce", "sigle non chimiche restano testo"):
        assert instruction in prompt
