"""
tests.test_encoding
Test per la gestione corretta dell'encoding UTF-8 e risoluzione mojibake in tutte le fasi:
- Modulo rt.core.encoding
- Sanitizzazione strutture dati
- apply_decisions_to_draft
- Scrittura atomica dei markdown
"""

import os
import tempfile
from rt.core.encoding import fix_mojibake, sanitize_text, sanitize_object_encoding
from rt.core.models import Draft, DraftUnit, DecisionLedger, ReviewDecision, ScienceIssue, ScienceType, ScienceSeverity
from rt.pipeline.ledger import apply_decisions_to_draft
from rt.pipeline.build import _atomic_write_text


import unittest


class TestEncoding(unittest.TestCase):
    def test_fix_mojibake_basic(self):
        cases = [
            ("per catene piÃ¹ lunghe l'attivazione citosolica Ã¨ seguita", "per catene più lunghe l'attivazione citosolica è seguita"),
            ("attivitÃ\xa0 dei trigliceridi", "attività dei trigliceridi"),
            ("poichÃ© Ã¨ cosÃ¬", "poiché è così"),
            ("realtÃ\xa0 del fenomeno", "realtà del fenomeno"),
            ("puÃ² contribuire", "può contribuire"),
            ("già perfetto con è, é, à, ò, ù", "già perfetto con è, é, à, ò, ù"),
            ("💡 Correzione: piÃ¹ Ã¨ bello 🔬", "💡 Correzione: più è bello 🔬"),
        ]
        for inp, expected in cases:
            self.assertEqual(fix_mojibake(inp), expected, f"Failed on '{inp}'")

    def test_sanitize_object_encoding(self):
        data = {
            "title": "Biochimica piÃ¹ avanzata",
            "units": [
                {"content": "la quota Ã¨ del 25%"},
                {"notes": ["in realtÃ\xa0 varia", "già corretto"]}
            ]
        }
        cleaned = sanitize_object_encoding(data)
        self.assertEqual(cleaned["title"], "Biochimica più avanzata")
        self.assertEqual(cleaned["units"][0]["content"], "la quota è del 25%")
        self.assertEqual(cleaned["units"][1]["notes"][0], "in realtà varia")
        self.assertEqual(cleaned["units"][1]["notes"][1], "già corretto")

    def test_apply_decisions_to_draft_heals_mojibake(self):
        unit = DraftUnit(
            unit_id="1.1",
            title="Mobilizzazione dei lipidi",
            start_segment_id="seg_000001",
            end_segment_id="seg_000010",
            source_segment_ids=["seg_000001"],
            content="La quota del glicerolo Ã¨ circa il 25%. Per catene piÃ¹ lunghe l'attivazione citosolica Ã¨ seguita dal trasporto."
        )
        draft = Draft(schema_version="1.0", lesson_id="test", units=[unit])

        sci_issue = ScienceIssue(
            id="sci_000001",
            type=ScienceType.ERR_CONCETTUALE,
            severity=ScienceSeverity.MEDIUM,
            unit_id="1.1",
            segment_id="seg_000001",
            claim="La quota del glicerolo Ã¨ circa il 25%.",
            reason="La quota non Ã¨ fissa.",
            suggested_fix="La quota puÃ² variare notevolmente."
        )

        ledger = DecisionLedger(
            schema_version="1.0",
            decisions=[
                ReviewDecision(
                    issue_id="sci_000001",
                    decision="accepted",
                    resolved_text="La quota puÃ² variare notevolmente.",
                    resolved_by="user",
                    timestamp="2026-09-06T00:00:00"
                )
            ]
        )

        resolved_draft = apply_decisions_to_draft(draft, ledger, science_issues=[sci_issue])
        res_content = resolved_draft.units[0].content

        self.assertIn("La quota può variare notevolmente.", res_content)
        self.assertNotIn("piÃ¹", res_content)
        self.assertNotIn("Ã¨", res_content)
        self.assertIn("più", res_content)
        self.assertIn("è", res_content)

    def test_atomic_write_text_sanitizes_mojibake(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = os.path.join(tmpdir, "test.md")
            raw_text = "# Titolo\n\nPer catene piÃ¹ lunghe l'attivazione citosolica Ã¨ seguita.\n"
            _atomic_write_text(out_file, raw_text)
            with open(out_file, "r", encoding="utf-8") as f:
                read_back = f.read()
            self.assertNotIn("piÃ¹", read_back)
            self.assertNotIn("Ã¨", read_back)
            self.assertIn("più", read_back)
            self.assertIn("è", read_back)


def test_latex_commands_eaten_by_json_escapes_are_repaired():
    import json
    from rt.core.encoding import repair_latex_escapes, sanitize_object_encoding
    raw = r'{"c": "$$\\sum_v\frac{|S_v|}{|S|}$$, $\beta$, $\theta$, $x\neq y$\nPoi\ttab\nne"}'
    content = json.loads(raw)["c"]
    assert "\x0c" in content and "\x08" in content
    fixed = sanitize_object_encoding({"c": content})["c"]
    assert fixed == "$$\\sum_v\\frac{|S_v|}{|S|}$$, $\\beta$, $\\theta$, $x\\neq y$\nPoi\ttab\nne"
    # a capo e tab veri restano: "\nne" è una riga che comincia con "ne", non \ne.
    assert repair_latex_escapes("riga\nuna\tvolta") == "riga\nuna\tvolta"


def test_latex_formula_repairs_and_invalid_commands():
    from rt.core.encoding import repair_latex_escapes
    # 1. "($\trm{RTPL}$)" diventa "($\mathrm{RTPL}$)"
    assert repair_latex_escapes("($\trm{RTPL}$)") == "($\\mathrm{RTPL}$)"
    assert repair_latex_escapes("($\\rm{RTPL}$)") == "($\\mathrm{RTPL}$)"
    assert repair_latex_escapes("($\\textrm{RTPL}$)") == "($\\mathrm{RTPL}$)"

    # 2. \theta, \frac, \nabla e \rho rovinati vengono riparati sia dentro che fuori
    # Rovinati da JSON: \t + heta, \x0c + rac, \n + abla, \r + ho
    assert repair_latex_escapes("$\\theta + \frac{1}{2} + \nabla + \rho$") == "$\\theta + \\frac{1}{2} + \\nabla + \\rho$"
    assert repair_latex_escapes("formula: \theta, \frac, \nabla, \rho") == "formula: \\theta, \\frac, \\nabla, \\rho"

    # 3. un TAB fuori dalle formule resta TAB
    assert repair_latex_escapes("colonna 1\tcolonna 2") == "colonna 1\tcolonna 2"

    # 4. un testo senza formule non cambia
    plain = "Testo accademico normale senza alcuna formula o comando."
    assert repair_latex_escapes(plain) == plain


def test_multiline_display_formulas_and_known_commands():
    from rt.core.encoding import repair_latex_escapes
    assert repair_latex_escapes("$$\na = b\n$$") == "$$\na = b\n$$"
    assert repair_latex_escapes("$\nabla$") == "$\\nabla$"
    assert repair_latex_escapes("$\rho$") == "$\\rho$"
    assert repair_latex_escapes("\nabla") == "\\nabla"
    assert repair_latex_escapes("\rho") == "\\rho"

