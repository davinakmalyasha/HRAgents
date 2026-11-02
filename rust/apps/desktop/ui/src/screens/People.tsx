import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  CalendarDays,
  Check,
  ChevronRight,
  FileText,
  Mail,
  Plus,
  UserPlus,
  Users,
} from "lucide-react";
import { businessToday, command, formatDate, formatDays } from "../api";
import type {
  Employee,
  LeaveBalance,
  LeaveRequest,
  LeaveType,
  LeaveView,
  OnboardingPlan,
} from "../types";
import { Avatar, EmptyState, ErrorBox, Field, Modal, StatusPill } from "../components/ui";
import { GrowthTab, OffboardingTab } from "./PeopleGrowth";
import { DocumentRequests, DocumentVault } from "./Documents";

type Tab = "overview" | "onboarding" | "leave" | "growth" | "offboarding" | "documents";

export function People() {
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [tab, setTab] = useState<Tab>("overview");
  const [error, setError] = useState<string | null>(null);

  const employees = useQuery({ queryKey: ["employees"], queryFn: () => command<Employee[]>("list_employees") });
  const active = useMemo(() => {
    const list = employees.data ?? [];
    return list.find((employee) => employee.id === selectedId) ?? list[0] ?? null;
  }, [employees.data, selectedId]);

  const onboarding = useQuery({
    queryKey: ["onboarding", active?.id],
    queryFn: () => command<OnboardingPlan | null>("onboarding_for", { employee_id: active?.id }),
    enabled: Boolean(active),
  });

  return (
    <>
      <div className="page-head">
        <div>
          <h1>People</h1>
          <p>Directory, contracts, onboarding, leave, and the payroll profile — one record per person.</p>
        </div>
        <div className="page-actions">
          <button className="btn primary" onClick={() => setCreateOpen(true)}>
            <UserPlus size={15} /> Add employee
          </button>
        </div>
      </div>

      {error ? <ErrorBox>{error}</ErrorBox> : null}

      <div className="split">
        <section className="card" style={{ overflow: "hidden" }}>
          <div className="card-head">
            <h2>Directory</h2>
            <span className="sub">{(employees.data ?? []).length} people</span>
          </div>
          <div className="scroll-list">
            {(employees.data ?? []).length === 0 ? (
              <EmptyState title="No employees yet" body="Add the first person to open a record and start onboarding." />
            ) : (
              (employees.data ?? []).map((employee) => (
                <button
                  key={employee.id}
                  className="list-row"
                  style={{
                    width: "100%",
                    border: 0,
                    borderBottom: "1px solid var(--line)",
                    background: active?.id === employee.id ? "var(--surface-muted)" : "transparent",
                    textAlign: "left",
                    cursor: "pointer",
                  }}
                  onClick={() => {
                    setSelectedId(employee.id);
                    setTab("overview");
                  }}
                >
                  <Avatar name={employee.full_name} />
                  <span className="grow">
                    <span className="title" style={{ display: "block" }}>{employee.full_name}</span>
                    <span className="meta" style={{ display: "block" }}>{employee.job_title}</span>
                  </span>
                  <ChevronRight size={15} className="faint" />
                </button>
              ))
            )}
          </div>
        </section>

        <section className="card">
          {active ? (
            <>
              <div className="card-pad" style={{ borderBottom: "1px solid var(--line)" }}>
                <div className="row" style={{ alignItems: "flex-start" }}>
                  <Avatar name={active.full_name} size={44} />
                  <div>
                    <div className="row" style={{ gap: 8 }}>
                      <h2 style={{ margin: 0, fontSize: 21, letterSpacing: "-0.03em" }}>{active.full_name}</h2>
                      <StatusPill
                        tone={active.status === "active" ? "ok" : active.status === "notice" ? "warn" : "neutral"}
                        label={active.status}
                      />
                    </div>
                    <div className="muted" style={{ marginTop: 2 }}>
                      {active.job_title} · {active.org_unit} · {active.employee_no}
                    </div>
                    <div className="row small muted" style={{ gap: 14, marginTop: 7 }}>
                      {active.email ? <span className="row" style={{ gap: 5 }}><Mail size={12} />{active.email}</span> : null}
                      <span>Joined {formatDate(active.hire_date)}</span>
                    </div>
                  </div>
                  <div style={{ marginLeft: "auto", textAlign: "right" }}>
                    <div className="faint small">Payroll profile</div>
                    <div style={{ fontWeight: 600 }}>
                      {active.jkk_risk_class ? `JKK class ${active.jkk_risk_class}` : "JKK not set"}
                    </div>
                    <div className="small muted">{active.ptkp_status ?? "PTKP not set"} · {active.dependents} dependent(s)</div>
                  </div>
                </div>
              </div>

              <div className="tabs">
                <button className={`tab ${tab === "overview" ? "active" : ""}`} onClick={() => setTab("overview")}>Overview</button>
                <button className={`tab ${tab === "onboarding" ? "active" : ""}`} onClick={() => setTab("onboarding")}>
                  Onboarding {onboarding.data ? `(${onboarding.data.steps.filter((step) => step.status === "done").length}/${onboarding.data.steps.length})` : ""}
                </button>
                <button className={`tab ${tab === "leave" ? "active" : ""}`} onClick={() => setTab("leave")}>Leave</button>
                <button className={`tab ${tab === "growth" ? "active" : ""}`} onClick={() => setTab("growth")}>Growth</button>
                <button className={`tab ${tab === "offboarding" ? "active" : ""}`} onClick={() => setTab("offboarding")}>Offboarding</button>
                <button className={`tab ${tab === "documents" ? "active" : ""}`} onClick={() => setTab("documents")}>Documents</button>
              </div>

              <div className="card-pad">
                {tab === "overview" ? <Overview employee={active} /> : null}
                {tab === "onboarding" ? (
                  <OnboardingTab
                    employee={active}
                    plan={onboarding.data ?? null}
                    onChange={async () => {
                      await queryClient.invalidateQueries({ queryKey: ["onboarding", active.id] });
                      await queryClient.invalidateQueries({ queryKey: ["today"] });
                    }}
                    onError={setError}
                  />
                ) : null}
                {tab === "leave" ? <LeaveTab employee={active} onError={setError} /> : null}
                {tab === "growth" ? <GrowthTab employee={active} onError={setError} /> : null}
                {tab === "offboarding" ? <OffboardingTab employee={active} onError={setError} /> : null}
                {tab === "documents" ? (
                  <div className="grid" style={{ gap: 18 }}>
                    <DocumentVault ownerType="employee" ownerId={active.id} ownerLabel={active.full_name} onError={setError} />
                    <DocumentRequests employeeId={active.id} employeeName={active.full_name} onError={setError} />
                  </div>
                ) : null}
              </div>
            </>
          ) : (
            <div className="empty" style={{ padding: "70px 24px" }}>
              <div className="icon"><Users size={18} /></div>
              <div style={{ fontWeight: 600, color: "var(--ink)" }}>No person selected</div>
              <div className="small" style={{ marginTop: 4 }}>Add an employee to open the first record.</div>
            </div>
          )}
        </section>
      </div>

      {createOpen ? (
        <CreateEmployeeDialog
          onClose={() => setCreateOpen(false)}
          onCreated={async (employee) => {
            setCreateOpen(false);
            setSelectedId(employee.id);
            setTab("overview");
            await queryClient.invalidateQueries({ queryKey: ["employees"] });
            await queryClient.invalidateQueries({ queryKey: ["today"] });
          }}
        />
      ) : null}
    </>
  );
}

function Overview({ employee }: { employee: Employee }) {
  return (
    <div className="grid" style={{ gap: 18 }}>
      <div className="detail-grid">
        <Fact k="Employee number" v={employee.employee_no} />
        <Fact k="Employment" v={employee.status} />
        <Fact k="Hire date" v={formatDate(employee.hire_date)} />
        <Fact k="Org unit" v={employee.org_unit} />
        <Fact k="PTKP status" v={employee.ptkp_status ?? "Not set"} />
        <Fact k="Dependents" v={String(employee.dependents)} />
        <Fact k="BPJS JKK class" v={employee.jkk_risk_class ? `Class ${employee.jkk_risk_class}` : "Not set"} />
        <Fact k="Bank" v={employee.bank_name ? `${employee.bank_name} · ${employee.bank_account ?? ""}` : "Not set"} />
        <Fact k="BPJS Kesehatan" v={employee.bpjs_kesehatan_no ?? "Not set"} />
        <Fact k="BPJS Ketenagakerjaan" v={employee.bpjs_ketenagakerjaan_no ?? "Not set"} />
      </div>
      <div className="notice">
        <FileText size={15} />
        <div>
          Documents, contracts, and compensation live on this record. None of them are visible to an
          employee or manager, because this edition has no employee or manager login.
        </div>
      </div>
    </div>
  );
}

function OnboardingTab({
  employee,
  plan,
  onChange,
  onError,
}: {
  employee: Employee;
  plan: OnboardingPlan | null;
  onChange: () => Promise<void>;
  onError: (error: string | null) => void;
}) {
  const [busy, setBusy] = useState(false);

  async function start() {
    setBusy(true);
    onError(null);
    try {
      await command("start_onboarding", { employee_id: employee.id, template: null });
      await onChange();
    } catch (caught) {
      onError(typeof caught === "object" && caught && "message" in caught ? String((caught as { message: unknown }).message) : String(caught));
    } finally {
      setBusy(false);
    }
  }

  async function complete(stepKey: string) {
    setBusy(true);
    onError(null);
    try {
      await command("complete_onboarding_step", { employee_id: employee.id, step_key: stepKey });
      await onChange();
    } catch (caught) {
      onError(typeof caught === "object" && caught && "message" in caught ? String((caught as { message: unknown }).message) : String(caught));
    } finally {
      setBusy(false);
    }
  }

  if (!plan) {
    return (
      <div className="empty" style={{ padding: "34px 12px" }}>
        <div className="icon"><Check size={18} /></div>
        <div style={{ fontWeight: 600, color: "var(--ink)" }}>No onboarding plan</div>
        <div className="small" style={{ marginTop: 4, marginBottom: 12 }}>
          Start a six-step plan for {employee.full_name} and chase the next required step.
        </div>
        <button className="btn primary" onClick={start} disabled={busy}>
          <Plus size={15} /> Start onboarding
        </button>
      </div>
    );
  }

  return (
    <div>
      <div className="row" style={{ justifyContent: "space-between", marginBottom: 8 }}>
        <div>
          <div style={{ fontWeight: 620 }}>{plan.template_name}</div>
          <div className="small muted">
            {plan.steps.filter((step) => step.status === "done").length} of {plan.steps.length} steps complete
          </div>
        </div>
        <StatusPill tone={plan.status === "completed" ? "ok" : "info"} label={plan.status.replaceAll("_", " ")} />
      </div>
      <div className="bar" style={{ marginBottom: 12 }}>
        <span style={{ width: `${(plan.steps.filter((step) => step.status === "done").length / plan.steps.length) * 100}%` }} />
      </div>
      {plan.steps.map((step) => (
        <div className="check-step" key={step.key}>
          <button
            className={`check ${step.status === "done" ? "done" : ""}`}
            onClick={() => (step.status === "done" ? undefined : complete(step.key))}
            disabled={busy || step.status === "done" || plan.status === "completed"}
            aria-label={step.status === "done" ? `${step.title} complete` : `Mark ${step.title} complete`}
          >
            {step.status === "done" ? <Check size={13} /> : null}
          </button>
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 550 }}>{step.title}</div>
            <div className="small muted">
              {step.category} · {step.completed_by ? `completed by ${step.completed_by}` : "waiting on HR"}
            </div>
          </div>
          <StatusPill tone={step.status === "done" ? "ok" : step.status === "skipped" ? "warn" : "neutral"} label={step.status} />
        </div>
      ))}
      {plan.status === "completed" ? (
        <div className="notice" style={{ marginTop: 12 }}>
          <Check size={15} />
          <div>Onboarding complete. The completion and each step are on the audit chain.</div>
        </div>
      ) : null}
    </div>
  );
}

function LeaveTab({ employee, onError }: { employee: Employee; onError: (error: string | null) => void }) {
  const queryClient = useQueryClient();
  const [days, setDays] = useState("2");
  const [start, setStart] = useState(businessToday());
  const [end, setEnd] = useState(businessToday());
  const [reason, setReason] = useState("");
  const [leaveTypeId, setLeaveTypeId] = useState("");
  const [busy, setBusy] = useState(false);

  const year = new Date().getFullYear();
  const types = useQuery({ queryKey: ["leave-types"], queryFn: () => command<LeaveType[]>("list_leave_types") });
  const balances = useQuery({
    queryKey: ["leave-balances", year],
    queryFn: () => command<LeaveBalance[]>("leave_balances", { year }),
  });
  const requests = useQuery({
    queryKey: ["leave-requests"],
    queryFn: () => command<LeaveRequest[]>("list_leave_requests", { status: null }),
  });

  const employeeBalances = (balances.data ?? []).filter((balance) => balance.employee_id === employee.id);
  const employeeRequests = (requests.data ?? []).filter((request) => request.employee_id === employee.id);
  const effectiveType = leaveTypeId || types.data?.[0]?.id || "";

  async function refresh() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["leave-balances"] }),
      queryClient.invalidateQueries({ queryKey: ["leave-requests"] }),
      queryClient.invalidateQueries({ queryKey: ["today"] }),
    ]);
  }

  async function ensureEntitlement() {
    if (!effectiveType) return;
    await command("set_leave_entitlement", {
      employee_id: employee.id,
      leave_type_id: effectiveType,
      year,
      days: 12,
    });
    await refresh();
  }

  async function record(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    onError(null);
    try {
      await command<LeaveView>("record_leave", {
        input: {
          employee_id: employee.id,
          leave_type_id: effectiveType,
          start_date: start,
          end_date: end,
          days_x2: Math.round(Number(days) * 2),
          reason,
        },
      });
      setReason("");
      await refresh();
    } catch (caught) {
      onError(typeof caught === "object" && caught && "message" in caught ? String((caught as { message: unknown }).message) : String(caught));
    } finally {
      setBusy(false);
    }
  }

  async function decide(request: LeaveRequest, approve: boolean) {
    setBusy(true);
    onError(null);
    try {
      await command<LeaveView>("decide_leave", {
        request_id: request.id,
        approve,
        note: approve ? "approved by HR" : "team coverage unavailable",
      });
      await refresh();
    } catch (caught) {
      onError(typeof caught === "object" && caught && "message" in caught ? String((caught as { message: unknown }).message) : String(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid" style={{ gap: 18 }}>
      <div>
        <div className="row" style={{ justifyContent: "space-between", marginBottom: 8 }}>
          <div style={{ fontWeight: 620 }}>Balances · {year}</div>
          {employeeBalances.length === 0 ? (
            <button className="btn sm" onClick={ensureEntitlement} disabled={!effectiveType || busy}>
              Set 12-day entitlement
            </button>
          ) : null}
        </div>
        {employeeBalances.length === 0 ? (
          <div className="small muted">No entitlement recorded for this year.</div>
        ) : (
          <div className="grid three-col">
            {employeeBalances.map((balance) => {
              const type = (types.data ?? []).find((item) => item.id === balance.leave_type_id);
              return (
                <div className="card card-pad" key={`${balance.leave_type_id}-${balance.year}`}>
                  <div className="small muted">{type?.name ?? "Leave"}</div>
                  <div style={{ fontSize: 24, fontWeight: 650, letterSpacing: "-0.03em" }}>
                    {formatDays(balance.entitled_x2 + balance.adjustment_x2 - balance.used_x2 - balance.pending_x2)}
                  </div>
                  <div className="small faint">
                    {formatDays(balance.used_x2)} used · {formatDays(balance.pending_x2)} pending
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <form onSubmit={record} className="grid" style={{ gap: 10 }}>
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div style={{ fontWeight: 620 }}>Record leave on behalf</div>
          <CalendarDays size={15} className="faint" />
        </div>
        <div className="form-grid">
          <Field label="Leave type">
            <select value={effectiveType} onChange={(event) => setLeaveTypeId(event.target.value)} required>
              {(types.data ?? []).map((type) => <option key={type.id} value={type.id}>{type.name}</option>)}
            </select>
          </Field>
          <Field label="Days">
            <input type="number" step="0.5" min="0.5" value={days} onChange={(event) => setDays(event.target.value)} />
          </Field>
          <Field label="Start">
            <input type="date" value={start} onChange={(event) => setStart(event.target.value)} />
          </Field>
          <Field label="End">
            <input type="date" value={end} onChange={(event) => setEnd(event.target.value)} />
          </Field>
          <Field label="Reason" span>
            <input value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Family event" required />
          </Field>
        </div>
        <div className="row">
          <button className="btn primary" type="submit" disabled={busy || !effectiveType || !reason}>
            <Plus size={15} /> Record request
          </button>
          <span className="small faint">HR records and decides; there is no employee self-service login.</span>
        </div>
      </form>

      <div>
        <div style={{ fontWeight: 620, marginBottom: 8 }}>Requests</div>
        {employeeRequests.length === 0 ? (
          <div className="small muted">No leave recorded for {employee.full_name}.</div>
        ) : (
          <div className="card">
            {employeeRequests.map((request) => (
              <div className="list-row" key={request.id}>
                <span className="icon-box"><CalendarDays size={15} /></span>
                <div className="grow">
                  <div className="title">{formatDate(request.start_date)} → {formatDate(request.end_date)}</div>
                  <div className="meta">{formatDays(request.days_x2)} · {request.reason}</div>
                </div>
                <StatusPill
                  tone={request.status === "approved" ? "ok" : request.status === "pending" ? "warn" : "bad"}
                  label={request.status}
                />
                {request.status === "pending" ? (
                  <span className="row" style={{ gap: 6 }}>
                    <button className="btn sm primary" onClick={() => decide(request, true)} disabled={busy}>Approve</button>
                    <button className="btn sm" onClick={() => decide(request, false)} disabled={busy}>Reject</button>
                  </span>
                ) : null}
              </div>
            ))}
          </div>
        )}
      </div>
      <div className="notice">
        <ArrowRight size={15} />
        <div>Approved leave reduces the balance and appears on the team calendar and audit chain.</div>
      </div>
    </div>
  );
}

function Fact({ k, v }: { k: string; v: string }) {
  return (
    <div className="fact">
      <div className="k">{k}</div>
      <div className="v">{v}</div>
    </div>
  );
}

function CreateEmployeeDialog({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (employee: Employee) => Promise<void>;
}) {
  const [employeeNo, setEmployeeNo] = useState("E-003");
  const [name, setName] = useState("");
  const [title, setTitle] = useState("");
  const [unit, setUnit] = useState("Product");
  const [email, setEmail] = useState("");
  const [hireDate, setHireDate] = useState(businessToday());
  const [dependents, setDependents] = useState("0");
  const [jkk, setJkk] = useState("1");
  const [bankName, setBankName] = useState("BCA");
  const [bankAccount, setBankAccount] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const employee = await command<Employee>("create_employee", {
        input: {
          employee_no: employeeNo,
          full_name: name,
          job_title: title,
          org_unit: unit,
          hire_date: hireDate,
          email: email || null,
          phone: null,
          ptkp_status: "TK/0",
          dependents: Number(dependents),
          jkk_risk_class: Number(jkk),
          bank_name: bankName,
          bank_account: bankAccount || null,
        },
      });
      await onCreated(employee);
    } catch (caught) {
      setError(typeof caught === "object" && caught && "message" in caught ? String((caught as { message: unknown }).message) : String(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      title="Add an employee"
      subtitle="The payroll profile is part of the record, so the first run does not guess."
      onClose={onClose}
      wide
      footer={
        <>
          <button className="btn" onClick={onClose} type="button">Cancel</button>
          <button className="btn primary" form="employee-form" type="submit" disabled={busy || !name || !title}>
            {busy ? "Saving…" : "Create record"}
            <ArrowRight size={15} />
          </button>
        </>
      }
    >
      <form id="employee-form" className="form-grid" onSubmit={submit}>
        <Field label="Employee number">
          <input value={employeeNo} onChange={(event) => setEmployeeNo(event.target.value)} required />
        </Field>
        <Field label="Full name">
          <input value={name} onChange={(event) => setName(event.target.value)} required autoFocus />
        </Field>
        <Field label="Job title">
          <input value={title} onChange={(event) => setTitle(event.target.value)} required />
        </Field>
        <Field label="Org unit">
          <input value={unit} onChange={(event) => setUnit(event.target.value)} required />
        </Field>
        <Field label="Email">
          <input type="email" value={email} onChange={(event) => setEmail(event.target.value)} />
        </Field>
        <Field label="Hire date">
          <input type="date" value={hireDate} onChange={(event) => setHireDate(event.target.value)} required />
        </Field>
        <Field label="Dependents" hint="Used for PTKP and PPh 21.">
          <input type="number" min="0" max="10" value={dependents} onChange={(event) => setDependents(event.target.value)} />
        </Field>
        <Field label="BPJS JKK risk class" hint="Required before payroll can compute the employer share.">
          <select value={jkk} onChange={(event) => setJkk(event.target.value)}>
            {[1, 2, 3, 4, 5].map((value) => <option key={value} value={value}>Class {value}</option>)}
          </select>
        </Field>
        <Field label="Bank">
          <input value={bankName} onChange={(event) => setBankName(event.target.value)} />
        </Field>
        <Field label="Bank account">
          <input value={bankAccount} onChange={(event) => setBankAccount(event.target.value)} />
        </Field>
        {error ? <div className="span-2"><ErrorBox>{error}</ErrorBox></div> : null}
      </form>
    </Modal>
  );
}
