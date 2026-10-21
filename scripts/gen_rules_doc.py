"""Generate docs/rules.md from the profile data files.

python scripts/gen_rules_doc.py          # rewrite docs/rules.md
python scripts/gen_rules_doc.py --check  # exit 1 if docs/rules.md is stale
"""

from __future__ import annotations

import sys
from pathlib import Path

from mcpdialect.profiles import list_profiles, load_profile

OUT = Path(__file__).resolve().parents[1] / "docs" / "rules.md"


def render() -> str:
    lines = [
        "# Rules",
        "",
        "Generated from `src/mcpdialect/profiles/*.json` by `scripts/gen_rules_doc.py`. Do not edit by hand.",
        "",
        "Every rule cites a source and the date it was last checked. **verified** rules cite the provider's own",
        "documentation. **unverified** rules are backed only by reproducible API errors quoted in public issues;",
        "skip them with `--no-unverified`.",
        "",
    ]
    for pid in list_profiles():
        prof = load_profile(pid)
        lines += [f"## `{pid}`: {prof.title}", "", f"Applies to: {prof.applies_to}", ""]
        lines += ["| Rule | Title | Severity | Fix | Status | Checked | Source |", "|---|---|---|---|---|---|---|"]
        for r in prof.rules:
            title = r.title.replace("|", "\\|")
            cells = [r.id, title, r.severity, r.fix or "-", r.status, r.verified_on, f"[link]({r.source})"]
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")
        for r in prof.rules:
            lines.append(f"- **{r.id}**: {r.rationale}")
            for ev in r.evidence:
                lines.append(f"  - evidence: {ev}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    text = render()
    if "--check" in sys.argv:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print("docs/rules.md is stale; run: python scripts/gen_rules_doc.py", file=sys.stderr)
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
