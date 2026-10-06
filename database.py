"""SQLite schema creation and migrations shared by the PathForge API and maintenance tools."""

import json
import os
import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent


# A relative override remains project-relative instead of depending on whichever
# terminal folder happened to launch the application.
def resolve_database_path(value=None):
    configured_value = value or os.environ.get("PATHFORGE_DATABASE_PATH")
    database_path = Path(configured_value) if configured_value else PROJECT_ROOT / "jobs.db"
    if not database_path.is_absolute():
        database_path = PROJECT_ROOT / database_path
    return str(database_path.resolve())


DB_NAME = resolve_database_path()


def get_connection(db_name=DB_NAME):
    """Open one consistently configured PathForge SQLite connection."""
    conn = sqlite3.connect(resolve_database_path(db_name), timeout=5)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def column_exists(cursor, table_name, column_name):
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = cursor.fetchall()

    return any(column[1] == column_name for column in columns)


# This migration is intentionally idempotent so startup can safely call it repeatedly.
def create_jobs_table(db_name=DB_NAME):
    """Build the current baseline schema against an explicitly selected database."""
    conn = get_connection(db_name)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            company TEXT NOT NULL,
            location TEXT NOT NULL,
            pay TEXT NOT NULL,
            description TEXT NOT NULL,
            requirements TEXT,
            preferred_qualifications TEXT,
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
            owner_user_id INTEGER,

            status TEXT NOT NULL DEFAULT 'active'
                CHECK (
                    status IN (
                        'active',
                        'closed',
                        'draft'
                    )
                ),

            application_deadline TEXT,

            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (employer_id)
                REFERENCES users(id),
            FOREIGN KEY (owner_user_id)
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

    # Private job references created by a job seeker solely for tracking an
    # application completed outside PathForge.
    if not column_exists(cursor, "jobs", "owner_user_id"):
        cursor.execute("""
            ALTER TABLE jobs
            ADD COLUMN owner_user_id INTEGER
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

    # Optional employer-provided deadline in YYYY-MM-DD format.
    if not column_exists(
        cursor,
        "jobs",
        "application_deadline"
    ):
        cursor.execute("""
            ALTER TABLE jobs
            ADD COLUMN application_deadline TEXT
        """)

    job_qualification_columns = {
        "requirements": "TEXT",
        "preferred_qualifications": "TEXT"
    }

    for column_name, column_type in job_qualification_columns.items():
        if not column_exists(cursor, "jobs", column_name):
            cursor.execute(
                f"""
                ALTER TABLE jobs
                ADD COLUMN {column_name} {column_type}
                """
            )

    # Adds source and verification metadata without rebuilding the table.
    # All fields remain nullable so legacy and employer-created jobs retain
    # their existing meaning.
    catalog_columns = {
        "source": "TEXT",
        "external_job_id": "TEXT",
        "source_url": "TEXT",
        "posted_at": "TEXT",
        "expires_at": "TEXT",
        "last_verified_at": "TEXT",
        "employment_type": "TEXT",
        "is_remote": "INTEGER",
        "salary_min": "REAL",
        "salary_max": "REAL",
        "salary_period": "TEXT",
        "verification_status": "TEXT",
        "link_status": "TEXT",
        "last_link_checked_at": "TEXT"
    }

    for column_name, column_type in catalog_columns.items():
        if not column_exists(cursor, "jobs", column_name):
            cursor.execute(
                f"""
                ALTER TABLE jobs
                ADD COLUMN {column_name} {column_type}
                """
            )

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

    # Normalize only invalid values in newly added catalog fields.
    cursor.execute("""
        UPDATE jobs
        SET is_remote = NULL
        WHERE is_remote IS NOT NULL
          AND is_remote NOT IN (0, 1)
    """)

    cursor.execute("""
        UPDATE jobs
        SET verification_status = NULL
        WHERE verification_status IS NOT NULL
          AND verification_status NOT IN (
              'verified',
              'unverified',
              'expired',
              'removed'
          )
    """)

    cursor.execute("""
        UPDATE jobs
        SET link_status = NULL
        WHERE link_status IS NOT NULL
          AND link_status NOT IN (
              'working',
              'unavailable',
              'unknown'
          )
    """)

    cursor.execute("""
        UPDATE jobs
        SET link_status = 'working',
            last_link_checked_at = COALESCE(
                last_link_checked_at,
                last_verified_at
            )
        WHERE employer_id IS NULL
          AND verification_status = 'verified'
          AND source_url IS NOT NULL
          AND link_status IS NULL
    """)

    cursor.execute("""
        UPDATE jobs
        SET link_status = 'unavailable',
            last_link_checked_at = COALESCE(
                last_link_checked_at,
                updated_at
            )
        WHERE employer_id IS NULL
          AND verification_status IN ('expired', 'removed')
          AND link_status IS NULL
    """)

    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS
        idx_jobs_source_external_job_id
        ON jobs(source, external_job_id)
        WHERE source IS NOT NULL
          AND external_job_id IS NOT NULL
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_jobs_verification_status
        ON jobs(verification_status)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_jobs_link_status
        ON jobs(link_status)
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
           OR role NOT IN ('job_seeker', 'employer', 'admin')
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

    if not column_exists(cursor, "company_profiles", "contact_email"):
        cursor.execute("ALTER TABLE company_profiles ADD COLUMN contact_email TEXT")
    if not column_exists(cursor, "company_profiles", "verification_status"):
        cursor.execute(
            "ALTER TABLE company_profiles ADD COLUMN verification_status TEXT NOT NULL DEFAULT 'unverified'"
        )

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
        CREATE TABLE IF NOT EXISTS user_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            expires_at TEXT NOT NULL,
            user_agent TEXT,
            sensitive_verified_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    if not column_exists(cursor, "user_sessions", "sensitive_verified_at"):
        cursor.execute("ALTER TABLE user_sessions ADD COLUMN sensitive_verified_at TEXT")

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_sessions_user_id
        ON user_sessions(user_id, expires_at)
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS security_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            event_summary TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS privacy_settings (
            user_id INTEGER PRIMARY KEY,
            allow_personalized_guidance INTEGER NOT NULL DEFAULT 1,
            allow_employer_discovery INTEGER NOT NULL DEFAULT 0,
            security_notifications INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    # Adds structured job preferences without replacing legacy profile data.
    profile_preference_columns = {
        "career_stage": "TEXT",
        "maximum_commute_distance": "INTEGER",
        "maximum_commute_time": "INTEGER",
        "pay_period": "TEXT",
        "minimum_base_pay": "REAL"
    }

    for column_name, column_type in profile_preference_columns.items():
        if not column_exists(cursor, "user_profiles", column_name):
            cursor.execute(
                f"""
                ALTER TABLE user_profiles
                ADD COLUMN {column_name} {column_type}
                """
            )

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS learning_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            lesson_id TEXT NOT NULL,

            is_completed INTEGER NOT NULL DEFAULT 0
                CHECK (is_completed IN (0, 1)),

            last_opened_at TEXT,
            completed_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (user_id)
                REFERENCES users(id)
                ON DELETE CASCADE,

            UNIQUE (user_id, lesson_id)
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_learning_progress_user_id
        ON learning_progress(user_id)
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
        CREATE TABLE IF NOT EXISTS saved_searches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            keyword TEXT NOT NULL DEFAULT '',
            location TEXT NOT NULL DEFAULT '',
            location_scope TEXT NOT NULL DEFAULT 'us'
                CHECK (location_scope IN ('us', 'all')),
            category TEXT NOT NULL DEFAULT 'all',
            employment_type TEXT NOT NULL DEFAULT 'all',
            remote_filter TEXT NOT NULL DEFAULT 'all'
                CHECK (remote_filter IN ('all', 'remote', 'hybrid', 'onsite')),
            experience TEXT NOT NULL DEFAULT 'all',
            location_mode TEXT NOT NULL DEFAULT 'nearby'
                CHECK (location_mode IN ('nearby', 'exact')),
            remote_eligibility TEXT NOT NULL DEFAULT 'all'
                CHECK (remote_eligibility IN ('all', 'us', 'anywhere')),
            age_fit TEXT NOT NULL DEFAULT 'all',
            date_posted TEXT NOT NULL DEFAULT 'all',
            listing_quality TEXT NOT NULL DEFAULT 'all',
            application_feature TEXT NOT NULL DEFAULT 'all',
            minimum_pay REAL NOT NULL DEFAULT 0,
            exclusions TEXT NOT NULL DEFAULT '',
            exclude_terms TEXT NOT NULL DEFAULT '',
            frequency TEXT NOT NULL DEFAULT 'daily'
                CHECK (frequency IN ('daily', 'weekly')),
            is_enabled INTEGER NOT NULL DEFAULT 1
                CHECK (is_enabled IN (0, 1)),
            baseline_job_id INTEGER NOT NULL DEFAULT 0,
            last_checked_at TEXT,
            next_check_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (user_id)
                REFERENCES users(id)
                ON DELETE CASCADE
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_saved_searches_user_id
        ON saved_searches(user_id)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_saved_searches_next_check
        ON saved_searches(is_enabled, next_check_at)
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS job_change_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            field_name TEXT NOT NULL,
            old_value TEXT,
            new_value TEXT,
            change_source TEXT NOT NULL,
            changed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_job_change_history_job
        ON job_change_history(job_id, changed_at DESC, id DESC)
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS saved_search_matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            saved_search_id INTEGER NOT NULL,
            job_id INTEGER NOT NULL,
            first_matched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            seen_at TEXT,

            FOREIGN KEY (saved_search_id)
                REFERENCES saved_searches(id)
                ON DELETE CASCADE,

            FOREIGN KEY (job_id)
                REFERENCES jobs(id)
                ON DELETE CASCADE,

            UNIQUE (saved_search_id, job_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS job_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            job_id INTEGER NOT NULL,
            reason TEXT NOT NULL
                CHECK (
                    reason IN (
                        'suspected_scam',
                        'misleading_information',
                        'expired_or_broken_link',
                        'discriminatory_content',
                        'duplicate_listing',
                        'other'
                    )
                ),
            details TEXT,
            status TEXT NOT NULL DEFAULT 'submitted'
                CHECK (status IN ('submitted', 'reviewed', 'resolved')),
            moderator_user_id INTEGER,
            moderation_note TEXT,
            reviewed_at TEXT,
            resolved_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (user_id)
                REFERENCES users(id)
                ON DELETE CASCADE,

            FOREIGN KEY (job_id)
                REFERENCES jobs(id)
                ON DELETE CASCADE,

            FOREIGN KEY (moderator_user_id)
                REFERENCES users(id)
                ON DELETE SET NULL,

            UNIQUE (user_id, job_id)
        )
    """)

    report_audit_columns = {
        "moderator_user_id": "INTEGER",
        "moderation_note": "TEXT",
        "reviewed_at": "TEXT",
        "resolved_at": "TEXT"
    }
    for column_name, column_type in report_audit_columns.items():
        if not column_exists(cursor, "job_reports", column_name):
            cursor.execute(
                f"ALTER TABLE job_reports "
                f"ADD COLUMN {column_name} {column_type}"
            )

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_job_reports_job_status
        ON job_reports(job_id, status)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_job_reports_status_created
        ON job_reports(status, created_at)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_saved_search_matches_search_seen
        ON saved_search_matches(saved_search_id, seen_at)
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            notification_type TEXT NOT NULL CHECK (
                notification_type IN (
                    'job_match', 'application_update', 'interview',
                    'follow_up', 'deadline', 'account'
                )
            ),
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            href TEXT NOT NULL,
            event_key TEXT NOT NULL,
            is_read INTEGER NOT NULL DEFAULT 0 CHECK (is_read IN (0, 1)),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            read_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            UNIQUE (user_id, event_key)
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_notifications_user_read_created
        ON notifications(user_id, is_read, created_at)
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

    if not column_exists(cursor, "users", "email_verified"):
        cursor.execute("""
            ALTER TABLE users
            ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 0
        """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS account_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            purpose TEXT NOT NULL CHECK (purpose IN ('email_verification', 'password_reset', 'sensitive_action')),
            token_hash TEXT NOT NULL UNIQUE,
            expires_at TEXT NOT NULL,
            used_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    # Databases created before sensitive-action verification need their table
    # constraint expanded. SQLite cannot alter a CHECK constraint in place, so
    # rebuild only this table and preserve every existing token.
    account_tokens_schema = cursor.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'account_tokens'"
    ).fetchone()[0]
    if "sensitive_action" not in account_tokens_schema:
        cursor.execute("ALTER TABLE account_tokens RENAME TO account_tokens_legacy")
        cursor.execute("""
            CREATE TABLE account_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                purpose TEXT NOT NULL CHECK (
                    purpose IN ('email_verification', 'password_reset', 'sensitive_action')
                ),
                token_hash TEXT NOT NULL UNIQUE,
                expires_at TEXT NOT NULL,
                used_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)
        cursor.execute("""
            INSERT INTO account_tokens (
                id, user_id, purpose, token_hash, expires_at, used_at, created_at
            )
            SELECT id, user_id, purpose, token_hash, expires_at, used_at, created_at
            FROM account_tokens_legacy
        """)
        cursor.execute("DROP TABLE account_tokens_legacy")

    # Authentication throttling is stored in SQLite so protection survives a
    # server restart and remains shared by every request handled by this app.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS auth_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            subject_hash TEXT NOT NULL,
            ip_hash TEXT NOT NULL,
            succeeded INTEGER NOT NULL DEFAULT 0
                CHECK (succeeded IN (0, 1)),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_auth_attempts_lookup
        ON auth_attempts(action, subject_hash, ip_hash, created_at)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_auth_attempts_ip
        ON auth_attempts(action, ip_hash, created_at)
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS message_conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            application_id INTEGER NOT NULL UNIQUE,
            applicant_id INTEGER NOT NULL,
            employer_id INTEGER NOT NULL,
            applicant_blocked INTEGER NOT NULL DEFAULT 0 CHECK (applicant_blocked IN (0, 1)),
            employer_blocked INTEGER NOT NULL DEFAULT 0 CHECK (employer_blocked IN (0, 1)),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE CASCADE,
            FOREIGN KEY (applicant_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (employer_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS direct_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            sender_id INTEGER NOT NULL,
            body TEXT NOT NULL,
            is_read INTEGER NOT NULL DEFAULT 0 CHECK (is_read IN (0, 1)),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (conversation_id) REFERENCES message_conversations(id) ON DELETE CASCADE,
            FOREIGN KEY (sender_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS message_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER NOT NULL,
            reporter_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (message_id, reporter_id),
            FOREIGN KEY (message_id) REFERENCES direct_messages(id) ON DELETE CASCADE,
            FOREIGN KEY (reporter_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_direct_messages_conversation
        ON direct_messages(conversation_id, created_at, id)
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS application_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            application_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            field_name TEXT,
            old_value TEXT,
            new_value TEXT,
            changed_by_type TEXT NOT NULL
                CHECK (
                    changed_by_type IN (
                        'user',
                        'employer',
                        'system'
                    )
                ),
            changed_by_user_id INTEGER,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (application_id)
                REFERENCES applications(id)
                ON DELETE CASCADE,

            FOREIGN KEY (changed_by_user_id)
                REFERENCES users(id)
                ON DELETE SET NULL
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_application_history_application_id
        ON application_history(application_id, created_at DESC)
    """)

    cursor.execute("""
        INSERT INTO application_history (
            application_id,
            event_type,
            field_name,
            old_value,
            new_value,
            changed_by_type,
            changed_by_user_id,
            created_at
        )
        SELECT
            applications.id,
            'application_created',
            'status',
            NULL,
            applications.status,
            'user',
            applications.user_id,
            applications.created_at
        FROM applications
        WHERE NOT EXISTS (
            SELECT 1
            FROM application_history
            WHERE application_history.application_id = applications.id
        )
    """)

    cursor.execute("""
        UPDATE application_history
        SET new_value = 'Applied'
        WHERE event_type = 'application_created'
          AND application_id IN (
              SELECT applications.id
              FROM applications
              JOIN jobs
                  ON jobs.id = applications.job_id
              WHERE applications.application_method = 'pathforge'
                AND jobs.employer_id IS NOT NULL
          )
    """)

    cursor.execute("""
        INSERT INTO application_history (
            application_id,
            event_type,
            field_name,
            old_value,
            new_value,
            changed_by_type,
            changed_by_user_id,
            created_at
        )
        SELECT
            applications.id,
            'status_changed',
            'status',
            'Applied',
            applications.status,
            'employer',
            jobs.employer_id,
            applications.updated_at
        FROM applications
        JOIN jobs
            ON jobs.id = applications.job_id
        WHERE applications.application_method = 'pathforge'
          AND jobs.employer_id IS NOT NULL
          AND applications.status != 'Applied'
          AND NOT EXISTS (
              SELECT 1
              FROM application_history
              WHERE application_history.application_id = applications.id
                AND application_history.event_type = 'status_changed'
          )
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


def populate_jobs(db_name=DB_NAME):
    conn = get_connection(db_name)
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
                    application_url,
                    status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                job.get("application_url"),
                # Bundled records demonstrate the UI, but are not verified
                # vacancies and must never appear in the public catalog.
                "closed"
            ))

        print("Jobs inserted successfully.")
    else:
        print("Database already contains jobs.")

    conn.commit()
    conn.close()


def create_public_job_indexes(db_name=DB_NAME):
    """Add indexes used by public discovery, company pages, and expiry checks."""
    conn = get_connection(db_name)
    try:
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_jobs_public_catalog
            ON jobs(status, owner_user_id, verification_status, application_method, id DESC)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_jobs_public_dates
            ON jobs(status, application_deadline, expires_at)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_jobs_company_public
            ON jobs(company COLLATE NOCASE, status, owner_user_id)
        """)
        conn.commit()
    finally:
        conn.close()


def close_bundled_sample_jobs(db_name=DB_NAME):
    """Keep UI-only seed records out of the public vacancy catalog."""
    sample_jobs = (
        ("Crew Member", "Taco Bell", "Saratoga Springs, UT"),
        ("Team Member", "Chick-fil-A", "Lehi, UT"),
        ("Cashier", "Target", "American Fork, UT"),
        ("Warehouse Associate", "Amazon", "Lehi, UT"),
    )
    conn = get_connection(db_name)
    try:
        conn.executemany(
            """UPDATE jobs
               SET status = 'closed', updated_at = CURRENT_TIMESTAMP
               WHERE title = ? AND company = ? AND location = ?
                 AND status = 'active'
                 AND owner_user_id IS NULL
                 AND source IS NULL
                 AND source_url IS NULL
                 AND application_url IS NULL""",
            sample_jobs,
        )
        conn.commit()
    finally:
        conn.close()


def add_saved_search_parity_and_job_history(db_name=DB_NAME):
    """Preserve old alerts while expanding them to the full discovery filter set."""
    conn = get_connection(db_name)
    conn.row_factory = sqlite3.Row
    try:
        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(saved_searches)")
        }
        required = {
            "location_mode", "remote_eligibility", "age_fit", "date_posted",
            "listing_quality", "minimum_pay", "exclusions", "exclude_terms",
        }
        table_sql_row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'saved_searches'"
        ).fetchone()
        supports_hybrid = bool(table_sql_row and "'hybrid'" in table_sql_row["sql"])

        if required - columns or not supports_hybrid:
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute("ALTER TABLE saved_searches RENAME TO saved_searches_legacy")
            conn.execute("""
                CREATE TABLE saved_searches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    keyword TEXT NOT NULL DEFAULT '',
                    location TEXT NOT NULL DEFAULT '',
                    location_scope TEXT NOT NULL DEFAULT 'us' CHECK (location_scope IN ('us', 'all')),
                    category TEXT NOT NULL DEFAULT 'all',
                    employment_type TEXT NOT NULL DEFAULT 'all',
                    remote_filter TEXT NOT NULL DEFAULT 'all' CHECK (remote_filter IN ('all', 'remote', 'hybrid', 'onsite')),
                    experience TEXT NOT NULL DEFAULT 'all',
                    location_mode TEXT NOT NULL DEFAULT 'nearby' CHECK (location_mode IN ('nearby', 'exact')),
                    remote_eligibility TEXT NOT NULL DEFAULT 'all' CHECK (remote_eligibility IN ('all', 'us', 'anywhere')),
                    age_fit TEXT NOT NULL DEFAULT 'all',
                    date_posted TEXT NOT NULL DEFAULT 'all',
                    listing_quality TEXT NOT NULL DEFAULT 'all',
                    minimum_pay REAL NOT NULL DEFAULT 0,
                    exclusions TEXT NOT NULL DEFAULT '',
                    exclude_terms TEXT NOT NULL DEFAULT '',
                    frequency TEXT NOT NULL DEFAULT 'daily' CHECK (frequency IN ('daily', 'weekly')),
                    is_enabled INTEGER NOT NULL DEFAULT 1 CHECK (is_enabled IN (0, 1)),
                    baseline_job_id INTEGER NOT NULL DEFAULT 0,
                    last_checked_at TEXT,
                    next_check_at TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
            """)
            legacy_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(saved_searches_legacy)")
            }
            target_columns = [
                "id", "user_id", "name", "keyword", "location", "location_scope",
                "category", "employment_type", "remote_filter", "experience",
                "location_mode", "remote_eligibility", "age_fit", "date_posted",
                "listing_quality", "minimum_pay", "exclusions", "exclude_terms",
                "frequency", "is_enabled", "baseline_job_id", "last_checked_at",
                "next_check_at", "created_at", "updated_at",
            ]
            copy_columns = [column for column in target_columns if column in legacy_columns]
            column_list = ", ".join(copy_columns)
            conn.execute(
                f"INSERT INTO saved_searches ({column_list}) SELECT {column_list} FROM saved_searches_legacy"
            )
            # SQLite rewrites dependent foreign-key definitions during a table
            # rename. Restore the match table so it points at the current name.
            conn.execute("ALTER TABLE saved_search_matches RENAME TO saved_search_matches_legacy")
            conn.execute("""
                CREATE TABLE saved_search_matches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    saved_search_id INTEGER NOT NULL,
                    job_id INTEGER NOT NULL,
                    first_matched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    seen_at TEXT,
                    FOREIGN KEY (saved_search_id) REFERENCES saved_searches(id) ON DELETE CASCADE,
                    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE,
                    UNIQUE (saved_search_id, job_id)
                )
            """)
            conn.execute("""INSERT INTO saved_search_matches
                            (id, saved_search_id, job_id, first_matched_at, seen_at)
                            SELECT id, saved_search_id, job_id, first_matched_at, seen_at
                            FROM saved_search_matches_legacy""")
            conn.execute("DROP TABLE saved_search_matches_legacy")
            conn.execute("DROP TABLE saved_searches_legacy")
            conn.execute("""CREATE INDEX IF NOT EXISTS idx_saved_searches_user_id
                            ON saved_searches(user_id)""")
            conn.execute("""CREATE INDEX IF NOT EXISTS idx_saved_searches_next_check
                            ON saved_searches(is_enabled, next_check_at)""")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS job_change_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                field_name TEXT NOT NULL,
                old_value TEXT,
                new_value TEXT,
                change_source TEXT NOT NULL,
                changed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
            )
        """)
        conn.execute("""CREATE INDEX IF NOT EXISTS idx_job_change_history_job
                        ON job_change_history(job_id, changed_at DESC, id DESC)""")
        conn.execute("""CREATE INDEX IF NOT EXISTS idx_job_change_history_time
                        ON job_change_history(changed_at DESC)""")
        conn.commit()
    finally:
        conn.close()


def repair_application_history_integrity(db_name=DB_NAME):
    """Remove history whose parent application was already deleted."""
    conn = get_connection(db_name)
    try:
        conn.execute("""
            DELETE FROM application_history
            WHERE NOT EXISTS (
                SELECT 1 FROM applications
                WHERE applications.id = application_history.application_id
            )
        """)
        conn.commit()
    finally:
        conn.close()


def add_saved_search_application_feature(db_name=DB_NAME):
    """Keep application-convenience filters in saved searches and alerts."""
    conn = get_connection(db_name)
    try:
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(saved_searches)")
        }
        if "application_feature" not in columns:
            conn.execute(
                "ALTER TABLE saved_searches "
                "ADD COLUMN application_feature TEXT NOT NULL DEFAULT 'all'"
            )
        conn.commit()
    finally:
        conn.close()


def add_catalog_sync_status(db_name=DB_NAME):
    """Track the most recent result for every configured catalog source."""
    conn = get_connection(db_name)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS catalog_sync_status (
                source TEXT NOT NULL,
                employer TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('ok', 'failed')),
                fetched INTEGER NOT NULL DEFAULT 0,
                imported INTEGER NOT NULL DEFAULT 0,
                excluded_by_country INTEGER NOT NULL DEFAULT 0,
                error TEXT,
                last_attempt_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (source, employer)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_catalog_sync_status_health
            ON catalog_sync_status(status, last_attempt_at DESC)
        """)
        conn.commit()
    finally:
        conn.close()


def add_catalog_sync_comparison(db_name=DB_NAME):
    """Retain prior imported counts so sharp source drops are visible."""
    conn = get_connection(db_name)
    try:
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(catalog_sync_status)")
        }
        if "previous_imported" not in columns:
            conn.execute(
                "ALTER TABLE catalog_sync_status ADD COLUMN previous_imported INTEGER"
            )
        conn.commit()
    finally:
        conn.close()


# Each migration has an immutable version and descriptive name. New schema
# changes belong in a new function and tuple entry instead of being silently
# added to application startup forever.
SCHEMA_MIGRATIONS = (
    (1, "baseline_pathforge_schema", create_jobs_table),
    (2, "public_job_catalog_indexes", create_public_job_indexes),
    (3, "saved_search_parity_and_job_history", add_saved_search_parity_and_job_history),
    (4, "repair_application_history_integrity", repair_application_history_integrity),
    (5, "saved_search_application_feature", add_saved_search_application_feature),
    (6, "catalog_sync_status", add_catalog_sync_status),
    (7, "catalog_sync_comparison", add_catalog_sync_comparison),
    (8, "close_bundled_sample_jobs", close_bundled_sample_jobs),
)


def initialize_database(db_name=DB_NAME):
    """Apply each pending schema migration once and record its completion."""
    migration_connection = get_connection(db_name)
    migration_connection.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    migration_connection.commit()
    applied_versions = {
        row[0]
        for row in migration_connection.execute(
            "SELECT version FROM schema_migrations"
        ).fetchall()
    }
    migration_connection.close()

    newly_applied = []
    for version, name, migration in SCHEMA_MIGRATIONS:
        if version in applied_versions:
            continue

        # The baseline builder is idempotent. A failed migration is deliberately
        # left unrecorded so the next run can retry after the cause is corrected.
        migration(db_name)
        migration_connection = get_connection(db_name)
        try:
            migration_connection.execute(
                "INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
                (version, name),
            )
            migration_connection.commit()
        finally:
            migration_connection.close()
        newly_applied.append(version)

    return newly_applied


if __name__ == "__main__":
    initialize_database()
    populate_jobs()
