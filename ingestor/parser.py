"""Pipe-delimited `.dat` file parser for FCC ULS records.

Given a schema (ordered list of field names, see schemas.py) and a file
path, yields one dict per row with `record_type` stripped and blank strings
normalized to None (FCC files use empty fields, not explicit NULL markers).

Also parses the `counts` member every FCC archive carries, which declares
FCC's own row count per file plus the archive's creation time -- see
parse_counts() at the bottom of this module.
"""
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, NamedTuple
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


class RowFieldCountMismatch(ValueError):
    """Raised when a data row doesn't have the expected number of fields.

    FCC has historically only appended new trailing fields to records
    (see docs/fcc-data-reference.md), so a mismatch here likely means the
    schema in schemas.py is stale and needs re-verification against a fresh
    sample rather than being silently ignored.
    """


def _logical_lines(path: Path, record_type: str | None) -> Iterator[str]:
    """Yield one string per LOGICAL record, re-joining rows that FCC split
    across multiple physical lines.

    Some FCC files contain raw CR/LF characters *inside* a free-text field,
    which naive line-oriented parsing silently turns into extra malformed
    rows. Verified 2026-09-07: 389 of the 1,068 physical lines in Ship's
    `SV.dat` (voyage descriptions) are continuations of a previous record,
    while `HD`/`EN`/`HS`/`SH`/`SR`/`SE` contained none. The handling is
    applied to every file rather than special-cased to SV, since it is
    strictly safer and guards against the same surprise in a future dataset.

    A physical line starts a new record only if it begins with the file's
    record-type prefix (e.g. "SV|"); anything else is appended to the record
    being built, with the newline preserved because it is real field content.
    Falls back to plain line splitting when the record type is unknown.
    """
    with open(path, encoding="latin-1", newline="") as f:
        physical = f.read().splitlines()

    if record_type is None:
        yield from (line for line in physical if line)
        return

    prefix = f"{record_type}|"
    buffer: str | None = None
    for line in physical:
        if line.startswith(prefix):
            if buffer is not None:
                yield buffer
            buffer = line
        elif buffer is not None:
            buffer += "\n" + line
        elif line.strip():
            # Content appearing before any record start (not seen in practice).
            # Passed through so it fails loudly on field count rather than
            # being silently discarded.
            yield line
    if buffer is not None:
        yield buffer


def parse_dat_file(
    path: Path,
    schema: list[str],
    strict: bool = True,
    record_type: str | None = None,
) -> Iterator[dict]:
    """Parse a pipe-delimited FCC `.dat` file into dicts.

    `record_type` is the two-letter ULS record type ("HD", "SV", ...) used to
    detect where each logical record starts. It defaults to the last
    underscore-separated segment of the file stem, so both FCC's own naming
    ("SV.dat") and this project's test-fixture naming ("ship_SV.dat") resolve
    correctly. Pass it explicitly when the filename can't be trusted.
    """
    expected = len(schema)
    if record_type is None:
        record_type = path.stem.rsplit("_", 1)[-1].upper() or None

    for line_num, raw in enumerate(_logical_lines(path, record_type), start=1):
        # Split on the delimiter directly rather than via csv.reader: these
        # files are raw pipe-delimited text with no quoting convention, and
        # csv.reader would (a) treat a leading double-quote in a field such
        # as an entity name as CSV quoting and silently rewrite the value,
        # and (b) re-split the newlines that _logical_lines() deliberately
        # preserved inside free-text fields.
        row = raw.split("|")
        if not row:
            continue
        if len(row) != expected:
            if strict:
                raise RowFieldCountMismatch(
                    f"{path.name} line {line_num}: expected {expected} fields, got {len(row)}"
                )
            # FCC does not escape or quote the delimiter, so a literal "|"
            # typed into a free-text field yields extra columns and shifts
            # everything after it. Verified 2026-09-07: real but very rare
            # (5 rows across ~1.5M in l_aircr/l_ship -- e.g. an attention
            # line reading "Director of Safety | Charter Ops Manager").
            # These rows are unparseable in principle, so they are tolerated
            # by truncating/padding rather than failing the whole ingest,
            # but they are logged so the damage is never silent.
            logger.warning(
                "%s line %s: expected %s fields, got %s -- tolerating "
                "(likely an unescaped '|' in a free-text field); "
                "fields after the extra delimiter may be shifted",
                path.name, line_num, expected, len(row),
            )
            if len(row) > expected:
                row = row[:expected]
            else:
                row = row + [""] * (expected - len(row))
        record = {name: (value if value != "" else None) for name, value in zip(schema, row)}
        record.pop("record_type", None)
        yield record


# ---------------------------------------------------------------------------
# The `counts` member every FCC archive carries
# ---------------------------------------------------------------------------

# Example (real, from l_am_tue.zip, CRLF line endings):
#   File Creation Date: Wed Sep  2 08:00:10 EDT 2026
#      819 /home/pubacc/scripts/licdayzipdata/AM.dat
#     3234 /home/pubacc/scripts/licdayzipdata/HS.dat
#     5812 total
_COUNTS_DATE_RE = re.compile(r"File Creation Date:\s*(?P<value>.+?)\s*$", re.MULTILINE)
_COUNTS_ROW_RE = re.compile(r"^\s*(?P<rows>\d+)\s+(?P<path>\S+\.dat)\s*$", re.MULTILINE | re.IGNORECASE)
# "Wed Sep  2 08:00:10 EDT 2026" -- note the padded single-digit day and the
# timezone ABBREVIATION, which strptime cannot portably interpret. The
# abbreviation is captured separately and deliberately discarded: FCC's
# publishing host is US Eastern, so the wall clock is re-interpreted in that
# named zone (matching index_scraper.FCC_TZ) instead of trusting %Z, which
# silently produces a naive/UTC datetime on most platforms.
_CREATION_DATE_RE = re.compile(
    r"^(?P<dow>\w{3})\s+(?P<mon>\w{3})\s+(?P<day>\d{1,2})\s+"
    r"(?P<time>\d{2}:\d{2}:\d{2})\s+(?P<tz>[A-Z]{2,5})\s+(?P<year>\d{4})$"
)

FCC_TZ = ZoneInfo("America/New_York")


class ArchiveCounts(NamedTuple):
    """FCC's own declared contents for one archive.

    `rows` maps a bare filename (e.g. "HD.dat") to the row count FCC says it
    wrote, which is an authoritative integrity oracle for what we parsed --
    verified to match exactly against production for two different services
    (amateur 2026-09-01 = 5,691 rows; ship 2026-09-02 = 219).

    `created_at` is the archive's PUBLICATION time, not its data date. It
    matches the Last-Modified header exactly, which makes it a usable
    fallback for dating a file whose Last-Modified is missing -- such files
    are otherwise skipped permanently.
    """
    rows: dict
    created_at: object


def parse_counts(text: str) -> ArchiveCounts:
    """Parse an archive's `counts` member.

    Tolerant by design: this is metadata, and failing to read it must never
    block an otherwise-valid ingest. An unrecognised document yields empty
    rows and a None timestamp, and callers treat that as "no integrity
    oracle available" rather than an error.

    Note the `N total` trailing line is deliberately NOT captured -- it
    counts every file in the archive, including record types this project
    does not ingest (CO/SC/LA/SF), so comparing against it would report a
    permanent false mismatch.
    """
    rows = {
        Path(match.group("path")).name: int(match.group("rows"))
        for match in _COUNTS_ROW_RE.finditer(text)
    }

    created_at = None
    date_match = _COUNTS_DATE_RE.search(text)
    if date_match:
        created_at = _parse_creation_date(date_match.group("value"))
        if created_at is None:
            logger.warning("unparseable File Creation Date in counts: %r", date_match.group("value"))

    return ArchiveCounts(rows=rows, created_at=created_at)


def _parse_creation_date(value: str):
    match = _CREATION_DATE_RE.match(value.strip())
    if not match:
        return None
    try:
        naive = datetime.strptime(
            f"{match.group('mon')} {match.group('day')} {match.group('year')} {match.group('time')}",
            "%b %d %Y %H:%M:%S",
        )
    except ValueError:
        return None
    return naive.replace(tzinfo=FCC_TZ).astimezone(timezone.utc)
