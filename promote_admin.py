"""Promote an existing PathForge account to administrator through an explicit CLI action."""

import argparse
import sqlite3

from database import DB_NAME, get_connection, initialize_database


# Promotion is an explicit maintenance action and asks for confirmation by default.
def promote_account(identifier, assume_yes=False):
    initialize_database()
    conn = get_connection(DB_NAME)
    conn.row_factory = sqlite3.Row
    account = conn.execute(
        "SELECT id, username, email, role FROM users "
        "WHERE username = ? OR email = ?",
        (identifier, identifier)
    ).fetchone()
    if not account:
        conn.close()
        raise SystemExit(
            "No PathForge account matches that username or email. "
            "Register the administrator account first."
        )
    if account["role"] == "admin":
        conn.close()
        print(f'{account["username"]} already has administrator access.')
        return
    if not assume_yes:
        confirmation = input(
            f'Promote {account["username"]} ({account["email"]}) '
            "to PathForge administrator? Type PROMOTE to continue: "
        ).strip()
        if confirmation != "PROMOTE":
            conn.close()
            print("No account changes were made.")
            return
    conn.execute("UPDATE users SET role = 'admin' WHERE id = ?", (account["id"],))
    conn.commit()
    conn.close()
    print(
        f'{account["username"]} now has administrator access. '
        "The account can open admin-moderation.html after signing in."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Promote an existing PathForge account to administrator."
    )
    parser.add_argument("identifier", help="Existing username or email")
    parser.add_argument("--yes", action="store_true", help="Skip confirmation")
    args = parser.parse_args()
    promote_account(args.identifier.strip(), args.yes)
