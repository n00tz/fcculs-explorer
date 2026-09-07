"""Column schemas for FCC ULS record types, in verified on-disk field order.

These lists are the source of truth for the pipe-delimited `.dat` parser and
were derived by cross-referencing real downloaded FCC files against
third-party documentation (see docs/fcc-data-reference.md for the
verification method and the specific corrections made — notably that ASR
Tower `RA`/`EN`/`CO` records carry a leading `content_indicator` field and a
`file_number`/`registration_number` order that several third-party docs got
wrong).

Each schema list is the *full* on-disk field order, i.e. it starts with
`record_type` (constant per file, e.g. "HD") which the parser strips before
handing rows to the database layer — so `len(schema) - 1` must equal the
column count of the corresponding `db/002_fcc_raw_tables.sql` table.
"""

# HD/EN/HS are GENERIC ULS record types, not Amateur-specific: the Amateur,
# GMRS, Aircraft and Ship license files all publish byte-identical layouts
# for them (verified 2026-09-07 by field-count distribution over hundreds of
# thousands of real rows in l_amat/l_gmrs/l_aircr/l_ship -- 59/30/6 fields
# respectively in every file). They are therefore named ULS_* and shared
# across services; the AMAT_* names below are kept as aliases so existing
# imports and tests keep working.
ULS_HD = [
    "record_type", "unique_system_identifier", "uls_file_number", "ebf_number",
    "call_sign", "license_status", "radio_service_code", "grant_date",
    "expired_date", "cancellation_date", "eligibility_rule_num",
    "applicant_type_code_reserved", "alien", "alien_government",
    "alien_corporation", "alien_officer", "alien_control", "revoked",
    "convicted", "adjudged", "involved_reserved", "common_carrier",
    "non_common_carrier", "private_comm", "fixed", "mobile", "radiolocation",
    "satellite", "developmental_or_sta", "interconnected_service",
    "certifier_first_name", "certifier_mi", "certifier_last_name",
    "certifier_suffix", "certifier_title", "gender", "african_american",
    "native_american", "hawaiian", "asian", "white", "ethnicity",
    "effective_date", "last_action_date", "auction_id", "reg_stat_broad_serv",
    "band_manager", "type_serv_broad_serv", "alien_ruling",
    "licensee_name_change", "reserved_1", "reserved_2", "reserved_3",
    "reserved_4", "reserved_5", "reserved_6", "reserved_7", "reserved_8",
    "reserved_9",
]

ULS_EN = [
    "record_type", "unique_system_identifier", "uls_file_number",
    "ebf_number", "call_sign", "entity_type", "licensee_id", "entity_name",
    "first_name", "mi", "last_name", "suffix", "phone", "fax", "email",
    "street_address", "city", "state", "zip_code", "po_box",
    "attention_line", "sgin", "frn", "applicant_type_code",
    "applicant_type_code_other", "status_code", "status_date",
    "reserved_1", "reserved_2", "reserved_3",
]

AMAT_AM = [
    "record_type", "unique_system_identifier", "uls_file_num", "ebf_number",
    "callsign", "operator_class", "group_code", "region_code",
    "trustee_callsign", "trustee_indicator", "physician_certification",
    "ve_signature", "systematic_callsign_change", "vanity_callsign_change",
    "vanity_relationship", "previous_callsign", "previous_operator_class",
    "trustee_name",
]

ULS_HS = [
    "record_type", "unique_system_identifier", "uls_file_number", "callsign",
    "log_date", "code",
]

# Backwards-compatible aliases: these were the original names from when the
# project only ingested Amateur, and are still referenced by existing tests
# and by AMATEUR_RECORD_TYPES below.
AMAT_HD = ULS_HD
AMAT_EN = ULS_EN
AMAT_HS = ULS_HS

# --- Service-specific record types -------------------------------------
#
# Field names/order below are transcribed verbatim from FCC's own "Public
# Access Database Definitions" SQL DDL (the PUBACC_AC / PUBACC_SH /
# PUBACC_SR / PUBACC_SV / PUBACC_SE table declarations). Two independently
# mirrored FCC versions (2025-04-17 and v6.0.0) were diffed field-by-field
# and are identical, and every field count matches real downloaded files
# (AC=10, SH=27, SR=21, SV=7, SE=42). See docs/fcc-data-reference.md.
#
# FCC's own spellings are preserved where they are irregular (`callsign`
# without an underscore in SH only; `operater`; `gmdss_exemp_req`) so these
# names stay traceable to the source document. INMARSAT/VHF/MF/HF/DSC are
# lowercased since Postgres folds unquoted identifiers anyway.

AIRCR_AC = [
    "record_type", "unique_system_identifier", "uls_file_number", "ebf_number",
    "call_sign", "aircraft_count", "type_of_carrier", "portable_indicator",
    "fleet_indicator", "n_number",
]

SHIP_SH = [
    "record_type", "unique_system_identifier", "uls_file_number", "ebf_number",
    "callsign", "type_of_authorization", "count_in_fleet", "general_class",
    "special_class", "ship_name", "ship_number", "international_voyages",
    "foreign_communications", "radiotelegraph", "mmsi_request", "gross_tonnage",
    "ship_length", "working_freq_s1", "working_freq_s2", "self_id_number",
    "comsat_id_number", "station_number", "required_cat_a", "required_cat_b",
    "required_cat_c", "required_cat_d", "required_cat_e",
]

SHIP_SR = [
    "record_type", "unique_system_identifier", "uls_file_number", "ebf_number",
    "call_sign", "epirb_identification_code", "inmarsat_a", "inmarsat_b",
    "inmarsat_c", "inmarsat_m", "inmarsat_mini", "vhf", "mf", "hf", "dsc",
    "epirb_406_mhz", "epirb_121_5_mhz", "sart", "raft_count", "lifeboat_count",
    "vessel_capacity",
]

SHIP_SV = [
    "record_type", "unique_system_identifier", "uls_file_number", "ebf_number",
    "call_sign", "voyage_number", "voyage_description",
]

SHIP_SE = [
    "record_type", "unique_system_identifier", "uls_file_number", "ebf_number",
    "call_sign", "ship_call_sign", "port_registry", "owner", "operater",
    "charter", "agent", "radiotelephone_exempt_req", "gmdss_exemp_req",
    "radio_dir_exempt_req", "prev_exempt_file_number", "foreign_port",
    "vessel_size_exempt", "equipment_exempt", "ltd_routes_exempt",
    "cond_voyages_exempt", "other_exempt", "other_exempt_desc", "ship_type",
    "number_of_crew", "number_passengers", "number_others", "count_vhf",
    "count_vhf_dsc", "count_epirb", "count_survival", "count_earth_station",
    "count_auto_alarm", "count_single_side_band", "single_side_band_type_mf",
    "single_side_band_type_hf", "single_side_band_type_dsc", "count_of_navtex",
    "count_of_9_ghz_radar", "count_of_500_khz_distress",
    "count_of_reserve_power", "count_of_other", "description_of_other",
]

TOWER_RA = [
    "record_type", "content_indicator", "file_number", "registration_number",
    "unique_system_identifier", "application_purpose", "previous_purpose",
    "input_source_code", "status_code", "date_entered", "date_received",
    "date_issued", "date_constructed", "date_dismantled", "date_action",
    "archive_flag_code", "version", "signature_first_name", "signature_mi",
    "signature_last_name", "signature_suffix", "signature_title",
    "invalid_signature", "structure_street_address", "structure_city",
    "structure_state_code", "county_code", "zip_code", "height_of_structure",
    "ground_elevation", "overall_height_above_ground", "overall_height_amsl",
    "structure_type", "date_faa_determination_issued", "faa_study_number",
    "faa_circular_number", "specification_option", "painting_and_lighting",
    "proposed_marking_and_lighting", "marking_and_lighting_other",
    "faa_emi_flag", "nepa_flag", "date_signed", "reserved_1", "reserved_2",
    "reserved_3", "reserved_4", "reserved_5", "reserved_6",
]

TOWER_EN = [
    "record_type", "content_indicator", "file_number", "registration_number",
    "unique_system_identifier", "contact_type", "entity_type",
    "entity_type_other", "licensee_id", "entity_name", "first_name", "mi",
    "last_name", "suffix", "phone", "fax_number", "internet_address",
    "street_address", "street_address_2", "po_box", "city", "state",
    "zip_code", "attention", "frn",
]

TOWER_CO = [
    "record_type", "content_indicator", "file_number", "registration_number",
    "unique_system_identifier", "coordinate_type", "latitude_degrees",
    "latitude_minutes", "latitude_seconds", "latitude_direction",
    "latitude_total_seconds", "longitude_degrees", "longitude_minutes",
    "longitude_seconds", "longitude_direction", "longitude_total_seconds",
    "array_tower_position", "array_total_tower",
]

# Maps the .dat filename (as found inside the FCC zip archives) to its
# schema, target table, and natural key columns (used for upsert + diffing).
# Amateur and Tower services each publish their own EN.dat with different
# schemas, so record-type maps are kept separate per service rather than
# merged into one filename-keyed dict.
AMATEUR_RECORD_TYPES = {
    "HD.dat": {"schema": AMAT_HD, "table": "amat_hd", "key": ["unique_system_identifier"]},
    "EN.dat": {"schema": AMAT_EN, "table": "amat_en", "key": ["unique_system_identifier"]},
    "AM.dat": {"schema": AMAT_AM, "table": "amat_am", "key": ["unique_system_identifier"]},
    "HS.dat": {"schema": AMAT_HS, "table": "amat_hs", "key": None},  # append-only history log
}

TOWER_RECORD_TYPES = {
    "RA.dat": {"schema": TOWER_RA, "table": "tower_ra", "key": ["registration_number"]},
    "EN.dat": {"schema": TOWER_EN, "table": "tower_en", "key": ["unique_system_identifier", "registration_number"]},
    "CO.dat": {"schema": TOWER_CO, "table": "tower_co", "key": ["unique_system_identifier", "registration_number", "coordinate_type"]},
}

# GMRS publishes no service-specific record type at all -- l_gmrs.zip contains
# only the generic HD/EN/HS (plus SC/LA/CO, which this project does not ingest
# for any service). So GMRS is fully described by the shared ULS layouts.
GMRS_RECORD_TYPES = {
    "HD.dat": {"schema": ULS_HD, "table": "gmrs_hd", "key": ["unique_system_identifier"]},
    "EN.dat": {"schema": ULS_EN, "table": "gmrs_en", "key": ["unique_system_identifier"]},
    "HS.dat": {"schema": ULS_HS, "table": "gmrs_hs", "key": None},  # append-only history log
}

AIRCRAFT_RECORD_TYPES = {
    "HD.dat": {"schema": ULS_HD, "table": "aircr_hd", "key": ["unique_system_identifier"]},
    "EN.dat": {"schema": ULS_EN, "table": "aircr_en", "key": ["unique_system_identifier"]},
    "AC.dat": {"schema": AIRCR_AC, "table": "aircr_ac", "key": ["unique_system_identifier"]},
    "HS.dat": {"schema": ULS_HS, "table": "aircr_hs", "key": None},
}

SHIP_RECORD_TYPES = {
    "HD.dat": {"schema": ULS_HD, "table": "ship_hd", "key": ["unique_system_identifier"]},
    "EN.dat": {"schema": ULS_EN, "table": "ship_en", "key": ["unique_system_identifier"]},
    "SH.dat": {"schema": SHIP_SH, "table": "ship_sh", "key": ["unique_system_identifier"]},
    "SR.dat": {"schema": SHIP_SR, "table": "ship_sr", "key": ["unique_system_identifier"]},
    # A single long voyage description is split by FCC across several SV rows
    # sharing one unique_system_identifier, distinguished only by
    # voyage_number -- so the natural key must include it or re-ingesting a
    # day would collapse a multi-part description down to its last fragment.
    "SV.dat": {"schema": SHIP_SV, "table": "ship_sv", "key": ["unique_system_identifier", "voyage_number"]},
    "SE.dat": {"schema": SHIP_SE, "table": "ship_se", "key": ["unique_system_identifier"]},
    "HS.dat": {"schema": ULS_HS, "table": "ship_hs", "key": None},
}

SERVICES = {
    "amateur": AMATEUR_RECORD_TYPES,
    "tower": TOWER_RECORD_TYPES,
    "gmrs": GMRS_RECORD_TYPES,
    "aircraft": AIRCRAFT_RECORD_TYPES,
    "ship": SHIP_RECORD_TYPES,
}

# The ULS record type ("HD", "SV", ...) is already encoded in each map's
# filename key, so derive it once here rather than repeating it in every
# entry where it could drift out of sync. The parser needs it to tell a new
# record from the continuation of a previous one (see parser._logical_lines).
for _record_types in SERVICES.values():
    for _filename, _meta in _record_types.items():
        _meta["record_type"] = _filename.split(".")[0].upper()
del _record_types, _filename, _meta

# Services whose records describe a personal/individual radio license keyed by
# callsign (as opposed to tower, which is keyed by ASR registration number).
# Used by the ingestor and API to apply callsign-shaped behavior uniformly.
PERSONAL_LICENSE_SERVICES = ("amateur", "gmrs", "aircraft", "ship")
