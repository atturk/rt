"""
tests.test_cli_review
Verifica delle funzionalità avanzate della review CLI:
- Estrazione del contesto (frase esatta dal draft, evidenziazione [termine], assenza di puntini)
- Logica dei flag --auto-accept, --auto-accept-asr, --auto-accept-science, con livelli (yellow, red)
- Normalizzazione degli argomenti CLI
"""

import unittest
from rt.core.models import ScienceIssue, ScienceType, ScienceSeverity
from rt.pipeline.ledger import extract_context_sentence
from rt.pipeline.issue_review import should_auto_accept_science
from rt.cli import normalize_review_cli_args


class TestCLIReview(unittest.TestCase):

    def test_extract_context_sentence_exact(self):
        content = (
            "### 2.1 Trasporto degli acidi grassi\n\n"
            "L'acil-CoA a catena lunga non può attraversare liberamente la membrana mitocondriale interna. "
            "Il passaggio attraverso la membrana interna richiede una specifica carrier proteina che consenta la traslocazione del complesso. "
            "Successivamente, la carnitina palmitoil-trasferasi II rigenera l'acil-CoA all'interno della matrice."
        )
        res = extract_context_sentence(content, target="carrier proteina", fallback_target="caso una proteina")
        self.assertEqual(
            res,
            "Il passaggio attraverso la membrana interna richiede una specifica [carrier proteina] che consenta la traslocazione del complesso."
        )
        self.assertNotIn("...", res)

    def test_extract_context_sentence_fallback(self):
        content = (
            "- Introduzione al processo.\n"
            "- In questo caso una proteina trasportatrice favorisce il legame con la membrana esterna.\n"
            "- Conclusione della prima fase."
        )
        res = extract_context_sentence(content, target="carrier proteina", fallback_target="caso una proteina")
        self.assertEqual(
            res,
            "In questo [caso una proteina] trasportatrice favorisce il legame con la membrana esterna."
        )

    def test_extract_context_sentence_clean_headings(self):
        content = "## 1.2 Regolazione\nL'enzima licorolo chinasi converte il substrato con alta efficienza."
        res = extract_context_sentence(content, target="licorolo chinasi")
        self.assertEqual(res, "L'enzima [licorolo chinasi] converte il substrato con alta efficienza.")

    def test_extract_context_not_found(self):
        content = "Testo completamente slegato che non contiene le parole cercate."
        res = extract_context_sentence(content, target="carnitina", fallback_target="traslocasi")
        self.assertEqual(res, "")

    def test_should_auto_accept_science_modes(self):
        iss_sci = ScienceIssue(
            id="sci_1", type=ScienceType.ERR_RECONSTRUCTION,
            severity=ScienceSeverity.MEDIUM, claim="claim", reason="reason"
        )

        # Default
        self.assertFalse(should_auto_accept_science(iss_sci, None))

        # --auto-accept (all)
        self.assertTrue(should_auto_accept_science(iss_sci, "all"))

    def test_normalize_review_cli_args(self):
        res1 = normalize_review_cli_args(["review", "/dir", "--auto-accept"])
        self.assertEqual(res1, ["review", "/dir", "--auto-accept", "all"])

        res2 = normalize_review_cli_args(["review", "/dir", "--auto-accept", "all"])
        self.assertEqual(res2, ["review", "/dir", "--auto-accept", "all"])

        res3 = normalize_review_cli_args(["review", "--auto-accept", "/dir"])
        self.assertEqual(res3, ["review", "--auto-accept", "all", "/dir"])

        # Non-review command non deve essere toccato
        res4 = normalize_review_cli_args(["run", "/dir", "--auto-accept"])
        self.assertEqual(res4, ["run", "/dir", "--auto-accept"])

    def test_cli_removed_review_subcommands_fail(self):
        from rt.cli import main
        from unittest.mock import patch
        # review-asr and review-science must fail as invalid choices
        with patch("sys.argv", ["rt", "review-asr", "dummy"]):
            with self.assertRaises(SystemExit) as cm1:
                main()
            self.assertEqual(cm1.exception.code, 2)

        with patch("sys.argv", ["rt", "review-science", "dummy"]):
            with self.assertRaises(SystemExit) as cm2:
                main()
            self.assertEqual(cm2.exception.code, 2)


if __name__ == "__main__":
    unittest.main()

