"""Deterministic, privacy-preserving automations for PathForge accounts and operations."""

import re
import sqlite3
from datetime import datetime, timezone

from database import DB_NAME, get_connection, initialize_database


TERMINAL_APPLICATION_STATUSES = ("Accepted", "Rejected", "Withdrawn")
SUSPICIOUS_TEXT = re.compile(
    r"\b(?:pay (?:a |the )?(?:fee|deposit)|buy (?:gift cards?|equipment)|"
    r"send (?:money|crypto)|(?:contact|message|reach) (?:us |the recruiter )?"
    r"(?:on|via|through) (?:telegram|whatsapp)|wire transfer|"
    r"(?:send|provide|share) (?:your )?(?:bank account (?:details|information)|"
    r"social security number))\b",
    re.IGNORECASE,
)


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _notify(cursor, user_id, kind, title, message, href, event_key):
    cursor.execute(
        """INSERT INTO notifications
           (user_id, notification_type, title, message, href, event_key)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(user_id, event_key) DO UPDATE SET
             title = excluded.title,
             message = excluded.message,
             href = excluded.href
           WHERE notifications.is_read = 0""",
        (user_id, kind, title[:160], message[:800], href[:500], event_key[:240]),
    )
    return cursor.rowcount


def ensure_preferences(cursor, user_id):
    cursor.execute(
        "INSERT OR IGNORE INTO automation_preferences (user_id) VALUES (?)",
        (user_id,),
    )
    return cursor.execute(
        "SELECT * FROM automation_preferences WHERE user_id = ?", (user_id,)
    ).fetchone()


def flag_listing(cursor, job_id, flag_type, severity, reason, event_key):
    cursor.execute(
        """INSERT INTO automation_review_flags
           (job_id, flag_type, severity, reason, event_key)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(event_key) DO UPDATE SET
             severity = excluded.severity,
             reason = excluded.reason,
             status = 'open',
             last_seen_at = CURRENT_TIMESTAMP,
             resolved_at = NULL""",
        (job_id, flag_type, severity, reason[:800], event_key),
    )


def scan_listing_risks(cursor):
    """Flag evidence for human review; never close or hide a listing."""
    seen = set()
    rows = cursor.execute(
        """SELECT jobs.id, jobs.title, jobs.company, jobs.description,
                  jobs.requirements, jobs.source,
                  jobs.posted_at, jobs.updated_at, jobs.last_verified_at,
                  jobs.link_status, jobs.application_deadline, jobs.expires_at,
                  CAST(julianday('now') - julianday(COALESCE(jobs.posted_at, jobs.updated_at))
                       AS INTEGER) AS listing_age_days,
                  CAST(julianday('now') - julianday(jobs.last_verified_at)
                       AS INTEGER) AS verification_age_days,
                  SUM(CASE WHEN reports.status != 'resolved'
                            AND reports.reason IN ('suspected_scam',
                                'misleading_information', 'expired_or_broken_link')
                           THEN 1 ELSE 0 END) AS report_count
           FROM jobs
           LEFT JOIN job_reports AS reports ON reports.job_id = jobs.id
           WHERE jobs.status = 'active' AND jobs.owner_user_id IS NULL"""
        + " GROUP BY jobs.id"
    ).fetchall()
    for row in rows:
        job_id = row["id"]
        content = " ".join(str(row[key] or "") for key in (
            "title", "company", "description", "requirements"
        ))
        if SUSPICIOUS_TEXT.search(content):
            key = f"suspicious-listing:{job_id}"
            seen.add(key)
            flag_listing(
                cursor, job_id, "suspicious_listing", "high",
                "The listing contains payment, off-platform messaging, or sensitive-data language that requires human review.",
                key,
            )
        if str(row["link_status"] or "").lower() == "unavailable":
            key = f"broken-link:{job_id}"
            seen.add(key)
            flag_listing(
                cursor, job_id, "broken_link", "high",
                "The official application link is currently marked unavailable.", key,
            )
        old_without_deadline = (
            (row["listing_age_days"] or 0) >= 120
            and (row["verification_age_days"] is None or row["verification_age_days"] >= 14)
            and not row["application_deadline"] and not row["expires_at"]
        )
        report_count = int(row["report_count"] or 0)
        if old_without_deadline or report_count:
            key = f"ghost-listing:{job_id}"
            seen.add(key)
            reasons = []
            if old_without_deadline:
                reasons.append("the posting is at least 120 days old, has no closing date, and has not been verified recently")
            if report_count:
                reasons.append(f"it has {report_count} unresolved user report(s)")
            flag_listing(
                cursor, job_id, "ghost_listing",
                "high" if report_count else "medium",
                "Possible ghost listing: " + " and ".join(reasons) + ". Confirm with the employer before changing its status.",
                key,
            )
    if seen:
        placeholders = ",".join("?" for _ in seen)
        cursor.execute(
            f"""UPDATE automation_review_flags
                SET status = 'resolved', resolved_at = CURRENT_TIMESTAMP
                WHERE status = 'open' AND event_key NOT IN ({placeholders})""",
            tuple(sorted(seen)),
        )
    else:
        cursor.execute(
            """UPDATE automation_review_flags
               SET status = 'resolved', resolved_at = CURRENT_TIMESTAMP
               WHERE status = 'open'"""
        )
    return cursor.execute(
        "SELECT COUNT(*) FROM automation_review_flags WHERE status = 'open'"
    ).fetchone()[0]


def create_employer_reminders(cursor):
    created = 0
    rows = cursor.execute(
        """SELECT applications.id, applications.status, applications.updated_at,
                  jobs.title, jobs.employer_id,
                  CAST(julianday('now') - julianday(applications.updated_at) AS INTEGER) AS age_days
           FROM applications JOIN jobs ON jobs.id = applications.job_id
           JOIN users ON users.id = jobs.employer_id AND users.role = 'employer'
           LEFT JOIN automation_preferences p ON p.user_id = jobs.employer_id
           WHERE applications.application_method = 'pathforge'
             AND applications.status IN ('Applied', 'Application Viewed', 'Under Review')
             AND datetime(applications.updated_at) <= datetime('now', '-2 days')
             AND COALESCE(p.employer_reminders, 1) = 1"""
    ).fetchall()
    for row in rows:
        checkpoint = 14 if row["age_days"] >= 14 else 7 if row["age_days"] >= 7 else 2
        created += _notify(
            cursor, row["employer_id"], "application_update",
            f"Candidate response reminder: {row['title']}",
            f"An application has remained {row['status']} for at least {checkpoint} days. Review it or update the candidate's status.",
            "employer.html", f"employer-response:{row['id']}:{checkpoint}",
        )
    return created


def create_employer_digest(cursor):
    """Summarize hiring work once per day without exposing applicant details."""
    created = 0
    rows = cursor.execute(
        """SELECT users.id,
                  SUM(CASE WHEN applications.created_at >= datetime('now', '-1 day')
                           THEN 1 ELSE 0 END) AS new_applications,
                  SUM(CASE WHEN applications.status IN ('Applied', 'Application Viewed', 'Under Review')
                            AND applications.updated_at <= datetime('now', '-2 days')
                           THEN 1 ELSE 0 END) AS awaiting_response
           FROM users
           LEFT JOIN jobs ON jobs.employer_id = users.id
           LEFT JOIN applications ON applications.job_id = jobs.id
           LEFT JOIN automation_preferences p ON p.user_id = users.id
           WHERE users.role = 'employer' AND COALESCE(p.employer_reminders, 1) = 1
           GROUP BY users.id"""
    ).fetchall()
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for row in rows:
        new_count = int(row["new_applications"] or 0)
        waiting = int(row["awaiting_response"] or 0)
        if not (new_count or waiting):
            continue
        created += _notify(
            cursor, row["id"], "application_update", "Daily hiring summary",
            f"New applications in 24 hours: {new_count}. Applications awaiting a response: {waiting}.",
            "employer.html", f"employer-digest:{day}",
        )
    return created


def create_archive_suggestions(cursor):
    created = 0
    users = cursor.execute(
        "SELECT id FROM users WHERE role = 'job_seeker'"
    ).fetchall()
    for user in users:
        preference = ensure_preferences(cursor, user["id"])
        days = int(preference["archive_suggestion_days"])
        if days <= 0:
            continue
        count = cursor.execute(
            """SELECT COUNT(*) FROM saved_jobs JOIN jobs ON jobs.id = saved_jobs.job_id
               WHERE saved_jobs.user_id = ?
                 AND datetime(saved_jobs.saved_at) <= datetime('now', ?)
                 AND (jobs.status != 'active' OR datetime(saved_jobs.saved_at) <= datetime('now', ?))""",
            (user["id"], f"-{days} days", f"-{days * 2} days"),
        ).fetchone()[0]
        if count:
            month = datetime.now(timezone.utc).strftime("%Y-%m")
            created += _notify(
                cursor, user["id"], "account", "Review older saved jobs",
                f"You have {count} older or closed saved job(s). Review them and archive or remove only the ones you no longer need.",
                "saved-jobs.html", f"archive-suggestion:{month}",
            )
    return created


def create_admin_alerts(cursor, open_flags):
    admins = cursor.execute("SELECT id FROM users WHERE role = 'admin'").fetchall()
    if not admins:
        return 0
    failed_sources = cursor.execute(
        "SELECT COUNT(*) FROM catalog_sync_status WHERE status = 'failed'"
    ).fetchone()[0]
    pending_reports = cursor.execute(
        "SELECT COUNT(*) FROM job_reports WHERE status = 'submitted'"
    ).fetchone()[0]
    failed_logins = cursor.execute(
        """SELECT COUNT(*) FROM auth_attempts
           WHERE action = 'login' AND succeeded = 0
             AND created_at >= datetime('now', '-24 hours')"""
    ).fetchone()[0]
    quality_gaps = cursor.execute(
        """SELECT COUNT(*) FROM jobs WHERE status = 'active' AND owner_user_id IS NULL
           AND ((salary_min IS NULL) + (trim(COALESCE(requirements, '')) = '')
                + (application_deadline IS NULL)) >= 2"""
    ).fetchone()[0]
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    created = 0
    for admin in admins:
        if failed_sources or open_flags or pending_reports or failed_logins >= 10:
            created += _notify(
                cursor, admin["id"], "account", "PathForge operations need review",
                f"Failed sources: {failed_sources}. Open listing flags: {open_flags}. Pending reports: {pending_reports}. Failed logins in 24 hours: {failed_logins}.",
                "admin-moderation.html", f"admin-operations:{day}",
            )
        if quality_gaps:
            created += _notify(
                cursor, admin["id"], "account", "Listing-quality review queue",
                f"{quality_gaps} active listings are missing pay, requirements, or a deadline. Prioritize high-traffic and teen-friendly listings first.",
                "admin-moderation.html#qualityReviewQueue", f"quality-review:{day}",
            )
    return created


def run_platform_automations(database_path=DB_NAME):
    initialize_database(database_path)
    connection = get_connection(database_path)
    connection.row_factory = sqlite3.Row
    try:
        cursor = connection.cursor()
        flags = scan_listing_risks(cursor)
        employer = create_employer_reminders(cursor)
        employer_digest = create_employer_digest(cursor)
        archive = create_archive_suggestions(cursor)
        admin = create_admin_alerts(cursor, flags)
        connection.commit()
        return {
            "status": "success",
            "generated_at": _utc_now(),
            "open_review_flags": flags,
            "employer_reminders_created": employer,
            "employer_digests_created": employer_digest,
            "archive_suggestions_created": archive,
            "admin_alerts_created": admin,
        }
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
