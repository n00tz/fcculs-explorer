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

AMAT_HD = [
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

AMAT_EN = [
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

AMAT_HS = [
    "record_type", "unique_system_identifier", "uls_file_number", "callsign",
    "log_date", "code",
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

SERVICES = {
    "amateur": AMATEUR_RECORD_TYPES,
    "tower": TOWER_RECORD_TYPES,
}
