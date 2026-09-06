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
VALUES (232195, 'K0WNL', 'A', '2026-08-29', '2036-11-21');

INSERT INTO amat_en (unique_system_identifier, call_sign, entity_name, frn, state, city, street_address)
VALUES (232195, 'K0WNL', 'BEAHM, DONALD E', '0002204154', 'KS', 'GREAT BEND', '328 Sunset Rd');

INSERT INTO amat_am (unique_system_identifier, callsign, operator_class, group_code)
VALUES (232195, 'K0WNL', 'E', 'A');

INSERT INTO amat_hs (unique_system_identifier, callsign, log_date, code)
VALUES (232195, 'K0WNL', '2026-08-29', 'GR');

-- A second amateur record sharing the same FRN, to prove identity grouping.
INSERT INTO amat_hd (unique_system_identifier, call_sign, license_status, grant_date, expired_date)
VALUES (232196, 'K0WNL2', 'A', '2026-08-29', '2036-11-21');
INSERT INTO amat_en (unique_system_identifier, call_sign, entity_name, frn, state, city, street_address)
VALUES (232196, 'K0WNL2', 'BEAHM, DONALD E', '0002204154', 'KS', 'GREAT BEND', '328 Sunset Rd');

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
VALUES ('amateur_license', 'K0WNL', '232195', 'license_status', 'A', 'E', 'l_am_mon.zip', '2026-09-02');
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
        resp = client.get("/api/search", params={"q": "K0WNL"})
        assert resp.status_code == 200, resp.text
        results = resp.json()["results"]
        assert any(r["key"] == "K0WNL" and r["result_type"] == "amateur" for r in results), results
        print("search OK:", len(results), "results")

        # --- amateur browse ---
        resp = client.get("/api/amateur", params={"state": "KS"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] >= 2, body
        print("amateur browse OK:", body["total"], "total")

        # --- amateur detail + identity grouping ---
        resp = client.get("/api/amateur/K0WNL")
        assert resp.status_code == 200, resp.text
        detail = resp.json()
        assert detail["header"]["call_sign"] == "K0WNL"
        assert detail["entity"]["frn"] == "0002204154"
        assert len(detail["history"]) == 1
        assert len(detail["change_log"]) == 1
        assert detail["change_log"][0]["field_name"] == "license_status"
        related_keys = {r["subject_key"] for r in detail["related_identities"]}
        assert "K0WNL2" in related_keys, detail["related_identities"]
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
        resp = client.get("/api/identity/frn/0002204154")
        assert resp.status_code == 200, resp.text
        members = resp.json()["members"]
        assert {"K0WNL", "K0WNL2"} <= {m["subject_key"] for m in members}
        print("identity by FRN OK")

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
            json={"subject_type": "callsign", "subject_value": "k0wnl", "channel_id": channel_id},
        )
        assert resp.status_code == 201, resp.text
        watch = resp.json()
        assert watch["subject_value"] == "K0WNL"
        print("watch create OK:", watch["id"])

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
        resp = client.get("/api/amateur", params={"state": "KS", "sort": "entity_name", "order": "desc"})
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
            json={"subject_type": "callsign", "subject_value": "K0WNL", "channel_id": channel_id},
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
