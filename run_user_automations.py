"""Run PathForge's free, deterministic user automations for every account."""

import argparse
import html
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import main
from auth import send_transactional_email
from database import DB_NAME, get_connection
from platform_automations import run_platform_automations


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_LOG_DIRECTORY = PROJECT_ROOT / "automation-logs"
DEFAULT_LOCK_PATH = PROJECT_ROOT / ".user-automations.lock"
MAX_LOCK_AGE = timedelta(hours=1)


def write_automation_report(report, log_directory=DEFAULT_LOG_DIRECTORY):
    """Persist operational counts without usernames, email, or job details."""
    directory = Path(log_directory)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    destination = directory / f"user-automations-{stamp}.json"
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, indent=2), encoding="utf-8")
    temporary.replace(destination)
    return destination


def lock_is_abandoned(lock_path):
    """Recover automatically from a crashed or abnormally old scheduler run."""
    lock = Path(lock_path)
    try:
        age = datetime.now(timezone.utc) - datetime.fromtimestamp(
            lock.stat().st_mtime, timezone.utc
        )
        contents = lock.read_text(encoding="utf-8")
    except OSError:
        return False
    if age > MAX_LOCK_AGE:
        return True
    # Windows does not implement POSIX signal 0 semantics consistently; a
    # scheduler lock younger than one hour is therefore treated as active.
    if os.name == "nt":
        return False
    pid = next(
        (line.partition("=")[2] for line in contents.splitlines()
         if line.startswith("pid=")),
        "",
    )
    if not pid.isdigit():
        return False
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return True
    except (OSError, PermissionError):
        return False
    return False


def create_lock(lock):
    try:
        return os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        if not lock_is_abandoned(lock):
            raise
        lock.unlink(missing_ok=True)
        return os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)


def run_user_automations(database_path=DB_NAME, lock_path=DEFAULT_LOCK_PATH):
    """Evaluate due searches and create idempotent in-app reminders."""
    lock = Path(lock_path)
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = create_lock(lock)
    except FileExistsError as error:
        raise RuntimeError(
            "User automations are already running. If no run is active, "
            f"remove the stale lock file at {lock}."
        ) from error
    with os.fdopen(descriptor, "w", encoding="utf-8") as lock_file:
        lock_file.write(f"pid={os.getpid()}\n")

    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    connection = None
    try:
        connection = get_connection(database_path)
        connection.row_factory = main.sqlite3.Row
        cursor = connection.cursor()
        users = cursor.execute(
            """
            SELECT users.id
            FROM users
            LEFT JOIN privacy_settings
              ON privacy_settings.user_id = users.id
            WHERE users.role = 'job_seeker'
              AND COALESCE(privacy_settings.security_notifications, 1) = 1
            ORDER BY users.id
            """
        ).fetchall()
        before = cursor.execute("SELECT COUNT(*) FROM notifications").fetchone()[0]
        searches_checked = 0
        for user in users:
            due_searches = cursor.execute(
                """
                SELECT COUNT(*) FROM saved_searches
                WHERE user_id = ? AND is_enabled = 1
                  AND (next_check_at IS NULL OR next_check_at <= CURRENT_TIMESTAMP)
                """,
                (user["id"],),
            ).fetchone()[0]
            searches_checked += due_searches
            main.evaluate_user_saved_searches(cursor, user["id"])
            main.synchronize_user_notifications(cursor, user["id"])
        connection.commit()
        after = cursor.execute("SELECT COUNT(*) FROM notifications").fetchone()[0]
    except Exception:
        if connection is not None:
            connection.rollback()
        raise
    finally:
        if connection is not None:
            connection.close()
        lock.unlink(missing_ok=True)

    platform = run_platform_automations(database_path)
    email_delivery = deliver_email_digests(database_path)
    return {
        "status": "success",
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "users_checked": len(users),
        "saved_searches_checked": searches_checked,
        "notifications_created": after - before,
        "delivery": {"in_app": True, "email": email_delivery},
        "platform": platform,
    }


def deliver_email_digests(database_path=DB_NAME):
    """Best-effort email summaries; in-app notifications remain authoritative."""
    connection = get_connection(database_path)
    connection.row_factory = main.sqlite3.Row
    sent = failed = skipped = 0
    try:
        users = connection.execute(
            """SELECT users.id, users.email, preferences.digest_frequency
               FROM users JOIN automation_preferences preferences
                 ON preferences.user_id = users.id
               WHERE preferences.delivery_channel = 'email_and_in_app'
                 AND COALESCE(users.email_verified, 0) = 1"""
        ).fetchall()
        now = datetime.now(timezone.utc)
        for user in users:
            weekly = user["digest_frequency"] == "weekly"
            period = now.strftime("%Y-W%W" if weekly else "%Y-%m-%d")
            key = f"notification-email:{user['id']}:{'weekly' if weekly else 'daily'}:{period}"
            if connection.execute(
                "SELECT 1 FROM automation_deliveries WHERE delivery_key = ? AND status = 'sent'", (key,)
            ).fetchone():
                skipped += 1
                continue
            window = "-7 days" if weekly else "-1 day"
            notifications = connection.execute(
                """SELECT title FROM notifications
                   WHERE user_id = ? AND created_at >= datetime('now', ?)
                   ORDER BY datetime(created_at) DESC LIMIT 20""",
                (user["id"], window),
            ).fetchall()
            if not notifications:
                skipped += 1
                continue
            titles = [str(row["title"])[:160] for row in notifications]
            text = "Your PathForge summary:\n\n" + "\n".join(f"- {title}" for title in titles) + "\n\nSign in to PathForge to review details."
            items = "".join(f"<li>{html.escape(title)}</li>" for title in titles)
            try:
                send_transactional_email(
                    user["email"], "Your PathForge notification summary", text,
                    f"<p>Your PathForge summary:</p><ul>{items}</ul><p>Sign in to PathForge to review details.</p>",
                    key,
                )
                delivery_status = "sent"; sent += 1
            except Exception:
                delivery_status = "failed"; failed += 1
            connection.execute(
                """INSERT INTO automation_deliveries
                   (user_id, delivery_key, channel, status) VALUES (?, ?, 'email', ?)
                   ON CONFLICT(delivery_key) DO UPDATE SET
                     status = excluded.status, created_at = CURRENT_TIMESTAMP""",
                (user["id"], key, delivery_status),
            )
        connection.commit()
        return {"sent": sent, "failed": failed, "skipped": skipped}
    finally:
        connection.close()


def main_cli():
    parser = argparse.ArgumentParser(
        description=(
            "Create due saved-search, interview, deadline, and application "
            "follow-up notifications without AI or paid services."
        )
    )
    parser.add_argument(
        "--database",
        default=DB_NAME,
        help="Path to the PathForge SQLite database.",
    )
    parser.add_argument(
        "--log-directory",
        default=str(DEFAULT_LOG_DIRECTORY),
        help="Directory for non-sensitive automation audit reports.",
    )
    arguments = parser.parse_args()
    try:
        report = run_user_automations(arguments.database)
    except RuntimeError as error:
        print(json.dumps({"status": "failed", "error": str(error)}, indent=2))
        return 1
    report_path = write_automation_report(report, arguments.log_directory)
    report["report_path"] = str(report_path)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main_cli())
