export type Role = "hr_operator";
export type Money = number; // integer sen (1/100 IDR), never a float

export interface AppInfo {
  name: string;
  version: string;
  company: string | null;
  setup_required: boolean;
  role: Role;
}

export interface SessionView {
  operator_id: string;
  display_name: string;
  role: Role;
  started_at: string;
  last_activity_at: string;
  locked: boolean;
  reauth_fresh: boolean;
}

export type EmploymentStatus = "active" | "probation" | "notice" | "exited";

export interface Employee {
  id: string;
  employee_no: string;
  full_name: string;
  preferred_name: string | null;
  email: string | null;
  phone: string | null;
  job_title: string;
  org_unit: string;
  manager_id: string | null;
  status: EmploymentStatus;
  hire_date: string;
  end_date: string | null;
  birth_date: string | null;
  ptkp_status: string | null;
  dependents: number;
  jkk_risk_class: number | null;
  npwp: string | null;
  bank_name: string | null;
  bank_account: string | null;
  bpjs_kesehatan_no: string | null;
  bpjs_ketenagakerjaan_no: string | null;
  created_at: string;
  updated_at: string;
  version: number;
}

export interface OnboardingStep {
  key: string;
  title: string;
  category: string;
  required: boolean;
  status: "pending" | "in_progress" | "done" | "skipped";
  due_date: string | null;
  completed_at: string | null;
  completed_by: string | null;
  document_request_id: string | null;
  notes: string | null;
}

export interface OnboardingPlan {
  id: string;
  employee_id: string;
  template_name: string;
  status: "draft" | "in_progress" | "completed" | "cancelled";
  steps: OnboardingStep[];
  created_at: string;
  completed_at: string | null;
}

export interface Job {
  id: string;
  title: string;
  org_unit: string;
  location: string;
  employment_type: string;
  status: "draft" | "open" | "paused" | "closed";
  openings: number;
  rubric_id: string | null;
  created_at: string;
}

export type ConsentStatus = "pending" | "granted" | "withdrawn" | "expired";

export interface Candidate {
  id: string;
  full_name: string;
  email: string | null;
  phone: string | null;
  source: string;
  headline: string | null;
  location: string | null;
  consent: ConsentStatus;
  document_ids: string[];
  created_at: string;
}

export type ApplicationStage =
  | "imported"
  | "screening"
  | "review"
  | "interview"
  | "offer"
  | "hired"
  | "rejected"
  | "withdrawn";

export interface Application {
  id: string;
  candidate_id: string;
  job_id: string;
  stage: ApplicationStage;
  priority: number;
  created_at: string;
  updated_at: string;
  rejection_reason: string | null;
  rejected_by: string | null;
}

export interface Dimension {
  key: string;
  label: string;
  weight_bp: number;
}

export interface Rubric {
  id: string;
  name: string;
  dimensions: Dimension[];
  merit_floor_bp: number;
  sigma_limit_bp: number;
}

export interface Evidence {
  dimension: string;
  quote: string;
  source_document_id: string;
  confidence_bp: number;
  page: number | null;
}

export interface Evaluation {
  id: string;
  application_id: string;
  rubric_id: string;
  dimension_scores: Record<string, number>;
  overall_bp: number;
  sigma_bp: number;
  runs: number;
  evidence: Evidence[];
  flags: string[];
  created_at: string;
}

export type PolicyOutcome =
  | "HumanReview"
  | { GatedRejection: { requires_signoff: boolean } }
  | { Blocked: { code: string; message: string } };

export interface EvaluationView {
  evaluation: Evaluation;
  policy: PolicyOutcome;
  candidate_name: string;
}

export type ApprovalKind =
  | "rejection_override"
  | "payroll_sign_off"
  | "offer_approval"
  | "erasure"
  | "leave"
  | "document";

export interface ApprovalRequest {
  id: string;
  kind: ApprovalKind;
  title: string;
  summary: string;
  subject_type: string;
  subject_id: string;
  status: "open" | "approved" | "rejected" | "expired" | "cancelled";
  priority: "low" | "normal" | "high" | "urgent";
  due_on: string | null;
  requested_by: string | null;
  created_at: string;
  decided_by: string | null;
  decided_at: string | null;
  decision_note: string | null;
}

export interface AuditEntry {
  seq: number;
  entry_id: string;
  created_at: string;
  actor: {
    actor_type: "system" | "agent" | "human";
    actor_id: string;
    display_name: string | null;
    provenance: "authenticated" | "system_job" | "agent_tool" | "legacy_string";
    role: string | null;
  };
  action: string;
  subject_type: string;
  subject_id: string;
  payload: unknown;
  prev_hash: string | null;
  entry_hash: string;
}

export interface AuditVerification {
  entries: number;
  head_hash: string | null;
}

export interface TodayView {
  approvals: ApprovalRequest[];
  open_onboarding: string[];
  expiring_documents: unknown[];
  recent_audit: AuditEntry[];
  headcount: number;
}

export interface LeaveType {
  id: string;
  name: string;
  annual_quota_x2: number;
  carry_over_max_x2: number;
  requires_attachment: boolean;
  active: boolean;
}

export interface LeaveBalance {
  employee_id: string;
  leave_type_id: string;
  year: number;
  entitled_x2: number;
  adjustment_x2: number;
  used_x2: number;
  pending_x2: number;
}

export interface LeaveRequest {
  id: string;
  employee_id: string;
  leave_type_id: string;
  start_date: string;
  end_date: string;
  days_x2: number;
  half_day_start: boolean;
  half_day_end: boolean;
  reason: string;
  status: "pending" | "approved" | "rejected" | "cancelled";
  recorded_by: string;
  decided_by: string | null;
  decided_at: string | null;
  decision_note: string | null;
  attachment_document_id: string | null;
  created_at: string;
}

export interface LeaveView {
  request: LeaveRequest;
  balance: LeaveBalance;
}

export interface PayrollAnomaly {
  code: string;
  severity: "info" | "warning" | "error";
  employee_id: string | null;
  detail: string;
}

export interface PayrollLine {
  employee_id: string;
  employee_name: string;
  base_salary: Money;
  allowances: Money;
  overtime_pay: Money;
  bonus: Money;
  gross: Money;
  bpjs_kesehatan_employee: Money;
  bpjs_jht_employee: Money;
  bpjs_jp_employee: Money;
  pph21: Money;
  other_deductions: Money;
  total_deductions: Money;
  net: Money;
  bpjs_kesehatan_employer: Money;
  bpjs_jht_employer: Money;
  bpjs_jp_employer: Money;
  bpjs_jkk_employer: Money;
  bpjs_jkm_employer: Money;
  employer_cost: Money;
  thr_months_bp: number | null;
  severance_pay: Money;
  leave_payout: Money;
  notes: string[];
}

export interface PayrollTotals {
  employees: number;
  gross: Money;
  net: Money;
  employee_deductions: Money;
  employer_cost: Money;
  pph21: Money;
}

export interface PayrollRun {
  id: string;
  kind: "monthly" | "thr" | "final" | "adjustment";
  period: string;
  status: "draft" | "computed" | "approved" | "cancelled" | "superseded";
  lines: PayrollLine[];
  anomalies: PayrollAnomaly[];
  totals: PayrollTotals;
  rate_table_ids: string[];
  created_at: string;
  computed_at: string | null;
  approved_at: string | null;
  approved_by: string | null;
  supersede_reason: string | null;
}

export interface PayrollView {
  run: PayrollRun;
  blocking: number;
}

export interface SearchHit {
  kind: string;
  id: string;
  title: string;
  subtitle: string;
}

export interface OperatorView {
  id: string;
  username: string;
  display_name: string;
  role: Role;
  active: boolean;
  created_at: string;
}

export interface RateTable {
  id: string;
  kind: string;
  effective_from: string;
  effective_to: string | null;
  verified: boolean;
  verified_by: string | null;
  verified_at: string | null;
  source_note: string | null;
  entries: unknown[];
}

export interface PayrollInput {
  employee_id: string;
  employee_name: string;
  base_salary: Money;
  fixed_allowances: Money;
  variable_allowances: Money;
  overtime_minutes: number;
  absence_days: number;
  working_days: number;
  bonus: Money;
  other_deductions: Money;
  loan_deduction: Money;
  service_months: number;
  severance_pay: Money;
  unused_leave_days_x2: number;
  leave_payout_per_day: Money;
  note: string | null;
}


export interface ReviewQuestion {
  key: string;
  prompt: string;
  kind: "rating" | "text" | "yes_no";
  required: boolean;
}

export interface ReviewForm {
  questions: ReviewQuestion[];
}

export interface ReviewCycle {
  id: string;
  name: string;
  status: "draft" | "active" | "closed";
  starts_on: string;
  ends_on: string;
  created_at: string;
}

export interface ReviewAnswer {
  rating: number | null;
  text: string | null;
  yes_no: boolean | null;
}

export interface ReviewAssignment {
  id: string;
  cycle_id: string;
  employee_id: string;
  reviewer_name: string;
  reviewer_email: string | null;
  status: "pending" | "sent" | "submitted" | "summarized";
  form: ReviewForm;
  response: Record<string, ReviewAnswer> | null;
  created_at: string;
  sent_at: string | null;
  submitted_at: string | null;
}

export interface Goal {
  id: string;
  employee_id: string;
  title: string;
  status: "draft" | "active" | "completed" | "cancelled";
  due_on: string | null;
  progress_bp: number;
  created_at: string;
}

export interface OffboardingStep {
  key: string;
  title: string;
  owner: string;
  required: boolean;
  status: "pending" | "in_progress" | "done" | "skipped";
  completed_at: string | null;
  completed_by: string | null;
  notes: string | null;
}

export interface OffboardingPlan {
  id: string;
  employee_id: string;
  last_day: string;
  status: "draft" | "in_progress" | "completed" | "cancelled";
  steps: OffboardingStep[];
  final_pay_run_id: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface DocumentRequest {
  id: string;
  employee_id: string;
  document_type: string;
  status: "requested" | "uploaded" | "verified" | "rejected" | "cancelled";
  requested_at: string;
  due_on: string | null;
  document_id: string | null;
  note: string | null;
}

export type DocumentOwnerType = "employee" | "candidate" | "company" | "payroll_run";

export interface Document {
  id: string;
  owner_type: DocumentOwnerType;
  owner_id: string;
  filename: string;
  mime_type: string;
  sha256: string;
  size_bytes: number;
  status: "pending" | "verified" | "rejected" | "expired";
  expires_on: string | null;
  uploaded_at: string;
  verified_at: string | null;
  verified_by: string | null;
  rejection_reason: string | null;
  tags: string[];
}

export interface DocumentBytes {
  document: Document;
  base64: string;
  size_bytes: number;
}

export type SlotMode = "onsite" | "remote" | "phone";

export interface InterviewSlot {
  starts_at: string;
  duration_minutes: number;
  mode: SlotMode;
  location: string | null;
}

export type ProposalStatus = "proposed" | "confirmed" | "declined" | "expired";

export interface ScheduleProposal {
  id: string;
  application_id: string;
  slots: InterviewSlot[];
  status: ProposalStatus;
  confirmed_index: number | null;
  created_at: string;
  decided_at: string | null;
}

export type OfferStatus = "draft" | "approved" | "sent" | "accepted" | "declined" | "expired";

export interface Offer {
  id: string;
  application_id: string;
  position_title: string;
  salary_sen: number | null;
  start_date: string | null;
  expires_on: string | null;
  status: OfferStatus;
  note: string | null;
  created_at: string;
  decided_at: string | null;
}

export type MessageKind = "rejection" | "offer" | "interview" | "update";
export type MessageChannel = "email" | "whatsapp" | "phone" | "note";
export type MessageStatus = "draft" | "queued" | "sent" | "cancelled";
export type MessageDirection = "outbound" | "inbound";

export interface CandidateMessage {
  id: string;
  candidate_id: string;
  application_id: string | null;
  kind: MessageKind;
  channel: MessageChannel;
  subject: string | null;
  body: string;
  status: MessageStatus;
  direction: MessageDirection;
  created_at: string;
  sent_at: string | null;
}

export interface FeedbackReport {
  id: string;
  application_id: string;
  candidate_name: string;
  job_title: string;
  summary: string;
  strengths: string[];
  growth_areas: string[];
  created_at: string;
}
