"""Test episode discovery: create, list, search, filter + publish/playback wiring."""

import asyncio
import io
import pathlib
import re
import shutil

import numpy as np
import soundfile as sf
from fastapi.testclient import TestClient

from audio_streaming.app import create_app
from audio_streaming.config import Settings

SR = 48000
SECONDS = 3.2


def _make_wav() -> bytes:
    t = np.arange(int(SR * SECONDS)) / SR
    tone = 0.2 * np.sin(2 * np.pi * 440 * t).astype(np.float32)
    buf = io.BytesIO()
    sf.write(buf, tone, SR, format="WAV", subtype="PCM_24")
    return buf.getvalue()


def test_episodes_create_list_search():
    data_dir = pathlib.Path("runtime-data/test-episodes")
    if data_dir.exists():
        shutil.rmtree(data_dir)
    db_path = data_dir / "streaming.db"

    settings = Settings(
        environment="test",
        data_dir=data_dir,
        database_path=db_path,
        auth_secret=b"a" * 40, capability_secret=b"c" * 40,
        watermark_secret=b"w" * 40, segment_key_secret=b"s" * 40,
    )

    def signup(client: TestClient, email: str) -> tuple[str, str]:
        r = client.post("/v1/auth/signup", json={
            "email": email, "display_name": "Creator", "password": "sup3rsecret", "is_creator": True,
        })
        assert r.status_code == 200, r.text
        token = r.json()["verify_token"]
        client.get("/v1/auth/verify-email", params={"token": token})
        r = client.post("/v1/auth/login", json={"email": email, "password": "sup3rsecret"})
        return r.json()["access_token"], r.json()["user_id"]

    async def make_ready_job(client: TestClient, user_id: str, asset_id: str, duration: float = SECONDS) -> None:
        jobs = client.app.state.jobs_repository
        await jobs.create_job(f"job_{asset_id}", user_id, None, "Untitled", f"{asset_id}.raw", asset_id, 0)
        await jobs.update_status(
            f"job_{asset_id}", "ready",
            mastered_key_wav=f"assets/{asset_id}/mastered.wav",
            mastered_key_mp3=f"assets/{asset_id}/mastered.mp3",
            report={"duration_seconds": duration},
        )
        client.app.state.media_store.put(f"assets/{asset_id}/mastered.wav", _make_wav())

    async def run():
        app = create_app(settings)
        with TestClient(app) as client:
            access, creator_id = signup(client, "creator@test.com")
            headers = {"Authorization": f"Bearer {access}"}

            # list empty
            r = client.get("/v1/episodes")
            assert r.status_code == 200
            assert r.json()["episodes"] == []

            # publishing without a ready upload -> 404
            r = client.post("/v1/episodes", headers=headers, json={
                "asset_id": "asset0", "title": "Not Ready", "category": "Tech",
            })
            assert r.status_code == 404, r.text

            # publishing an upload that is still processing -> 409
            jobs = client.app.state.jobs_repository
            await jobs.create_job("job_stillproc", creator_id, None, "Untitled", "x.raw", "assetx", 0)
            r = client.post("/v1/episodes", headers=headers, json={
                "asset_id": "assetx", "title": "Queued", "category": "Tech",
            })
            assert r.status_code == 409, r.text

            # create ready uploads + publish episodes
            await make_ready_job(client, creator_id, "asset1")
            await make_ready_job(client, creator_id, "asset2")
            await make_ready_job(client, creator_id, "asset3")

            r = client.post("/v1/episodes", headers=headers, json={
                "asset_id": "asset1", "title": "AI Signals in Tech", "category": "Tech",
            })
            assert r.status_code == 201, r.text
            ep1 = r.json()
            assert ep1["asset_id"] == "asset1"
            assert ep1["duration_seconds"] == SECONDS

            r = client.post("/v1/episodes", headers=headers, json={
                "asset_id": "asset2", "title": "SaaS Valuations in Q3", "category": "Business",
            })
            assert r.status_code == 201, r.text

            r = client.post("/v1/episodes", headers=headers, json={
                "asset_id": "asset3", "title": "Building in Public", "category": "Founder Stories",
            })
            assert r.status_code == 201, r.text

            # published episodes are immediately playable (ingest baked the variants)
            r = client.post("/v1/ab/streams/asset1/sessions", headers=headers)
            assert r.status_code == 200, r.text
            sid = r.json()["session_id"]
            r = client.get(f"/v1/ab/streams/{sid}/playlist.m3u8")
            assert r.status_code == 200, r.text
            assert r.text.startswith("#EXTM3U")
            m = re.search(r"segments/(\d{4}\.ts)\?tok=([^\"\s]+)", r.text)
            assert m, r.text
            r = client.get(f"/v1/ab/cdn/streams/{sid}/segments/{m.group(1)}?tok={m.group(2)}")
            assert r.status_code == 200, r.text
            assert len(r.content) > 0

            # someone else's upload cannot be published -> 403
            other, other_id = signup(client, "other@test.com")
            assert other
            await make_ready_job(client, other_id, "asset4")
            r = client.post("/v1/episodes", headers=headers, json={
                "asset_id": "asset4", "title": "Their Hidden Gem", "category": "Tech",
            })
            assert r.status_code == 403, r.text

            # list all (only this creator's public episodes)
            r = client.get("/v1/episodes")
            assert r.status_code == 200
            assert len(r.json()["episodes"]) == 3

            # search
            r = client.get("/v1/episodes", params={"search": "AI"})
            assert len(r.json()["episodes"]) == 1

            # filter by category
            r = client.get("/v1/episodes", params={"category": "Business"})
            assert len(r.json()["episodes"]) == 1
            assert r.json()["episodes"][0]["title"] == "SaaS Valuations in Q3"

            # categories
            r = client.get("/v1/episodes/categories")
            assert r.status_code == 200
            cats = r.json()["categories"]
            assert "Business" in cats and "Tech" in cats

            # get one
            r = client.get(f"/v1/episodes/{ep1['episode_id']}")
            assert r.status_code == 200
            assert r.json()["title"] == "AI Signals in Tech"

            # not found
            r = client.get("/v1/episodes/nonexistent")
            assert r.status_code == 404

    asyncio.run(run())

    if data_dir.exists():
        shutil.rmtree(data_dir)