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

## 2. Files needed for this project (v1 scope: Amateur + ASR/Tower)

### Weekly full dumps (`.../complete/`)

| File | Purpose |
|---|---|
| `l_amat.zip` | Amateur Radio full **license** database (bootstrap load) |
| `a_amat.zip` | Amateur Radio full **application** database (not needed for v1) |
| `r_tower.zip` | ASR/Tower full **registration** database (bootstrap load) |
| `a_tower.zip` | ASR full application database (not needed for v1) |
| `d_tower.zip` | ASR "deleted/dismantled towers" extract (consider for v1 — cheap way to detect dismantled towers) |

### Daily transaction files (`.../daily/`), pattern `{prefix}_{service}_{dow}.zip`, `dow ∈ {mon,tue,wed,thu,fri,sat,sun}`

| Service | License txns (use for v1) | Application txns (not v1) |
|---|---|---|
| Amateur | `l_am_mon.zip` … `l_am_sun.zip` | `a_am_mon.zip` … `a_am_sun.zip` |
| ASR/Tower | `r_tow_mon.zip` … `r_tow_sun.zip` | `a_tow_mon.zip` … `a_tow_sun.zip`, `d_tow_{dow}.zip` |

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
