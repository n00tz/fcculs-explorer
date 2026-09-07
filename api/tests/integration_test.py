"""End-to-end integration test for the API: seeds representative Amateur +
Tower rows directly, then exercises search/browse/detail/identity endpoints,
plus the full auth -> channel -> watch CRUD lifecycle, against a real
Postgres instance and the actual FastAPI app object (in-process ASGI, no
separate uvicorn process needed).
"""
import os
import sys

sys.path.insert(0, "/app")

os.environ.setdefault(
    "FCCULS_DATABASE_URL", "postgresql://postgres:test@localhost:5432/fcculs_test"
)
os.environ.setdefault("FCCULS_MAGIC_LINK_BASE_URL", "http://testserver")
os.environ.setdefault("FCCULS_SESSION_SECRET", "test-secret")
# No notifier worker runs in this isolated test pod, so keep the test-send
# poll short -- the endpoint will legitimately time out waiting for a
# result, which is exactly what we assert on below.
os.environ.setdefault("FCCULS_TEST_SEND_POLL_TIMEOUT_SECONDS", "1")

import psycopg
from fastapi.testclient import TestClient

DSN = os.environ["FCCULS_DATABASE_URL"]

SEED_SQL = """
INSERT INTO amat_hd (unique_system_identifier, call_sign, license_status, grant_date, expired_date)
VALUES (232195, 'N0OTZ', 'A', '2026-08-29', '2036-11-21');

INSERT INTO amat_en (unique_system_identifier, call_sign, entity_name, frn, state, city, street_address)
VALUES (232195, 'N0OTZ', 'SLOAN, RIAL II', '0001112223', 'GA', 'RINGGOLD', '100 Test Rd');

INSERT INTO amat_am (unique_system_identifier, callsign, operator_class, group_code)
VALUES (232195, 'N0OTZ', 'G', 'A');

INSERT INTO amat_hs (unique_system_identifier, callsign, log_date, code)
VALUES (232195, 'N0OTZ', '2026-08-29', 'GR');

-- A second amateur record sharing the same FRN, to prove identity grouping.
INSERT INTO amat_hd (unique_system_identifier, call_sign, license_status, grant_date, expired_date)
VALUES (232196, 'KJ4IKD', 'A', '2026-08-29', '2036-11-21');
INSERT INTO amat_en (unique_system_identifier, call_sign, entity_name, frn, state, city, street_address)
VALUES (232196, 'KJ4IKD', 'SLOAN, RIAL II', '0001112223', 'GA', 'RINGGOLD', '100 Test Rd');

INSERT INTO tower_ra (registration_number, unique_system_identifier, content_indicator, file_number,
                       structure_city, structure_state_code, structure_type, status_code)
VALUES ('1234567', 1334621, 'REG', 'A1385250', 'Columbia', 'TN', 'LTOWER', 'C');

INSERT INTO tower_en (registration_number, unique_system_identifier, content_indicator, file_number,
                       entity_name, frn, state, city, street_address)
VALUES ('1234567', 1334621, 'REG', 'A1385250', 'ACME TOWERS LLC', '9999999999', 'TN', 'Columbia', '1520 Lasea Road');

INSERT INTO tower_co (registration_number, unique_system_identifier, content_indicator, file_number,
                       coordinate_type, latitude_direction, latitude_total_seconds,
                       longitude_direction, longitude_total_seconds)
VALUES ('1234567', 1334621, 'REG', 'A1385250', 'T', 'N', 151663.9, 'W', 316512.9);

-- A second tower at the same site (same rounded coordinates), different reg number.
INSERT INTO tower_ra (registration_number, unique_system_identifier, content_indicator, file_number,
                       structure_city, structure_state_code, structure_type, status_code)
VALUES ('7654321', 1334622, 'REG', 'A1385251', 'Columbia', 'TN', 'TOWER', 'C');
INSERT INTO tower_co (registration_number, unique_system_identifier, content_indicator, file_number,
                       coordinate_type, latitude_direction, latitude_total_seconds,
                       longitude_direction, longitude_total_seconds)
VALUES ('7654321', 1334622, 'REG', 'A1385251', 'T', 'N', 151663.9, 'W', 316512.9);

INSERT INTO change_events (subject_type, subject_key, uls_system_id, field_name, old_value, new_value, source_file, effective_date)
VALUES ('amateur_license', 'N0OTZ', '232195', 'license_status', 'A', 'E', 'l_am_mon.zip', '2026-09-02');

-- "New hams" celebration fixtures: a first-ever individual grant, a
-- first-ever club grant, and a SECOND callsign for an already-known FRN
-- (must be excluded from the celebration feed despite also being a
-- synthetic license_granted event).
INSERT INTO amat_hd (unique_system_identifier, call_sign, license_status, grant_date, expired_date)
VALUES (500001, 'KJ4TEST1', 'A', '2026-09-05', '2036-09-05');
INSERT INTO amat_en (unique_system_identifier, call_sign, entity_name, frn, state, city, street_address, applicant_type_code)
VALUES (500001, 'KJ4TEST1', 'NEWHAM, TEST A', '0005550001', 'GA', 'RINGGOLD', '1 New Ham Way', 'I');
-- Deliberately Amateur Extra, not Technician: a first-time licensee can
-- test straight into a higher class, and the celebration table must show
-- that rather than assuming everyone starts at Technician.
INSERT INTO amat_am (unique_system_identifier, callsign, operator_class, group_code)
VALUES (500001, 'KJ4TEST1', 'E', 'A');
INSERT INTO change_events (subject_type, subject_key, uls_system_id, field_name, old_value, new_value, source_file, effective_date, frn, is_new_operator)
VALUES ('amateur_license', 'KJ4TEST1', '500001', 'license_granted', NULL, 'KJ4TEST1', 'l_am_wed.zip', '2026-09-05', '0005550001', TRUE);

INSERT INTO amat_hd (unique_system_identifier, call_sign, license_status, grant_date, expired_date)
VALUES (500002, 'W4TESTCLUB', 'A', '2026-09-06', '2036-09-06');
INSERT INTO amat_en (unique_system_identifier, call_sign, entity_name, frn, state, city, street_address, applicant_type_code)
VALUES (500002, 'W4TESTCLUB', 'TEST AMATEUR RADIO CLUB', '0005550002', 'GA', 'RINGGOLD', '2 New Ham Way', 'B');
INSERT INTO change_events (subject_type, subject_key, uls_system_id, field_name, old_value, new_value, source_file, effective_date, frn, is_new_operator)
VALUES ('amateur_license', 'W4TESTCLUB', '500002', 'license_granted', NULL, 'W4TESTCLUB', 'l_am_thu.zip', '2026-09-06', '0005550002', TRUE);

INSERT INTO amat_hd (unique_system_identifier, call_sign, license_status, grant_date, expired_date)
VALUES (500003, 'KJ4TEST2', 'A', '2026-09-07', '2036-09-07');
INSERT INTO amat_en (unique_system_identifier, call_sign, entity_name, frn, state, city, street_address, applicant_type_code)
VALUES (500003, 'KJ4TEST2', 'NEWHAM, TEST A', '0005550001', 'GA', 'RINGGOLD', '1 New Ham Way', 'I');
INSERT INTO change_events (subject_type, subject_key, uls_system_id, field_name, old_value, new_value, source_file, effective_date, frn, is_new_operator)
VALUES ('amateur_license', 'KJ4TEST2', '500003', 'license_granted', NULL, 'KJ4TEST2', 'l_am_fri.zip', '2026-09-07', '0005550001', FALSE);

-- === Personal radio services: GMRS, Aircraft, Ship ===
-- The GMRS licence deliberately reuses N0OTZ's FRN (0001112223): holding
-- both an Amateur and a GMRS licence under one FRN is extremely common and
-- is exactly what cross-service identity grouping exists to surface.
INSERT INTO gmrs_hd (unique_system_identifier, call_sign, license_status, radio_service_code, grant_date, expired_date)
VALUES (600001, 'WRAA123', 'A', 'ZA', '2026-08-15', '2036-08-15');
INSERT INTO gmrs_en (unique_system_identifier, call_sign, entity_name, frn, state, city, street_address, applicant_type_code)
VALUES (600001, 'WRAA123', 'SLOAN, RIAL II', '0001112223', 'GA', 'RINGGOLD', '100 Test Rd', 'I');
INSERT INTO gmrs_hs (unique_system_identifier, callsign, log_date, code)
VALUES (600001, 'WRAA123', '2026-08-15', 'GR');

INSERT INTO aircr_hd (unique_system_identifier, call_sign, license_status, radio_service_code, grant_date, expired_date)
VALUES (700001, 'N123AB', 'A', 'AC', '2026-07-01', '2036-07-01');
INSERT INTO aircr_en (unique_system_identifier, call_sign, entity_name, frn, state, city, street_address, applicant_type_code)
VALUES (700001, 'N123AB', 'TEST AVIATION LLC', '0007770001', 'TN', 'NASHVILLE', '5 Hangar Row', 'B');
INSERT INTO aircr_ac (unique_system_identifier, call_sign, n_number, type_of_carrier, fleet_indicator)
VALUES (700001, 'N123AB', 'N123AB', 'P', 'N');
INSERT INTO aircr_hs (unique_system_identifier, callsign, log_date, code)
VALUES (700001, 'N123AB', '2026-07-01', 'GR');

INSERT INTO ship_hd (unique_system_identifier, call_sign, license_status, radio_service_code, grant_date, expired_date)
VALUES (800001, 'WDF1234', 'A', 'SA', '2026-06-01', '2036-06-01');
INSERT INTO ship_en (unique_system_identifier, call_sign, entity_name, frn, state, city, street_address, applicant_type_code)
VALUES (800001, 'WDF1234', 'TEST MARINE CO', '0008880001', 'FL', 'MIAMI', '7 Dock St', 'B');
INSERT INTO ship_sh (unique_system_identifier, callsign, ship_name, general_class, special_class,
                     station_number, type_of_authorization, gross_tonnage)
VALUES (800001, 'WDF1234', 'SEA TESTER', 'PL', 'CO', '338123456', 'R', '150');
INSERT INTO ship_sr (unique_system_identifier, call_sign)
VALUES (800001, 'WDF1234');
-- FCC splits one long description across sequence-numbered SV rows; seeded
-- out of order here to prove the detail endpoint returns them sorted.
INSERT INTO ship_sv (unique_system_identifier, call_sign, voyage_number, voyage_description)
VALUES (800001, 'WDF1234', '2', 'and the Gulf of Mexico.');
INSERT INTO ship_sv (unique_system_identifier, call_sign, voyage_number, voyage_description)
VALUES (800001, 'WDF1234', '1', 'Coastal voyages along the eastern seaboard');
INSERT INTO ship_se (unique_system_identifier, call_sign, ship_type)
VALUES (800001, 'WDF1234', 'C');
INSERT INTO ship_hs (unique_system_identifier, callsign, log_date, code)
VALUES (800001, 'WDF1234', '2026-06-01', 'GR');

-- A service-stamped change event per new service, to prove the detail
-- change_log and the notifier's service-scoped matching both work.
INSERT INTO change_events (subject_type, subject_key, uls_system_id, field_name, old_value, new_value, source_file, effective_date, frn, service)
VALUES ('gmrs_license', 'WRAA123', '600001', 'license_granted', NULL, 'WRAA123', 'l_gm_mon.zip', '2026-08-15', '0001112223', 'gmrs');
INSERT INTO change_events (subject_type, subject_key, uls_system_id, field_name, old_value, new_value, source_file, effective_date, frn, service)
VALUES ('aircraft_license', 'N123AB', '700001', 'license_granted', NULL, 'N123AB', 'l_ac_mon.zip', '2026-07-01', '0007770001', 'aircraft');
INSERT INTO change_events (subject_type, subject_key, uls_system_id, field_name, old_value, new_value, source_file, effective_date, frn, service)
VALUES ('ship_license', 'WDF1234', '800001', 'license_granted', NULL, 'WDF1234', 'l_sh_mon.zip', '2026-06-01', '0008880001', 'ship');
"""


def seed_database():
    with psycopg.connect(DSN, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(SEED_SQL)
            cur.execute("REFRESH MATERIALIZED VIEW identity_by_frn")
            cur.execute("REFRESH MATERIALIZED VIEW towers_by_site")
            cur.execute("REFRESH MATERIALIZED VIEW entities_by_address")


def main():
    seed_database()

    from app.main import app
    from app import mailer

    sent_links = []

    async def fake_send_magic_link_email(to_address, link_url):
        sent_links.append((to_address, link_url))

    mailer.send_magic_link_email = fake_send_magic_link_email
    # Router module imported the function by reference, so patch there too.
    from app.routers import auth as auth_router
    auth_router.send_magic_link_email = fake_send_magic_link_email

    with TestClient(app) as client:
        # --- search ---
        resp = client.get("/api/search", params={"q": "N0OTZ"})
        assert resp.status_code == 200, resp.text
        results = resp.json()["results"]
        assert any(r["key"] == "N0OTZ" and r["result_type"] == "amateur" for r in results), results
        print("search OK:", len(results), "results")

        # --- amateur browse ---
        resp = client.get("/api/amateur", params={"state": "GA"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] >= 2, body
        print("amateur browse OK:", body["total"], "total")

        # --- amateur detail + identity grouping ---
        resp = client.get("/api/amateur/N0OTZ")
        assert resp.status_code == 200, resp.text
        detail = resp.json()
        assert detail["header"]["call_sign"] == "N0OTZ"
        assert detail["entity"]["frn"] == "0001112223"
        assert len(detail["history"]) == 1
        assert len(detail["change_log"]) == 1
        assert detail["change_log"][0]["field_name"] == "license_status"
        related_keys = {r["subject_key"] for r in detail["related_identities"]}
        assert "KJ4IKD" in related_keys, detail["related_identities"]
        print("amateur detail + identity grouping OK")

        resp = client.get("/api/amateur/NOSUCHCALL")
        assert resp.status_code == 404
        print("amateur detail 404 OK")

        # --- tower browse + detail + site grouping ---
        resp = client.get("/api/towers", params={"state": "TN"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["total"] >= 2
        print("tower browse OK")

        resp = client.get("/api/towers/1234567")
        assert resp.status_code == 200, resp.text
        tdetail = resp.json()
        assert tdetail["registration"]["registration_number"] == "1234567"
        assert len(tdetail["entities"]) == 1
        assert len(tdetail["coordinates"]) == 1
        site_keys = {r["registration_number"] for r in tdetail["related_by_site"]}
        assert "7654321" in site_keys, tdetail["related_by_site"]
        print("tower detail + site grouping OK")

        # --- identity by FRN ---
        resp = client.get("/api/identity/frn/0001112223")
        assert resp.status_code == 200, resp.text
        members = resp.json()["members"]
        assert {"N0OTZ", "KJ4IKD"} <= {m["subject_key"] for m in members}
        # The shared-FRN endpoint is source-agnostic (it reads the
        # identity_by_frn view), so it must surface the GMRS licence held
        # under this same FRN without any endpoint change.
        by_source = {m["source"]: m["subject_key"] for m in members}
        assert by_source.get("gmrs") == "WRAA123", members
        print("identity by FRN OK")

        # --- new hams celebration ---
        resp = client.get("/api/new-hams")
        assert resp.status_code == 200, resp.text
        nh = resp.json()
        assert nh["total_individuals"] == 1, nh  # KJ4TEST1 only -- KJ4TEST2 must be excluded
        assert nh["total_clubs"] == 1, nh
        assert nh["total"] == 2, nh
        call_signs = {item["call_sign"] for item in nh["items"]}
        assert call_signs == {"KJ4TEST1", "W4TESTCLUB"}, call_signs
        by_call = {item["call_sign"]: item for item in nh["items"]}
        assert by_call["KJ4TEST1"]["applicant_type"] == "individual"
        assert by_call["KJ4TEST1"]["grant_date"] == "2026-09-05"
        # A first-time licensee who tested straight into Amateur Extra --
        # ~10% of real new hams start above Technician, so the class must be
        # carried through rather than assumed.
        assert by_call["KJ4TEST1"]["operator_class"] == "E", by_call["KJ4TEST1"]
        assert by_call["W4TESTCLUB"]["applicant_type"] == "club"
        # Clubs have no operator class at all (confirmed against production
        # data); the field must be present-but-null, not missing, so the UI
        # can render its em-dash fallback.
        assert by_call["W4TESTCLUB"]["operator_class"] is None, by_call["W4TESTCLUB"]
        print("new hams celebration (unfiltered) OK")

        resp = client.get("/api/new-hams", params={"type": "individual"})
        assert resp.status_code == 200, resp.text
        nh_ind = resp.json()
        assert nh_ind["total"] == 1, nh_ind
        assert {item["call_sign"] for item in nh_ind["items"]} == {"KJ4TEST1"}
        print("new hams celebration (type=individual) OK")

        resp = client.get("/api/new-hams", params={"type": "club"})
        assert resp.status_code == 200, resp.text
        nh_club = resp.json()
        assert nh_club["total"] == 1, nh_club
        assert {item["call_sign"] for item in nh_club["items"]} == {"W4TESTCLUB"}
        print("new hams celebration (type=club) OK")

        resp = client.get("/api/new-hams", params={"type": "not-a-real-type"})
        assert resp.status_code == 400, resp.text
        print("new hams celebration type validation OK")

        resp = client.get("/api/new-hams", params={"page": 1, "page_size": 1})
        assert resp.status_code == 200, resp.text
        assert len(resp.json()["items"]) == 1
        assert resp.json()["total"] == 2
        print("new hams celebration pagination OK")

        # --- personal radio services: GMRS / Aircraft / Ship ---
        # Browse, sort validation, service-specific filters, detail sections,
        # and the New Hams exclusion, exercised uniformly across all three.
        for service, callsign, entity in (
            ("gmrs", "WRAA123", "SLOAN, RIAL II"),
            ("aircraft", "N123AB", "TEST AVIATION LLC"),
            ("ship", "WDF1234", "TEST MARINE CO"),
        ):
            resp = client.get(f"/api/{service}")
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["total"] == 1, (service, body)
            assert body["items"][0]["call_sign"] == callsign, (service, body)
            assert body["items"][0]["entity_name"] == entity, (service, body)

            # Sorting is allow-listed; an arbitrary column must be rejected
            # rather than interpolated into the ORDER BY.
            resp = client.get(f"/api/{service}", params={"sort": "entity_name", "order": "desc"})
            assert resp.status_code == 200, resp.text
            resp = client.get(f"/api/{service}", params={"sort": "1; DROP TABLE gmrs_hd"})
            assert resp.status_code == 400, resp.text

            # Filters shared by every service.
            resp = client.get(f"/api/{service}", params={"callsign": callsign[:4]})
            assert resp.json()["total"] == 1, service
            resp = client.get(f"/api/{service}", params={"state": "ZZ"})
            assert resp.json()["total"] == 0, service

            resp = client.get(f"/api/{service}/{callsign}")
            assert resp.status_code == 200, resp.text
            detail = resp.json()
            assert detail["service"] == service
            assert detail["header"]["call_sign"] == callsign
            assert detail["entity"]["entity_name"] == entity
            assert len(detail["history"]) == 1, detail["history"]
            # History codes are decoded for display, same as Amateur.
            assert detail["history"][0]["code_description"], detail["history"][0]
            assert len(detail["change_log"]) == 1, detail["change_log"]

            resp = client.get(f"/api/{service}/NOSUCHCALL")
            assert resp.status_code == 404, resp.text
            print(f"{service} browse + detail OK")

        # Service-specific filters and detail sections.
        assert client.get("/api/aircraft", params={"n_number": "123AB"}).json()["total"] == 1
        assert client.get("/api/aircraft", params={"n_number": "999ZZ"}).json()["total"] == 0
        air = client.get("/api/aircraft/N123AB").json()
        assert air["aircraft_specific"]["type_of_carrier"] == "P", air["aircraft_specific"]
        print("aircraft n_number filter + AC section OK")

        assert client.get("/api/ship", params={"ship_name": "TESTER"}).json()["total"] == 1
        assert client.get("/api/ship", params={"mmsi": "338123"}).json()["total"] == 1
        assert client.get("/api/ship", params={"mmsi": "000000"}).json()["total"] == 0
        ship = client.get("/api/ship/WDF1234").json()
        assert ship["ship_specific"]["ship_name"] == "SEA TESTER", ship["ship_specific"]
        assert ship["radio_equipment"] is not None
        assert ship["exemption_request"]["ship_type"] == "C"
        # SV rows must come back in sequence order so the split description
        # reads correctly, even though they were seeded out of order.
        voyages = ship["voyages"]
        assert [v["voyage_number"] for v in voyages] == ["1", "2"], voyages
        assert voyages[0]["voyage_description"].startswith("Coastal voyages"), voyages
        print("ship filters + SH/SR/SV/SE sections OK")

        # A filter that doesn't apply to a service is ignored, not an error.
        assert client.get("/api/gmrs", params={"ship_name": "SEA TESTER"}).json()["total"] == 1

        # Cross-service identity grouping: N0OTZ's FRN also holds a GMRS
        # licence, so each must surface the other. This is the headline
        # reason for adding these services together rather than as silos.
        gmrs_detail = client.get("/api/gmrs/WRAA123").json()
        related = {r["subject_key"] for r in gmrs_detail["related_identities"]}
        assert {"N0OTZ", "KJ4IKD"} <= related, related
        amateur_detail = client.get("/api/amateur/N0OTZ").json()
        amateur_related = {r["subject_key"] for r in amateur_detail["related_identities"]}
        assert "WRAA123" in amateur_related, amateur_related
        print("cross-service FRN identity grouping OK")

        # Search must find the new services by callsign, entity name, tail
        # number and vessel name.
        for query, expected_type, expected_key in (
            ("WRAA123", "gmrs", "WRAA123"),
            ("N123AB", "aircraft", "N123AB"),
            ("WDF1234", "ship", "WDF1234"),
            ("TEST AVIATION LLC", "aircraft_entity", "N123AB"),
            ("SEA TESTER", "ship_name", "WDF1234"),
        ):
            results = client.get("/api/search", params={"q": query}).json()["results"]
            assert any(
                r["result_type"] == expected_type and r["key"] == expected_key
                for r in results
            ), (query, expected_type, results)
        print("search across new services OK")

        # The New Hams celebration is Amateur-only: none of the new services
        # may ever appear in it, no matter how many licences they grant.
        nh_after = client.get("/api/new-hams").json()
        assert nh_after["total"] == 2, nh_after
        assert {i["call_sign"] for i in nh_after["items"]} == {"KJ4TEST1", "W4TESTCLUB"}
        print("new hams remains amateur-only OK")

        # --- auth: request link -> verify -> me ---
        resp = client.post("/api/auth/request-link", json={"email": "n0test@example.com"})
        assert resp.status_code == 202, resp.text
        assert len(sent_links) == 1, sent_links
        to_address, link_url = sent_links[0]
        assert to_address == "n0test@example.com"
        token = link_url.split("token=")[1]

        resp = client.get("/api/auth/verify", params={"token": token})
        assert resp.status_code == 200, resp.text
        assert "fcculs_session" in resp.cookies

        resp = client.get("/api/auth/me")
        assert resp.status_code == 200, resp.text
        assert resp.json()["email"] == "n0test@example.com"
        print("auth request-link/verify/me OK")

        # Re-using a consumed token must fail.
        resp = client.get("/api/auth/verify", params={"token": token})
        assert resp.status_code == 400
        print("auth token single-use enforcement OK")

        # --- channel + watch CRUD ---
        resp = client.post(
            "/api/channels",
            json={"channel_type": "webhook", "label": "test", "config": {"url": "https://example.com/hook"}},
        )
        assert resp.status_code == 201, resp.text
        channel_id = resp.json()["id"]
        print("channel create OK:", channel_id)

        resp = client.post(
            "/api/watches",
            json={"subject_type": "callsign", "subject_value": "n0otz", "channel_id": channel_id},
        )
        assert resp.status_code == 201, resp.text
        watch = resp.json()
        assert watch["subject_value"] == "N0OTZ"
        # A watch with no service scope means "any service" -- the default,
        # and what every watch created before services existed still does.
        assert watch["service"] is None, watch
        print("watch create OK:", watch["id"])

        # --- optional per-watch service scope ---
        resp = client.post(
            "/api/watches",
            json={
                "subject_type": "callsign", "subject_value": "WRAA123",
                "channel_id": channel_id, "service": "gmrs",
            },
        )
        assert resp.status_code == 201, resp.text
        scoped_watch = resp.json()
        assert scoped_watch["service"] == "gmrs", scoped_watch
        print("service-scoped watch create OK:", scoped_watch["id"])

        resp = client.post(
            "/api/watches",
            json={
                "subject_type": "callsign", "subject_value": "WRAA124",
                "channel_id": channel_id, "service": "not-a-service",
            },
        )
        assert resp.status_code == 400, resp.text
        print("watch service validation OK")

        assert any(
            w["id"] == scoped_watch["id"] and w["service"] == "gmrs"
            for w in client.get("/api/watches").json()["watches"]
        )
        resp = client.delete(f"/api/watches/{scoped_watch['id']}")
        assert resp.status_code == 204

        # --- watch-by-FRN: a brand-new ham watching their FRN before they
        # have a callsign/ULS ID yet must be an allowed subject type ---
        resp = client.post(
            "/api/watches",
            json={"subject_type": "frn", "subject_value": "0009999999", "channel_id": channel_id},
        )
        assert resp.status_code == 201, resp.text
        frn_watch = resp.json()
        assert frn_watch["subject_type"] == "frn"
        assert frn_watch["subject_value"] == "0009999999"
        print("watch-by-frn create OK:", frn_watch["id"])
        resp = client.delete(f"/api/watches/{frn_watch['id']}")
        assert resp.status_code == 204

        # --- browse column sorting: amateur + tower browse both accept
        # sort/order and reject unknown columns ---
        resp = client.get("/api/amateur", params={"state": "GA", "sort": "entity_name", "order": "desc"})
        assert resp.status_code == 200, resp.text
        resp = client.get("/api/amateur", params={"sort": "not_a_real_column"})
        assert resp.status_code == 400, resp.text
        resp = client.get("/api/towers", params={"state": "TN", "sort": "overall_height_above_ground", "order": "asc"})
        assert resp.status_code == 200, resp.text
        resp = client.get("/api/towers", params={"sort": "not_a_real_column"})
        assert resp.status_code == 400, resp.text
        print("browse column sorting OK")

        # --- channel test-send: ownership-checked, and (with no notifier
        # worker running in this isolated pod) legitimately times out
        # waiting for a result rather than erroring ---
        resp = client.post(f"/api/channels/{channel_id}/test")
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "timeout", resp.json()
        print("channel test-send enqueue OK (no worker in pod -> timeout as expected)")

        resp = client.post("/api/channels/999999/test")
        assert resp.status_code == 404, resp.text
        print("channel test-send ownership check OK")

        # Duplicate watch should conflict.
        resp = client.post(
            "/api/watches",
            json={"subject_type": "callsign", "subject_value": "N0OTZ", "channel_id": channel_id},
        )
        assert resp.status_code == 409, resp.text
        print("watch duplicate conflict OK")

        resp = client.get("/api/watches")
        assert resp.status_code == 200
        assert len(resp.json()["watches"]) == 1

        # --- webhook SSRF guard: internal/loopback URLs must be rejected ---
        for bad_url in ("http://127.0.0.1:5432/", "http://localhost/", "http://postgres:5432/", "ftp://example.com/"):
            resp = client.post(
                "/api/channels",
                json={"channel_type": "webhook", "label": "bad", "config": {"url": bad_url}},
            )
            assert resp.status_code == 400, f"expected 400 for {bad_url}, got {resp.status_code}: {resp.text}"
        print("webhook SSRF guard rejects internal/invalid URLs OK")

        # --- per-user channel/watch caps ---
        from app.routers.channels import MAX_CHANNELS_PER_USER

        extra_channel_ids = []
        for i in range(MAX_CHANNELS_PER_USER - 1):  # one webhook channel already exists
            resp = client.post(
                "/api/channels",
                json={"channel_type": "webhook", "label": f"cap-{i}", "config": {"url": "https://example.com/hook"}},
            )
            assert resp.status_code == 201, resp.text
            extra_channel_ids.append(resp.json()["id"])
        resp = client.post(
            "/api/channels",
            json={"channel_type": "webhook", "label": "over-cap", "config": {"url": "https://example.com/hook"}},
        )
        assert resp.status_code == 429, resp.text
        print("per-user channel cap enforced OK")
        for cid in extra_channel_ids:
            resp = client.delete(f"/api/channels/{cid}")
            assert resp.status_code == 204, resp.text

        resp = client.delete(f"/api/watches/{watch['id']}")
        assert resp.status_code == 204

        resp = client.delete(f"/api/channels/{channel_id}")
        assert resp.status_code == 204

        # Unauthenticated access must be rejected.
        client.cookies.clear()
        resp = client.get("/api/watches")
        assert resp.status_code == 401
        print("auth-required enforcement OK")

        # --- hidden /admin panel: login, list, edit, delete ---
        import app.admin_auth as admin_auth_module

        known_password = "itest-admin-password"
        admin_auth_module._admin_password_hash = None
        admin_auth_module.init_admin_password()  # rotate once so tests don't depend on a stale hash
        # Force a known password rather than parsing logs here (log-derived
        # discovery is covered by tests/test_admin_auth.py); this block only
        # needs a valid session to exercise the admin CRUD endpoints.
        from app.security import hash_token

        admin_auth_module._admin_password_hash = hash_token(known_password)

        resp = client.post("/api/admin/login", json={"password": "wrong"})
        assert resp.status_code == 401, resp.text

        resp = client.post("/api/admin/login", json={"password": known_password})
        assert resp.status_code == 200, resp.text
        assert "fcculs_admin_session" in resp.cookies
        print("admin login OK")

        resp = client.get("/api/admin/users")
        assert resp.status_code == 200, resp.text
        users = resp.json()["items"]
        assert any(u["email"] == "n0test@example.com" for u in users)
        target_user = next(u for u in users if u["email"] == "n0test@example.com")
        print("admin users list OK:", len(users))

        resp = client.patch(f"/api/admin/users/{target_user['id']}", json={"email": "n0test-edited@example.com"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["email"] == "n0test-edited@example.com"
        print("admin user edit OK")

        resp = client.delete(f"/api/admin/users/{target_user['id']}")
        assert resp.status_code == 204, resp.text
        print("admin user delete OK")

        resp = client.post("/api/admin/logout")
        assert resp.status_code == 200, resp.text
        resp = client.get("/api/admin/users")
        assert resp.status_code == 401
        print("admin auth-required enforcement OK")

    print("ALL API INTEGRATION CHECKS PASSED")


if __name__ == "__main__":
    main()
