"""Apply pending PathForge database migrations as an explicit maintenance step."""

from database import DB_NAME, initialize_database


def main():
    applied_versions = initialize_database()
    if applied_versions:
        versions = ", ".join(str(version) for version in applied_versions)
        print(f"Applied PathForge database migration(s): {versions}.")
    else:
        print(f"{DB_NAME} is already at the latest schema version.")


if __name__ == "__main__":
    main()
