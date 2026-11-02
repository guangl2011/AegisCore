"""Verify docs/nsf/PITCH.md against seedfund.nsf.gov constraints.

Checks that each of the four pitch sections exists and stays within its
character limit (counted on the raw body text, conservatively including
markdown formatting characters), and that no placeholder tokens remain.
Exit code 1 on any failure so CI can gate the pitch document.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PITCH_PATH = Path(__file__).resolve().parents[1] / "docs" / "nsf" / "PITCH.md"

# seedfund.nsf.gov hard limits per section.
SECTION_LIMITS: dict[str, int] = {
    "1. Technology Innovation": 3500,
    "2. Technical Objectives and Challenges": 3500,
    "3. Market Opportunity": 1750,
    "4. Company and Team": 1750,
}

# Placeholder tokens that must never reach a reviewer (the draft DOCX carried
# literal "XXX" markers in Market Opportunity and Company and Team).
PLACEHOLDER_PATTERNS = [r"\bXXX\b", r"\bTBD\b", r"\bTODO\b"]


def parse_sections(text: str) -> dict[str, str]:
    """Map each `## <heading>` to its body text (everything before the next ##)."""
    pattern = re.compile(r"^## (.+)$", re.MULTILINE)
    matches = list(pattern.finditer(text))
    sections: dict[str, str] = {}
    for i, match in enumerate(matches):
        heading = match.group(1).strip()
        body_start = match.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections[heading] = text[body_start:body_end].strip()
    return sections


def main() -> int:
    text = PITCH_PATH.read_text(encoding="utf-8")
    sections = parse_sections(text)

    failures: list[str] = []

    for heading, limit in SECTION_LIMITS.items():
        if heading not in sections:
            failures.append(f"missing section: {heading}")
            continue
        count = len(sections[heading])
        status = "OK" if count <= limit else "OVER LIMIT"
        print(f"{status:10} {heading}: {count} / {limit} chars")
        if count > limit:
            failures.append(f"{heading}: {count} chars exceeds limit {limit}")

    for pattern in PLACEHOLDER_PATTERNS:
        hits = re.findall(pattern, text)
        if hits:
            failures.append(f"placeholder token {pattern!r} found {len(hits)}x")

    if failures:
        print("\nFAIL:")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print("\nAll pitch sections within limits; no placeholder tokens.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
