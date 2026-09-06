"""
tests.test_cli_review
Verifica delle funzionalità avanzate della review CLI:
- Estrazione del contesto (frase esatta dal draft, evidenziazione [termine], assenza di puntini)
- Logica dei flag --auto-accept, --auto-accept-asr, --auto-accept-science, con livelli (yellow, red)
- Normalizzazione degli argomenti CLI
"""

import unittest
from rt.core.models import ASRLevel, ASRIssue, ScienceIssue, ScienceType, ScienceSeverity
from rt.cli import (
    extract_context_sentence,
    should_auto_accept_asr,
    should_auto_accept_science,
    normalize_review_cli_args,
)


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

    def test_should_auto_accept_asr_modes(self):
        iss_yellow = ASRIssue(
            id="asr_1", segment_id="s1", source_text="a", candidate="b",
            confidence=0.8, level=ASRLevel.YELLOW, reason="test"
        )
        iss_red = ASRIssue(
            id="asr_2", segment_id="s2", source_text="a", candidate="b",
            confidence=0.5, level=ASRLevel.RED, reason="test"
        )

        # Default (nessun flag)
        self.assertFalse(should_auto_accept_asr(iss_yellow, None, None, None))
        self.assertFalse(should_auto_accept_asr(iss_red, None, None, None))

        # --auto-accept (all)
        self.assertTrue(should_auto_accept_asr(iss_yellow, "all", None, None))
        self.assertTrue(should_auto_accept_asr(iss_red, "all", None, None))

        # --auto-accept yellow -> auto-accetta le gialle (rimangono le rosse da controllare)
        self.assertTrue(should_auto_accept_asr(iss_yellow, "yellow", None, None))
        self.assertFalse(should_auto_accept_asr(iss_red, "yellow", None, None))

        # --auto-accept-asr
        self.assertTrue(should_auto_accept_asr(iss_yellow, None, "all", None))
        self.assertTrue(should_auto_accept_asr(iss_red, None, "all", None))

        # --auto-accept-science red -> approva tutto tranne science e red (quindi approva yellow, lascia red)
        self.assertTrue(should_auto_accept_asr(iss_yellow, None, None, "red"))
        self.assertFalse(should_auto_accept_asr(iss_red, None, None, "red"))

    def test_should_auto_accept_science_modes(self):
        iss_sci = ScienceIssue(
            id="sci_1", type=ScienceType.ERR_RECONSTRUCTION,
            severity=ScienceSeverity.MEDIUM, claim="claim", reason="reason"
        )

        # Default
        self.assertFalse(should_auto_accept_science(iss_sci, None, None, None))

        # --auto-accept (all)
        self.assertTrue(should_auto_accept_science(iss_sci, "all", None, None))

        # --auto-accept yellow (lascia controllare solo yellow ASR -> science approvata)
        self.assertTrue(should_auto_accept_science(iss_sci, "yellow", None, None))

        # --auto-accept-asr (accetta solo ASR, lascia science)
        self.assertFalse(should_auto_accept_science(iss_sci, None, "all", None))

        # --auto-accept-science (accetta science)
        self.assertTrue(should_auto_accept_science(iss_sci, None, None, "all"))

        # --auto-accept-science red (approva tutto tranne science e red -> science NON approvata)
        self.assertFalse(should_auto_accept_science(iss_sci, None, None, "red"))

    def test_normalize_review_cli_args(self):
        # review con cartella e flag
        res1 = normalize_review_cli_args(["review", "/dir", "--auto-accept"])
        self.assertEqual(res1, ["review", "/dir", "--auto-accept", "all"])

        res2 = normalize_review_cli_args(["review", "/dir", "--auto-accept", "yellow"])
        self.assertEqual(res2, ["review", "/dir", "--auto-accept", "yellow"])

        res3 = normalize_review_cli_args(["review", "--auto-accept-science", "red", "/dir"])
        self.assertEqual(res3, ["review", "--auto-accept-science", "red", "/dir"])

        res4 = normalize_review_cli_args(["review", "--auto-accept-asr", "/dir"])
        self.assertEqual(res4, ["review", "--auto-accept-asr", "all", "/dir"])

        # Non-review command non deve essere toccato
        res5 = normalize_review_cli_args(["run", "/dir", "--auto-accept"])
        self.assertEqual(res5, ["run", "/dir", "--auto-accept"])


if __name__ == "__main__":
    unittest.main()
