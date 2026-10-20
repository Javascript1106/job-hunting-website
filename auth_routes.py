"""FastAPI routes for account registration and server-side sessions."""

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets
import sqlite3
from typing import Callable

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr
from html import escape

import auth as auth_service
from database import get_connection


class RegisterUser(BaseModel):
    username: str
    email: EmailStr
    password: str


class LoginUser(BaseModel):
    identifier: str
    password: str


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


class AccountCodeConfirmation(BaseModel):
    code: str


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirmation(BaseModel):
    email: EmailStr
    code: str
    new_password: str


def create_auth_router(
    database_path: Callable[[], str], is_production: bool = False
):
    """Build account routes around a late-bound database path for test isolation."""
    router = APIRouter(tags=["authentication"])

    @router.post("/register")
    def register_user(user: RegisterUser, request: Request):
        registration_subject = f"{user.username}:{user.email}"
        path = database_path()
        auth_service.enforce_authentication_rate_limit(
            "register", request, registration_subject, path
        )
        auth_service.validate_password_strength(
            user.password, user.username, str(user.email)
        )
        connection = get_connection(path)
        try:
            existing_user = connection.execute(
                "SELECT * FROM users WHERE email = ? OR username = ?",
                (user.email, user.username),
            ).fetchone()
            if existing_user:
                connection.close()
                auth_service.record_authentication_attempt(
                    "register", request, registration_subject, False, path
                )
                raise HTTPException(
                    status_code=400,
                    detail="Username or email already exists.",
                )
            connection.execute(
                """
                INSERT INTO users (username, email, password, role)
                VALUES (?, ?, ?, 'job_seeker')
                """,
                (
                    user.username,
                    user.email,
                    auth_service.hash_password(user.password),
                ),
            )
            connection.commit()
        finally:
            connection.close()
        auth_service.record_authentication_attempt(
            "register", request, registration_subject, True, path
        )
        return {"message": "Account created successfully."}

    @router.post("/login")
    def login_user(user: LoginUser, response: Response, request: Request):
        login_subject = user.identifier
        path = database_path()
        auth_service.enforce_authentication_rate_limit(
            "login", request, login_subject, path
        )
        connection = get_connection(path)
        try:
            db_user = connection.execute(
                """
                SELECT id, username, email, password, role
                FROM users WHERE email = ? OR username = ?
                """,
                (user.identifier, user.identifier),
            ).fetchone()
            if not db_user:
                auth_service.verify_password(
                    user.password, auth_service.DUMMY_PASSWORD_HASH
                )
                connection.close()
                auth_service.record_authentication_attempt(
                    "login", request, login_subject, False, path
                )
                raise HTTPException(
                    status_code=401, detail="Invalid email or password."
                )

            user_id, username, email, hashed_password, role = db_user
            if not auth_service.verify_password(user.password, hashed_password):
                connection.close()
                auth_service.record_authentication_attempt(
                    "login", request, login_subject, False, path
                )
                raise HTTPException(
                    status_code=401, detail="Invalid email or password."
                )
            if auth_service.password_hash_needs_upgrade(hashed_password):
                connection.execute(
                    "UPDATE users SET password = ? WHERE id = ?",
                    (auth_service.hash_password(user.password), user_id),
                )

            session_token = secrets.token_urlsafe(32)
            token_hash = hashlib.sha256(session_token.encode("utf-8")).hexdigest()
            expires_at = datetime.now(timezone.utc) + timedelta(days=14)
            connection.execute(
                """
                INSERT INTO user_sessions (user_id, token_hash, expires_at, user_agent)
                VALUES (?, ?, ?, ?)
                """,
                (
                    user_id,
                    token_hash,
                    expires_at.isoformat(),
                    request.headers.get("user-agent", "")[:250],
                ),
            )
            connection.execute(
                """INSERT INTO security_events (user_id, event_type, event_summary)
                   VALUES (?, 'login', ?)""",
                (user_id, "A new sign-in was recorded."),
            )
            connection.commit()
        finally:
            connection.close()
        auth_service.record_authentication_attempt(
            "login", request, login_subject, True, path
        )
        response.delete_cookie("user_id")
        response.set_cookie(
            key="pathforge_session",
            value=session_token,
            httponly=True,
            samesite="lax",
            # Production cookies stay secure even when TLS is terminated by a
            # reverse proxy and the application sees an internal HTTP request.
            secure=is_production or request.url.scheme == "https",
            max_age=14 * 24 * 60 * 60,
            path="/",
        )
        return {
            "message": "Login successful.",
            "user": {
                "id": user_id,
                "username": username,
                "email": email,
                "role": role,
            },
        }

    @router.post("/logout")
    def logout_user(response: Response, request: Request):
        session_token = request.cookies.get("pathforge_session")
        if session_token:
            connection = get_connection(database_path())
            try:
                connection.execute(
                    "DELETE FROM user_sessions WHERE token_hash = ?",
                    (hashlib.sha256(session_token.encode("utf-8")).hexdigest(),),
                )
                connection.commit()
            finally:
                connection.close()
        response.delete_cookie("pathforge_session", path="/")
        response.delete_cookie("user_id")
        return {"message": "Logged out successfully."}

    @router.get("/account/sessions")
    def list_account_sessions(request: Request):
        path = database_path()
        user = auth_service.get_authenticated_user(request, path)
        current_token = request.cookies.get("pathforge_session", "")
        current_hash = hashlib.sha256(current_token.encode("utf-8")).hexdigest()
        connection = get_connection(path)
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(
                """
                SELECT id, token_hash, created_at, last_seen_at, expires_at, user_agent
                FROM user_sessions
                WHERE user_id = ? AND datetime(expires_at) > CURRENT_TIMESTAMP
                ORDER BY datetime(last_seen_at) DESC
                """,
                (user["id"],),
            ).fetchall()
        finally:
            connection.close()
        return {
            "sessions": [
                {
                    "id": row["id"],
                    "created_at": row["created_at"],
                    "last_seen_at": row["last_seen_at"],
                    "expires_at": row["expires_at"],
                    "device": row["user_agent"] or "Unknown browser",
                    "current": hmac.compare_digest(row["token_hash"], current_hash),
                }
                for row in rows
            ]
        }

    @router.delete("/account/sessions/{session_id}")
    def revoke_account_session(session_id: int, request: Request, response: Response):
        path = database_path()
        user = auth_service.get_authenticated_user(request, path)
        current_token = request.cookies.get("pathforge_session", "")
        current_hash = hashlib.sha256(current_token.encode("utf-8")).hexdigest()
        connection = get_connection(path)
        try:
            row = connection.execute(
                "SELECT token_hash FROM user_sessions WHERE id = ? AND user_id = ?",
                (session_id, user["id"]),
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Session not found.")
            connection.execute(
                "DELETE FROM user_sessions WHERE id = ? AND user_id = ?",
                (session_id, user["id"]),
            )
            connection.execute(
                """INSERT INTO security_events (user_id, event_type, event_summary)
                   VALUES (?, 'session_revoked', ?)""",
                (user["id"], "A signed-in session was revoked."),
            )
            connection.commit()
        finally:
            connection.close()
        if hmac.compare_digest(row[0], current_hash):
            response.delete_cookie("pathforge_session", path="/")
        return {"message": "Session revoked."}

    @router.post("/account/change-password")
    def change_account_password(data: PasswordChange, request: Request):
        path = database_path()
        user = auth_service.require_recent_sensitive_verification(request, path)
        auth_service.validate_password_strength(
            data.new_password, user["username"], user["email"]
        )
        connection = get_connection(path)
        try:
            saved = connection.execute(
                "SELECT password FROM users WHERE id = ?", (user["id"],)
            ).fetchone()
            if not saved or not auth_service.verify_password(
                data.current_password, saved[0]
            ):
                raise HTTPException(
                    status_code=400, detail="Current password is incorrect."
                )
            connection.execute(
                "UPDATE users SET password = ? WHERE id = ?",
                (auth_service.hash_password(data.new_password), user["id"]),
            )
            current_token = request.cookies.get("pathforge_session", "")
            current_hash = hashlib.sha256(
                current_token.encode("utf-8")
            ).hexdigest()
            connection.execute(
                "DELETE FROM user_sessions WHERE user_id = ? AND token_hash != ?",
                (user["id"], current_hash),
            )
            connection.execute(
                """INSERT INTO security_events (user_id, event_type, event_summary)
                   VALUES (?, 'password_changed', ?)""",
                (
                    user["id"],
                    "Your password was changed and other sessions were signed out.",
                ),
            )
            connection.commit()
        finally:
            connection.close()
        return {"message": "Password changed. Other signed-in sessions were revoked."}

    @router.get("/account/sensitive-verification/status")
    def sensitive_verification_status(request: Request):
        path = database_path()
        user = auth_service.get_authenticated_user(request, path)
        token_hash = hashlib.sha256(
            request.cookies.get("pathforge_session", "").encode("utf-8")
        ).hexdigest()
        connection = get_connection(path)
        try:
            row = connection.execute(
                """SELECT 1 FROM user_sessions
                   WHERE token_hash = ? AND user_id = ?
                     AND datetime(sensitive_verified_at) > datetime('now', '-15 minutes')""",
                (token_hash, user["id"]),
            ).fetchone()
        finally:
            connection.close()
        return {"verified": bool(row), "expires_in_minutes": 15}

    @router.post("/account/sensitive-verification/request")
    def request_sensitive_verification(request: Request):
        path = database_path()
        user = auth_service.get_authenticated_user(request, path)
        connection = get_connection(path)
        cursor = connection.cursor()
        try:
            recent = cursor.execute(
                """SELECT 1 FROM account_tokens WHERE user_id = ?
                   AND purpose = 'sensitive_action'
                   AND datetime(created_at) > datetime('now', '-1 minute')""",
                (user["id"],),
            ).fetchone()
            if recent:
                raise HTTPException(
                    status_code=429,
                    detail="Please wait one minute before requesting another code.",
                )
            code = auth_service.create_account_code(
                cursor, user["id"], "sensitive_action"
            )
            token_id = cursor.lastrowid
            connection.commit()
            try:
                auth_service.send_transactional_email(
                    user["email"],
                    "Confirm a sensitive PathForge action",
                    f"Your PathForge security code is {code}. It expires in 15 minutes.",
                    f"<h1>Confirm it is you</h1><p>Your PathForge security code is:</p><p style='font-size:28px;font-weight:bold;letter-spacing:4px'>{escape(code)}</p><p>This code expires in 15 minutes. Do not share it.</p>",
                    f"sensitive-{user['id']}-{token_id}",
                )
            except HTTPException:
                cursor.execute(
                    """DELETE FROM account_tokens WHERE user_id = ?
                       AND purpose = 'sensitive_action' AND used_at IS NULL""",
                    (user["id"],),
                )
                connection.commit()
                raise
        finally:
            connection.close()
        return {"message": f"A security code was sent to {user['email']}."}

    @router.post("/account/sensitive-verification/confirm")
    def confirm_sensitive_verification(
        data: AccountCodeConfirmation, request: Request
    ):
        path = database_path()
        user = auth_service.get_authenticated_user(request, path)
        subject = str(user["id"])
        action = "sensitive_verification_confirm"
        auth_service.enforce_authentication_rate_limit(
            action, request, subject, path
        )
        token_hash = hashlib.sha256(
            request.cookies.get("pathforge_session", "").encode("utf-8")
        ).hexdigest()
        connection = get_connection(path)
        cursor = connection.cursor()
        try:
            if not auth_service.verify_account_code(
                cursor, user["id"], "sensitive_action", data.code
            ):
                connection.close()
                auth_service.record_authentication_attempt(
                    action, request, subject, False, path
                )
                raise HTTPException(
                    status_code=400, detail="Security code is invalid or expired."
                )
            cursor.execute(
                """UPDATE user_sessions SET sensitive_verified_at = CURRENT_TIMESTAMP
                   WHERE token_hash = ? AND user_id = ?""",
                (token_hash, user["id"]),
            )
            cursor.execute(
                """INSERT INTO security_events (user_id, event_type, event_summary)
                   VALUES (?, 'sensitive_verified', ?)""",
                (
                    user["id"],
                    "Identity verified for a sensitive account action.",
                ),
            )
            connection.commit()
        finally:
            connection.close()
        auth_service.record_authentication_attempt(
            action, request, subject, True, path
        )
        return {"message": "Identity verified for 15 minutes.", "verified": True}

    @router.post("/account/email-verification/request")
    def request_email_verification(request: Request):
        path = database_path()
        user = auth_service.get_authenticated_user(request, path)
        if user.get("email_verified"):
            return {"message": "Your email is already verified.", "verified": True}
        connection = get_connection(path)
        cursor = connection.cursor()
        try:
            recent = cursor.execute(
                """SELECT 1 FROM account_tokens WHERE user_id = ?
                   AND purpose = 'email_verification'
                   AND datetime(created_at) > datetime('now', '-1 minute')""",
                (user["id"],),
            ).fetchone()
            if recent:
                raise HTTPException(
                    status_code=429,
                    detail="Please wait one minute before requesting another code.",
                )
            code = auth_service.create_account_code(
                cursor, user["id"], "email_verification"
            )
            token_id = cursor.lastrowid
            connection.commit()
            try:
                auth_service.send_transactional_email(
                    user["email"],
                    "Verify your PathForge email",
                    f"Your PathForge verification code is {code}. It expires in 15 minutes.",
                    f"<h1>Verify your PathForge email</h1><p>Your verification code is:</p><p style='font-size:28px;font-weight:bold;letter-spacing:4px'>{escape(code)}</p><p>This code expires in 15 minutes. If you did not request it, you can ignore this email.</p>",
                    f"verify-{user['id']}-{token_id}",
                )
            except HTTPException:
                cursor.execute(
                    """DELETE FROM account_tokens WHERE user_id = ?
                       AND purpose = 'email_verification' AND used_at IS NULL""",
                    (user["id"],),
                )
                connection.commit()
                raise
        finally:
            connection.close()
        return {
            "message": f"A verification code was sent to {user['email']}.",
            "verified": False,
        }

    @router.post("/account/email-verification/confirm")
    def confirm_email_verification(data: AccountCodeConfirmation, request: Request):
        path = database_path()
        user = auth_service.get_authenticated_user(request, path)
        subject = str(user["id"])
        action = "email_verification_confirm"
        auth_service.enforce_authentication_rate_limit(
            action, request, subject, path
        )
        connection = get_connection(path)
        cursor = connection.cursor()
        try:
            if not auth_service.verify_account_code(
                cursor, user["id"], "email_verification", data.code
            ):
                connection.close()
                auth_service.record_authentication_attempt(
                    action, request, subject, False, path
                )
                raise HTTPException(
                    status_code=400,
                    detail="Verification code is invalid or expired.",
                )
            cursor.execute(
                "UPDATE users SET email_verified = 1 WHERE id = ?",
                (user["id"],),
            )
            cursor.execute(
                """INSERT INTO security_events (user_id, event_type, event_summary)
                   VALUES (?, 'email_verified', ?)""",
                (user["id"], "Your account email was verified."),
            )
            connection.commit()
        finally:
            connection.close()
        auth_service.record_authentication_attempt(
            action, request, subject, True, path
        )
        return {"message": "Email verified successfully.", "verified": True}

    @router.post("/password-reset/request")
    def request_password_reset(data: PasswordResetRequest, request: Request):
        generic_message = (
            "If that email belongs to an account, a reset code has been sent."
        )
        path = database_path()
        subject = str(data.email)
        action = "password_reset_request"
        auth_service.enforce_authentication_rate_limit(
            action, request, subject, path
        )
        connection = get_connection(path)
        cursor = connection.cursor()
        try:
            row = cursor.execute(
                "SELECT id, email FROM users WHERE lower(email) = lower(?)",
                (str(data.email),),
            ).fetchone()
            if not row:
                connection.close()
                auth_service.record_authentication_attempt(
                    action, request, subject, False, path
                )
                return {"message": generic_message}
            recent = cursor.execute(
                """SELECT 1 FROM account_tokens WHERE user_id = ?
                   AND purpose = 'password_reset'
                   AND datetime(created_at) > datetime('now', '-1 minute')""",
                (row[0],),
            ).fetchone()
            if recent:
                return {"message": generic_message}
            token_id = None
            try:
                code = auth_service.create_account_code(
                    cursor, row[0], "password_reset"
                )
                token_id = cursor.lastrowid
                connection.commit()
                auth_service.send_transactional_email(
                    row[1],
                    "Reset your PathForge password",
                    f"Your PathForge password-reset code is {code}. It expires in 15 minutes.",
                    f"<h1>Reset your PathForge password</h1><p>Your reset code is:</p><p style='font-size:28px;font-weight:bold;letter-spacing:4px'>{escape(code)}</p><p>This code expires in 15 minutes. If you did not request it, you can ignore this email.</p>",
                    f"reset-{row[0]}-{token_id}",
                )
            except Exception as error:
                auth_service.record_email_error("password_reset", error)
                if token_id is not None:
                    cursor.execute(
                        "DELETE FROM account_tokens WHERE id = ?", (token_id,)
                    )
                    connection.commit()
        finally:
            connection.close()
        auth_service.record_authentication_attempt(
            action, request, subject, True, path
        )
        return {"message": generic_message}

    @router.post("/password-reset/confirm")
    def confirm_password_reset(
        data: PasswordResetConfirmation, request: Request
    ):
        path = database_path()
        subject = str(data.email)
        action = "password_reset_confirm"
        auth_service.enforce_authentication_rate_limit(
            action, request, subject, path
        )
        connection = get_connection(path)
        cursor = connection.cursor()
        try:
            row = cursor.execute(
                """SELECT id, username, email FROM users
                   WHERE lower(email) = lower(?)""",
                (str(data.email),),
            ).fetchone()
            if not row:
                connection.close()
                auth_service.record_authentication_attempt(
                    action, request, subject, False, path
                )
                raise HTTPException(
                    status_code=400, detail="Reset code is invalid or expired."
                )
            auth_service.validate_password_strength(
                data.new_password, row[1], row[2]
            )
            if not auth_service.verify_account_code(
                cursor, row[0], "password_reset", data.code
            ):
                connection.close()
                auth_service.record_authentication_attempt(
                    action, request, subject, False, path
                )
                raise HTTPException(
                    status_code=400, detail="Reset code is invalid or expired."
                )
            cursor.execute(
                "UPDATE users SET password = ? WHERE id = ?",
                (auth_service.hash_password(data.new_password), row[0]),
            )
            cursor.execute("DELETE FROM user_sessions WHERE user_id = ?", (row[0],))
            cursor.execute(
                """INSERT INTO security_events (user_id, event_type, event_summary)
                   VALUES (?, 'password_reset', ?)""",
                (
                    row[0],
                    "Your password was reset and all sessions were signed out.",
                ),
            )
            connection.commit()
        finally:
            connection.close()
        auth_service.record_authentication_attempt(
            action, request, subject, True, path
        )
        return {"message": "Password reset successfully. You can now log in."}

    return router
