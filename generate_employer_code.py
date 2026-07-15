import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import secrets
import sqlite3

from database import initialize_database


DB_NAME = "jobs.db"


def hash_access_code(code: str):
    normalized_code = code.strip().upper()

    return hashlib.sha256(
        normalized_code.encode("utf-8")
    ).hexdigest()


def generate_code():
    random_section = secrets.token_hex(8).upper()

    return f"PF-EMP-{random_section}"


def main():
    parser = argparse.ArgumentParser(
        description="Create a one-time PathForge employer access code."
    )

    parser.add_argument(
        "--company",
        default=None,
        help="Optional company name associated with the code."
    )

    parser.add_argument(
        "--expires-days",
        type=int,
        default=None,
        help="Optional number of days before the code expires."
    )

    args = parser.parse_args()

    if args.expires_days is not None and args.expires_days <= 0:
        parser.error(
            "--expires-days must be greater than zero."
        )

    initialize_database()

    code = generate_code()
    code_hash = hash_access_code(code)
    code_preview = code[-6:]

    expiration_date = None

    if args.expires_days is not None:
        expiration_date = (
            datetime.now(timezone.utc)
            + timedelta(days=args.expires_days)
        ).isoformat()

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            INSERT INTO employer_access_codes (
                code_hash,
                code_preview,
                company_name,
                expires_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                code_hash,
                code_preview,
                args.company,
                expiration_date
            )
        )

        conn.commit()

    finally:
        conn.close()

    print()
    print("Employer access code created successfully.")
    print(f"Code: {code}")
    print(
        "Company:",
        args.company or "Not specified"
    )
    print(
        "Expires:",
        expiration_date or "Never"
    )
    print()
    print(
        "Save this code temporarily because the complete code "
        "cannot be recovered from the database."
    )


if __name__ == "__main__":
    main()