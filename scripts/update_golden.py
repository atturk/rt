"""Rigenera le copie golden in tests/golden/ (RT4-A0).

Da usare solo quando un cambiamento dell'output della pipeline mock è voluto:
    .venv/bin/python scripts/update_golden.py            # tutti gli scenari
    .venv/bin/python scripts/update_golden.py audio_full # uno solo
Poi rivedi il diff di tests/golden/ prima del commit.
"""
import os
import sys
import tempfile

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from tests.golden_support import SCENARIOS, run_scenario, write_golden  # noqa: E402


def main(argv):
    names = argv or list(SCENARIOS)
    unknown = [n for n in names if n not in SCENARIOS]
    if unknown:
        print(f"Scenari sconosciuti: {', '.join(unknown)}. Disponibili: {', '.join(SCENARIOS)}")
        return 2
    for name in names:
        with tempfile.TemporaryDirectory() as root:
            data = run_scenario(name, root)
        write_golden(name, data)
        print(f"✔ {name}: {len(data)} file scritti in tests/golden/{name}/")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
