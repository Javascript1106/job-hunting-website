"""Small, shared audit trail for material job-listing changes."""

TRACKED_JOB_FIELDS = {
    "title", "company", "location", "pay", "description", "requirements",
    "preferred_qualifications", "schedule", "experience", "category",
    "application_method", "application_url", "application_deadline", "status",
    "source_url", "expires_at", "employment_type", "is_remote", "salary_min",
    "salary_max", "salary_period", "verification_status", "link_status",
}


def _history_value(value):
    if value is None:
        return None
    return str(value)[:5000]


def record_job_changes(cursor, job_id, existing, updates, change_source):
    """Record changed tracked fields using the caller's current transaction."""
    existing_values = dict(existing)
    rows = []
    for field, new_value in updates.items():
        if field not in TRACKED_JOB_FIELDS:
            continue
        old_value = existing_values.get(field)
        if old_value == new_value:
            continue
        rows.append((job_id, field, _history_value(old_value), _history_value(new_value), change_source))
    if rows:
        cursor.executemany(
            """INSERT INTO job_change_history
               (job_id, field_name, old_value, new_value, change_source)
               VALUES (?, ?, ?, ?, ?)""",
            rows,
        )
    return len(rows)
