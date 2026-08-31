"""Local SQLite dev auth test: signup -> dev-verify -> login -> whoami, plus rejection paths."""

import shutil

from fastapi.testclient import TestClient

from audio_streaming.app import create_app
from audio_streaming.config import Settings


def test_auth_signup_verify_login_me():
    import pathlib

    data_dir = pathlib.Path("runtime-data/test-auth")
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

    app = create_app(settings)
    with TestClient(app) as client:
        # signup
        r = client.post("/v1/auth/signup", json={
            "email": "Founder@Startup.com", "display_name": "Likhith", "password": "sup3rsecret", "is_creator": True,
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["email"] == "founder@startup.com"  # normalized lowercase
        assert body["email_verified"] is False
        token = body["verify_token"]
        assert token and len(token) >= 32

        # login before verify -> 403
        r = client.post("/v1/auth/login", json={"email": "founder@startup.com", "password": "sup3rsecret"})
        assert r.status_code == 403, r.text

        # verify
        r = client.get("/v1/auth/verify-email", params={"token": token})
        assert r.status_code == 200, r.text
        assert r.json()["verified"] is True

        # reuse token -> 410
        r = client.get("/v1/auth/verify-email", params={"token": token})
        assert r.status_code == 410, r.text

        # login after verify -> token
        r = client.post("/v1/auth/login", json={"email": "founder@startup.com", "password": "sup3rsecret"})
        assert r.status_code == 200, r.text
        auth = r.json()
        assert auth["access_token"] and auth["is_creator"] is True
        bearer = "Bearer " + auth["access_token"]

        # whoami
        r = client.get("/v1/auth/me", headers={"Authorization": bearer})
        assert r.status_code == 200, r.text
        assert r.json()["email_verified"] is True

        # bad password -> 401
        r = client.post("/v1/auth/login", json={"email": "founder@startup.com", "password": "wrong"})
        assert r.status_code == 401, r.text

        # duplicate email -> 409
        r = client.post("/v1/auth/signup", json={
            "email": "founder@startup.com", "display_name": "x", "password": "anotherpass",
        })
        assert r.status_code == 409, r.text

        # weak password -> 422
        r = client.post("/v1/auth/signup", json={
            "email": "weak@x.com", "display_name": "x", "password": "short",
        })
        assert r.status_code == 422, r.text

        # whoami without token -> 401
        r = client.get("/v1/auth/me")
        assert r.status_code == 401, r.text

    if data_dir.exists():
        shutil.rmtree(data_dir)
