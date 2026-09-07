"""Integrity checks for the generated `app.field_defs` module.

The real drift gate against `web/src/lib/fieldDefs.js` is
`scripts/gen_field_defs.py --check`, which needs node and the web source
and therefore runs outside this container (see the api test runner). What
these tests cover is that the generated module is structurally sound and
that `describe_code()` matches the frontend's `describeCode()` semantics,
since the MCP server and the web UI must decode identically.
"""
import os
import sys

sys.path.insert(0, "/app")
os.environ.setdefault("FCCULS_SESSION_SECRET", "test-secret")

from app.field_defs import (  # noqa: E402
    CODE_MAPS,
    FIELD_HELP,
    code_map,
    describe_code,
    field_help,
)


def test_tables_are_populated():
    # Guards against the generator silently emitting empty dicts (e.g. if
    # the JS export names were renamed) and the file still importing fine.
    assert len(FIELD_HELP) > 50
    assert len(CODE_MAPS) > 15
    assert sum(len(m) for m in CODE_MAPS.values()) > 150


def test_all_values_are_non_empty_strings():
    for key, value in FIELD_HELP.items():
        assert isinstance(value, str) and value.strip(), key
    for category, mapping in CODE_MAPS.items():
        assert isinstance(mapping, dict) and mapping, category
        for code, description in mapping.items():
            assert isinstance(code, str), (category, code)
            assert isinstance(description, str) and description.strip(), (category, code)


def test_known_decodings_survived_generation():
    # Spot-check one value per service so a mangled extraction can't pass.
    assert describe_code("license_status", "A") == "Active"
    assert describe_code("operator_class", "E") == "Amateur Extra"
    assert describe_code("applicant_type_code", "B") == "Amateur Club"


def test_describe_code_is_case_insensitive_like_the_frontend():
    # The frontend retries with an upper-cased key; so must this, or the
    # same input would decode on the website but not through the API.
    assert describe_code("license_status", "a") == describe_code("license_status", "A")


def test_unmapped_lookups_return_none_not_raise():
    # Callers fall back to displaying the raw code, so an unknown code and
    # an unknown category are both normal, non-exceptional outcomes.
    assert describe_code("license_status", "ZZZZ") is None
    assert describe_code("no_such_category", "A") is None
    assert describe_code("license_status", None) is None
    assert describe_code("license_status", "") is None


def test_accessor_fallbacks():
    assert field_help("no_such_field") == ""
    assert code_map("no_such_category") == {}
    assert field_help("license_status")
    assert code_map("license_status")
