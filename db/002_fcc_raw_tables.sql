-- FCC-sourced raw record tables (Amateur Radio + ASR/Tower).
--
-- Column names/order below are derived from FCC's generic ULS data
-- dictionary (for Amateur HD/EN/AM) cross-checked against real downloaded
-- daily transaction samples on 2026-09-05, and from third-party-corroborated
-- ASR layouts (RA/EN/CO) also cross-checked against real samples.
-- See docs/fcc-data-reference.md for verification notes and known gaps.
--
-- A handful of trailing columns in amat_en and tower_ra could not be
-- unambiguously named against third-party docs (fields present in real
-- files beyond/short of the documented list) -- these are captured as
-- reserved_n placeholders and should be resolved by cross-referencing
-- populated (non-blank) sample values once a larger sample is available,
-- without blocking the rest of the schema.

CREATE TABLE amat_hd (
    unique_system_identifier     BIGINT PRIMARY KEY,
    uls_file_number               TEXT,
    ebf_number                    TEXT,
    call_sign                     TEXT,
    license_status                TEXT,
    radio_service_code            TEXT,
    grant_date                    DATE,
    expired_date                  DATE,
    cancellation_date             DATE,
    eligibility_rule_num          TEXT,
    applicant_type_code_reserved  TEXT,
    alien                         TEXT,
    alien_government              TEXT,
    alien_corporation             TEXT,
    alien_officer                 TEXT,
    alien_control                 TEXT,
    revoked                       TEXT,
    convicted                     TEXT,
    adjudged                      TEXT,
    involved_reserved             TEXT,
    common_carrier                TEXT,
    non_common_carrier            TEXT,
    private_comm                  TEXT,
    fixed                         TEXT,
    mobile                        TEXT,
    radiolocation                 TEXT,
    satellite                     TEXT,
    developmental_or_sta          TEXT,
    interconnected_service        TEXT,
    certifier_first_name          TEXT,
    certifier_mi                  TEXT,
    certifier_last_name           TEXT,
    certifier_suffix              TEXT,
    certifier_title               TEXT,
    gender                        TEXT,
    african_american              TEXT,
    native_american               TEXT,
    hawaiian                      TEXT,
    asian                         TEXT,
    white                         TEXT,
    ethnicity                     TEXT,
    effective_date                DATE,
    last_action_date              DATE,
    auction_id                    TEXT,
    reg_stat_broad_serv           TEXT,
    band_manager                  TEXT,
    type_serv_broad_serv          TEXT,
    alien_ruling                  TEXT,
    licensee_name_change          TEXT,
    reserved_1                    TEXT,
    reserved_2                    TEXT,
    reserved_3                    TEXT,
    reserved_4                    TEXT,
    reserved_5                    TEXT,
    reserved_6                    TEXT,
    reserved_7                    TEXT,
    reserved_8                    TEXT,
    reserved_9                    TEXT,
    updated_at                    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_amat_hd_call_sign ON amat_hd (call_sign);
CREATE INDEX idx_amat_hd_call_sign_trgm ON amat_hd USING gin (call_sign gin_trgm_ops);

CREATE TABLE amat_en (
    unique_system_identifier   BIGINT PRIMARY KEY,
    uls_file_number            TEXT,
    ebf_number                 TEXT,
    call_sign                  TEXT,
    entity_type                TEXT,
    licensee_id                TEXT,
    entity_name                TEXT,
    first_name                 TEXT,
    mi                         TEXT,
    last_name                  TEXT,
    suffix                     TEXT,
    phone                      TEXT,
    fax                        TEXT,
    email                      TEXT,
    street_address             TEXT,
    city                       TEXT,
    state                      TEXT,
    zip_code                   TEXT,
    po_box                     TEXT,
    attention_line             TEXT,
    sgin                       TEXT,
    frn                        TEXT,
    applicant_type_code        TEXT,
    applicant_type_code_other  TEXT,
    status_code                TEXT,
    status_date                DATE,
    reserved_1                 TEXT,
    reserved_2                 TEXT,
    reserved_3                 TEXT,
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_amat_en_frn ON amat_en (frn);
CREATE INDEX idx_amat_en_call_sign ON amat_en (call_sign);
CREATE INDEX idx_amat_en_entity_name_trgm ON amat_en USING gin (entity_name gin_trgm_ops);

CREATE TABLE amat_am (
    unique_system_identifier    BIGINT PRIMARY KEY,
    uls_file_num                TEXT,
    ebf_number                  TEXT,
    callsign                    TEXT,
    operator_class               TEXT,
    group_code                   TEXT,
    region_code                  TEXT,
    trustee_callsign             TEXT,
    trustee_indicator            TEXT,
    physician_certification      TEXT,
    ve_signature                 TEXT,
    systematic_callsign_change   TEXT,
    vanity_callsign_change       TEXT,
    vanity_relationship          TEXT,
    previous_callsign            TEXT,
    previous_operator_class      TEXT,
    trustee_name                 TEXT,
    updated_at                   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_amat_am_callsign_trgm ON amat_am USING gin (callsign gin_trgm_ops);
CREATE INDEX idx_amat_am_trustee_callsign ON amat_am (trustee_callsign);

CREATE TABLE amat_hs (
    unique_system_identifier   BIGINT,
    uls_file_number            TEXT,
    callsign                   TEXT,
    log_date                   DATE,
    code                       TEXT,
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_amat_hs_usid ON amat_hs (unique_system_identifier);

CREATE TABLE tower_ra (
    content_indicator                TEXT,
    file_number                      TEXT,
    registration_number              TEXT PRIMARY KEY,
    unique_system_identifier         BIGINT,
    application_purpose              TEXT,
    previous_purpose                 TEXT,
    input_source_code                TEXT,
    status_code                      TEXT,
    date_entered                     DATE,
    date_received                    DATE,
    date_issued                      DATE,
    date_constructed                 DATE,
    date_dismantled                  DATE,
    date_action                      DATE,
    archive_flag_code                TEXT,
    version                          TEXT,
    signature_first_name             TEXT,
    signature_mi                     TEXT,
    signature_last_name              TEXT,
    signature_suffix                 TEXT,
    signature_title                  TEXT,
    invalid_signature                TEXT,
    structure_street_address         TEXT,
    structure_city                   TEXT,
    structure_state_code             TEXT,
    county_code                      TEXT,
    zip_code                         TEXT,
    height_of_structure              NUMERIC,
    ground_elevation                 NUMERIC,
    overall_height_above_ground      NUMERIC,
    overall_height_amsl              NUMERIC,
    structure_type                   TEXT,
    date_faa_determination_issued    DATE,
    faa_study_number                 TEXT,
    faa_circular_number              TEXT,
    specification_option             TEXT,
    painting_and_lighting             TEXT,
    proposed_marking_and_lighting      TEXT,
    marking_and_lighting_other          TEXT,
    faa_emi_flag                        TEXT,
    nepa_flag                           TEXT,
    date_signed                         DATE,
    reserved_1                          TEXT,
    reserved_2                          TEXT,
    reserved_3                          TEXT,
    reserved_4                          TEXT,
    reserved_5                          TEXT,
    reserved_6                          TEXT,
    updated_at                          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_tower_ra_usid ON tower_ra (unique_system_identifier);
CREATE INDEX idx_tower_ra_status ON tower_ra (status_code);

CREATE TABLE tower_en (
    content_indicator          TEXT,
    file_number                TEXT,
    registration_number        TEXT,
    unique_system_identifier   BIGINT,
    contact_type                TEXT,
    entity_type                 TEXT,
    entity_type_other           TEXT,
    licensee_id                 TEXT,
    entity_name                 TEXT,
    first_name                  TEXT,
    mi                          TEXT,
    last_name                   TEXT,
    suffix                      TEXT,
    phone                       TEXT,
    fax_number                  TEXT,
    internet_address             TEXT,
    street_address               TEXT,
    street_address_2             TEXT,
    po_box                        TEXT,
    city                          TEXT,
    state                         TEXT,
    zip_code                      TEXT,
    attention                     TEXT,
    frn                           TEXT,
    updated_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (unique_system_identifier, registration_number)
);

CREATE INDEX idx_tower_en_frn ON tower_en (frn);
CREATE INDEX idx_tower_en_reg_num ON tower_en (registration_number);
CREATE INDEX idx_tower_en_entity_name_trgm ON tower_en USING gin (entity_name gin_trgm_ops);

CREATE TABLE tower_co (
    content_indicator          TEXT,
    file_number                TEXT,
    registration_number         TEXT,
    unique_system_identifier    BIGINT,
    coordinate_type              TEXT,
    latitude_degrees             INT,
    latitude_minutes             INT,
    latitude_seconds             NUMERIC,
    latitude_direction           TEXT,
    latitude_total_seconds       NUMERIC,
    longitude_degrees            INT,
    longitude_minutes            INT,
    longitude_seconds            NUMERIC,
    longitude_direction          TEXT,
    longitude_total_seconds      NUMERIC,
    array_tower_position         INT,
    array_total_tower            INT,
    updated_at                   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (unique_system_identifier, registration_number, coordinate_type)
);

CREATE TABLE tower_hs (
    unique_system_identifier   BIGINT,
    registration_number        TEXT,
    file_number                TEXT,
    date                        DATE,
    description                 TEXT,
    updated_at                   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_tower_hs_usid ON tower_hs (unique_system_identifier);
