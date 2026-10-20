"""Run PathForge's free, deterministic user automations for every account."""

import argparse
import json
from datetime import datetime, timezone

import main
from database import DB_NAME, get_connection


def run_user_automations(database_path=DB_NAME):
    """Evaluate due searches and create idempotent in-app reminders."""
    connection = get_connection(database_path)
    connection.row_factory = main.sqlite3.Row
    cursor = connection.cursor()
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

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

    try:
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
        connection.rollback()
        raise
    finally:
        connection.close()

    return {
        "status": "success",
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "users_checked": len(users),
        "saved_searches_checked": searches_checked,
        "notifications_created": after - before,
        "delivery": "in_app",
    }


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
    arguments = parser.parse_args()
    print(json.dumps(run_user_automations(arguments.database), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main_cli())
