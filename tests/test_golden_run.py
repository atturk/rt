"""
tests/test_golden_run.py
Test di caratterizzazione (RT4-A0): la pipeline completa in mock deve produrre lo stesso
output a terminale e gli stessi file finali delle copie salvate in tests/golden/.

Se un cambiamento è voluto, rigenera con 'python scripts/update_golden.py' e rivedi il diff.
"""
import pytest

from tests.golden_support import SCENARIOS, run_scenario, load_golden


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_golden_run(scenario, tmp_path):
    expected = load_golden(scenario)
    assert expected, f"Golden mancante per '{scenario}': esegui scripts/update_golden.py"
    actual = run_scenario(scenario, str(tmp_path))
    assert sorted(actual) == sorted(expected)
    for rel in sorted(expected):
        assert actual[rel] == expected[rel], (
            f"{scenario}/{rel} diverso dal golden. Se il cambiamento è voluto, "
            f"esegui 'python scripts/update_golden.py {scenario}' e rivedi il diff."
        )
