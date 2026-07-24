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

            application_url TEXT,

            employer_id INTEGER,

            status TEXT NOT NULL DEFAULT 'active'
                CHECK (
                    status IN (
                        'active',
                        'closed',
                        'draft'
                    )
                ),

            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (employer_id)
                REFERENCES users(id)
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

    # Adds employer ownership to older databases.
    if not column_exists(
        cursor,
        "jobs",
        "employer_id"
    ):
        cursor.execute("""
            ALTER TABLE jobs
            ADD COLUMN employer_id INTEGER
        """)

    # Adds job status to older databases.
    if not column_exists(
        cursor,
        "jobs",
        "status"
    ):
        cursor.execute("""
            ALTER TABLE jobs
            ADD COLUMN status TEXT
            NOT NULL DEFAULT 'active'
        """)

    # Adds job creation timestamps to older databases.
    if not column_exists(
        cursor,
        "jobs",
        "created_at"
    ):
        cursor.execute("""
            ALTER TABLE jobs
            ADD COLUMN created_at TEXT
        """)

        cursor.execute("""
            UPDATE jobs
            SET created_at = CURRENT_TIMESTAMP
            WHERE created_at IS NULL
        """)

    # Adds job update timestamps to older databases.
    if not column_exists(
        cursor,
        "jobs",
        "updated_at"
    ):
        cursor.execute("""
            ALTER TABLE jobs
            ADD COLUMN updated_at TEXT
        """)

        cursor.execute("""
            UPDATE jobs
            SET updated_at = CURRENT_TIMESTAMP
            WHERE updated_at IS NULL
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

    # Keeps invalid or blank job statuses from breaking
    # employer job management.
    cursor.execute("""
        UPDATE jobs
        SET status = 'active'
        WHERE status IS NULL
           OR status NOT IN (
               'active',
               'closed',
               'draft'
           )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_jobs_employer_id
        ON jobs(employer_id)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_jobs_status
        ON jobs(status)
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
        CREATE TABLE IF NOT EXISTS company_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employer_id INTEGER NOT NULL UNIQUE,
            company_name TEXT NOT NULL DEFAULT '',
            company_description TEXT,
            website TEXT,
            logo_url TEXT,
            brand_color TEXT,
            hiring_preferences TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (employer_id)
                REFERENCES users(id)
                ON DELETE CASCADE
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_company_profiles_employer_id
        ON company_profiles(employer_id)
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
            interview_time TEXT,
            interview_format TEXT
                CHECK (
                    interview_format IS NULL
                    OR interview_format IN (
                        'In Person',
                        'Phone',
                        'Video'
                    )
                ),
            interview_location TEXT,
            interview_details TEXT,
            follow_up_date TEXT,
            notes TEXT,
            employer_notes TEXT,

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

    if not column_exists(
        cursor,
        "applications",
        "interview_time"
    ):
        cursor.execute("""
            ALTER TABLE applications
            ADD COLUMN interview_time TEXT
        """)

    if not column_exists(
        cursor,
        "applications",
        "interview_format"
    ):
        cursor.execute("""
            ALTER TABLE applications
            ADD COLUMN interview_format TEXT
        """)

    if not column_exists(
        cursor,
        "applications",
        "interview_location"
    ):
        cursor.execute("""
            ALTER TABLE applications
            ADD COLUMN interview_location TEXT
        """)

    if not column_exists(
        cursor,
        "applications",
        "interview_details"
    ):
        cursor.execute("""
            ALTER TABLE applications
            ADD COLUMN interview_details TEXT
        """)

    if not column_exists(
        cursor,
        "applications",
        "employer_notes"
    ):
        cursor.execute("""
            ALTER TABLE applications
            ADD COLUMN employer_notes TEXT
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_applications_job_id
            ON applications(job_id)
        """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS application_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            question_text TEXT NOT NULL,

            field_type TEXT NOT NULL DEFAULT 'short_text'
                CHECK (
                    field_type IN (
                        'short_text',
                        'long_text',
                        'yes_no'
                    )
                ),

            is_required INTEGER NOT NULL DEFAULT 1,
            display_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (job_id)
                REFERENCES jobs(id)
                ON DELETE CASCADE
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS application_answers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            application_id INTEGER NOT NULL,
            question_id INTEGER NOT NULL,
            answer_text TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (application_id)
                REFERENCES applications(id)
                ON DELETE CASCADE,

            FOREIGN KEY (question_id)
                REFERENCES application_questions(id)
                ON DELETE CASCADE,

            UNIQUE (application_id, question_id)
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_application_questions_job_id
        ON application_questions(job_id)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_application_answers_application_id
        ON application_answers(application_id)
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