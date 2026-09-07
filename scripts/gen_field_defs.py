#!/usr/bin/env python3
"""Generate `api/app/field_defs.py` from `web/src/lib/fieldDefs.js`.

The FCC field-help text and code-decoding tables were authored in the
frontend, where they are consumed by every browse/detail page. They are
now also needed server-side, so API clients (notably the MCP server) can
decode raw FCC codes instead of receiving bare values a human would see
explained in a tooltip.

Rather than hand-transcribing ~400 lines into Python -- which would drift
silently the first time someone edits only one copy -- the JS stays the
single authored source and this script mechanically derives the Python
module from it. Run this script with `--check` to fail when the
checked-in Python module has gone stale; that is the drift gate, and it
lives here rather than in `api/tests/` because the api container has no
copy of the web source or of node.

Node is used to evaluate the module rather than regex-parsing it, so the
values are exactly what the frontend sees (the JS uses unquoted keys,
single quotes, comments and trailing commas -- none of which is JSON).

Usage (from the repo root, with node available):
    python3 scripts/gen_field_defs.py            # rewrite the module
    python3 scripts/gen_field_defs.py --check    # exit 1 if out of date
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
JS_SOURCE = REPO_ROOT / "web" / "src" / "lib" / "fieldDefs.js"
PY_TARGET = REPO_ROOT / "api" / "app" / "field_defs.py"

_DUMP_SCRIPT = """
import { FIELD_HELP, CODE_MAPS } from '%s';
process.stdout.write(JSON.stringify({ FIELD_HELP, CODE_MAPS }));
"""

_HEADER = '''"""FCC field help text and code-decoding tables (GENERATED -- do not edit).

Generated from `web/src/lib/fieldDefs.js` by `scripts/gen_field_defs.py`.
That JS module is the single authored source of truth; edit it there and
re-run the generator. `scripts/gen_field_defs.py --check` fails if this
file has drifted from it.

Exposed over HTTP by `api/app/routers/field_definitions.py` so non-browser
clients can decode raw FCC codes the same way the web UI does.
"""
from __future__ import annotations

'''

_FOOTER = '''

def field_help(key: str) -> str:
    """Field-level help text for a field key, or '' if none is defined."""
    return FIELD_HELP.get(key, "")


def code_map(category: str) -> dict[str, str]:
    """The code -> description map for a category, or {} if none exists."""
    return CODE_MAPS.get(category, {})


def describe_code(category: str, code: str | None) -> str | None:
    """Description for `code` within `category`, or None when unmapped.

    Mirrors the frontend's `describeCode()`, including its case-insensitive
    retry, so both surfaces decode identically. Callers should fall back to
    displaying the raw code unchanged when this returns None.
    """
    if not code:
        return None
    mapping = CODE_MAPS.get(category)
    if not mapping:
        return None
    found = mapping.get(code)
    if found is not None:
        return found
    return mapping.get(str(code).upper())
'''


def extract() -> dict:
    """Evaluate the JS module with node and return its exported tables."""
    if shutil.which("node") is None:
        sys.exit("node is required to read the JS source; install node or run in a container")
    with tempfile.TemporaryDirectory() as tmp:
        # Node needs an ESM extension to honour the module's `export`s.
        module_copy = pathlib.Path(tmp) / "fieldDefs.mjs"
        module_copy.write_text(JS_SOURCE.read_text(encoding="utf-8"), encoding="utf-8")
        dump = pathlib.Path(tmp) / "dump.mjs"
        dump.write_text(_DUMP_SCRIPT % module_copy.as_uri(), encoding="utf-8")
        result = subprocess.run(
            ["node", str(dump)], capture_output=True, text=True, check=True
        )
    return json.loads(result.stdout)


def render(data: dict) -> str:
    """Render the extracted tables as a deterministic Python module.

    Keys are emitted in the JS module's own order (not sorted) so the diff
    stays readable and grouped by service the way the source is.
    """
    parts = [_HEADER, "FIELD_HELP: dict[str, str] = {\n"]
    for key, value in data["FIELD_HELP"].items():
        parts.append(f"    {key!r}: {value!r},\n")
    parts.append("}\n\nCODE_MAPS: dict[str, dict[str, str]] = {\n")
    for category, mapping in data["CODE_MAPS"].items():
        parts.append(f"    {category!r}: {{\n")
        for code, description in mapping.items():
            parts.append(f"        {code!r}: {description!r},\n")
        parts.append("    },\n")
    parts.append("}\n")
    parts.append(_FOOTER)
    return "".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if the generated module is out of date, without writing.",
    )
    args = parser.parse_args()

    rendered = render(extract())
    if args.check:
        current = PY_TARGET.read_text(encoding="utf-8") if PY_TARGET.exists() else ""
        if current != rendered:
            print(
                f"{PY_TARGET.relative_to(REPO_ROOT)} is out of date; "
                "re-run scripts/gen_field_defs.py",
                file=sys.stderr,
            )
            return 1
        print("field_defs.py is up to date")
        return 0

    PY_TARGET.write_text(rendered, encoding="utf-8")
    print(f"wrote {PY_TARGET.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
