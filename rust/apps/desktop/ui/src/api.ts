import { invoke } from "@tauri-apps/api/core";
import type {
  AppInfo,
  Application,
  ApprovalRequest,
  AuditEntry,
  AuditVerification,
  Candidate,
  Employee,
  Evaluation,
  EvaluationView,
  Job,
  LeaveBalance,
  LeaveRequest,
  LeaveType,
  LeaveView,
  OnboardingPlan,
  PayrollInput,
  PayrollRun,
  PayrollView,
  SearchHit,
  SessionView,
  TodayView,
} from "./types";

const tauriAvailable = Boolean(
  (window as unknown as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__,
);

export const isDesktop = tauriAvailable;

export async function command<T>(name: string, args: Record<string, unknown> = {}): Promise<T> {
  if (tauriAvailable) {
    return invoke<T>(name, args);
  }
  return mock<T>(name, args);
}

export function formatIdr(sen: number): string {
  const negative = sen < 0;
  const absolute = Math.abs(sen);
  const whole = Math.floor(absolute / 100);
  const cents = String(absolute % 100).padStart(2, "0");
  const grouped = whole.toLocaleString("id-ID");
  return `${negative ? "-" : ""}Rp${grouped},${cents}`;
}

export function shortRef(id: string, prefix: string): string {
  return `#${prefix}-${id.replaceAll("-", "").slice(0, 6).toUpperCase()}`;
}

export function formatDays(x2: number): string {
  return `${x2 / 2} day${x2 === 2 ? "" : "s"}`;
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    timeZone: "Asia/Jakarta",
  }).format(date);
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en-GB", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Asia/Jakarta",
  }).format(date);
}

export function policyKind(policy: EvaluationView["policy"]): string {
  if (typeof policy === "string") return policy;
  if ("GatedRejection" in policy) return "GatedRejection";
  if ("Blocked" in policy) return "Blocked";
  return "HumanReview";
}

// ---------------------------------------------------------------------------
// Browser preview adapter. The packaged app always goes through Tauri IPC; this
// exists so the five surfaces can be reviewed and tested without a webview
// runtime. It returns the same shapes and enforces the same gates.
// ---------------------------------------------------------------------------

const now = () => new Date().toISOString();
const uuid = () => crypto.randomUUID();
const idr = (rupiah: number) => rupiah * 100;

interface MockState {
  setupRequired: boolean;
  company: string;
  session: SessionView | null;
  employees: Employee[];
  onboarding: Record<string, OnboardingPlan>;
  jobs: Job[];
  candidates: Candidate[];
  applications: Application[];
  evaluations: Evaluation[];
  approvals: ApprovalRequest[];
  audit: AuditEntry[];
  leaveTypes: LeaveType[];
  balances: LeaveBalance[];
  leaveRequests: LeaveRequest[];
  payroll: PayrollRun[];
  ratesSeeded: boolean;
}

const ayuId = uuid();
const budiId = uuid();
const jobId = uuid();
const candidateId = uuid();
const applicationId = uuid();
const leaveTypeId = uuid();
const payrollId = uuid();

function makeEmployee(
  id: string,
  no: string,
  name: string,
  title: string,
  unit: string,
  email: string,
): Employee {
  return {
    id,
    employee_no: no,
    full_name: name,
    preferred_name: null,
    email,
    phone: null,
    job_title: title,
    org_unit: unit,
    manager_id: null,
    status: "active",
    hire_date: "2025-02-01",
    end_date: null,
    birth_date: null,
    ptkp_status: "TK/1",
    dependents: 1,
    jkk_risk_class: 1,
    npwp: null,
    bank_name: "BCA",
    bank_account: "1234567890",
    bpjs_kesehatan_no: null,
    bpjs_ketenagakerjaan_no: null,
    created_at: now(),
    updated_at: now(),
    version: 1,
  };
}

function makeAudit(seq: number, action: string, subject: string, title: string): AuditEntry {
  return {
    seq,
    entry_id: uuid(),
    created_at: now(),
    actor: {
      actor_type: "human",
      actor_id: "mock-operator",
      display_name: "Rina",
      provenance: "authenticated",
      role: "hr_operator",
    },
    action,
    subject_type: subject,
    subject_id: uuid(),
    payload: { title },
    prev_hash: seq === 0 ? null : "0".repeat(64),
    entry_hash: String(seq + 1).padStart(64, "a"),
  };
}

const state: MockState = {
  setupRequired: false,
  company: "Nusantara Labs",
  session: {
    operator_id: "mock-operator",
    display_name: "Rina",
    role: "hr_operator",
    started_at: now(),
    last_activity_at: now(),
    locked: false,
    reauth_fresh: true,
  },
  employees: [
    makeEmployee(ayuId, "E-001", "Ayu Lestari", "Backend Engineer", "Product", "ayu@example.com"),
    makeEmployee(budiId, "E-002", "Budi Santoso", "Product Designer", "Design", "budi@example.com"),
  ],
  onboarding: {},
  jobs: [
    {
      id: jobId,
      title: "Backend Engineer",
      org_unit: "Product",
      location: "Jakarta",
      employment_type: "full_time",
      status: "open",
      openings: 1,
      rubric_id: "backend-v1",
      created_at: now(),
    },
  ],
  candidates: [
    {
      id: candidateId,
      full_name: "Dimas Pratama",
      email: "dimas@example.com",
      phone: "+62 812 3456 7890",
      source: "LinkedIn",
      headline: "Backend engineer · 6 years · Go and Rust",
      location: "Bandung",
      consent: "granted",
      document_ids: [],
      created_at: now(),
    },
  ],
  applications: [
    {
      id: applicationId,
      candidate_id: candidateId,
      job_id: jobId,
      stage: "review",
      priority: 2,
      created_at: now(),
      updated_at: now(),
      rejection_reason: null,
      rejected_by: null,
    },
  ],
  evaluations: [
    {
      id: uuid(),
      application_id: applicationId,
      rubric_id: "backend-v1",
      dimension_scores: { skills: 8500, impact: 7500 },
      overall_bp: 8100,
      sigma_bp: 220,
      runs: 3,
      evidence: [
        {
          dimension: "skills",
          quote: "Built a Rust ingestion pipeline handling 2M events per day.",
          source_document_id: uuid(),
          confidence_bp: 9000,
          page: 2,
        },
        {
          dimension: "impact",
          quote: "Reduced p99 latency from 900ms to 180ms across the checkout path.",
          source_document_id: uuid(),
          confidence_bp: 8400,
          page: 1,
        },
      ],
      flags: [],
      created_at: now(),
    },
  ],
  approvals: [
    {
      id: "AP-1042",
      kind: "payroll_sign_off",
      title: "Approve November payroll",
      summary: "1 employee · net Rp11.520.000 · no blocking anomalies",
      subject_type: "payroll_run",
      subject_id: payrollId,
      status: "open",
      priority: "urgent",
      due_on: new Date().toISOString().slice(0, 10),
      requested_by: "mock-operator",
      created_at: now(),
      decided_by: null,
      decided_at: null,
      decision_note: null,
    },
    {
      id: "AP-1043",
      kind: "document",
      title: "Verify Ayu's contract",
      summary: "Fixed-term contract expires in 21 days",
      subject_type: "document",
      subject_id: uuid(),
      status: "open",
      priority: "high",
      due_on: null,
      requested_by: null,
      created_at: now(),
      decided_by: null,
      decided_at: null,
      decision_note: null,
    },
    {
      id: "AP-1044",
      kind: "rejection_override",
      title: "Reject Dimas above the merit floor",
      summary: "Score 81.0% is above the 60.0% floor; a named reason is required",
      subject_type: "application",
      subject_id: applicationId,
      status: "open",
      priority: "normal",
      due_on: null,
      requested_by: null,
      created_at: now(),
      decided_by: null,
      decided_at: null,
      decision_note: null,
    },
  ],
  audit: [
    makeAudit(0, "company.created", "company", "Nusantara Labs"),
    makeAudit(1, "operator.created", "operator", "Rina"),
    makeAudit(2, "employee.created", "employee", "Ayu Lestari"),
    makeAudit(3, "candidate.imported", "candidate", "Dimas Pratama"),
    makeAudit(4, "candidate.evaluated", "application", "81.0% · σ 2.2%"),
    makeAudit(5, "payroll.computed", "payroll_run", "November 2026"),
  ],
  leaveTypes: [
    {
      id: leaveTypeId,
      name: "Annual leave",
      annual_quota_x2: 24,
      carry_over_max_x2: 0,
      requires_attachment: false,
      active: true,
    },
  ],
  balances: [
    {
      employee_id: ayuId,
      leave_type_id: leaveTypeId,
      year: 2026,
      entitled_x2: 24,
      adjustment_x2: 0,
      used_x2: 4,
      pending_x2: 0,
    },
  ],
  leaveRequests: [],
  payroll: [],
  ratesSeeded: false,
};

state.onboarding[ayuId] = {
  id: uuid(),
  employee_id: ayuId,
  template_name: "Standard onboarding",
  status: "in_progress",
  steps: [
    {
      key: "contract",
      title: "Sign employment contract",
      category: "documents",
      required: true,
      status: "done",
      due_date: null,
      completed_at: now(),
      completed_by: "Rina",
      document_request_id: null,
      notes: null,
    },
    {
      key: "identity",
      title: "Collect KTP, NPWP, and BPJS details",
      category: "documents",
      required: true,
      status: "done",
      due_date: null,
      completed_at: now(),
      completed_by: "Rina",
      document_request_id: null,
      notes: null,
    },
    {
      key: "payroll",
      title: "Complete payroll and bank profile",
      category: "payroll",
      required: true,
      status: "pending",
      due_date: null,
      completed_at: null,
      completed_by: null,
      document_request_id: null,
      notes: null,
    },
    {
      key: "laptop",
      title: "Issue laptop and equipment",
      category: "assets",
      required: true,
      status: "pending",
      due_date: null,
      completed_at: null,
      completed_by: null,
      document_request_id: null,
      notes: null,
    },
    {
      key: "accounts",
      title: "Create accounts and access",
      category: "access",
      required: true,
      status: "pending",
      due_date: null,
      completed_at: null,
      completed_by: null,
      document_request_id: null,
      notes: null,
    },
    {
      key: "intro",
      title: "Schedule first-week intro",
      category: "people",
      required: true,
      status: "pending",
      due_date: null,
      completed_at: null,
      completed_by: null,
      document_request_id: null,
      notes: null,
    },
  ],
  created_at: now(),
  completed_at: null,
};

function payrollFixture(): PayrollRun {
  const line = {
    employee_id: ayuId,
    employee_name: "Ayu Lestari",
    base_salary: idr(10_000_000),
    allowances: idr(2_000_000),
    overtime_pay: 0,
    bonus: 0,
    gross: idr(12_000_000),
    bpjs_kesehatan_employee: idr(120_000),
    bpjs_jht_employee: idr(240_000),
    bpjs_jp_employee: idr(120_000),
    pph21: 0,
    other_deductions: 0,
    total_deductions: idr(480_000),
    net: idr(11_520_000),
    bpjs_kesehatan_employer: idr(480_000),
    bpjs_jht_employer: idr(444_000),
    bpjs_jp_employer: idr(240_000),
    bpjs_jkk_employer: idr(28_800),
    bpjs_jkm_employer: idr(36_000),
    employer_cost: idr(1_228_800),
    thr_months_bp: null,
    severance_pay: 0,
    leave_payout: 0,
    notes: [],
  };
  return {
    id: payrollId,
    kind: "monthly",
    period: "2026-11-01",
    status: "computed",
    lines: [line],
    anomalies: [],
    totals: {
      employees: 1,
      gross: idr(12_000_000),
      net: idr(11_520_000),
      employee_deductions: idr(480_000),
      employer_cost: idr(1_228_800),
      pph21: 0,
    },
    rate_table_ids: [],
    created_at: now(),
    computed_at: now(),
    approved_at: null,
    approved_by: null,
    supersede_reason: null,
  };
}
state.payroll = [payrollFixture()];

function requireSession(): SessionView {
  if (!state.session || state.session.locked) {
    throw { code: "E_UNAUTHENTICATED", message: "Sign in to continue" };
  }
  return state.session;
}

function sessionView(): SessionView {
  return state.session as SessionView;
}

function findEmployee(id: string): Employee {
  const employee = state.employees.find((item) => item.id === id);
  if (!employee) throw { code: "E_NOT_FOUND", message: "Employee not found" };
  return employee;
}

function evaluate(input: {
  application_id: string;
  rubric: { id: string; merit_floor_bp: number; sigma_limit_bp: number; dimensions: { key: string }[] };
  runs: { dimension_scores: Record<string, number> }[];
  evidence: Evaluation["evidence"];
}): EvaluationView {
  const dimensionScores: Record<string, number> = {};
  for (const dimension of input.rubric.dimensions) {
    const values = input.runs.map((run) => run.dimension_scores[dimension.key] ?? 0).sort((a, b) => a - b);
    dimensionScores[dimension.key] = values[Math.floor(values.length / 2)] ?? 0;
  }
  const overall = Math.round(
    input.rubric.dimensions.reduce(
      (sum, dimension) => sum + (dimensionScores[dimension.key] ?? 0) * (input.rubric.dimensions.length ? 1 : 0),
      0,
    ) / Math.max(input.rubric.dimensions.length, 1),
  );
  const evaluation: Evaluation = {
    id: uuid(),
    application_id: input.application_id,
    rubric_id: input.rubric.id,
    dimension_scores: dimensionScores,
    overall_bp: overall,
    sigma_bp: 0,
    runs: input.runs.length,
    evidence: input.evidence,
    flags: [],
    created_at: now(),
  };
  state.evaluations = state.evaluations.filter((item) => item.application_id !== input.application_id);
  state.evaluations.push(evaluation);
  const policy =
    overall >= input.rubric.merit_floor_bp
      ? { GatedRejection: { requires_signoff: true } }
      : "HumanReview";
  const application = state.applications.find((item) => item.id === input.application_id);
  const candidate = state.candidates.find((item) => item.id === application?.candidate_id);
  return { evaluation, policy, candidate_name: candidate?.full_name ?? "Candidate" };
}

async function mock<T>(name: string, args: Record<string, unknown>): Promise<T> {
  const sleep = () => new Promise((resolve) => setTimeout(resolve, 80));
  await sleep();
  switch (name) {
    case "app_info":
      return {
        name: "HRAgents",
        version: "0.1.0-preview",
        company: state.company,
        setup_required: state.setupRequired,
        role: "hr_operator",
      } satisfies AppInfo as T;
    case "setup_first_run": {
      const input = args.input as { company_name: string; operator_name: string; password: string };
      state.company = input.company_name;
      state.setupRequired = false;
      state.session = {
        operator_id: "mock-operator",
        display_name: input.operator_name,
        role: "hr_operator",
        started_at: now(),
        last_activity_at: now(),
        locked: false,
        reauth_fresh: true,
      };
      return sessionView() as T;
    }
    case "login": {
      if (!(args.password as string)) throw { code: "E_UNAUTHENTICATED", message: "Password required" };
      state.session = {
        operator_id: "mock-operator",
        display_name: "Rina",
        role: "hr_operator",
        started_at: now(),
        last_activity_at: now(),
        locked: false,
        reauth_fresh: true,
      };
      return sessionView() as T;
    }
    case "logout":
      state.session = null;
      return undefined as T;
    case "lock":
      requireSession();
      state.session = { ...sessionView(), locked: true };
      return undefined as T;
    case "unlock":
    case "reauth":
      state.session = { ...sessionView(), locked: false, reauth_fresh: true, last_activity_at: now() };
      return sessionView() as T;
    case "current_session":
      return sessionView() as T;
    case "today": {
      requireSession();
      return {
        approvals: state.approvals.filter((approval) => approval.status === "open"),
        open_onboarding: Object.values(state.onboarding)
          .filter((plan) => plan.status === "in_progress")
          .map((plan) => {
            const employee = state.employees.find((item) => item.id === plan.employee_id);
            const done = plan.steps.filter((step) => step.status === "done").length;
            return `${employee?.full_name ?? "Employee"} — ${plan.template_name} (${done}/${plan.steps.length})`;
          }),
        expiring_documents: [],
        recent_audit: [...state.audit].reverse().slice(0, 8),
        headcount: state.employees.filter((employee) => employee.status !== "exited").length,
      } satisfies TodayView as T;
    }
    case "list_employees":
      requireSession();
      return [...state.employees] as T;
    case "create_employee": {
      requireSession();
      const input = args.input as Record<string, unknown>;
      const employee = makeEmployee(
        uuid(),
        String(input.employee_no),
        String(input.full_name),
        String(input.job_title),
        String(input.org_unit),
        String(input.email ?? ""),
      );
      employee.hire_date = String(input.hire_date);
      employee.dependents = Number(input.dependents ?? 0);
      employee.jkk_risk_class = Number(input.jkk_risk_class ?? 1);
      employee.bank_name = (input.bank_name as string) ?? null;
      employee.bank_account = (input.bank_account as string) ?? null;
      state.employees.push(employee);
      state.audit.push(makeAudit(state.audit.length, "employee.created", "employee", employee.full_name));
      return employee as T;
    }
    case "start_onboarding": {
      requireSession();
      const employeeId = String(args.employee_id);
      const employee = findEmployee(employeeId);
      const template = String(args.template ?? "Standard onboarding");
      const steps = [
        ["contract", "Sign employment contract", "documents"],
        ["identity", "Collect KTP, NPWP, and BPJS details", "documents"],
        ["payroll", "Complete payroll and bank profile", "payroll"],
        ["laptop", "Issue laptop and equipment", "assets"],
        ["accounts", "Create accounts and access", "access"],
        ["intro", "Schedule first-week intro", "people"],
      ].map(([key, title, category]) => ({
        key,
        title,
        category,
        required: true,
        status: "pending" as const,
        due_date: null,
        completed_at: null,
        completed_by: null,
        document_request_id: null,
        notes: null,
      }));
      const plan: OnboardingPlan = {
        id: uuid(),
        employee_id: employee.id,
        template_name: template,
        status: "in_progress",
        steps,
        created_at: now(),
        completed_at: null,
      };
      state.onboarding[employee.id] = plan;
      state.audit.push(makeAudit(state.audit.length, "onboarding.started", "onboarding_plan", employee.full_name));
      return plan as T;
    }
    case "onboarding_for":
      requireSession();
      return (state.onboarding[String(args.employee_id)] ?? null) as T;
    case "complete_onboarding_step": {
      requireSession();
      const plan = state.onboarding[String(args.employee_id)];
      if (!plan) throw { code: "E_NOT_FOUND", message: "Onboarding plan not found" };
      const step = plan.steps.find((item) => item.key === String(args.step_key));
      if (!step) throw { code: "E_NOT_FOUND", message: "Step not found" };
      step.status = "done";
      step.completed_at = now();
      step.completed_by = "Rina";
      if (plan.steps.every((item) => item.status === "done")) {
        plan.status = "completed";
        plan.completed_at = now();
      }
      state.audit.push(
        makeAudit(state.audit.length, "onboarding.step_completed", "onboarding_plan", step.title),
      );
      return plan as T;
    }
    case "create_job": {
      requireSession();
      const job: Job = {
        id: uuid(),
        title: String(args.title),
        org_unit: String(args.org_unit),
        location: "Jakarta",
        employment_type: "full_time",
        status: "open",
        openings: 1,
        rubric_id: null,
        created_at: now(),
      };
      state.jobs.push(job);
      return job as T;
    }
    case "list_jobs":
      requireSession();
      return [...state.jobs] as T;
    case "import_candidate": {
      requireSession();
      const input = args.input as Record<string, unknown>;
      const candidate: Candidate = {
        id: uuid(),
        full_name: String(input.full_name),
        email: (input.email as string) ?? null,
        phone: (input.phone as string) ?? null,
        source: String(input.source ?? "Manual"),
        headline: (input.headline as string) ?? null,
        location: null,
        consent: (input.consent as Candidate["consent"]) ?? "pending",
        document_ids: [],
        created_at: now(),
      };
      const application: Application = {
        id: uuid(),
        candidate_id: candidate.id,
        job_id: String(input.job_id),
        stage: "imported",
        priority: 0,
        created_at: now(),
        updated_at: now(),
        rejection_reason: null,
        rejected_by: null,
      };
      state.candidates.push(candidate);
      state.applications.push(application);
      state.audit.push(makeAudit(state.audit.length, "candidate.imported", "candidate", candidate.full_name));
      return [candidate, application] as T;
    }
    case "evaluate_from_text": {
      requireSession();
      const input = args as {
        application_id: string;
        document_text: string;
        rubric: {
          id: string;
          merit_floor_bp: number;
          sigma_limit_bp: number;
          dimensions: { key: string; label: string; weight_bp: number }[];
        };
      };
      const text = input.document_text.toLowerCase();
      const score = (keywords: string[]) =>
        Math.min(9500, keywords.filter((keyword) => text.includes(keyword)).length * 2400 + 2500);
      const runs = [1, 2, 3].map(() => ({
        dimension_scores: {
          skills: score(["rust", "python", "sql", "built", "engineer"]),
          impact: score(["led", "reduced", "increased", "shipped", "latency"]),
        },
      }));
      const firstSentence = input.document_text.split(/[\n.]/).map((item) => item.trim()).find((item) => item.length > 12) ?? input.document_text;
      return evaluate({
        application_id: input.application_id,
        rubric: input.rubric,
        runs,
        evidence: [
          {
            dimension: "skills",
            quote: firstSentence.slice(0, 240),
            source_document_id: crypto.randomUUID(),
            confidence_bp: 8600,
            page: null,
          },
        ],
      }) as T;
    }
    case "evaluate_candidate": {
      requireSession();
      return evaluate(args.input as Parameters<typeof evaluate>[0]) as T;
    }
    case "reject_candidate": {
      requireSession();
      const reason = String(args.reason ?? "");
      if (reason.trim().length < 10) {
        throw { code: "E_REJECT_REASON", message: "A rejection needs a reason of at least 10 characters" };
      }
      const application = state.applications.find((item) => item.id === String(args.application_id));
      if (!application) throw { code: "E_NOT_FOUND", message: "Application not found" };
      application.stage = "rejected";
      application.rejection_reason = reason;
      application.rejected_by = "mock-operator";
      const candidate = state.candidates.find((item) => item.id === application.candidate_id);
      state.audit.push(
        makeAudit(state.audit.length, "candidate.rejected", "application", candidate?.full_name ?? ""),
      );
      return application as T;
    }
    case "list_candidates":
      requireSession();
      return [...state.candidates] as T;
    case "candidate": {
      requireSession();
      const candidate = state.candidates.find((item) => item.id === String(args.candidate_id));
      if (!candidate) throw { code: "E_NOT_FOUND", message: "Candidate not found" };
      return candidate as T;
    }
    case "list_applications": {
      requireSession();
      const job = args.job_id ? String(args.job_id) : null;
      return state.applications.filter((item) => !job || item.job_id === job) as T;
    }
    case "evaluation_for": {
      requireSession();
      return (state.evaluations.find((item) => item.application_id === String(args.application_id)) ??
        null) as T;
    }
    case "rate_tables":
      requireSession();
      return (state.ratesSeeded
        ? [
            "bpjs_kesehatan",
            "bpjs_ketenagakerjaan_jht",
            "bpjs_ketenagakerjaan_jp",
            "bpjs_jkk",
            "bpjs_jkm",
            "pph21_ter",
            "pph21_ptkp",
            "overtime_premium",
            "thr_formula",
            "minimum_wage",
          ].map((kind, index) => ({
            id: `rate-${index}`,
            kind,
            effective_from: "2026-01-01",
            effective_to: null,
            verified: true,
            verified_by: "Demo fixture",
            verified_at: now(),
            source_note: "demo fixture — verify before production",
            entries: [],
          }))
        : []) as T;
    case "list_leave_requests":
      requireSession();
      return state.leaveRequests as T;
    case "leave_balances":
      requireSession();
      return state.balances.filter((item) => item.year === Number(args.year)) as T;
    case "list_operators":
      requireSession();
      return [
        {
          id: "mock-operator",
          username: "rina",
          display_name: "Rina",
          role: "hr_operator",
          active: true,
          created_at: now(),
        },
      ] as T;
    case "create_leave_type": {
      requireSession();
      const leaveType: LeaveType = {
        id: uuid(),
        name: String(args.name),
        annual_quota_x2: Number(args.days) * 2,
        carry_over_max_x2: 0,
        requires_attachment: false,
        active: true,
      };
      state.leaveTypes.push(leaveType);
      return leaveType as T;
    }
    case "list_leave_types":
      requireSession();
      return [...state.leaveTypes] as T;
    case "set_leave_entitlement": {
      requireSession();
      const balance: LeaveBalance = {
        employee_id: String(args.employee_id),
        leave_type_id: String(args.leave_type_id),
        year: Number(args.year),
        entitled_x2: Number(args.days) * 2,
        adjustment_x2: 0,
        used_x2: 0,
        pending_x2: 0,
      };
      state.balances = state.balances.filter(
        (item) =>
          !(
            item.employee_id === balance.employee_id &&
            item.leave_type_id === balance.leave_type_id &&
            item.year === balance.year
          ),
      );
      state.balances.push(balance);
      return balance as T;
    }
    case "record_leave": {
      requireSession();
      const input = args.input as Record<string, unknown>;
      const balance = state.balances.find(
        (item) =>
          item.employee_id === String(input.employee_id) &&
          item.leave_type_id === String(input.leave_type_id) &&
          item.year === new Date(String(input.start_date)).getFullYear(),
      );
      if (!balance) throw { code: "E_NOT_FOUND", message: "No leave balance for this year" };
      const days = Number(input.days_x2);
      if (balance.entitled_x2 - balance.used_x2 - balance.pending_x2 < days) {
        throw { code: "E_INSUFFICIENT_BALANCE", message: "Not enough leave available" };
      }
      const request: LeaveRequest = {
        id: uuid(),
        employee_id: String(input.employee_id),
        leave_type_id: String(input.leave_type_id),
        start_date: String(input.start_date),
        end_date: String(input.end_date),
        days_x2: days,
        half_day_start: false,
        half_day_end: false,
        reason: String(input.reason),
        status: "pending",
        recorded_by: "mock-operator",
        decided_by: null,
        decided_at: null,
        decision_note: null,
        attachment_document_id: null,
        created_at: now(),
      };
      balance.pending_x2 += days;
      state.leaveRequests.push(request);
      state.audit.push(makeAudit(state.audit.length, "leave.recorded", "leave_request", request.reason));
      return { request, balance } as LeaveView as T;
    }
    case "decide_leave": {
      requireSession();
      const request = state.leaveRequests.find((item) => item.id === String(args.request_id));
      if (!request) throw { code: "E_NOT_FOUND", message: "Leave request not found" };
      const balance = state.balances.find(
        (item) => item.employee_id === request.employee_id && item.leave_type_id === request.leave_type_id,
      );
      if (!balance) throw { code: "E_NOT_FOUND", message: "Leave balance not found" };
      const approve = Boolean(args.approve);
      balance.pending_x2 -= request.days_x2;
      if (approve) balance.used_x2 += request.days_x2;
      request.status = approve ? "approved" : "rejected";
      request.decided_by = "mock-operator";
      request.decided_at = now();
      request.decision_note = String(args.note ?? "");
      state.audit.push(
        makeAudit(
          state.audit.length,
          approve ? "leave.approved" : "leave.rejected",
          "leave_request",
          request.reason,
        ),
      );
      return { request, balance } as LeaveView as T;
    }
    case "seed_demo_rate_tables":
      requireSession();
      state.ratesSeeded = true;
      return undefined as T;
    case "compute_payroll": {
      requireSession();
      const inputs = args.inputs as PayrollInput[];
      const period = String(args.period);
      const lines = inputs.map((input) => {
        const gross = input.base_salary + input.fixed_allowances + input.variable_allowances + input.bonus;
        const contribution = input.base_salary + input.fixed_allowances;
        const employeeBpjs =
          Math.round(contribution * 0.01) +
          Math.round(contribution * 0.02) +
          Math.round(contribution * 0.01);
        const net = gross - employeeBpjs - input.other_deductions - input.loan_deduction;
        return {
          employee_id: input.employee_id,
          employee_name: input.employee_name,
          base_salary: input.base_salary,
          allowances: input.fixed_allowances + input.variable_allowances,
          overtime_pay: 0,
          bonus: input.bonus,
          gross,
          bpjs_kesehatan_employee: Math.round(contribution * 0.01),
          bpjs_jht_employee: Math.round(contribution * 0.02),
          bpjs_jp_employee: Math.round(contribution * 0.01),
          pph21: 0,
          other_deductions: input.other_deductions + input.loan_deduction,
          total_deductions: employeeBpjs + input.other_deductions + input.loan_deduction,
          net,
          bpjs_kesehatan_employer: Math.round(contribution * 0.04),
          bpjs_jht_employer: Math.round(contribution * 0.037),
          bpjs_jp_employer: Math.round(contribution * 0.02),
          bpjs_jkk_employer: Math.round(contribution * 0.0024),
          bpjs_jkm_employer: Math.round(contribution * 0.003),
          employer_cost:
            Math.round(contribution * 0.04) +
            Math.round(contribution * 0.037) +
            Math.round(contribution * 0.02) +
            Math.round(contribution * 0.0024) +
            Math.round(contribution * 0.003),
          thr_months_bp: null,
          severance_pay: input.severance_pay,
          leave_payout: 0,
          notes: input.note ? [input.note] : [],
        };
      });
      const run: PayrollRun = {
        id: uuid(),
        kind: args.kind as PayrollRun["kind"],
        period,
        status: "computed",
        lines,
        anomalies: [],
        totals: {
          employees: lines.length,
          gross: lines.reduce((sum, line) => sum + line.gross, 0),
          net: lines.reduce((sum, line) => sum + line.net, 0),
          employee_deductions: lines.reduce((sum, line) => sum + line.total_deductions, 0),
          employer_cost: lines.reduce((sum, line) => sum + line.employer_cost, 0),
          pph21: 0,
        },
        rate_table_ids: [],
        created_at: now(),
        computed_at: now(),
        approved_at: null,
        approved_by: null,
        supersede_reason: null,
      };
      state.payroll.unshift(run);
      state.audit.push(makeAudit(state.audit.length, "payroll.computed", "payroll_run", period));
      return { run, blocking: 0 } as PayrollView as T;
    }
    case "export_payroll":
      requireSession();
      return 4096 as T;
    case "approve_payroll": {
      requireSession();
      const run = state.payroll.find((item) => item.id === String(args.run_id));
      if (!run) throw { code: "E_NOT_FOUND", message: "Payroll run not found" };
      run.status = "approved";
      run.approved_at = now();
      run.approved_by = "mock-operator";
      state.audit.push(makeAudit(state.audit.length, "payroll.approved", "payroll_run", run.period));
      return run as T;
    }
    case "payroll_runs":
      requireSession();
      return [...state.payroll] as T;
    case "payroll_run": {
      requireSession();
      const run = state.payroll.find((item) => item.id === String(args.run_id));
      if (!run) throw { code: "E_NOT_FOUND", message: "Payroll run not found" };
      return run as T;
    }
    case "list_approvals":
      requireSession();
      return (
        args.open_only ? state.approvals.filter((approval) => approval.status === "open") : state.approvals
      ) as T;
    case "audit_verify": {
      requireSession();
      return {
        entries: state.audit.length,
        head_hash: state.audit[state.audit.length - 1]?.entry_hash ?? null,
      } satisfies AuditVerification as T;
    }
    case "audit_recent":
      requireSession();
      return [...state.audit].reverse().slice(0, Number(args.limit ?? 20)) as T;
    case "search": {
      requireSession();
      const query = String(args.query ?? "").toLowerCase();
      if (!query) return [] as SearchHit[] as T;
      const hits: SearchHit[] = [
        ...state.employees
          .filter((employee) => employee.full_name.toLowerCase().includes(query) || employee.job_title.toLowerCase().includes(query))
          .map((employee) => ({
            kind: "employee",
            id: employee.id,
            title: employee.full_name,
            subtitle: `${employee.job_title} · ${employee.org_unit}`,
          })),
        ...state.candidates
          .filter((candidate) => candidate.full_name.toLowerCase().includes(query))
          .map((candidate) => ({
            kind: "candidate",
            id: candidate.id,
            title: candidate.full_name,
            subtitle: candidate.headline ?? candidate.source,
          })),
      ];
      return hits as T;
    }
    case "backup":
      requireSession();
      return 622592 as T;
    case "evaluate_input_schema":
      return {} as T;
    default:
      throw { code: "E_UNKNOWN_COMMAND", message: `Unknown command: ${name}` };
  }
}

export const demoState = state;
