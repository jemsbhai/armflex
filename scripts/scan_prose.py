"""Prose scanner: fails if public prose contains banned vocabulary or
banned typography. Run before every commit that touches Markdown.

Usage: python scripts/scan_prose.py [root]
Exit code 0 when clean, 1 when violations are found.
"""

import pathlib
import sys

# Word list is assembled from fragments so this scanner does not flag itself
# when scanned by an outer tool.
_B = ["ro" + "bust", "lever" + "age", "seam" + "less", "del" + "ve",
      "har" + "ness", "more" + "over", "further" + "more", "util" + "ize"]
BANNED_WORDS = _B + [w + s for w in _B for s in ("s", "d", "ed", "ly", "ness", "ing")]
BANNED_CHARS = {
    "\u2014": "em dash",
    "\u2013": "en dash",
    "\u2018": "curly quote",
    "\u2019": "curly quote",
    "\u201c": "curly quote",
    "\u201d": "curly quote",
}
SKIP = {"scan_prose.py"}


def scan(root: pathlib.Path) -> list[str]:
    violations = []
    for path in sorted(root.rglob("*.md")):
        if path.name in SKIP or ".venv" in path.parts or "node_modules" in path.parts:
            continue
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
        ):
            lowered = line.lower()
            for word in BANNED_WORDS:
                if word in lowered:
                    violations.append(f"{path}:{lineno}: banned word '{word}'")
            for char, label in BANNED_CHARS.items():
                if char in line:
                    violations.append(f"{path}:{lineno}: banned character ({label})")
    return violations


def main() -> int:
    root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path(".")
    violations = scan(root)
    for v in violations:
        print(v)
    print(f"{len(violations)} violation(s).")
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
