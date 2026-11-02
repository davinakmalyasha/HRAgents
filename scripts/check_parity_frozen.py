"""Verify the parity corpus against `parity/FROZEN.md`.

Hashes are computed over LF-normalized bytes so a Windows checkout does not
produce a false failure. Any extra, missing, or changed fixture is a failure:
the corpus is shrink-only until Gate 5.
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "parity" / "fixtures"
FROZEN = ROOT / "parity" / "FROZEN.md"


def main() -> int:
    text = FROZEN.read_text(encoding="utf-8")
    frozen = {
        name: expected
        for name, expected in re.findall(r"\| ([A-Za-z0-9_.-]+\.json) \| `([0-9a-f]{64})` \|", text)
    }
    if not frozen:
        print("no fixture hashes found in parity/FROZEN.md", file=sys.stderr)
        return 1

    actual = {}
    for path in sorted(FIXTURES.glob("*.json")):
        data = path.read_bytes().replace(b"\r\n", b"\n")
        actual[path.name] = hashlib.sha256(data).hexdigest()

    failures = []
    for name in sorted(set(frozen) | set(actual)):
        if name not in actual:
            failures.append(f"missing fixture: {name}")
        elif name not in frozen:
            failures.append(f"unfrozen fixture: {name}")
        elif actual[name] != frozen[name]:
            failures.append(
                f"hash mismatch: {name}\n  frozen {frozen[name]}\n  actual {actual[name]}"
            )

    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(f"parity corpus ok: {len(actual)} fixtures match FROZEN.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
