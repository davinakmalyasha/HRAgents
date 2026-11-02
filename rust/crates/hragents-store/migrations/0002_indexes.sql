-- Indexes for foreign-key lookups and status filters used on hot screens.
-- SQLite does not index foreign keys automatically; without these every
-- per-employee or per-application read degrades to a table scan as data grows.

CREATE INDEX IF NOT EXISTS onboarding_plans_employee_status_idx
    ON onboarding_plans(employee_id, status);
CREATE INDEX IF NOT EXISTS onboarding_steps_plan_idx
    ON onboarding_steps(plan_id);

CREATE INDEX IF NOT EXISTS document_requests_employee_idx
    ON document_requests(employee_id, requested_at);

CREATE INDEX IF NOT EXISTS offers_application_idx
    ON offers(application_id);
CREATE INDEX IF NOT EXISTS candidate_comms_application_idx
    ON candidate_communications(application_id, created_at);
CREATE INDEX IF NOT EXISTS candidate_comms_candidate_idx
    ON candidate_communications(candidate_id, created_at);
CREATE INDEX IF NOT EXISTS schedule_proposals_application_idx
    ON schedule_proposals(application_id);
CREATE INDEX IF NOT EXISTS feedback_reports_application_idx
    ON feedback_reports(application_id);

CREATE INDEX IF NOT EXISTS offboarding_plans_employee_idx
    ON offboarding_plans(employee_id, created_at);
CREATE INDEX IF NOT EXISTS growth_assignments_cycle_idx
    ON growth_assignments(cycle_id, created_at);
CREATE INDEX IF NOT EXISTS growth_assignments_employee_idx
    ON growth_assignments(employee_id);
CREATE INDEX IF NOT EXISTS goals_employee_idx
    ON goals(employee_id, created_at);

CREATE INDEX IF NOT EXISTS retention_holds_subject_idx
    ON retention_holds(subject_type, subject_id);
CREATE INDEX IF NOT EXISTS erasure_requests_status_idx
    ON erasure_requests(status, requested_at);
CREATE INDEX IF NOT EXISTS breach_incidents_status_idx
    ON breach_incidents(status, discovered_at);
CREATE INDEX IF NOT EXISTS chat_messages_conversation_idx
    ON chat_messages(conversation_id, created_at);
CREATE INDEX IF NOT EXISTS payroll_lines_employee_idx
    ON payroll_lines(employee_id);

PRAGMA user_version = 2;
