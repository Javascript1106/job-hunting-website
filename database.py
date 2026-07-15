import sqlite3
import json

DB_NAME = "jobs.db"


def column_exists(cursor, table_name, column_name):
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = cursor.fetchall()

    return any(column[1] == column_name for column in columns)


def create_jobs_table():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            company TEXT NOT NULL,
            location TEXT NOT NULL,
            pay TEXT NOT NULL,
            description TEXT NOT NULL,
            schedule TEXT NOT NULL,
            experience TEXT NOT NULL,
            category TEXT NOT NULL,

            application_method TEXT NOT NULL
                DEFAULT 'pathforge'
                CHECK (
                    application_method IN (
                        'pathforge',
                        'employer_website'
                    )
                ),

            application_url TEXT
        )
    """)

    # Adds application workflow fields to older databases.
    if not column_exists(
        cursor,
        "jobs",
        "application_method"
    ):
        cursor.execute("""
            ALTER TABLE jobs
            ADD COLUMN application_method TEXT
            NOT NULL DEFAULT 'pathforge'
        """)

    if not column_exists(
        cursor,
        "jobs",
        "application_url"
    ):
        cursor.execute("""
            ALTER TABLE jobs
            ADD COLUMN application_url TEXT
        """)

    # Keeps invalid or blank older values from breaking
    # the application workflow.
    cursor.execute("""
        UPDATE jobs
        SET application_method = 'pathforge'
        WHERE application_method IS NULL
           OR application_method NOT IN (
               'pathforge',
               'employer_website'
           )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'job_seeker'
        )
    """)
    # Adds the role column to databases created before this feature.
    if not column_exists(cursor, "users", "role"):
        cursor.execute("""
            ALTER TABLE users
            ADD COLUMN role TEXT NOT NULL DEFAULT 'job_seeker'
        """)

    # Ensures old accounts receive the job_seeker role.
    cursor.execute("""
        UPDATE users
        SET role = 'job_seeker'
        WHERE role IS NULL
           OR role NOT IN ('job_seeker', 'employer')
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS employer_access_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code_hash TEXT NOT NULL UNIQUE,
            code_preview TEXT NOT NULL,
            company_name TEXT,
            is_used INTEGER NOT NULL DEFAULT 0,
            redeemed_by_user_id INTEGER,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            expires_at TEXT,
            redeemed_at TEXT,
            FOREIGN KEY (redeemed_by_user_id) REFERENCES users(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL UNIQUE,
            display_name TEXT,
            career_interests TEXT,
            preferred_industries TEXT,
            skills TEXT,
            experience_level TEXT,
            preferred_location TEXT,
            schedule_preference TEXT,
            work_preference TEXT,
            desired_pay TEXT,
            career_goals TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS saved_jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        job_id INTEGER NOT NULL,
        saved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

        FOREIGN KEY (user_id)
            REFERENCES users(id)
            ON DELETE CASCADE,

        FOREIGN KEY (job_id)
            REFERENCES jobs(id)
            ON DELETE CASCADE,

        UNIQUE (user_id, job_id)
    )
""")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            job_id INTEGER NOT NULL,

            application_method TEXT NOT NULL
                CHECK (
                    application_method IN (
                        'pathforge',
                        'employer_website'
                    )
                ),

            status TEXT NOT NULL DEFAULT 'Interested'
                CHECK (
                    status IN (
                        'Interested',
                        'Applied',
                        'Application Viewed',
                        'Under Review',
                        'Interview Scheduled',
                        'Interview Completed',
                        'Offer Extended',
                        'Accepted',
                        'Rejected',
                        'Withdrawn'
                    )
                ),

            applied_at TEXT,
            interview_date TEXT,
            follow_up_date TEXT,
            notes TEXT,

            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (user_id)
                REFERENCES users(id)
                ON DELETE CASCADE,

            FOREIGN KEY (job_id)
                REFERENCES jobs(id)
                ON DELETE CASCADE,

            UNIQUE (user_id, job_id)
        )
    """)

    conn.commit()
    conn.close()

def populate_jobs():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM jobs")
    count = cursor.fetchone()[0]

    if count == 0:
        with open("jobs.json", "r") as file:
            jobs = json.load(file)

        for job in jobs:
            cursor.execute("""
                    INSERT INTO jobs (
                    title,
                    company,
                    location,
                    pay,
                    description,
                    schedule,
                    experience,
                    category,
                    application_method,
                    application_url
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                job["title"],
                job["company"],
                job["location"],
                job["pay"],
                job["description"],
                job["schedule"],
                job["experience"],
                job["category"],
                job.get(
                    "application_method",
                    "pathforge"
                ),
                job.get("application_url")
            ))

        print("Jobs inserted successfully.")
    else:
        print("Database already contains jobs.")

    conn.commit()
    conn.close()


def initialize_database():
    create_jobs_table()


if __name__ == "__main__":
    create_jobs_table()
    populate_jobs()