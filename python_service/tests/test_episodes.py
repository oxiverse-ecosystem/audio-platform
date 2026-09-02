"""Test episode discovery: create, list, search, filter."""

import asyncio
import pathlib

import httpx

from audio_streaming.app import create_app
from audio_streaming.config import Settings
from audio_streaming.security import issue_identity


def test_episodes_create_list_search():
    data_dir = pathlib.Path("runtime-data/test-episodes")
    db_path = data_dir / "streaming.db"
    if db_path.exists():
        db_path.unlink()

    settings = Settings(
        environment="test",
        data_dir=data_dir,
        database_path=db_path,
        auth_secret=b"a" * 40, capability_secret=b"c" * 40,
        watermark_secret=b"w" * 40, segment_key_secret=b"s" * 40,
    )

    async def run():
        app = create_app(settings)
        from fastapi.testclient import TestClient
        with TestClient(app) as client:
            # create a user + token
            r = client.post("/v1/auth/signup", json={
                "email": "creator@test.com", "display_name": "Creator", "password": "sup3rsecret", "is_creator": True,
            })
            assert r.status_code == 200, r.text
            token = r.json()["verify_token"]
            client.get("/v1/auth/verify-email", params={"token": token})
            r = client.post("/v1/auth/login", json={"email": "creator@test.com", "password": "sup3rsecret"})
            access = r.json()["access_token"]
            headers = {"Authorization": f"Bearer {access}"}

            # list empty
            r = client.get("/v1/episodes")
            assert r.status_code == 200
            assert r.json()["episodes"] == []

            # create episodes
            r = client.post("/v1/episodes", headers=headers, json={
                "asset_id": "asset1", "title": "AI Signals in Tech", "category": "Tech",
            })
            assert r.status_code == 201, r.text
            ep1 = r.json()

            r = client.post("/v1/episodes", headers=headers, json={
                "asset_id": "asset2", "title": "SaaS Valuations in Q3", "category": "Business",
            })
            assert r.status_code == 201, r.text

            r = client.post("/v1/episodes", headers=headers, json={
                "asset_id": "asset3", "title": "Building in Public", "category": "Founder Stories",
            })
            assert r.status_code == 201, r.text

            # list all
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

    import shutil
    if data_dir.exists():
        shutil.rmtree(data_dir)
