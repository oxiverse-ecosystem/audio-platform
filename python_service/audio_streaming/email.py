"""Transactional Email Service supporting Resend and SendGrid.

Handles:
  1. Email verification workflows for new user signups.
  2. Password reset workflows for account recovery.

Configuration via environment variables:
  - RESEND_API_KEY (optional): Resend API key
  - RESEND_FROM (optional): Sender address, defaults to "Oxiverse Audio <onboarding@resend.dev>"
  - SENDGRID_API_KEY (optional): SendGrid API key
  - SENDGRID_FROM (optional): Sender address, defaults to "no-reply@oxiverse.audio"
  - Dev fallback: Writes formatted link logs to runtime-data/dev-emails.log
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("audio_streaming.email")


def _get_dev_log_path() -> Path:
    data_dir = Path(os.getenv("AUDIO_DATA_DIR", "./runtime-data")).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "dev-emails.log"


def _log_dev_email(email_type: str, to_email: str, action_url: str) -> None:
    try:
        log_path = _get_dev_log_path()
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [{email_type}] {to_email} -> {action_url}\n")
    except Exception as exc:
        logger.warning(f"Could not write to dev email log: {exc}")


def _send_via_resend(to_email: str, subject: str, html_body: str, text_body: str) -> bool:
    api_key = (os.getenv("RESEND_API_KEY") or "").strip()
    if not api_key or api_key == "REPLACE_WITH_YOUR_RESEND_KEY":
        return False

    sender = os.getenv("RESEND_FROM") or "Oxiverse Audio <onboarding@resend.dev>"
    try:
        import resend
        resend.api_key = api_key
        resend.Emails.send({
            "from": sender,
            "to": [to_email],
            "subject": subject,
            "html": html_body,
            "text": text_body,
        })
        logger.info(f"Sent email via Resend to {to_email}")
        return True
    except Exception as exc:
        logger.warning(f"Resend dispatch failed: {exc}")
        return False


def _send_via_sendgrid(to_email: str, subject: str, html_body: str, text_body: str) -> bool:
    api_key = (os.getenv("SENDGRID_API_KEY") or "").strip()
    if not api_key or api_key == "REPLACE_WITH_YOUR_SENDGRID_KEY":
        return False

    sender = os.getenv("SENDGRID_FROM") or "no-reply@oxiverse.audio"
    try:
        import httpx
        payload = {
            "personalizations": [{"to": [{"email": to_email}]}],
            "from": {"email": sender, "name": "Oxiverse Audio"},
            "subject": subject,
            "content": [
                {"type": "text/plain", "value": text_body},
                {"type": "text/html", "value": html_body},
            ],
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=10.0) as client:
            resp = client.post("https://api.sendgrid.com/v3/mail/send", json=payload, headers=headers)
            if resp.status_code in (200, 201, 202):
                logger.info(f"Sent email via SendGrid to {to_email}")
                return True
            else:
                logger.warning(f"SendGrid API returned status {resp.status_code}: {resp.text[:200]}")
                return False
    except Exception as exc:
        logger.warning(f"SendGrid dispatch failed: {exc}")
        return False


def send_email(to_email: str, subject: str, html_body: str, text_body: str, email_type: str, action_url: str) -> bool:
    """Send transactional email via Resend, then SendGrid, or fallback to dev log."""
    # 1. Try Resend
    if _send_via_resend(to_email, subject, html_body, text_body):
        return True

    # 2. Try SendGrid
    if _send_via_sendgrid(to_email, subject, html_body, text_body):
        return True

    # 3. Dev mode fallback: log to file
    _log_dev_email(email_type, to_email, action_url)
    return False


def send_verification_email(to_email: str, display_name: str, verify_url: str) -> bool:
    """Send verification email with token link."""
    subject = "Verify your Oxiverse Audio account"
    safe_name = display_name or "Creator"
    html_body = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #0d0e15; color: #e2e1ec; margin: 0; padding: 40px 20px;">
  <div style="max-width: 540px; margin: 0 auto; background: #13131c; border: 1px solid #282937; border-radius: 12px; padding: 32px; box-shadow: 0 4px 24px rgba(0,0,0,0.4);">
    <div style="margin-bottom: 24px;">
      <h1 style="color: #bec2ff; font-size: 24px; font-weight: 700; margin: 0;">Oxiverse Audio</h1>
      <p style="color: #9090a2; font-size: 14px; margin: 4px 0 0 0;">Studio Sound &amp; Dynamic Voice Discovery</p>
    </div>
    <div style="border-top: 1px solid #282937; padding-top: 20px; margin-bottom: 24px;">
      <h2 style="color: #ffffff; font-size: 18px; margin: 0 0 12px 0;">Welcome, {safe_name}!</h2>
      <p style="color: #c6c5d4; font-size: 15px; line-height: 1.5; margin: 0 0 20px 0;">
        Thank you for joining Oxiverse Audio. Please confirm your email address to begin uploading studio-mastered voice drops and listening to exclusive founder audio.
      </p>
      <div style="text-align: center; margin: 28px 0;">
        <a href="{verify_url}" style="background-color: #4648d4; color: #ffffff; font-size: 15px; font-weight: 600; text-decoration: none; padding: 12px 28px; border-radius: 8px; display: inline-block;">
          Verify Email Address
        </a>
      </div>
      <p style="color: #9090a2; font-size: 13px; margin: 20px 0 8px 0;">Or copy and paste this link into your browser:</p>
      <p style="background: #1c1b26; border: 1px solid #282937; border-radius: 6px; padding: 10px; font-size: 12px; color: #bec2ff; word-break: break-all; margin: 0;">
        {verify_url}
      </p>
      <p style="color: #9090a2; font-size: 12px; margin: 16px 0 0 0;">This verification link expires in 24 hours.</p>
    </div>
    <div style="border-top: 1px solid #282937; padding-top: 16px; font-size: 12px; color: #646477;">
      Oxiverse Audio &bull; Enterprise-grade audio protection and studio mastering
    </div>
  </div>
</body>
</html>"""
    text_body = (
        f"Welcome to Oxiverse Audio, {safe_name}!\n\n"
        f"Please verify your email address by visiting this link:\n{verify_url}\n\n"
        f"This link expires in 24 hours."
    )
    return send_email(to_email, subject, html_body, text_body, "VERIFY", verify_url)


def send_password_reset_email(to_email: str, reset_url: str) -> bool:
    """Send password reset email with recovery link."""
    subject = "Reset your Oxiverse Audio password"
    html_body = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #0d0e15; color: #e2e1ec; margin: 0; padding: 40px 20px;">
  <div style="max-width: 540px; margin: 0 auto; background: #13131c; border: 1px solid #282937; border-radius: 12px; padding: 32px; box-shadow: 0 4px 24px rgba(0,0,0,0.4);">
    <div style="margin-bottom: 24px;">
      <h1 style="color: #bec2ff; font-size: 24px; font-weight: 700; margin: 0;">Oxiverse Audio</h1>
      <p style="color: #9090a2; font-size: 14px; margin: 4px 0 0 0;">Password Reset Request</p>
    </div>
    <div style="border-top: 1px solid #282937; padding-top: 20px; margin-bottom: 24px;">
      <h2 style="color: #ffffff; font-size: 18px; margin: 0 0 12px 0;">Reset Your Password</h2>
      <p style="color: #c6c5d4; font-size: 15px; line-height: 1.5; margin: 0 0 20px 0;">
        We received a request to reset the password for your Oxiverse Audio account. Click the button below to choose a new password.
      </p>
      <div style="text-align: center; margin: 28px 0;">
        <a href="{reset_url}" style="background-color: #4648d4; color: #ffffff; font-size: 15px; font-weight: 600; text-decoration: none; padding: 12px 28px; border-radius: 8px; display: inline-block;">
          Reset Password
        </a>
      </div>
      <p style="color: #9090a2; font-size: 13px; margin: 20px 0 8px 0;">Or copy and paste this link into your browser:</p>
      <p style="background: #1c1b26; border: 1px solid #282937; border-radius: 6px; padding: 10px; font-size: 12px; color: #bec2ff; word-break: break-all; margin: 0;">
        {reset_url}
      </p>
      <p style="color: #9090a2; font-size: 12px; margin: 16px 0 0 0;">
        This password reset link expires in 1 hour. If you didn't request a password reset, you can safely ignore this email.
      </p>
    </div>
    <div style="border-top: 1px solid #282937; padding-top: 16px; font-size: 12px; color: #646477;">
      Oxiverse Audio &bull; Security Team
    </div>
  </div>
</body>
</html>"""
    text_body = (
        f"We received a request to reset your Oxiverse Audio password.\n\n"
        f"Reset your password here:\n{reset_url}\n\n"
        f"This link expires in 1 hour. If you did not request this, please ignore this email."
    )
    return send_email(to_email, subject, html_body, text_body, "RESET", reset_url)
