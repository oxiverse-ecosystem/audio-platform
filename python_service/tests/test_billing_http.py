"""HTTP-level P2 checks: the metered manifest endpoint returns 402 on quota exhaustion and
issues a windowed, metered playlist otherwise. Uses TestClient and a temporary SQLite db; the
heavy ffmpeg ingest is bypassed by directly inserting a variant asset + entitlement.
"""

import time

import pytest
from fastapi.testclient import TestClient

from audio_streaming.app import create_app
from audio_streaming.repository import Repository


def _client_and_repo(tmp_path):
    db_path = tmp_path / "http.db"
    app = create_app()
    # Point the app at an isolated DB by monkeypatching the lifespan init is overkill; instead
    # we use the repos directly via TestClient against the default env but a temp data dir.
    app.state._override_db = str(db_path)
    return app


def test_manifest_returns_402_when_free_quota_spent(tmp_path):
    # Build a real app and swap its repository to an isolated, seeded SQLite file.
    from audio_streaming import app as app_mod
    app = app_mod.create_app()

    db_path = tmp_path / "billing_http.db"
    repo = Repository(db_path)
    import asyncio
    asyncio.run(repo.initialize())
    asyncio.run(repo.seed_billing(
        {"payout_pool_bps": "5500", "creator_flowthrough_bps": "8800", "gst_bps": "1800",
         "psp_fee_bps": "236", "creator_price_min_paise": "14900", "creator_price_max_paise": "49900",
         "currency": "INR"},
        ({"plan_code": "free", "name": "Free", "kind": "platform", "price_paise": 0,
          "included_seconds": 12, "active": True},),  # tiny 12s free allowance for the test
    ))
    asyncio.run(repo.create_creator("cr1", "Nadia", "upi:nadia@x"))
    asyncio.run(repo.set_asset_creator("ep1", "cr1"))
    asyncio.run(repo.save_variant_asset(__import__("audio_streaming.models", fromlist=["VariantAssetRecord"]).VariantAssetRecord(
        asset_id="ep1", title="Ep", source_sha256="x", sample_rate=48000, channels=2,
        segment_samples=48000 * 4, segment_count=5, duration_samples=48000 * 20, created_at=int(time.time()),
    )))
    # Inject the repo into the app state, then drive it through the (lifespan-initialized) client.
    from fastapi.testclient import TestClient
    with TestClient(app) as client:
        app.state.repository = repo
        app.state.variant_service.repository = repo

        from audio_streaming.security import issue_identity, issue_signed_token
        secret = app.state.settings.auth_secret
        cap_secret = app.state.settings.capability_secret
        user = issue_identity(secret, "u1", role="listener")
        headers = {"Authorization": f"Bearer {user}"}
        asyncio.run(repo.create_variant_session(__import__("audio_streaming.models", fromlist=["SessionRecord"]).SessionRecord(
            session_id="sess1", asset_id="ep1", user_id="u1",
            watermark_id=1, created_at=int(time.time()), expires_at=int(time.time()) + 9999, status="active",
        )))
        cap = issue_signed_token(cap_secret, {"kind": "variant-playlist", "sid": "sess1", "asset": "ep1", "sub": "u1"}, 120)
        r1 = client.get(f"/v1/variant-streams/sess1/playlist.m3u8?cap={cap}", headers=headers)
        assert r1.status_code == 200, r1.text
        assert "X-Consumed-Seconds" in r1.headers
        # Retry the same window (position 0): idempotent, but the free allowance (1 segment) is
        # now spent, so the retry is correctly rejected with 402 rather than double-charging.
        cap2 = issue_signed_token(cap_secret, {"kind": "variant-playlist", "sid": "sess1", "asset": "ep1", "sub": "u1"}, 120)
        r2 = client.get(f"/v1/variant-streams/sess1/playlist.m3u8?cap={cap2}", headers=headers)
        assert r2.status_code == 402, r2.text
