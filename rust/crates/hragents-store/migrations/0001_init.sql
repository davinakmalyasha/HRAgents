-- HRAgents Desktop schema v1.
-- One company per database. No tenant_id, no RLS, no Postgres-specific types.
-- Instants are epoch milliseconds (INTEGER); civil dates are ISO-8601 TEXT.
-- Money is integer sen (1/100 IDR); floats never store a monetary amount.

PRAGMA foreign_keys = ON;

CREATE TABLE schema_migrations (
    version    INTEGER PRIMARY KEY,
    applied_at INTEGER NOT NULL
) STRICT;

CREATE TABLE company (
    id            TEXT PRIMARY KEY,
    legal_name    TEXT NOT NULL,
    npwp          TEXT,
    address       TEXT,
    timezone      TEXT NOT NULL DEFAULT 'Asia/Jakarta',
    currency      TEXT NOT NULL DEFAULT 'IDR',
    created_at    INTEGER NOT NULL
) STRICT;

CREATE TABLE operator (
    id            TEXT PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE,
    display_name  TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'hr_operator' CHECK (role = 'hr_operator'),
    active        INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    created_at    INTEGER NOT NULL
) STRICT;

CREATE TABLE settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL CHECK (json_valid(value)),
    updated_at INTEGER NOT NULL
) STRICT;

CREATE TABLE audit_log (
    seq          INTEGER PRIMARY KEY,
    entry_id     TEXT NOT NULL UNIQUE,
    created_at   INTEGER NOT NULL,
    actor_json   TEXT NOT NULL CHECK (json_valid(actor_json)),
    action       TEXT NOT NULL,
    subject_type TEXT NOT NULL,
    subject_id   TEXT NOT NULL,
    payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
    prev_hash    TEXT,
    entry_hash   TEXT NOT NULL
) STRICT;

CREATE TABLE employees (
    id                        TEXT PRIMARY KEY,
    employee_no               TEXT NOT NULL UNIQUE,
    full_name                 TEXT NOT NULL,
    preferred_name            TEXT,
    email                     TEXT,
    phone                     TEXT,
    job_title                 TEXT NOT NULL,
    org_unit                  TEXT NOT NULL,
    manager_id                TEXT REFERENCES employees(id),
    status                    TEXT NOT NULL CHECK (status IN ('active','probation','notice','exited')),
    hire_date                 TEXT NOT NULL,
    end_date                  TEXT,
    birth_date                TEXT,
    ptkp_status               TEXT,
    dependents                INTEGER NOT NULL DEFAULT 0 CHECK (dependents BETWEEN 0 AND 10),
    jkk_risk_class            INTEGER CHECK (jkk_risk_class BETWEEN 1 AND 5),
    npwp                      TEXT,
    bank_name                 TEXT,
    bank_account              TEXT,
    bpjs_kesehatan_no         TEXT,
    bpjs_ketenagakerjaan_no   TEXT,
    created_at                INTEGER NOT NULL,
    updated_at                INTEGER NOT NULL,
    version                   INTEGER NOT NULL DEFAULT 1
) STRICT;

CREATE INDEX employees_status_idx ON employees(status);
CREATE INDEX employees_org_unit_idx ON employees(org_unit);
CREATE INDEX employees_manager_idx ON employees(manager_id);

CREATE TABLE contracts (
    id          TEXT PRIMARY KEY,
    employee_id TEXT NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL CHECK (kind IN ('permanent','fixed_term','probation','intern')),
    start_date  TEXT NOT NULL,
    end_date    TEXT,
    status      TEXT NOT NULL CHECK (status IN ('draft','active','expired','terminated')),
    document_id TEXT,
    created_at  INTEGER NOT NULL
) STRICT;

CREATE INDEX contracts_employee_idx ON contracts(employee_id);
CREATE INDEX contracts_end_date_idx ON contracts(end_date);

CREATE TABLE documents (
    id               TEXT PRIMARY KEY,
    owner_type       TEXT NOT NULL CHECK (owner_type IN ('employee','candidate','company','payroll_run')),
    owner_id         TEXT NOT NULL,
    filename         TEXT NOT NULL,
    mime_type        TEXT NOT NULL,
    sha256           TEXT NOT NULL,
    size_bytes       INTEGER NOT NULL,
    storage_path     TEXT NOT NULL,
    status           TEXT NOT NULL CHECK (status IN ('pending','verified','rejected','expired')),
    expires_on       TEXT,
    uploaded_at      INTEGER NOT NULL,
    verified_at      INTEGER,
    verified_by      TEXT,
    rejection_reason TEXT,
    tags_json        TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(tags_json))
) STRICT;

CREATE INDEX documents_owner_idx ON documents(owner_type, owner_id);
CREATE INDEX documents_expiry_idx ON documents(expires_on);

CREATE TABLE document_requests (
    id             TEXT PRIMARY KEY,
    employee_id    TEXT NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    document_type  TEXT NOT NULL,
    status         TEXT NOT NULL CHECK (status IN ('requested','uploaded','verified','rejected','cancelled')),
    requested_at   INTEGER NOT NULL,
    due_on         TEXT,
    document_id    TEXT REFERENCES documents(id),
    note           TEXT
) STRICT;

CREATE TABLE onboarding_plans (
    id            TEXT PRIMARY KEY,
    employee_id   TEXT NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    template_name TEXT NOT NULL,
    status        TEXT NOT NULL CHECK (status IN ('draft','in_progress','completed','cancelled')),
    created_at    INTEGER NOT NULL,
    completed_at  INTEGER
) STRICT;

CREATE INDEX onboarding_plans_employee_idx ON onboarding_plans(employee_id);

CREATE TABLE onboarding_steps (
    plan_id              TEXT NOT NULL REFERENCES onboarding_plans(id) ON DELETE CASCADE,
    step_key             TEXT NOT NULL,
    title                TEXT NOT NULL,
    category             TEXT NOT NULL,
    required             INTEGER NOT NULL DEFAULT 1 CHECK (required IN (0,1)),
    status               TEXT NOT NULL CHECK (status IN ('pending','in_progress','done','skipped')),
    due_date             TEXT,
    completed_at         INTEGER,
    completed_by         TEXT,
    document_request_id  TEXT,
    notes                TEXT,
    position             INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (plan_id, step_key)
) STRICT;

CREATE TABLE jobs (
    id              TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    org_unit        TEXT NOT NULL,
    location        TEXT NOT NULL,
    employment_type TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('draft','open','paused','closed')),
    openings        INTEGER NOT NULL DEFAULT 1,
    rubric_json     TEXT CHECK (rubric_json IS NULL OR json_valid(rubric_json)),
    created_at      INTEGER NOT NULL
) STRICT;

CREATE TABLE candidates (
    id         TEXT PRIMARY KEY,
    full_name  TEXT NOT NULL,
    email      TEXT,
    phone      TEXT,
    source     TEXT NOT NULL,
    headline   TEXT,
    location   TEXT,
    consent    TEXT NOT NULL CHECK (consent IN ('pending','granted','withdrawn','expired')),
    created_at INTEGER NOT NULL
) STRICT;

CREATE INDEX candidates_consent_idx ON candidates(consent);

CREATE TABLE candidate_documents (
    candidate_id TEXT NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    document_id  TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    PRIMARY KEY (candidate_id, document_id)
) STRICT;

CREATE TABLE applications (
    id               TEXT PRIMARY KEY,
    candidate_id     TEXT NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    job_id           TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    stage            TEXT NOT NULL CHECK (stage IN ('imported','screening','review','interview','offer','hired','rejected','withdrawn')),
    priority         INTEGER NOT NULL DEFAULT 0,
    created_at       INTEGER NOT NULL,
    updated_at       INTEGER NOT NULL,
    rejection_reason TEXT,
    rejected_by      TEXT
) STRICT;

CREATE INDEX applications_job_stage_idx ON applications(job_id, stage);
CREATE INDEX applications_candidate_idx ON applications(candidate_id);

CREATE TABLE evaluations (
    id                    TEXT PRIMARY KEY,
    application_id        TEXT NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    rubric_id             TEXT NOT NULL,
    dimension_scores_json TEXT NOT NULL CHECK (json_valid(dimension_scores_json)),
    overall_bp            INTEGER NOT NULL,
    sigma_bp              INTEGER NOT NULL,
    runs                  INTEGER NOT NULL,
    evidence_json         TEXT NOT NULL CHECK (json_valid(evidence_json)),
    flags_json            TEXT NOT NULL CHECK (json_valid(flags_json)),
    created_at            INTEGER NOT NULL
) STRICT;

CREATE INDEX evaluations_application_idx ON evaluations(application_id);

CREATE TABLE evaluation_overrides (
    id             TEXT PRIMARY KEY,
    evaluation_id  TEXT NOT NULL REFERENCES evaluations(id) ON DELETE CASCADE,
    operator_id    TEXT NOT NULL,
    previous_bp    INTEGER NOT NULL,
    override_bp    INTEGER NOT NULL,
    reason         TEXT NOT NULL,
    created_at     INTEGER NOT NULL
) STRICT;

CREATE TABLE offers (
    id           TEXT PRIMARY KEY,
    application_id TEXT NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    status       TEXT NOT NULL CHECK (status IN ('draft','approved','sent','accepted','declined','expired')),
    salary_sen   INTEGER,
    start_date   TEXT,
    expires_on   TEXT,
    created_at   INTEGER NOT NULL,
    decided_at   INTEGER
) STRICT;

CREATE TABLE candidate_communications (
    id             TEXT PRIMARY KEY,
    candidate_id   TEXT NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    application_id TEXT REFERENCES applications(id) ON DELETE SET NULL,
    channel        TEXT NOT NULL CHECK (channel IN ('email','whatsapp','phone','note')),
    direction      TEXT NOT NULL CHECK (direction IN ('outbound','inbound')),
    subject        TEXT,
    body           TEXT NOT NULL,
    status         TEXT NOT NULL,
    created_at     INTEGER NOT NULL
) STRICT;

CREATE TABLE schedule_proposals (
    id             TEXT PRIMARY KEY,
    application_id TEXT NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    slots_json     TEXT NOT NULL CHECK (json_valid(slots_json)),
    status         TEXT NOT NULL CHECK (status IN ('proposed','confirmed','declined','expired')),
    created_at     INTEGER NOT NULL
) STRICT;

CREATE TABLE feedback_reports (
    id             TEXT PRIMARY KEY,
    application_id TEXT NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    body           TEXT NOT NULL,
    created_at     INTEGER NOT NULL
) STRICT;

CREATE TABLE leave_types (
    id                  TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    annual_quota_x2     INTEGER NOT NULL,
    carry_over_max_x2   INTEGER NOT NULL DEFAULT 0,
    requires_attachment INTEGER NOT NULL DEFAULT 0 CHECK (requires_attachment IN (0,1)),
    active              INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1))
) STRICT;

CREATE TABLE leave_balances (
    employee_id   TEXT NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    leave_type_id TEXT NOT NULL REFERENCES leave_types(id) ON DELETE CASCADE,
    year          INTEGER NOT NULL,
    entitled_x2   INTEGER NOT NULL,
    adjustment_x2 INTEGER NOT NULL DEFAULT 0,
    used_x2       INTEGER NOT NULL DEFAULT 0,
    pending_x2    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (employee_id, leave_type_id, year)
) STRICT;

CREATE TABLE leave_requests (
    id                    TEXT PRIMARY KEY,
    employee_id           TEXT NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    leave_type_id         TEXT NOT NULL REFERENCES leave_types(id),
    start_date            TEXT NOT NULL,
    end_date              TEXT NOT NULL,
    days_x2               INTEGER NOT NULL CHECK (days_x2 > 0),
    half_day_start        INTEGER NOT NULL DEFAULT 0 CHECK (half_day_start IN (0,1)),
    half_day_end          INTEGER NOT NULL DEFAULT 0 CHECK (half_day_end IN (0,1)),
    reason                TEXT NOT NULL,
    status                TEXT NOT NULL CHECK (status IN ('pending','approved','rejected','cancelled')),
    recorded_by           TEXT NOT NULL,
    decided_by            TEXT,
    decided_at            INTEGER,
    decision_note         TEXT,
    attachment_document_id TEXT,
    created_at            INTEGER NOT NULL
) STRICT;

CREATE INDEX leave_requests_employee_idx ON leave_requests(employee_id, start_date);
CREATE INDEX leave_requests_status_idx ON leave_requests(status);

CREATE TABLE holidays (
    id        TEXT PRIMARY KEY,
    date      TEXT NOT NULL UNIQUE,
    name      TEXT NOT NULL,
    is_joint  INTEGER NOT NULL DEFAULT 0 CHECK (is_joint IN (0,1))
) STRICT;

CREATE TABLE compensation (
    id              TEXT PRIMARY KEY,
    employee_id     TEXT NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    effective_from  TEXT NOT NULL,
    base_salary_sen INTEGER NOT NULL,
    fixed_allowances_sen INTEGER NOT NULL DEFAULT 0,
    variable_allowances_sen INTEGER NOT NULL DEFAULT 0,
    currency        TEXT NOT NULL DEFAULT 'IDR',
    created_at      INTEGER NOT NULL,
    created_by      TEXT NOT NULL
) STRICT;

CREATE INDEX compensation_employee_idx ON compensation(employee_id, effective_from);

CREATE TABLE rate_tables (
    id             TEXT PRIMARY KEY,
    kind           TEXT NOT NULL,
    effective_from TEXT NOT NULL,
    effective_to   TEXT,
    verified       INTEGER NOT NULL DEFAULT 0 CHECK (verified IN (0,1)),
    verified_by    TEXT,
    verified_at    INTEGER,
    source_note    TEXT,
    UNIQUE (kind, effective_from)
) STRICT;

CREATE TABLE rate_entries (
    table_id          TEXT NOT NULL REFERENCES rate_tables(id) ON DELETE CASCADE,
    position          INTEGER NOT NULL,
    entry_key         TEXT,
    employee_share_bp INTEGER NOT NULL DEFAULT 0,
    employer_share_bp INTEGER NOT NULL DEFAULT 0,
    wage_cap_sen      INTEGER,
    flat_amount_sen   INTEGER,
    multiplier_bp     INTEGER,
    lower_bound_sen   INTEGER,
    upper_bound_sen   INTEGER,
    hours_per_month   INTEGER,
    note              TEXT,
    PRIMARY KEY (table_id, position)
) STRICT;

CREATE TABLE payroll_runs (
    id                   TEXT PRIMARY KEY,
    kind                 TEXT NOT NULL CHECK (kind IN ('monthly','thr','final','adjustment')),
    period               TEXT NOT NULL,
    status               TEXT NOT NULL CHECK (status IN ('draft','computed','approved','cancelled','superseded')),
    anomalies_json       TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(anomalies_json)),
    totals_json          TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(totals_json)),
    rate_table_ids_json  TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(rate_table_ids_json)),
    created_at           INTEGER NOT NULL,
    computed_at          INTEGER,
    approved_at          INTEGER,
    approved_by          TEXT,
    supersede_reason     TEXT
) STRICT;

CREATE INDEX payroll_runs_period_idx ON payroll_runs(period, kind);

CREATE TABLE payroll_lines (
    run_id        TEXT NOT NULL REFERENCES payroll_runs(id) ON DELETE CASCADE,
    employee_id   TEXT NOT NULL,
    employee_name TEXT NOT NULL,
    line_json     TEXT NOT NULL CHECK (json_valid(line_json)),
    position      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (run_id, employee_id)
) STRICT;

CREATE TABLE approvals (
    id            TEXT PRIMARY KEY,
    kind          TEXT NOT NULL,
    title         TEXT NOT NULL,
    summary       TEXT NOT NULL,
    subject_type  TEXT NOT NULL,
    subject_id    TEXT NOT NULL,
    status        TEXT NOT NULL CHECK (status IN ('open','approved','rejected','expired','cancelled')),
    priority      TEXT NOT NULL CHECK (priority IN ('low','normal','high','urgent')),
    due_on        TEXT,
    requested_by  TEXT,
    created_at    INTEGER NOT NULL,
    decided_by    TEXT,
    decided_at    INTEGER,
    decision_note TEXT
) STRICT;

CREATE INDEX approvals_status_priority_idx ON approvals(status, priority);

CREATE TABLE consents (
    id            TEXT PRIMARY KEY,
    subject_type  TEXT NOT NULL CHECK (subject_type IN ('candidate','employee')),
    subject_id    TEXT NOT NULL,
    purpose       TEXT NOT NULL,
    state         TEXT NOT NULL CHECK (state IN ('pending','granted','withdrawn','expired')),
    source        TEXT NOT NULL,
    granted_at    INTEGER,
    withdrawn_at  INTEGER,
    expires_on    TEXT,
    note          TEXT
) STRICT;

CREATE INDEX consents_subject_idx ON consents(subject_type, subject_id);

CREATE TABLE retention_policies (
    id               TEXT PRIMARY KEY,
    record_type      TEXT NOT NULL UNIQUE,
    retention_months INTEGER NOT NULL,
    action           TEXT NOT NULL CHECK (action IN ('purge','anonymize','archive')),
    legal_basis      TEXT NOT NULL,
    active           INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1))
) STRICT;

CREATE TABLE retention_holds (
    id           TEXT PRIMARY KEY,
    subject_type TEXT NOT NULL,
    subject_id   TEXT NOT NULL,
    reason       TEXT NOT NULL,
    until        TEXT,
    created_by   TEXT NOT NULL,
    created_at   INTEGER NOT NULL
) STRICT;

CREATE TABLE erasure_requests (
    id           TEXT PRIMARY KEY,
    subject_type TEXT NOT NULL CHECK (subject_type IN ('candidate','employee')),
    subject_id   TEXT NOT NULL,
    reason       TEXT NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('pending','approved','rejected','completed','cancelled')),
    requested_at INTEGER NOT NULL,
    decided_by   TEXT,
    decided_at   INTEGER,
    executed_at  INTEGER,
    retained_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(retained_json))
) STRICT;

CREATE TABLE breach_incidents (
    id            TEXT PRIMARY KEY,
    title         TEXT NOT NULL,
    description   TEXT NOT NULL,
    severity      TEXT NOT NULL CHECK (severity IN ('low','medium','high','critical')),
    status        TEXT NOT NULL CHECK (status IN ('open','contained','notified','closed')),
    discovered_at INTEGER NOT NULL,
    contained_at  INTEGER,
    notified_at   INTEGER,
    steps_json    TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(steps_json)),
    owner         TEXT NOT NULL
) STRICT;

CREATE TABLE policy_documents (
    slug           TEXT PRIMARY KEY,
    title          TEXT NOT NULL,
    body           TEXT NOT NULL,
    effective_from TEXT,
    owner          TEXT
) STRICT;

CREATE TABLE chat_conversations (
    id         TEXT PRIMARY KEY,
    title      TEXT NOT NULL,
    scope      TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
) STRICT;

CREATE TABLE chat_messages (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES chat_conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('operator','assistant','system')),
    body            TEXT NOT NULL,
    citations_json  TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(citations_json)),
    created_at      INTEGER NOT NULL
) STRICT;

CREATE TABLE growth_cycles (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    status     TEXT NOT NULL CHECK (status IN ('draft','active','closed')),
    starts_on  TEXT NOT NULL,
    ends_on    TEXT NOT NULL,
    created_at INTEGER NOT NULL
) STRICT;

CREATE TABLE growth_assignments (
    id             TEXT PRIMARY KEY,
    cycle_id       TEXT NOT NULL REFERENCES growth_cycles(id) ON DELETE CASCADE,
    employee_id    TEXT NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    reviewer_name  TEXT NOT NULL,
    status         TEXT NOT NULL CHECK (status IN ('pending','sent','submitted','summarized')),
    form_json      TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(form_json)),
    response_json  TEXT CHECK (response_json IS NULL OR json_valid(response_json))
) STRICT;

CREATE TABLE goals (
    id          TEXT PRIMARY KEY,
    employee_id TEXT NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('draft','active','completed','cancelled')),
    due_on      TEXT,
    progress_bp INTEGER NOT NULL DEFAULT 0 CHECK (progress_bp BETWEEN 0 AND 10000),
    created_at  INTEGER NOT NULL
) STRICT;

CREATE TABLE offboarding_plans (
    id           TEXT PRIMARY KEY,
    employee_id  TEXT NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    status       TEXT NOT NULL CHECK (status IN ('draft','in_progress','completed','cancelled')),
    last_day     TEXT NOT NULL,
    created_at   INTEGER NOT NULL,
    completed_at INTEGER
) STRICT;

CREATE TABLE offboarding_steps (
    plan_id    TEXT NOT NULL REFERENCES offboarding_plans(id) ON DELETE CASCADE,
    step_key   TEXT NOT NULL,
    title      TEXT NOT NULL,
    owner      TEXT,
    status     TEXT NOT NULL CHECK (status IN ('pending','in_progress','done','skipped')),
    completed_at INTEGER,
    notes      TEXT,
    position   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (plan_id, step_key)
) STRICT;

CREATE TABLE jobs_queue (
    id          TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(payload_json)),
    status      TEXT NOT NULL CHECK (status IN ('pending','running','done','failed','cancelled')),
    attempts    INTEGER NOT NULL DEFAULT 0,
    run_after   INTEGER NOT NULL,
    lease_until INTEGER,
    dedup_key   TEXT,
    last_error  TEXT,
    created_at  INTEGER NOT NULL,
    updated_at  INTEGER NOT NULL
) STRICT;

CREATE UNIQUE INDEX jobs_queue_dedup_idx ON jobs_queue(dedup_key) WHERE dedup_key IS NOT NULL;
CREATE INDEX jobs_queue_status_idx ON jobs_queue(status, run_after);

CREATE TABLE backup_runs (
    id          TEXT PRIMARY KEY,
    path        TEXT NOT NULL,
    size_bytes  INTEGER NOT NULL,
    sha256      TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('running','verified','failed','restored')),
    started_at  INTEGER NOT NULL,
    finished_at INTEGER,
    note        TEXT
) STRICT;

CREATE TABLE import_runs (
    id          TEXT PRIMARY KEY,
    source      TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('running','completed','failed')),
    rows_read   INTEGER NOT NULL DEFAULT 0,
    rows_written INTEGER NOT NULL DEFAULT 0,
    errors_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(errors_json)),
    started_at  INTEGER NOT NULL,
    finished_at INTEGER
) STRICT;

-- FTS5 external-content indexes. Triggers keep them in sync; a delete must use
-- the 'delete' command with the old values or the index retains ghost rows.

CREATE VIRTUAL TABLE employees_fts USING fts5(
    full_name, employee_no, job_title, org_unit,
    content='employees', content_rowid='rowid', tokenize='unicode61'
);
CREATE TRIGGER employees_ai AFTER INSERT ON employees BEGIN
    INSERT INTO employees_fts(rowid, full_name, employee_no, job_title, org_unit)
    VALUES (new.rowid, new.full_name, new.employee_no, new.job_title, new.org_unit);
END;
CREATE TRIGGER employees_ad AFTER DELETE ON employees BEGIN
    INSERT INTO employees_fts(employees_fts, rowid, full_name, employee_no, job_title, org_unit)
    VALUES ('delete', old.rowid, old.full_name, old.employee_no, old.job_title, old.org_unit);
END;
CREATE TRIGGER employees_au AFTER UPDATE ON employees BEGIN
    INSERT INTO employees_fts(employees_fts, rowid, full_name, employee_no, job_title, org_unit)
    VALUES ('delete', old.rowid, old.full_name, old.employee_no, old.job_title, old.org_unit);
    INSERT INTO employees_fts(rowid, full_name, employee_no, job_title, org_unit)
    VALUES (new.rowid, new.full_name, new.employee_no, new.job_title, new.org_unit);
END;

CREATE VIRTUAL TABLE candidates_fts USING fts5(
    full_name, email, headline, source,
    content='candidates', content_rowid='rowid', tokenize='unicode61'
);
CREATE TRIGGER candidates_ai AFTER INSERT ON candidates BEGIN
    INSERT INTO candidates_fts(rowid, full_name, email, headline, source)
    VALUES (new.rowid, new.full_name, new.email, new.headline, new.source);
END;
CREATE TRIGGER candidates_ad AFTER DELETE ON candidates BEGIN
    INSERT INTO candidates_fts(candidates_fts, rowid, full_name, email, headline, source)
    VALUES ('delete', old.rowid, old.full_name, old.email, old.headline, old.source);
END;
CREATE TRIGGER candidates_au AFTER UPDATE ON candidates BEGIN
    INSERT INTO candidates_fts(candidates_fts, rowid, full_name, email, headline, source)
    VALUES ('delete', old.rowid, old.full_name, old.email, old.headline, old.source);
    INSERT INTO candidates_fts(rowid, full_name, email, headline, source)
    VALUES (new.rowid, new.full_name, new.email, new.headline, new.source);
END;

CREATE VIRTUAL TABLE jobs_fts USING fts5(
    title, org_unit, location,
    content='jobs', content_rowid='rowid', tokenize='unicode61'
);
CREATE TRIGGER jobs_ai AFTER INSERT ON jobs BEGIN
    INSERT INTO jobs_fts(rowid, title, org_unit, location)
    VALUES (new.rowid, new.title, new.org_unit, new.location);
END;
CREATE TRIGGER jobs_ad AFTER DELETE ON jobs BEGIN
    INSERT INTO jobs_fts(jobs_fts, rowid, title, org_unit, location)
    VALUES ('delete', old.rowid, old.title, old.org_unit, old.location);
END;
CREATE TRIGGER jobs_au AFTER UPDATE ON jobs BEGIN
    INSERT INTO jobs_fts(jobs_fts, rowid, title, org_unit, location)
    VALUES ('delete', old.rowid, old.title, old.org_unit, old.location);
    INSERT INTO jobs_fts(rowid, title, org_unit, location)
    VALUES (new.rowid, new.title, new.org_unit, new.location);
END;

CREATE VIRTUAL TABLE documents_fts USING fts5(
    filename, tags_json,
    content='documents', content_rowid='rowid', tokenize='unicode61'
);
CREATE TRIGGER documents_ai AFTER INSERT ON documents BEGIN
    INSERT INTO documents_fts(rowid, filename, tags_json)
    VALUES (new.rowid, new.filename, new.tags_json);
END;
CREATE TRIGGER documents_ad AFTER DELETE ON documents BEGIN
    INSERT INTO documents_fts(documents_fts, rowid, filename, tags_json)
    VALUES ('delete', old.rowid, old.filename, old.tags_json);
END;
CREATE TRIGGER documents_au AFTER UPDATE ON documents BEGIN
    INSERT INTO documents_fts(documents_fts, rowid, filename, tags_json)
    VALUES ('delete', old.rowid, old.filename, old.tags_json);
    INSERT INTO documents_fts(rowid, filename, tags_json)
    VALUES (new.rowid, new.filename, new.tags_json);
END;

CREATE VIRTUAL TABLE audit_fts USING fts5(
    action, subject_type, subject_id,
    content='audit_log', content_rowid='rowid', tokenize='unicode61'
);
CREATE TRIGGER audit_ai AFTER INSERT ON audit_log BEGIN
    INSERT INTO audit_fts(rowid, action, subject_type, subject_id)
    VALUES (new.rowid, new.action, new.subject_type, new.subject_id);
END;
CREATE TRIGGER audit_ad AFTER DELETE ON audit_log BEGIN
    INSERT INTO audit_fts(audit_fts, rowid, action, subject_type, subject_id)
    VALUES ('delete', old.rowid, old.action, old.subject_type, old.subject_id);
END;

PRAGMA user_version = 1;
