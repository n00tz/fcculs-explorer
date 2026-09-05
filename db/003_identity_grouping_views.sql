-- Identity-grouping materialized views: surface "related records" across
-- Amateur licenses and Towers sharing an FRN, licensee, or physical site.
-- Refreshed by the ingestor after each daily/weekly load.

-- Every entity/licensee seen across both datasets, keyed by FRN where present.
CREATE MATERIALIZED VIEW identity_by_frn AS
SELECT frn, 'amateur' AS source, call_sign AS subject_key, entity_name, licensee_id
FROM amat_en
WHERE frn IS NOT NULL AND frn <> ''
UNION ALL
SELECT frn, 'tower' AS source, registration_number AS subject_key, entity_name, licensee_id
FROM tower_en
WHERE frn IS NOT NULL AND frn <> '';

CREATE INDEX idx_identity_by_frn_frn ON identity_by_frn (frn);

-- Towers grouped by rounded coordinates (same physical site), joined to any
-- amateur station using that tower's address (best-effort; exact site
-- matching arrives with future GPS-based work).
CREATE MATERIALIZED VIEW towers_by_site AS
SELECT
    ra.registration_number,
    ra.structure_city,
    ra.structure_state_code,
    ra.zip_code,
    co.latitude_direction, co.latitude_degrees, co.latitude_minutes, co.latitude_seconds,
    co.longitude_direction, co.longitude_degrees, co.longitude_minutes, co.longitude_seconds,
    round(co.latitude_total_seconds::numeric, 0) AS lat_site_key,
    round(co.longitude_total_seconds::numeric, 0) AS lon_site_key
FROM tower_ra ra
JOIN tower_co co ON co.registration_number = ra.registration_number AND co.coordinate_type = 'T';

CREATE INDEX idx_towers_by_site_key ON towers_by_site (lat_site_key, lon_site_key);

-- Licensees/entities grouped by normalized mailing address (amateur clubs
-- and trustees sharing one address, common in club-station groupings).
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
WHERE street_address IS NOT NULL AND street_address <> '';

CREATE INDEX idx_entities_by_address_key ON entities_by_address (address_key);
