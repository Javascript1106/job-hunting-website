"""Authentication, password, session, verification, and email services."""

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import urllib.request

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import HTTPException, Request

from database import get_connection


last_email_error_type = None
last_email_error_detail = None


COMMON_PASSWORDS = {
    "password", "password1", "password123", "12345678", "123456789",
    "qwerty123", "letmein", "welcome", "admin", "iloveyou",
    "changeme", "pathforge", "password1!",
}

PASSWORD_HASHER = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
)

# Unknown accounts still perform a real verification, reducing timing-based
# username discovery without ever granting access to the synthetic password.
DUMMY_PASSWORD_HASH = PASSWORD_HASHER.hash(secrets.token_urlsafe(32))

AUTH_RATE_LIMITS = {
    "login": {"subject_limit": 5, "ip_limit": 30, "window_minutes": 15},
    "register": {"subject_limit": 3, "ip_limit": 10, "window_minutes": 60},
    "password_reset_request": {
        "subject_limit": 3,
        "ip_limit": 10,
        "window_minutes": 60,
        "count_successes": True,
    },
    "password_reset_confirm": {
        "subject_limit": 5,
        "ip_limit": 20,
        "window_minutes": 15,
    },
    "email_verification_confirm": {
        "subject_limit": 5,
        "ip_limit": 20,
        "window_minutes": 15,
    },
    "sensitive_verification_confirm": {
        "subject_limit": 5,
        "ip_limit": 20,
        "window_minutes": 15,
    },
}


def authentication_fingerprint(value: str):
    """Hash normalized abuse-control identifiers before storing them."""
    normalized = str(value or "unknown").strip().lower().encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()


def authentication_client_address(request: Request):
    """Use the socket peer; trusted-proxy handling belongs in deployment setup."""
    return request.client.host if request.client else "unknown"


def enforce_authentication_rate_limit(action, request, subject, database_path):
    """Reject an authentication action after too many recent attempts."""
    rule = AUTH_RATE_LIMITS[action]
    subject_hash = authentication_fingerprint(subject)
    ip_hash = authentication_fingerprint(authentication_client_address(request))
    window = f"-{int(rule['window_minutes'])} minutes"
    outcome_clause = "" if rule.get("count_successes") else "AND succeeded = 0"
    connection = get_connection(database_path)
    try:
        connection.execute(
            "DELETE FROM auth_attempts WHERE datetime(created_at) < datetime('now', '-1 day')"
        )
        subject_failures = connection.execute(
            f"""SELECT COUNT(*) FROM auth_attempts
                WHERE action = ? AND subject_hash = ? AND ip_hash = ?
                  {outcome_clause} AND datetime(created_at) > datetime('now', ?)""",
            (action, subject_hash, ip_hash, window),
        ).fetchone()[0]
        ip_failures = connection.execute(
            f"""SELECT COUNT(*) FROM auth_attempts
                WHERE action = ? AND ip_hash = ?
                  {outcome_clause} AND datetime(created_at) > datetime('now', ?)""",
            (action, ip_hash, window),
        ).fetchone()[0]
        connection.commit()
    finally:
        connection.close()

    if subject_failures >= rule["subject_limit"] or ip_failures >= rule["ip_limit"]:
        seconds = int(rule["window_minutes"]) * 60
        raise HTTPException(
            status_code=429,
            detail="Too many attempts. Please wait and try again.",
            headers={"Retry-After": str(seconds)},
        )


def record_authentication_attempt(action, request, subject, succeeded, database_path):
    """Store hashed abuse-control identifiers and clear failures after success."""
    subject_hash = authentication_fingerprint(subject)
    ip_hash = authentication_fingerprint(authentication_client_address(request))
    connection = get_connection(database_path)
    try:
        if succeeded and not AUTH_RATE_LIMITS[action].get("count_successes"):
            connection.execute(
                "DELETE FROM auth_attempts WHERE action = ? AND subject_hash = ? AND ip_hash = ?",
                (action, subject_hash, ip_hash),
            )
        connection.execute(
            "INSERT INTO auth_attempts (action, subject_hash, ip_hash, succeeded) VALUES (?, ?, ?, ?)",
            (action, subject_hash, ip_hash, int(succeeded)),
        )
        connection.commit()
    finally:
        connection.close()


def validate_password_strength(password: str, username: str = "", email: str = ""):
    """Enforce PathForge's password and identity-substring policy."""
    password_bytes = len(password.encode("utf-8"))
    if len(password) < 12 or password_bytes > 72:
        raise HTTPException(
            status_code=400,
            detail=(
                "Use at least 12 characters and no more than 72 UTF-8 bytes. "
                "A multi-word passphrase works well."
            ),
        )
    normalized = re.sub(r"\s+", "", password).lower()
    if normalized in COMMON_PASSWORDS:
        raise HTTPException(status_code=400, detail="Choose a less common password or passphrase.")
    identity_parts = {
        username.strip().lower(),
        email.split("@", 1)[0].strip().lower() if email else "",
    }
    if any(part and len(part) >= 4 and part in password.lower() for part in identity_parts):
        raise HTTPException(
            status_code=400,
            detail="Your password cannot contain your username or email name.",
        )


def hash_password(password: str):
    """Create a new password hash using the current Argon2id policy."""
    return PASSWORD_HASHER.hash(password)


def verify_password(plain_password: str, stored_password: str):
    """Verify current Argon2id hashes and legacy PBKDF2 hashes safely."""
    if stored_password.startswith("$argon2"):
        try:
            return PASSWORD_HASHER.verify(stored_password, plain_password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    try:
        salt, saved_hash = stored_password.split(":", 1)
    except ValueError:
        return False
    password_hash = hashlib.pbkdf2_hmac(
        "sha256",
        plain_password.encode("utf-8"),
        salt.encode("utf-8"),
        100000,
    ).hex()
    return hmac.compare_digest(password_hash, saved_hash)


def password_hash_needs_upgrade(stored_password: str):
    """Return true for legacy hashes or Argon2 hashes using an older policy."""
    if not stored_password.startswith("$argon2"):
        return True
    try:
        return PASSWORD_HASHER.check_needs_rehash(stored_password)
    except InvalidHashError:
        return True


def create_account_code(cursor, user_id: int, purpose: str):
    """Replace any unused code for a purpose and return a new six-digit code."""
    code = f"{secrets.randbelow(1000000):06d}"
    token_hash = hashlib.sha256(
        f"{user_id}:{purpose}:{code}".encode("utf-8")
    ).hexdigest()
    cursor.execute(
        "DELETE FROM account_tokens WHERE user_id = ? AND purpose = ? AND used_at IS NULL",
        (user_id, purpose),
    )
    cursor.execute(
        """INSERT INTO account_tokens (user_id, purpose, token_hash, expires_at)
           VALUES (?, ?, ?, ?)""",
        (
            user_id,
            purpose,
            token_hash,
            (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
        ),
    )
    return code


def verify_account_code(cursor, user_id: int, purpose: str, code: str):
    """Consume one matching, unexpired verification code exactly once."""
    token_hash = hashlib.sha256(
        f"{user_id}:{purpose}:{code.strip()}".encode("utf-8")
    ).hexdigest()
    row = cursor.execute(
        """
        SELECT id FROM account_tokens
        WHERE user_id = ? AND purpose = ? AND token_hash = ?
          AND used_at IS NULL AND datetime(expires_at) > CURRENT_TIMESTAMP
        """,
        (user_id, purpose, token_hash),
    ).fetchone()
    if not row:
        return False
    cursor.execute(
        "UPDATE account_tokens SET used_at = CURRENT_TIMESTAMP WHERE id = ?",
        (row[0],),
    )
    return True


def send_transactional_email(recipient, subject, text, html, idempotency_key):
    """Deliver an account email and retain bounded diagnostics for administrators."""
    global last_email_error_type, last_email_error_detail
    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    from_email = os.environ.get("PATHFORGE_FROM_EMAIL", "").strip()
    if not api_key or not from_email:
        raise HTTPException(
            status_code=503,
            detail=(
                "Email delivery is not configured yet. Add RESEND_API_KEY "
                "and PATHFORGE_FROM_EMAIL."
            ),
        )
    payload = json.dumps(
        {
            "from": from_email,
            "to": [recipient],
            "subject": subject,
            "text": text,
            "html": html,
        }
    ).encode("utf-8")
    email_request = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "PathForge/1.0",
            "Idempotency-Key": idempotency_key[:256],
        },
    )
    try:
        with urllib.request.urlopen(email_request, timeout=12) as response:
            result = json.loads(response.read().decode("utf-8"))
            last_email_error_type = None
            last_email_error_detail = None
            return result
    except Exception as error:
        last_email_error_type = type(error).__name__
        last_email_error_detail = str(error)[:160]
        raise HTTPException(
            status_code=502,
            detail="The email provider could not deliver this message. Please try again.",
        ) from error


def record_email_error(prefix: str, error: Exception):
    """Record a bounded internal error without exposing provider details publicly."""
    global last_email_error_type, last_email_error_detail
    last_email_error_type = f"{prefix}:{type(error).__name__}"
    last_email_error_detail = str(error)[:160]


def get_email_diagnostics():
    """Return provider configuration and the most recent bounded error details."""
    return {
        "provider": "resend",
        "api_key_configured": bool(os.environ.get("RESEND_API_KEY", "").strip()),
        "sender_configured": bool(os.environ.get("PATHFORGE_FROM_EMAIL", "").strip()),
        "last_error_type": last_email_error_type,
        "last_error_detail": last_email_error_detail,
    }


def get_authenticated_user(request: Request, database_path):
    """Resolve a valid session cookie into the associated public user fields."""
    session_token = request.cookies.get("pathforge_session")
    if not session_token:
        raise HTTPException(status_code=401, detail="Not logged in.")

    token_hash = hashlib.sha256(session_token.encode("utf-8")).hexdigest()
    connection = get_connection(database_path)
    connection.row_factory = sqlite3.Row
    try:
        user = connection.execute(
            """
            SELECT users.id, users.username, users.email, users.role,
                   users.email_verified
            FROM user_sessions
            JOIN users ON users.id = user_sessions.user_id
            WHERE user_sessions.token_hash = ?
              AND datetime(user_sessions.expires_at) > CURRENT_TIMESTAMP
            """,
            (token_hash,),
        ).fetchone()
        if not user:
            raise HTTPException(status_code=401, detail="Invalid session.")
        connection.execute(
            """
            UPDATE user_sessions
            SET last_seen_at = CURRENT_TIMESTAMP
            WHERE token_hash = ?
              AND datetime(last_seen_at) < datetime('now', '-5 minutes')
            """,
            (token_hash,),
        )
        connection.commit()
        return dict(user)
    finally:
        connection.close()


def require_recent_sensitive_verification(request: Request, database_path):
    """Require a recent verification code before a sensitive account action."""
    user = get_authenticated_user(request, database_path)
    session_token = request.cookies.get("pathforge_session", "")
    token_hash = hashlib.sha256(session_token.encode("utf-8")).hexdigest()
    connection = get_connection(database_path)
    try:
        row = connection.execute(
            """SELECT sensitive_verified_at FROM user_sessions
               WHERE token_hash = ? AND user_id = ?
                 AND datetime(sensitive_verified_at) > datetime('now', '-15 minutes')""",
            (token_hash, user["id"]),
        ).fetchone()
    finally:
        connection.close()
    if not row:
        raise HTTPException(
            status_code=403,
            detail="Verify your identity with the emailed code before changing your password.",
        )
    return user


def require_role(request: Request, database_path, role: str):
    """Require the authenticated account to have one exact application role."""
    user = get_authenticated_user(request, database_path)
    if user["role"] != role:
        role_label = "Administrator" if role == "admin" else "Employer"
        raise HTTPException(status_code=403, detail=f"{role_label} access is required.")
    return user
