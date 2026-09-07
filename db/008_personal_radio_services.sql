-- Personal radio services: GMRS (ZA), Aircraft (Part 87), Ship (Part 80).
--
-- Verified against real FCC complete dumps on 2026-09-07 (l_gmrs.zip,
-- l_aircr.zip, l_ship.zip). See docs/fcc-data-reference.md for the full
-- verification notes, including the l_aircr naming trap and the SV.dat
-- embedded-newline finding.
--
-- KEY FACT: HD, EN and HS are GENERIC ULS record types, not Amateur-specific.
-- Their layouts are byte-identical across the Amateur, GMRS, Aircraft and
-- Ship files (58/29/5 data columns respectively, confirmed by strict-parsing
-- every row of all three new complete dumps -- 5.6M rows -- with zero field
-- count mismatches beyond 17 rows containing an unescaped '|' in a free-text
-- field).
--
-- Because of that, the per-service HD/EN/HS tables are declared with
-- `LIKE amat_hd INCLUDING ALL` rather than by re-transcribing 58 columns
-- three times. This makes structural identity a guarantee of the schema
-- itself instead of something a reader has to diff by eye, and copies the
-- column types, defaults, PRIMARY KEY and every index (btree + pg_trgm)
-- that already makes Amateur browse/search/identity-grouping fast.

-- === GMRS (radio_service_code 'ZA') ====================================
-- GMRS publishes NO service-specific record type: l_gmrs.zip contains only
-- HD/EN/HS (plus CO/LA/SC, which this project does not ingest for any
-- service). So these three tables describe GMRS completely.
CREATE TABLE IF NOT EXISTS gmrs_hd (LIKE amat_hd INCLUDING ALL);
CREATE TABLE IF NOT EXISTS gmrs_en (LIKE amat_en INCLUDING ALL);
CREATE TABLE IF NOT EXISTS gmrs_hs (LIKE amat_hs INCLUDING ALL);

-- === Aircraft (Part 87, radio_service_code 'AC') =======================
CREATE TABLE IF NOT EXISTS aircr_hd (LIKE amat_hd INCLUDING ALL);
CREATE TABLE IF NOT EXISTS aircr_en (LIKE amat_en INCLUDING ALL);
CREATE TABLE IF NOT EXISTS aircr_hs (LIKE amat_hs INCLUDING ALL);

-- AC: aircraft-specific detail. Field names/order transcribed verbatim from
-- FCC's Public Access Database Definitions DDL (PUBACC_AC); 10 fields,
-- matching all 152,632 real rows.
CREATE TABLE IF NOT EXISTS aircr_ac (
    unique_system_identifier   BIGINT PRIMARY KEY,
    uls_file_number            TEXT,
    ebf_number                 TEXT,
    call_sign                  TEXT,
    aircraft_count             TEXT,
    type_of_carrier            TEXT,
    portable_indicator         TEXT,
    fleet_indicator            TEXT,
    n_number                   TEXT,
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_aircr_ac_call_sign ON aircr_ac (call_sign);
-- N-number (FAA tail number) is how aircraft operators actually look up a
-- record, so it gets the same trigram treatment as a callsign.
CREATE INDEX IF NOT EXISTS idx_aircr_ac_n_number_trgm ON aircr_ac USING gin (n_number gin_trgm_ops);

-- === Ship (Part 80, radio_service_codes 'SA' / 'SB' / 'SE') ============
CREATE TABLE IF NOT EXISTS ship_hd (LIKE amat_hd INCLUDING ALL);
CREATE TABLE IF NOT EXISTS ship_en (LIKE amat_en INCLUDING ALL);
CREATE TABLE IF NOT EXISTS ship_hs (LIKE amat_hs INCLUDING ALL);

-- SH: ship station detail (27 fields). NOTE: FCC spells the callsign column
-- "callsign" (no underscore) in this record type only -- preserved verbatim
-- so the column stays traceable to the source definition.
CREATE TABLE IF NOT EXISTS ship_sh (
    unique_system_identifier   BIGINT PRIMARY KEY,
    uls_file_number            TEXT,
    ebf_number                 TEXT,
    callsign                   TEXT,
    type_of_authorization      TEXT,
    count_in_fleet             TEXT,
    general_class              TEXT,
    special_class              TEXT,
    ship_name                  TEXT,
    ship_number                TEXT,
    international_voyages      TEXT,
    foreign_communications     TEXT,
    radiotelegraph             TEXT,
    mmsi_request               TEXT,
    -- The numeric-looking columns below are stored as TEXT deliberately.
    -- Every populated value in the current dump is digits-only, but a
    -- narrower type would turn a single malformed future value into a hard
    -- failure of the nightly ingest. The API sorts them numerically with a
    -- regex-guarded cast instead. (See count_vhf_dsc in ship_se for a live
    -- example of an FCC column whose name promises a count and delivers 'Y'.)
    gross_tonnage              TEXT,
    ship_length                TEXT,
    working_freq_s1            TEXT,
    working_freq_s2            TEXT,
    self_id_number             TEXT,
    comsat_id_number           TEXT,
    station_number             TEXT,
    required_cat_a             TEXT,
    required_cat_b             TEXT,
    required_cat_c             TEXT,
    required_cat_d             TEXT,
    required_cat_e             TEXT,
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ship_sh_callsign ON ship_sh (callsign);
-- Vessel name is the ship equivalent of an entity name for search purposes.
CREATE INDEX IF NOT EXISTS idx_ship_sh_ship_name_trgm ON ship_sh USING gin (ship_name gin_trgm_ops);
-- MMSI / maritime station number is a primary real-world identifier.
CREATE INDEX IF NOT EXISTS idx_ship_sh_station_number ON ship_sh (station_number);

-- SR: ship radio equipment / safety fit-out (21 fields).
CREATE TABLE IF NOT EXISTS ship_sr (
    unique_system_identifier   BIGINT PRIMARY KEY,
    uls_file_number            TEXT,
    ebf_number                 TEXT,
    call_sign                  TEXT,
    epirb_identification_code  TEXT,
    inmarsat_a                 TEXT,
    inmarsat_b                 TEXT,
    inmarsat_c                 TEXT,
    inmarsat_m                 TEXT,
    inmarsat_mini              TEXT,
    vhf                        TEXT,
    mf                         TEXT,
    hf                         TEXT,
    dsc                        TEXT,
    epirb_406_mhz              TEXT,
    epirb_121_5_mhz            TEXT,
    sart                       TEXT,
    raft_count                 TEXT,
    lifeboat_count             TEXT,
    vessel_capacity            TEXT,
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ship_sr_call_sign ON ship_sr (call_sign);

-- SV: voyage description (7 fields).
-- A single long description is split by FCC across SEVERAL SV rows sharing
-- one unique_system_identifier and distinguished only by voyage_number (193
-- such multi-row descriptions in the current dump), so the natural key MUST
-- include voyage_number -- keying on the identifier alone would collapse a
-- multi-part description down to whichever fragment was written last.
CREATE TABLE IF NOT EXISTS ship_sv (
    unique_system_identifier   BIGINT NOT NULL,
    uls_file_number            TEXT,
    ebf_number                 TEXT,
    call_sign                  TEXT,
    voyage_number              TEXT NOT NULL,
    -- Free text that legitimately contains embedded newlines; the ingestor
    -- reassembles the physical lines FCC splits it across.
    voyage_description         TEXT,
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (unique_system_identifier, voyage_number)
);
CREATE INDEX IF NOT EXISTS idx_ship_sv_call_sign ON ship_sv (call_sign);

-- SE: ship exemption request detail (42 fields).
CREATE TABLE IF NOT EXISTS ship_se (
    unique_system_identifier   BIGINT PRIMARY KEY,
    uls_file_number            TEXT,
    ebf_number                 TEXT,
    call_sign                  TEXT,
    ship_call_sign             TEXT,
    port_registry              TEXT,
    owner                      TEXT,
    -- "operater" and "gmdss_exemp_req" are FCC's own misspellings, kept
    -- verbatim so both stay traceable to the published definition.
    operater                   TEXT,
    charter                    TEXT,
    agent                      TEXT,
    radiotelephone_exempt_req  TEXT,
    gmdss_exemp_req            TEXT,
    radio_dir_exempt_req       TEXT,
    prev_exempt_file_number    TEXT,
    foreign_port               TEXT,
    vessel_size_exempt         TEXT,
    equipment_exempt           TEXT,
    ltd_routes_exempt          TEXT,
    cond_voyages_exempt        TEXT,
    other_exempt               TEXT,
    other_exempt_desc          TEXT,
    ship_type                  TEXT,
    number_of_crew             TEXT,
    number_passengers          TEXT,
    number_others              TEXT,
    count_vhf                  TEXT,
    -- Despite the name, this holds 'Y'/'N', not a count (verified against
    -- all 198 populated rows in the current dump).
    count_vhf_dsc              TEXT,
    count_epirb                TEXT,
    count_survival             TEXT,
    count_earth_station        TEXT,
    count_auto_alarm           TEXT,
    count_single_side_band     TEXT,
    single_side_band_type_mf   TEXT,
    single_side_band_type_hf   TEXT,
    single_side_band_type_dsc  TEXT,
    count_of_navtex            TEXT,
    count_of_9_ghz_radar       TEXT,
    count_of_500_khz_distress  TEXT,
    count_of_reserve_power     TEXT,
    count_of_other             TEXT,
    description_of_other       TEXT,
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ship_se_call_sign ON ship_se (call_sign);

-- === Service tagging for change events and watches =====================

-- Which service a change event came from, so a watch can optionally be
-- scoped to one service. Nullable: rows written before this migration
-- (Amateur/Tower) legitimately predate the concept.
ALTER TABLE change_events ADD COLUMN IF NOT EXISTS service TEXT;
CREATE INDEX IF NOT EXISTS idx_change_events_service ON change_events (service);

-- Optional per-watch service filter. NULL means "any service", which
-- preserves the existing behavior of every watch already in the database:
-- a plain callsign watch keeps matching across all services by default.
ALTER TABLE watches ADD COLUMN IF NOT EXISTS service TEXT;

-- The original uniqueness rule was (user_id, subject_type, subject_value,
-- channel_id), which predates services. Left alone, it would make the new
-- service scope largely useless: a user could not watch the same callsign
-- for two different services on one channel (e.g. their callsign as both a
-- GMRS and an Amateur licence), because the two rows would collide.
--
-- NULLS NOT DISTINCT (Postgres 15+) is the important detail here. By
-- default Postgres treats NULLs as distinct in a unique constraint, which
-- would silently DROP duplicate protection for unscoped watches -- the
-- most common kind -- letting a user create the same watch over and over.
-- NULLS NOT DISTINCT keeps NULL == NULL, so unscoped duplicates are still
-- rejected exactly as before, while differently-scoped watches coexist.
ALTER TABLE watches DROP CONSTRAINT IF EXISTS watches_user_id_subject_type_subject_value_channel_id_key;
DO $$
BEGIN
    ALTER TABLE watches ADD CONSTRAINT watches_user_subject_channel_service_key
        UNIQUE NULLS NOT DISTINCT (user_id, subject_type, subject_value, channel_id, service);
EXCEPTION
    WHEN duplicate_table THEN NULL;  -- already applied
END $$;
