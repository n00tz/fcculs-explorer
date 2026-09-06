"""End-to-end integration test for the notifier: seeds a watch + webhook
channel + change_event against real Postgres, runs the dispatch matcher
(real Redis/RQ queue), then runs an RQ worker in burst mode to actually
process the job and deliver it to a local HTTP server -- proving the full
match -> enqueue -> send -> mark-sent pipeline, plus idempotency of
re-running the matcher.
"""
import http.server
import json
import os
import sys
import threading
import time

sys.path.insert(0, "/app")

os.environ.setdefault("FCCULS_DATABASE_URL", "postgresql://postgres:test@localhost:5432/fcculs_test")
os.environ.setdefault("FCCULS_REDIS_URL", "redis://localhost:6379/0")

import psycopg
from redis import Redis
from rq import Queue, Worker

from app import dispatch
from app.db import get_connection
from app.jobs import send_test_message

DSN = os.environ["FCCULS_DATABASE_URL"]

received_requests = []


class CaptureHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        received_requests.append(json.loads(body) if body else None)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, fmt, *args):
        pass  # keep test output quiet


def start_capture_server(port: int):
    server = http.server.HTTPServer(("0.0.0.0", port), CaptureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def seed(webhook_url: str):
    with psycopg.connect(DSN, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO users (email) VALUES ('watcher@example.com') RETURNING id")
            user_id = cur.fetchone()[0]

            cur.execute(
                """
                INSERT INTO notification_channels (user_id, channel_type, label, config)
                VALUES (%s, 'webhook', 'test webhook', %s) RETURNING id
                """,
                (user_id, json.dumps({"url": webhook_url})),
            )
            channel_id = cur.fetchone()[0]

            cur.execute(
                """
                INSERT INTO watches (user_id, subject_type, subject_value, channel_id)
                VALUES (%s, 'callsign', 'K0WNL', %s)
                """,
                (user_id, channel_id),
            )

            cur.execute(
                """
                INSERT INTO change_events (subject_type, subject_key, uls_system_id, field_name, old_value, new_value, source_file, effective_date)
                VALUES ('amateur_license', 'K0WNL', '232195', 'license_status', 'A', 'E', 'l_am_mon.zip', '2026-09-02')
                RETURNING id
                """
            )
            change_event_id = cur.fetchone()[0]
    return channel_id, change_event_id


def main():
    start_capture_server(18080)
    time.sleep(0.2)

    channel_id, change_event_id = seed("http://localhost:18080/hook")

    # --- dispatch: match + enqueue ---
    enqueued = dispatch.run_once()
    assert enqueued == 1, f"expected 1 new delivery enqueued, got {enqueued}"
    print("dispatch.run_once() enqueued OK:", enqueued)

    # Re-running immediately must not enqueue duplicates (idempotency).
    enqueued_again = dispatch.run_once()
    assert enqueued_again == 0, f"expected 0 on re-run, got {enqueued_again}"
    print("dispatch idempotency OK")

    # --- process the queued job with a burst worker ---
    # This test's mock webhook receiver deliberately lives on loopback
    # (http://localhost:18080), which the SSRF guard (correctly) blocks in
    # production. Set the guard's test-only escape hatch (see
    # app/url_safety.py) for the duration of the burst worker so this
    # test can still prove the full match -> enqueue -> send -> mark-sent
    # pipeline against a real local capture server, without weakening the
    # guard itself or touching any real socket/DNS behavior.
    os.environ["FCCULS_ALLOW_PRIVATE_WEBHOOK_TARGETS_FOR_TESTING"] = "1"
    redis_conn = Redis.from_url(os.environ["FCCULS_REDIS_URL"])
    queue = Queue("fcculs-notifications", connection=redis_conn)
    worker = Worker([queue], connection=redis_conn)
    worker.work(burst=True)

    assert len(received_requests) == 1, received_requests
    payload = received_requests[0]
    assert "K0WNL" in payload["subject"]
    assert "license_status" in payload["body"]
    print("webhook received payload OK:", payload["subject"])

    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT status, attempts, sent_at FROM notification_deliveries WHERE change_event_id = %s", (change_event_id,))
        delivery = cur.fetchone()
    assert delivery["status"] == "sent", delivery
    assert delivery["attempts"] == 1
    assert delivery["sent_at"] is not None
    print("notification_deliveries row marked sent OK:", dict(delivery))

    # --- send_test_message() marks is_verified even though this call path
    # never goes through the api's poll-timeout logic at all -- this is
    # the regression test for the bug found during live production testing
    # where a real ntfy.sh send took ~11s (longer than the api's former 8s
    # poll window), so the api reported "timeout" and never told the DB
    # the send actually succeeded. send_test_message() itself must be the
    # source of truth for is_verified, not the api's poll result. ---
    result = send_test_message(channel_id)
    assert result == {"channel_type": "webhook", "sent": True}, result
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT is_verified FROM notification_channels WHERE id = %s", (channel_id,))
        channel = cur.fetchone()
    assert channel["is_verified"] is True, channel
    print("send_test_message() marks is_verified OK")

    print("ALL NOTIFIER INTEGRATION CHECKS PASSED")


if __name__ == "__main__":
    main()
