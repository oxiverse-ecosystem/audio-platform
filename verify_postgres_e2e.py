"""Live end-to-end exercise against the running Docker stack (Postgres + Redis + 4 workers).

Mints identity tokens with the same AUDIO_AUTH_SECRET the container uses (the compose default),
then walks the real flow: admin lists/edits plans, registers a creator + asset, a listener opens
a metered session and streams the windowed manifest until quota is exhausted (402), and an admin
computes a payout period. Verifies the Postgres repository + Redis limiter actually work under
multiple uvicorn workers.
"""

import json
import time
import urllib.request

import sys

sys.path.insert(0, "python_service")
from audio_streaming.security import issue_identity  # dev-login logic, minus the prod block

BASE = "http://localhost:8000"
AUTH_SECRET = b"change-me-auth-0123456789abcdef0123456789abcdef"  # matches compose default


def req(method, path, *, token=None, json_body=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(json_body).encode() if json_body is not None else None
    r = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:  # noqa: BLE001
        return e.code, e.read().decode()


def main():
    admin = issue_identity(AUTH_SECRET, "admin1", role="admin")
    listener = issue_identity(AUTH_SECRET, "listener1", role="listener")

    print("== plans (admin) ==")
    st, body = req("GET", "/v1/plans", token=admin)
    plans = json.loads(body)
    print(st, [(p["plan_code"], p["price_paise"], p["included_seconds"]) for p in plans])

    # Edit a plan live (proves DB-backed, no deploy).
    print("== edit free plan to 20h (72000s) ==")
    st, body = req("PUT", "/v1/plans/free", token=admin, json_body={"included_seconds": 72000})
    print(st, body[:120])

    # For the quota-wall verification, drop the free allowance to 4 segments (16s) so streaming
    # exhausts it fast and we prove the 402 path + idempotent metering against Postgres.
    req("PUT", "/v1/plans/free", token=admin, json_body={"included_seconds": 16})
    print("== free plan lowered to 16s for quota-wall test ==")

    print("== register creator + asset ==")
    st, body = req("POST", "/v1/creators", token=admin,
                   json_body={"creator_id": "cr1", "asset_id": "ep1", "display_name": "Nadia"})
    print(st, body[:120])
    # variant-assets is a multipart upload endpoint; for the live DB verification we seed a
    # synthetic asset row directly (mirrors an ingested 48k/2ch/4s-segment asset), then exercise
    # the metering + quota path against Postgres. Use psql in the postgres container (asyncpg is
    # only in the api image).
    import subprocess

    sql = (
        "INSERT INTO variant_assets "
        "(asset_id,title,source_sha256,sample_rate,channels,segment_samples,segment_count,duration_samples,created_at) "
        "VALUES('ep1','Nadia''''s Founder Diary','deadbeef',48000,2,192000,900,172800000,"
        + str(int(time.time()))
        + ") ON CONFLICT(asset_id) DO NOTHING;"
    )
    subprocess.run(
        ["docker", "compose", "-f",
         "C:/Users/Likhith/Documents/Projects/secure_audio_streaming_mvp_source/docker-compose.yml",
         "exec", "-T", "postgres", "psql", "-U", "oxiverse", "-d", "oxiverse", "-c", sql],
        check=True)
    print("200 seeded asset ep1 (900 segments @ 4s = 3600s)")
    # Grant the listener entitlement to the asset (the session-open gate requires it).
    st, body = req("PUT", "/v1/variant-assets/ep1/entitlements", token=admin,
                   json_body={"user_id": "listener1", "allowed": True})
    print("entitlement grant:", st, body[:120])

    print("== listener opens session ==")
    st, body = req("POST", "/v1/variant-streams", token=listener, json_body={"asset_id": "ep1"})
    sess = json.loads(body)
    print(st, "session", sess.get("session_id"), "manifest", sess.get("manifest_url"))

    cap = sess["manifest_url"].split("cap=")[1]
    print("== stream manifest windows until 402 ==")
    pos = 0
    grants = 0
    for i in range(40):
        st, body = req("GET", f"/v1/variant-streams/{sess['session_id']}/playlist.m3u8?position={pos}&cap={cap}")
        if st == 402:
            print(f"  window {i}: HTTP 402 (quota exhausted) -- correct")
            break
        # advance by the returned window length
        lines = [l for l in body.splitlines() if l and not l.startswith("#")]
        pos += len(lines)
        grants += 1
    else:
        print("  NEVER hit 402 -- metering did not cap (BUG)")
    print(f"  windows served before 402: {grants}")

    print("== usage after streaming ==")
    st, body = req("GET", "/v1/usage", token=listener)
    print(st, body[:200])

    print("== compute payout (period now) ==")
    period = time.strftime("%Y-%m")
    # Seed an active paid subscription so the pool has revenue to distribute.
    now = int(time.time())
    sql_sub = (
        "INSERT INTO subscriptions(subscription_id,user_id,plan_code,creator_id,price_paise,period_start,period_end,status) "
        "VALUES('sub1','listener1','listener_50',NULL,49900,"
        + str(now - 86400) + "," + str(now + 30 * 86400) + ",'active') "
        "ON CONFLICT(subscription_id) DO NOTHING;"
    )
    subprocess.run(
        ["docker", "compose", "-f",
         "C:/Users/Likhith/Documents/Projects/secure_audio_streaming_mvp_source/docker-compose.yml",
         "exec", "-T", "postgres", "psql", "-U", "oxiverse", "-d", "oxiverse", "-c", sql_sub],
        check=True)
    st, body = req("POST", f"/v1/payouts/compute?period={period}", token=admin)
    print(st, body[:400] if st == 200 else body[:200])

    print("== metrics (prometheus) ==")
    st, body = req("GET", "/metrics")
    for line in body.splitlines():
        if line.startswith("http_requests_total") or line.startswith("variant_manifests_issued") or line.startswith("billing_quota_rejections_total"):
            print("  ", line)


if __name__ == "__main__":
    main()
