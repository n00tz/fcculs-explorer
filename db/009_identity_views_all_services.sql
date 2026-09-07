-- Extend identity grouping to every personal radio service.
--
-- This is what turns GMRS/Aircraft/Ship from three bolted-on silos into part
-- of the same product: a very common real-world case is one person holding
-- an Amateur licence AND a GMRS licence under the SAME FRN (GMRS is licensed
-- per-family, and hams frequently hold both). Before this migration an FRN
-- lookup would show only their Amateur licence and towers, silently hiding
-- the rest of their FCC footprint.
--
-- identity_by_frn and entities_by_address are recreated (rather than altered)
-- because a materialized view's defining query cannot be changed in place.
-- towers_by_site is untouched -- it is ASR-specific and has no analogue in
-- the new services.
--
-- Both views are already refreshed by the ingestor after every load
-- (MATERIALIZED_VIEWS in ingestor/scheduler.py), so no new refresh plumbing
-- is required; they simply have more sources from now on.

DROP MATERIALIZED VIEW IF EXISTS identity_by_frn;

CREATE MATERIALIZED VIEW identity_by_frn AS
SELECT frn, 'amateur' AS source, call_sign AS subject_key, entity_name, licensee_id
FROM amat_en
WHERE frn IS NOT NULL AND frn <> ''
UNION ALL
SELECT frn, 'tower' AS source, registration_number AS subject_key, entity_name, licensee_id
FROM tower_en
WHERE frn IS NOT NULL AND frn <> ''
UNION ALL
SELECT frn, 'gmrs' AS source, call_sign AS subject_key, entity_name, licensee_id
FROM gmrs_en
WHERE frn IS NOT NULL AND frn <> ''
UNION ALL
SELECT frn, 'aircraft' AS source, call_sign AS subject_key, entity_name, licensee_id
FROM aircr_en
WHERE frn IS NOT NULL AND frn <> ''
UNION ALL
SELECT frn, 'ship' AS source, call_sign AS subject_key, entity_name, licensee_id
FROM ship_en
WHERE frn IS NOT NULL AND frn <> '';

CREATE INDEX IF NOT EXISTS idx_identity_by_frn_frn ON identity_by_frn (frn);

DROP MATERIALIZED VIEW IF EXISTS entities_by_address;

CREATE MATERIALIZED VIEW entities_by_address AS
SELECT
    lower(trim(street_address)) || '|' || lower(trim(city)) || '|' || upper(trim(state)) || '|' || left(zip_code, 5) AS address_key,
    'amateur' AS source,
    call_sign AS subject_key,
    entity_name
FROM amat_en
WHERE street_address IS NOT NULL AND street_address <> ''
UNION ALL
SELECT
    lower(trim(street_address)) || '|' || lower(trim(city)) || '|' || upper(trim(state)) || '|' || left(zip_code, 5) AS address_key,
    'tower' AS source,
    registration_number AS subject_key,
    entity_name
FROM tower_en
WHERE street_address IS NOT NULL AND street_address <> ''
UNION ALL
SELECT
    lower(trim(street_address)) || '|' || lower(trim(city)) || '|' || upper(trim(state)) || '|' || left(zip_code, 5) AS address_key,
    'gmrs' AS source,
    call_sign AS subject_key,
    entity_name
FROM gmrs_en
WHERE street_address IS NOT NULL AND street_address <> ''
UNION ALL
SELECT
    lower(trim(street_address)) || '|' || lower(trim(city)) || '|' || upper(trim(state)) || '|' || left(zip_code, 5) AS address_key,
    'aircraft' AS source,
    call_sign AS subject_key,
    entity_name
FROM aircr_en
WHERE street_address IS NOT NULL AND street_address <> ''
UNION ALL
SELECT
    lower(trim(street_address)) || '|' || lower(trim(city)) || '|' || upper(trim(state)) || '|' || left(zip_code, 5) AS address_key,
    'ship' AS source,
    call_sign AS subject_key,
    entity_name
FROM ship_en
WHERE street_address IS NOT NULL AND street_address <> '';

CREATE INDEX IF NOT EXISTS idx_entities_by_address_key ON entities_by_address (address_key);
