PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    phone TEXT,
    sms_consent INTEGER NOT NULL DEFAULT 0 CHECK (sms_consent IN (0, 1)),
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('citizen', 'municipal', 'admin')),
    department TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS complaints (
    complaint_id TEXT PRIMARY KEY,
    citizen_id TEXT NOT NULL REFERENCES users(id),
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    description TEXT NOT NULL,
    image_path TEXT,
    location TEXT NOT NULL,
    latitude REAL,
    longitude REAL,
    assigned_department TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('Pending', 'In progress', 'Resolved')),
    priority TEXT NOT NULL DEFAULT 'Medium' CHECK (priority IN ('Low', 'Medium', 'High')),
    overdue INTEGER NOT NULL DEFAULT 0 CHECK (overdue IN (0, 1)),
    workflow_status TEXT CHECK (workflow_status IN ('Pending', 'Accepted', 'In progress', 'Completed')),
    assignment_review_required INTEGER NOT NULL DEFAULT 0 CHECK (assignment_review_required IN (0, 1)),
    review_reason TEXT,
    predicted_category TEXT,
    category_confidence REAL,
    classifier_model TEXT,
    predicted_priority TEXT,
    urgency_score REAL,
    dissatisfaction_score REAL,
    sentiment_score REAL,
    expected_completion_at TEXT,
    eta_method TEXT,
    accepted_by TEXT REFERENCES users(id),
    accepted_at TEXT,
    last_escalated_at TEXT,
    last_overdue_reminder_at TEXT,
    legacy_source_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_complaints_citizen_created
    ON complaints(citizen_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_complaints_status
    ON complaints(status);
CREATE INDEX IF NOT EXISTS idx_complaints_category
    ON complaints(category);
CREATE UNIQUE INDEX IF NOT EXISTS idx_complaints_legacy_source
    ON complaints(citizen_id, legacy_source_id)
    WHERE legacy_source_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS complaint_status_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_id TEXT NOT NULL REFERENCES complaints(complaint_id) ON DELETE CASCADE,
    changed_by TEXT NOT NULL REFERENCES users(id),
    old_status TEXT,
    new_status TEXT NOT NULL CHECK (new_status IN ('Pending', 'In progress', 'Resolved')),
    note TEXT,
    changed_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_status_history_complaint
    ON complaint_status_history(complaint_id, changed_at DESC);

CREATE TABLE IF NOT EXISTS complaint_department_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_id TEXT NOT NULL REFERENCES complaints(complaint_id) ON DELETE CASCADE,
    department TEXT NOT NULL,
    assigned_by TEXT REFERENCES users(id),
    assigned_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_department_history_complaint
    ON complaint_department_history(complaint_id, assigned_at DESC);

CREATE TABLE IF NOT EXISTS category_department_mappings (
    category TEXT PRIMARY KEY,
    department TEXT NOT NULL,
    verified INTEGER NOT NULL DEFAULT 1 CHECK (verified IN (0, 1)),
    updated_by TEXT REFERENCES users(id),
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS category_mapping_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    old_department TEXT,
    new_department TEXT NOT NULL,
    reason TEXT NOT NULL,
    changed_by TEXT NOT NULL REFERENCES users(id),
    changed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_category_mapping_history_category
    ON category_mapping_history(category, changed_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS verified_training_examples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    description TEXT NOT NULL,
    category TEXT NOT NULL,
    source_complaint_id TEXT UNIQUE REFERENCES complaints(complaint_id),
    verified_by TEXT NOT NULL REFERENCES users(id),
    verification_note TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_verified_training_category
    ON verified_training_examples(category, created_at DESC);

CREATE TABLE IF NOT EXISTS verified_training_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    example_id INTEGER,
    action TEXT NOT NULL CHECK (action IN ('added', 'updated', 'removed')),
    old_description TEXT,
    old_category TEXT,
    new_description TEXT,
    new_category TEXT,
    verification_note TEXT NOT NULL,
    changed_by TEXT NOT NULL REFERENCES users(id),
    changed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_verified_training_history_example
    ON verified_training_history(example_id, changed_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS ml_model_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    status TEXT NOT NULL CHECK (status IN ('insufficient_data', 'evaluated_advisory')),
    model_name TEXT NOT NULL,
    model_version INTEGER NOT NULL,
    sample_count INTEGER NOT NULL,
    category_counts TEXT NOT NULL,
    metrics TEXT NOT NULL,
    artifact TEXT,
    created_by TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ml_model_runs_created
    ON ml_model_runs(created_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS complaint_progress_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_id TEXT NOT NULL REFERENCES complaints(complaint_id) ON DELETE CASCADE,
    author_id TEXT NOT NULL REFERENCES users(id),
    note TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_progress_notes_complaint
    ON complaint_progress_notes(complaint_id, created_at DESC);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    complaint_id TEXT REFERENCES complaints(complaint_id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL,
    read_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_notifications_user_created
    ON notifications(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS notification_deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    complaint_id TEXT NOT NULL REFERENCES complaints(complaint_id) ON DELETE CASCADE,
    channel TEXT NOT NULL CHECK (channel IN ('sms', 'email')),
    event_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'sent', 'delivered', 'failed', 'skipped', 'not_configured')),
    message TEXT,
    progress_note TEXT,
    provider_response TEXT,
    failure_detail TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (complaint_id, channel, event_key)
);
CREATE INDEX IF NOT EXISTS idx_notification_deliveries_status
    ON notification_deliveries(status, created_at DESC);

CREATE TABLE IF NOT EXISTS complaint_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_id TEXT NOT NULL UNIQUE REFERENCES complaints(complaint_id) ON DELETE CASCADE,
    citizen_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS department_status_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_id TEXT NOT NULL REFERENCES complaints(complaint_id) ON DELETE CASCADE,
    changed_by TEXT NOT NULL REFERENCES users(id),
    old_status TEXT,
    new_status TEXT NOT NULL CHECK (new_status IN ('Pending', 'Accepted', 'In progress', 'Completed')),
    note TEXT,
    changed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_department_status_history_complaint
    ON department_status_history(complaint_id, changed_at DESC);
