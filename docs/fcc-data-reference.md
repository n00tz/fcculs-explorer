# FCC ULS Data Reference (verified 2026-09-05)

This document records verified, current facts about FCC ULS public data access,
superseding any assumptions carried over from older personal projects or blog
posts. All access is **free, unauthenticated, public HTTP** — no API key,
login, or registration required.

## 1. Download hosts

The working file host is **`data.fcc.gov`**, not `www.fcc.gov` (landing/description
page only) or the legacy `wireless.fcc.gov` / `ftp://wirelessftp.fcc.gov`
paths (stale — redirect or dead). Directory listings are plain browsable
Apache/mod_autoindex indexes:

- Weekly full dumps: `https://data.fcc.gov/download/pub/uls/complete/`
- Daily transaction files: `https://data.fcc.gov/download/pub/uls/daily/`

## 2. Files needed for this project (Amateur + ASR/Tower + personal radio services)

### Weekly full dumps (`.../complete/`)

| File | Purpose |
|---|---|
| `l_amat.zip` | Amateur Radio full **license** database (bootstrap load) |
| `a_amat.zip` | Amateur Radio full **application** database (not needed for v1) |
| `r_tower.zip` | ASR/Tower full **registration** database (bootstrap load) |
| `a_tower.zip` | ASR full application database (not needed for v1) |
| `d_tower.zip` | ASR "deleted/dismantled towers" extract (consider for v1 — cheap way to detect dismantled towers) |
| `l_gmrs.zip` | GMRS full license database (~53 MB) |
| `l_aircr.zip` | Aircraft (Part 87) full license database (~16 MB) |
| `l_ship.zip` | Ship (Part 80) full license database (~45 MB) |

> **`l_aircraft.zip` does not exist — the real name is `l_aircr.zip`.**
> FCC returns a **`302` redirect, not a `404`**, for a file that isn't
> there, so an existence check that only tests for 404 will report a wrong
> filename as present. The `complete/` and `daily/` directory listings are
> enabled and are the authoritative source for filenames; use them rather
> than guessing at a name.

### Daily transaction files (`.../daily/`), pattern `{prefix}_{service}_{dow}.zip`, `dow ∈ {mon,tue,wed,thu,fri,sat,sun}`

| Service | License txns (use for v1) | Application txns (not v1) |
|---|---|---|
| Amateur | `l_am_mon.zip` … `l_am_sun.zip` | `a_am_mon.zip` … `a_am_sun.zip` |
| ASR/Tower | `r_tow_mon.zip` … `r_tow_sun.zip` | `a_tow_mon.zip` … `a_tow_sun.zip`, `d_tow_{dow}.zip` |
| GMRS | `l_gm_mon.zip` … `l_gm_sun.zip` | `a_gm_{dow}.zip` |
| Aircraft | `l_ac_mon.zip` … `l_ac_sun.zip` | `a_ac_{dow}.zip` |
| Ship | `l_sh_mon.zip` … `l_sh_sun.zip` | `a_sh_{dow}.zip` |

No rate-limiting/auth observed; ingestor should still use reasonable
delay/retry/backoff as a good citizen and for resilience.

## 3. Field layout documentation

- Generic ULS data dictionary (covers Amateur's `HD`/`EN`/`AM`/etc.):
  `public_access_database_definitions_<version>.pdf` on `www.fcc.gov`
  (exact current version unconfirmed from this environment — verify
  manually; last known-good reference version `v9.0` / Feb 2024 revision).
  This PDF does **not** cover ASR/Tower.
- ASR/Tower has no located FCC-published dictionary PDF; its field layout
  below is corroborated by 3 independent, actively-maintained third-party
  parser projects spanning ~10 years, but should be diffed against a real
  downloaded sample file before production use.

## 4. Record layouts (fields, in order, pipe-delimited `.dat` files)

### Amateur Radio — `l_amat.zip` / `l_am_<dow>.zip`

**HD** (License Header): `record_type, unique_system_identifier, uls_file_number,
ebf_number, call_sign, license_status, radio_service_code, grant_date,
expired_date, cancellation_date, eligibility_rule_num,
applicant_type_code_reserved, alien, alien_government, alien_corporation,
alien_officer, alien_control, revoked, convicted, adjudged,
involved_reserved, common_carrier, non_common_carrier, private_comm, fixed,
mobile, radiolocation, satellite, developmental_or_sta,
interconnected_service, certifier_first_name, certifier_mi,
certifier_last_name, certifier_suffix, certifier_title, gender,
african_american, native_american, hawaiian, asian, white, ethnicity,
effective_date, last_action_date, auction_id, reg_stat_broad_serv,
band_manager, type_serv_broad_serv, alien_ruling, licensee_name_change,
whitespace_ind, additional_cert_choice, additional_cert_answer,
discontinuation_ind, regulatory_compliance_ind, eligibility_cert_900,
transition_plan_cert_900, return_spectrum_cert_900, payment_cert_900`.
*(Fields from `whitespace_ind` onward are additions since ~2015-era
integrations; append-only, safe to parse positionally with tolerance for
trailing fields.)*

**EN** (Entity/Licensee): `record_type, unique_system_identifier,
uls_file_number, ebf_number, call_sign, entity_type, licensee_id,
entity_name, first_name, mi, last_name, suffix, phone, fax, email,
street_address, city, state, zip_code, po_box, attention_line, sgin, frn,
applicant_type_code, applicant_type_code_other, status_code, status_date,
lic_category_code, linked_license_id, linked_callsign, license_3_7ghz_type`.
*(Last field renamed from "37 GHz license type" to "3.7 GHz license type"
circa 2020-21 C-band repurposing; `linked_*` fields are newer additions.)*

**AM** (Amateur-specific): `record_type, unique_system_identifier,
uls_file_num, ebf_number, callsign, operator_class, group_code, region_code,
trustee_callsign, trustee_indicator, physician_certification, ve_signature,
systematic_callsign_change, vanity_callsign_change, vanity_relationship,
previous_callsign, previous_operator_class, trustee_name`. *(Unchanged from
long-standing ham tooling.)*

Other Amateur record types present in files but lower priority for v1:
`HS` (license history), `SC`/`SF` (special conditions), `CO` (comments),
`LA` (attachments) — same generic ULS layout family as HD/EN.

### ASR/Tower — `r_tower.zip` / `r_tow_<dow>.zip`

**RA** (Registration): `record_type, content_indicator, file_number,
registration_number, unique_system_identifier, application_purpose,
previous_purpose, input_source_code, status_code, date_entered,
date_received, date_issued, date_constructed, date_dismantled, date_action,
archive_flag_code, version, signature_first_name, signature_mi,
signature_last_name, signature_suffix, signature_title, invalid_signature,
structure_street_address, structure_city, structure_state_code, county_code,
zip_code, height_of_structure, ground_elevation,
overall_height_above_ground, overall_height_amsl, structure_type,
date_faa_determination_issued, faa_study_number, faa_circular_number,
specification_option, painting_and_lighting, proposed_marking_and_lighting,
marking_and_lighting_other, faa_emi_flag, nepa_flag, date_signed,
assignor_signature_first_name, assignor_signature_mi,
assignor_signature_last_name, assignor_signature_suffix,
assignor_signature_title`.

**EN** (Entity — ASR-specific layout, distinct from Amateur's EN):
`record_type, content_indicator, file_number, registration_number,
unique_system_identifier, contact_type, entity_type, entity_type_other,
licensee_id, entity_name, first_name, mi, last_name, suffix, phone,
fax_number, internet_address, street_address, street_address_2, po_box,
city, state, zip_code, attention, frn`.

**CO** (Coordinates — lat/long as DMS, not decimal): `record_type,
content_indicator, file_number, registration_number,
unique_system_identifier, coordinate_type, latitude_degrees,
latitude_minutes, latitude_seconds, latitude_direction,
longitude_degrees, longitude_minutes, longitude_seconds,
longitude_direction, array_tower_position, array_total_tower`.

Other ASR record types present but lower priority for v1: `HS` (history),
`RE`/`SC` (remarks).

## 5. Field counts verified against real downloaded samples (2026-09-05)

Sample daily files (`l_am_mon.zip`, `r_tow_mon.zip`) were downloaded directly
from `data.fcc.gov` and inspected field-by-field. **The section 4 field-name
lists (sourced from third-party docs) had several errors, all now corrected
in `db/002_fcc_raw_tables.sql` and confirmed against real data end-to-end
(loaded into a live Postgres 16 instance and queried successfully):**

| Record | Issue found | Resolution |
|---|---|---|
| Amateur `HD` | None — 59 fields, order matched exactly | No change |
| Amateur `EN` | None — 30 fields, order matched exactly | No change |
| Amateur `AM` | None — 18 fields, order matched exactly | No change |
| Amateur `HS` | Field count was under-counted by 1 (missing `uls_file_number`) | Added `uls_file_number` column (6 fields total: `unique_system_identifier, uls_file_number, callsign, log_date, code`) |
| Tower `RA` | **Missing `content_indicator` field entirely; `file_number`/`registration_number` order was reversed**; had 1 extra unneeded `reserved_7` | Added `content_indicator` as first column; corrected order to `content_indicator, file_number, registration_number, unique_system_identifier, ...`; reduced to `reserved_1..6` |
| Tower `EN` | Same missing `content_indicator` + reversed `file_number`/`registration_number` order | Same fix applied |
| Tower `CO` | Same missing `content_indicator` + reversed order; also missing `latitude_total_seconds`/`longitude_total_seconds` (now added) | Same fix applied, plus the two total-seconds columns |

**Verification method**: rather than trust hand-transcribed field names, a
Python script (`ingestor/tests/inspect_*.py`, used transiently, not
committed) zipped each documented column name against the actual
pipe-split values from a real downloaded row and printed `index, name,
value` for visual sanity-check (dates in date fields, callsign-shaped
strings in callsign fields, etc.) — this caught the `content_indicator`/
column-order bug that a field-count-only check would have missed (RA/EN/CO
each still summed to the same *total* field count even with the wrong
column mapping, since one missing column was offset by one column being
counted at the wrong position).

**End-to-end confirmation**: the corrected schema (`db/002_fcc_raw_tables.sql`)
was applied to a real PostgreSQL 16 container (rootless Podman host), and
all 6 real fixture files (`amat_HD.dat`, `amat_EN.dat`, `amat_AM.dat`,
`tower_RA.dat`, `tower_EN.dat`, `tower_CO.dat`) were loaded via `\copy`
without error. Loaded data round-tripped correctly (e.g. `grant_date`/
`expired_date` parsed as valid dates, `structure_city`/`structure_type`
correct on tower rows). The `identity_by_frn` materialized view
(`db/003_identity_grouping_views.sql`) correctly surfaced a real identity
grouping from the sample data: three different tower registration numbers
owned by "The Towers, LLC" all grouped under FRN `0033815929`, and two
registration numbers for "POTOMAC ELECTRIC POWER CO" grouped under FRN
`0002108785` — confirming the core "discover similar identity groupings"
feature works against real FCC data.

`towers_by_site` (coordinate-based site grouping) returned zero rows on this
5-row sample because the sample `tower_RA.dat` and `tower_CO.dat` rows
happened not to share any `registration_number` (small unrelated random
samples) — this is a sample-size artifact, not a schema bug, and should be
re-tested once the ingestor is loading a full (or larger sample) dataset.
Also corrected: the coordinate join uses `coordinate_type = 'T'` (observed
in real data), not the originally assumed `'P'`.

## 5b. Personal radio services: GMRS, Aircraft, Ship (verified 2026-09-07)

Verified by downloading the real complete dumps and strict-parsing **every
row** (5,622,629 rows total), not by sampling.

### Record types actually present

| Service | Records ingested | Row counts (complete dump) |
|---|---|---|
| GMRS | `HD`, `EN`, `HS` — **no service-specific record exists** | 609,247 HD/EN; 1,046,673 HS |
| Aircraft | `HD`, `EN`, `HS`, `AC` | 152,633 HD/EN; 152,632 AC; 365,787 HS |
| Ship | `HD`, `EN`, `HS`, `SH`, `SR`, `SV`, `SE` | 402,277 HD/EN; 402,276 SH; 131,815 SR; 679 SV; 368 SE; 1,194,085 HS |

### Key finding: HD/EN/HS are generic, not Amateur-specific

`HD` (59 fields), `EN` (30) and `HS` (6) are **byte-identical in layout
across all services** — proven by strict-parsing every row of every
service with exact field counts and zero mismatches. They are generic ULS
record types. Accordingly `schemas.py` names them `ULS_HD`/`ULS_EN`/
`ULS_HS` (the old `AMAT_*` names are retained as aliases), and the
per-service tables are created with
`CREATE TABLE ... (LIKE amat_hd INCLUDING ALL)` so structural identity is
a schema guarantee rather than three hand-transcribed copies that can
drift.

### Three parsing hazards found in the real data

1. **Embedded newlines in `SV.dat`.** 389 of its 1,068 physical lines are
   continuations — the free-text voyage description contains bare `CR`/
   `CRLF`. A line-oriented parser silently produces garbage: the old
   parser yielded 970 rows of which 291 were malformed; the current
   prefix-aware reassembly yields 679 correct records. `HD`/`EN`/`HS`/
   `SH`/`SR`/`SE` have zero continuations, but reassembly is applied
   generically because it is strictly safer.
2. **Unescaped `|` inside free-text fields.** FCC applies no quoting or
   escaping whatsoever, so a pipe typed into a free-text field breaks that
   row's field count (e.g. an attention line reading
   `Director of Safety | Charter Ops Manager`). Only 17 rows out of
   5.62M are affected, and they are *unparseable in principle* — there is
   no way to know where the real boundaries were. They are tolerated via
   truncate/pad and **logged as a warning** so the damage is never silent.
   `validate_schema.py` uses `MISMATCH_TOLERANCE = 0.001` to distinguish
   this known noise from an actual layout change.
3. **Double quotes in free text** (e.g. `"inland waters"`). Python's
   `csv.reader` treats a leading `"` as CSV syntax and rewrites the value,
   and also re-splits the embedded newlines that reassembly deliberately
   preserved. The parser therefore uses a plain `raw.split("|")`.

### Ship `SV`: one description split across several rows

Separately from the embedded-newline issue, FCC splits a long voyage
description across multiple sequence-numbered `SV` rows sharing one
`unique_system_identifier` (193 such cases). The natural key **must** be
`(unique_system_identifier, voyage_number)` — a single-column key makes
re-ingest collapse the description down to its last fragment. Enforced by
a composite primary key in `db/008` and re-joined in display order by the
API and UI.

### Column typing

Every numeric-looking column was checked against real data. All are
digits-only **except `ship_se.count_vhf_dsc`, which contains `'Y'`**
despite its name. All columns are therefore `TEXT` (ingest robustness and
project convention); numeric sorting is handled in the API with a
regex-guarded cast.

## 6. Known gaps / verify-before-production

- Exact current version number of the generic ULS PDF spec unconfirmed
  from this environment (FCC's `www.fcc.gov` blocks automated fetches from
  this sandbox at the Akamai edge — confirm manually in a normal browser).
- No FCC-native ASR data dictionary located; ASR field layout above is
  third-party corroborated (high confidence, not first-party confirmed).
  **Action**: download a real `RA.dat`/`EN.dat` sample during
  `build-ingestor` and diff column count/order against this list before
  relying on it in production.
- Byte sizes/timestamps observed during research are a live snapshot proving
  the endpoints are currently active, not permanent values.
- No rate-limiting observed, but not stress-tested — ingestor should still
  apply retry/backoff.

## 7. Additional high-value third-party code-definition sources

Discovered while researching field-level tooltip/definition support
(the `web/src/lib/fieldDefs.js` module):

- **`github.com/tgies/uls`** (Rust ULS parser project): mirrors an actual
  FCC-published code-definitions text file at
  `fcc-docs/uls_code_definitions_20240718.txt`, covering License Status,
  Application Purpose/Status, Entity Type, Applicant Type Code, Operator
  Class Code, and the generic "LO Structure Type" list — a genuine
  first-party FCC reference, not reverse-engineered. Also has a mirrored
  copy of `public_access_database_definitions` as
  `fcc-docs/public_access_database_definitions_sql_20250417.txt` (SQL
  `CREATE TABLE` statements confirming field names/order/types) and a
  fully-enumerated Rust `codes.rs` typed representation of the same codes.
  Treat this repo as the first place to check when decoding any future
  ULS dataset's coded fields.
- **`github.com/lf-connectivity/ISPToolbox`**
  (`webserver/dataUpdate/scripts/update_asr_towers.py`): an independent
  ASR/Tower ingestion script whose `STATUS_CODES`/`TYPE_MAP` dicts cite
  the FCC's own `pubacc_asr_codes_data_elem.pdf` as their source —
  useful because ASR/Tower has no FCC-published record dictionary PDF of
  its own (see gap noted above), so this is the best corroborating
  source found for ASR-specific `status_code`/`structure_type` values.
  Its `STATUS_CODES` mapping corrected an earlier best-effort guess in
  this project (`I` is **Dismantled**, not "Inactive"; `A` is
  **Cancelled**, not "Application filed").
- Some ASR/Tower `application_purpose`/`previous_purpose` values observed
  in this project's own production data (`OC`, `DI`, `SU`) do **not**
  appear in the FCC's generic ULS purpose-code list and have no located
  authoritative decode — deliberately left undecoded (shown as the raw
  code) in `fieldDefs.js` rather than guessed.
- `amat_am.systematic_callsign_change` and `.vanity_callsign_change` are
  declared as plain `char(1)` columns in every schema/definitions source
  found (no enumerated code list anywhere), yet production data shows
  `vanity_callsign_change` actually taking 6 distinct values (A/B/E/F/D/C,
  not a Y/N flag as originally assumed) — corrected to display the raw
  code with a "not officially documented" field-help note rather than a
  fabricated decode.

### Code definitions for GMRS / Aircraft / Ship (researched 2026-09-07)

Sources: FCC `uls_code_definitions_20240718.txt`, FCC **Form 605**
(Schedules B, C and G, which bind letter codes verbatim), and the FCC
radio-service code CSV. Six of the seven coded fields were substantiated
from first-party material:

- `radio_service_code`: `ZA` = General Mobile Radio (GMRS), `AC` =
  Aircraft, `SA` = Ship Recreational or Voluntarily Equipped, `SB` = Ship
  Compulsory Equipped, `SE` = Ship Exemption.
- `AC.type_of_carrier`: `P` = Private aircraft, `A` = Air carrier
  (Form 605 Schedule C item 5).
- `SH.type_of_authorization`: `R` = Regular (one vessel), `P` = Portable,
  `F` = Fleet. Real data also contains a single lowercase `'r'`;
  `describeCode()` uppercases unknown codes as a fallback, so it resolves.
- `SH.general_class`: only 5 codes are defined (`MM`/`PL`/`SV`/`FV`/`GV`)
  and they cover **99.997%** of rows. Five rare values (`PH`, `MV`, `SH`,
  `PA`, `MB` — 1 to 4 rows each) are data-entry errors and are
  deliberately left undecoded.
- `SH.special_class`: 30 codes defined; 51 distinct values appear in the
  data. The extra 21 are tiny-count dirty data, left undecoded.
- `SE.ship_type`: `C` = Cargo vessel, `P` = Passenger vessel. Form-derived
  (high confidence) rather than literally printed in a code table.

**One genuine negative result worth recording:**
`SH.working_freq_s1`/`working_freq_s2` hold values shaped like `Wnn`, and
**no published decode table for them exists anywhere** — confirmed by an
exhaustive search across FCC documentation and 10 independent third-party
ULS parsers. They are deliberately left undefined, with a tooltip saying
exactly that, rather than guessed.

**Correction adopted from this research:** `SH.station_number` is
officially the **MMSI Number**. Other official display names captured:
`self_id_number` = "Sel Call Number", `comsat_id_number` = "Sel Call —
INMARSAT", `ship_number` = "Official Number of Ship", `radiotelegraph` =
"Radiotelegraph Working Series Requested".
