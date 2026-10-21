"""docs/rules.md must match the profile data."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_rules_doc_is_up_to_date():
    script = Path(__file__).resolve().parents[1] / "scripts" / "gen_rules_doc.py"
    r = subprocess.run([sys.executable, str(script), "--check"], capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr
