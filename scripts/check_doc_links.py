"""Verify every intra-document anchor link in the docs actually resolves."""
import re
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
FILES = ["docs/architecture.md", "docs/user-guide.md", "docs/plan.md", "README.md"]


def slug(heading: str) -> str:
    s = heading.strip().lower()
    s = re.sub(r"[`*_]", "", s)
    s = re.sub(r"[^\w\s-]", "", s)
    # GitHub maps each whitespace char to its own hyphen and does not collapse
    # runs, so "in - no" (em dash stripped) becomes "in--no", not "in-no".
    # It also keeps the leading hyphen left behind by a leading emoji.
    return re.sub(r"\s", "-", s)


bad = 0
for rel in FILES:
    p = ROOT / rel
    if not p.exists():
        print(f"MISSING FILE {rel}")
        bad += 1
        continue
    text = p.read_text(encoding="utf-8")
    anchors = {slug(m.group(2)) for m in re.finditer(r"^(#{1,6})\s+(.*)$", text, re.M)}
    for m in re.finditer(r"\[([^\]]+)\]\(#([^)]+)\)", text):
        if m.group(2) not in anchors:
            print(f"BROKEN  {rel}: [{m.group(1)}](#{m.group(2)})")
            bad += 1
    # relative file links
    for m in re.finditer(r"\[([^\]]+)\]\((?!https?:|#)([^)#]+)(#[^)]+)?\)", text):
        target = (p.parent / m.group(2)).resolve()
        if not target.exists():
            print(f"MISSING {rel}: [{m.group(1)}]({m.group(2)})")
            bad += 1

print("OK - all doc links resolve" if not bad else f"{bad} broken link(s)")
sys.exit(1 if bad else 0)
