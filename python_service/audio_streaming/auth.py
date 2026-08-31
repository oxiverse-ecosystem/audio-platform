"""Local SQLite dev auth: signup + dev email-verify + login + whoami.

Dev-only email verification (no SMTP): the verification token is returned in the
signup response and appended to runtime-data/dev-emails.log as a copy-pasteable
verify URL. Production should delegate to a real email provider + magic-link / OIDC.

Security notes:
  * passwords hashed with stdlib pbkdf2_hmac (no new dependency); bcrypt is the prod upgrade
  * verification tokens are random, single-use, expiring
  * login returns a stateless JWT bearer (reuses security.issue_identity)
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import time
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel

from .security import SecurityError, issue_identity, verify_identity


router = APIRouter(prefix="/v1/auth", tags=["auth"])

VERIFY_TTL_SECONDS = 24 * 3600
AUTH_TOKEN_TTL_SECONDS = 7 * 24 * 3600
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

RESEND_API_KEY = os.getenv("RESEND_API_KEY") or ""
RESEND_FROM = os.getenv("RESEND_FROM") or "onboarding@resend.dev"
APP_PUBLIC_BASE_URL = (os.getenv("APP_PUBLIC_BASE_URL") or "http://localhost:3000").rstrip("/")


def _send_verify_email(email: str, verify_url: str) -> bool:
    """Send the verification email via Resend. Returns True if sent, False if not configured (dev fallback)."""
    # Read env lazily so this works regardless of import order (config.load_dotenv may not have run yet).
    api_key = os.getenv("RESEND_API_KEY") or ""
    resend_from = os.getenv("RESEND_FROM") or "onboarding@resend.dev"
    if not api_key or api_key == "REPLACE_WITH_YOUR_RESEND_KEY":
        return False
    try:
        import resend

        resend.api_key = api_key
        resend.Emails.send({
            "from": resend_from,
            "to": [email],
            "subject": "Verify your Oxiverse Audio email",
            "html": (
                "<p>Welcome to Oxiverse Audio.</p>"
                f"<p>Confirm your email to start listening and publishing:</p>"
                f'<p><a href="{verify_url}" style="background:#4648d4;color:#fff;padding:10px 18px;'
                'border-radius:8px;text-decoration:none;display:inline-block;">Verify email</a></p>'
                f'<p>Or paste this link: {verify_url}</p>'
                "<p>This link expires in 24 hours.</p>"
            ),
        })
        return True
    except Exception:
        return False


# --- password hashing (stdlib) ---
def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    d = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, 200_000)
    return "pbkdf2_sha256$" + salt.hex() + "$" + d.hex()


def verify_password(pw: str, stored: str) -> bool:
    try:
        _alg, salt_hex, d_hex = stored.split("$")
    except ValueError:
        return False
    salt = bytes.fromhex(salt_hex)
    d = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, 200_000)
    return hmac.compare_digest(d.hex(), d_hex)


# --- request helpers ---
def _repo(request: Request):
    return request.app.state.repository


def _auth_secret(request: Request) -> bytes:
    return request.app.state.settings.auth_secret


def _write_dev_email(settings, email: str, url: str) -> None:
    try:
        log_path = settings.data_dir / "dev-emails.log"
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} VERIFY {email} -> {url}\n")
    except OSError:
        pass


async def require_auth(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    """Return the authenticated user_id; raise 401 otherwise."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="bearer token required")
    try:
        principal = verify_identity(_auth_secret(request), authorization.removeprefix("Bearer ").strip())
    except SecurityError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid bearer token") from exc
    return principal.subject


# --- request bodies ---
class SignupRequest(BaseModel):
    email: str
    display_name: str
    password: str
    is_creator: bool = False


class VerifyRequest(BaseModel):
    token: str


class LoginRequest(BaseModel):
    email: str
    password: str


# --- endpoints ---
@router.post("/signup")
async def signup(request: Request, body: SignupRequest):
    email = body.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid email")
    if not body.display_name.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="display_name required")
    if len(body.password) < 8:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="password must be >= 8 chars")

    repo = _repo(request)
    if await repo.get_user_by_email(email) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="email already registered")

    user_id = "u_" + secrets.token_hex(12)
    now = int(time.time())
    await repo.create_user(user_id, email, body.display_name.strip(), hash_password(body.password), body.is_creator, now)

    token = secrets.token_hex(32)
    await repo.create_verification(token, user_id, now, now + VERIFY_TTL_SECONDS)
    verify_url = f"{APP_PUBLIC_BASE_URL}/v1/auth/verify-email?token={token}"
    emailed = _send_verify_email(email, verify_url)
    if not emailed:
        _write_dev_email(request.app.state.settings, email, verify_url)

    return {
        "user_id": user_id,
        "email": email,
        "email_verified": False,
        "email_sent": emailed,
        "dev_note": None if emailed else "Resend not configured; verify via runtime-data/dev-emails.log or the returned URL",
        "verify_url": verify_url,
        "verify_token": token,
    }


@router.get("/verify-email")
async def verify_email_get(request: Request, token: str):
    return await _do_verify(request, token)


@router.post("/verify-email")
async def verify_email_post(request: Request, body: VerifyRequest):
    return await _do_verify(request, body.token)


async def _do_verify(request: Request, token: str) -> dict:
    repo = _repo(request)
    row = await repo.get_verification(token)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="invalid verification token")
    if row["used_at"] is not None:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="verification token already used")
    if row["expires_at"] < int(time.time()):
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="verification token expired")
    now = int(time.time())
    await repo.set_email_verified(row["user_id"], now)
    await repo.mark_verification_used(token, now)
    return {"verified": True, "user_id": row["user_id"]}


@router.post("/login")
async def login(request: Request, body: LoginRequest):
    email = body.email.strip().lower()
    repo = _repo(request)
    user = await repo.get_user_by_email(email)
    if user is None or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid email or password")

    if not user["email_verified"]:
        # dev convenience: issue a fresh token so the user can verify without re-signing-up
        now = int(time.time())
        token = secrets.token_hex(32)
        await repo.create_verification(token, user["user_id"], now, now + VERIFY_TTL_SECONDS)
        verify_url = f"{APP_PUBLIC_BASE_URL}/v1/auth/verify-email?token={token}"
        emailed = _send_verify_email(email, verify_url)
        if not emailed:
            _write_dev_email(request.app.state.settings, email, verify_url)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="email not verified" + ("" if emailed else "; verification link re-issued (see email or dev log)"),
            headers={"X-Verify-Token": token},
        )

    access_token = issue_identity(_auth_secret(request), user["user_id"], "creator" if user["is_creator"] else "listener", AUTH_TOKEN_TTL_SECONDS)
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user_id": user["user_id"],
        "display_name": user["display_name"],
        "email_verified": True,
        "is_creator": bool(user["is_creator"]),
    }


@router.get("/me")
async def me(request: Request, user_id: Annotated[str, Depends(require_auth)]):
    user = await _repo(request).get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    return {
        "user_id": user["user_id"],
        "email": user["email"],
        "display_name": user["display_name"],
        "email_verified": bool(user["email_verified"]),
        "is_creator": bool(user["is_creator"]),
        "created_at": user["created_at"],
    }
