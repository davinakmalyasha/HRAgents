import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Database,
  LockKeyhole,
  Play,
  ShieldCheck,
  Wallet,
} from "lucide-react";
import { businessMonthStart, command, formatIdr } from "../api";
import type {
  Employee,
  PayrollInput,
  PayrollRun,
  PayrollView,
  PayslipView,
  RateTable,
  SessionView,
} from "../types";
import { ErrorBox, Field, Modal, StatusPill, errorMessage } from "../components/ui";

export function Pay({ session }: { session: SessionView }) {
  const queryClient = useQueryClient();
  const [selectedRun, setSelectedRun] = useState<string | null>(null);
  const [employeeId, setEmployeeId] = useState("");
  const [baseSalary, setBaseSalary] = useState("10000000");
  const [allowances, setAllowances] = useState("2000000");
  const [serviceMonths, setServiceMonths] = useState("30");
  const [period, setPeriod] = useState(businessMonthStart());
  const [kind, setKind] = useState<PayrollRun["kind"]>("monthly");
  const [approveOpen, setApproveOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const employees = useQuery({ queryKey: ["employees"], queryFn: () => command<Employee[]>("list_employees") });
  const runs = useQuery({ queryKey: ["payroll-runs"], queryFn: () => command<PayrollRun[]>("payroll_runs") });
  const tables = useQuery({ queryKey: ["rate-tables"], queryFn: () => command<RateTable[]>("rate_tables") });

  const activeRun = useMemo(() => {
    const list = runs.data ?? [];
    return list.find((run) => run.id === selectedRun) ?? list[0] ?? null;
  }, [runs.data, selectedRun]);

  const required = new Set(["bpjs_kesehatan", "bpjs_ketenagakerjaan_jht", "bpjs_ketenagakerjaan_jp", "bpjs_jkk", "bpjs_jkm", "pph21_ter", "pph21_ptkp"]);
  const verifiedTables = (tables.data ?? []).filter((table) => table.verified && required.has(table.kind)).length;

  async function seedRates() {
    setBusy(true);
    setError(null);
    try {
      await command("seed_demo_rate_tables", { effective_from: "2026-01-01" });
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["rate-tables"] }),
        queryClient.invalidateQueries({ queryKey: ["today"] }),
      ]);
    } catch (caught) {
      setError(message(caught));
    } finally {
      setBusy(false);
    }
  }

  async function compute(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const employee = (employees.data ?? []).find((item) => item.id === employeeId) ?? employees.data?.[0];
      if (!employee) throw new Error("Add an employee first");
      const rupiah = (value: string) => Math.round(Number(value) * 100);
      const input: PayrollInput = {
        employee_id: employee.id,
        employee_name: employee.full_name,
        base_salary: rupiah(baseSalary),
        fixed_allowances: rupiah(allowances),
        variable_allowances: 0,
        overtime_minutes: 0,
        absence_days: 0,
        working_days: 22,
        bonus: 0,
        other_deductions: 0,
        loan_deduction: 0,
        service_months: Number(serviceMonths),
        severance_pay: 0,
        unused_leave_days_x2: 0,
        leave_payout_per_day: 0,
        note: null,
      };
      const view = await command<PayrollView>("compute_payroll", {
        kind,
        period,
        inputs: [input],
      });
      setSelectedRun(view.run.id);
      if (view.blocking > 0) {
        setError(`${view.blocking} blocking anomaly(ies). Resolve them before sign-off.`);
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["payroll-runs"] }),
        queryClient.invalidateQueries({ queryKey: ["today"] }),
        queryClient.invalidateQueries({ queryKey: ["approvals"] }),
      ]);
    } catch (caught) {
      setError(message(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Pay</h1>
          <p>Prepare, reconcile, and sign off. This app never executes a payment.</p>
        </div>
        <div className="page-actions">
          <span className={`pill ${verifiedTables >= 7 ? "ok" : "warn"}`}>
            {verifiedTables >= 7 ? <CheckCircle2 size={11} /> : <AlertTriangle size={11} />}
            {verifiedTables >= 7 ? "rate tables verified" : `${verifiedTables}/7 tables verified`}
          </span>
        </div>
      </div>

      {error ? <ErrorBox>{error}</ErrorBox> : null}

      {verifiedTables < 7 ? (
        <div className="notice" style={{ marginBottom: 16 }}>
          <Database size={15} />
          <div style={{ flex: 1 }}>
            Statutory tables are operator-maintained. Payroll refuses to compute until they are entered,
            effective-dated, and verified. The demo fixture can seed the shape, but real installs must
            verify every figure against the current regulation.
          </div>
          <button className="btn sm" onClick={seedRates} disabled={busy}>
            Seed demo tables
          </button>
        </div>
      ) : null}

      <div className="split">
        <div className="grid" style={{ alignContent: "start" }}>
          <section className="card">
            <div className="card-head">
              <h2>New run</h2>
              <span className="sub">monthly, THR, final, adjustment</span>
            </div>
            <form className="card-pad grid" style={{ gap: 12 }} onSubmit={compute}>
              <Field label="Employee">
                <select value={employeeId || employees.data?.[0]?.id || ""} onChange={(event) => setEmployeeId(event.target.value)}>
                  {(employees.data ?? []).map((employee) => (
                    <option key={employee.id} value={employee.id}>{employee.full_name}</option>
                  ))}
                </select>
              </Field>
              <div className="form-grid">
                <Field label="Base salary (IDR)">
                  <input type="number" value={baseSalary} onChange={(event) => setBaseSalary(event.target.value)} />
                </Field>
                <Field label="Fixed allowances (IDR)">
                  <input type="number" value={allowances} onChange={(event) => setAllowances(event.target.value)} />
                </Field>
                <Field label="Service months">
                  <input type="number" value={serviceMonths} onChange={(event) => setServiceMonths(event.target.value)} />
                </Field>
                <Field label="Kind">
                  <select value={kind} onChange={(event) => setKind(event.target.value as PayrollRun["kind"])}>
                    <option value="monthly">Monthly</option>
                    <option value="thr">THR / termination</option>
                    <option value="final">Final settlement</option>
                    <option value="adjustment">Adjustment</option>
                  </select>
                </Field>
                <Field label="Period" span>
                  <input type="date" value={period} onChange={(event) => setPeriod(event.target.value)} />
                </Field>
              </div>
              <button className="btn primary" type="submit" disabled={busy || verifiedTables < 7}>
                <Play size={15} /> {busy ? "Computing…" : "Compute run"}
              </button>
              <div className="small faint">
                Payroll is integer sen end to end. Rounding is half away from zero, once, and invariants
                reconcile gross, deductions, net, and employer cost.
              </div>
            </form>
          </section>

          <section className="card" style={{ overflow: "hidden" }}>
            <div className="card-head">
              <h2>Runs</h2>
              <span className="sub">{(runs.data ?? []).length}</span>
            </div>
            {(runs.data ?? []).length === 0 ? (
              <div className="empty"><div className="small">No payroll runs yet.</div></div>
            ) : (
              (runs.data ?? []).map((run) => (
                <button
                  key={run.id}
                  className="list-row"
                  style={{
                    width: "100%",
                    border: 0,
                    borderBottom: "1px solid var(--line)",
                    background: activeRun?.id === run.id ? "var(--surface-muted)" : "transparent",
                    textAlign: "left",
                    cursor: "pointer",
                  }}
                  onClick={() => setSelectedRun(run.id)}
                >
                  <span className="icon-box"><Wallet size={15} /></span>
                  <span className="grow">
                    <span className="title" style={{ display: "block" }}>{run.kind} · {run.period.slice(0, 7)}</span>
                    <span className="meta" style={{ display: "block" }}>{run.totals.employees} employee(s) · net {formatIdr(run.totals.net)}</span>
                  </span>
                  <StatusPill
                    tone={run.status === "approved" ? "ok" : run.status === "computed" ? "info" : "neutral"}
                    label={run.status}
                  />
                </button>
              ))
            )}
          </section>
        </div>

        <section className="card">
          {activeRun ? (
            <RunDetail
              run={activeRun}
              onApprove={() => setApproveOpen(true)}
              onExport={() => setExportOpen(true)}
              busy={busy}
            />
          ) : (
            <div className="empty" style={{ padding: "70px 24px" }}>
              <div className="icon"><Wallet size={18} /></div>
              <div style={{ fontWeight: 600, color: "var(--ink)" }}>No run selected</div>
              <div className="small" style={{ marginTop: 4 }}>Compute a run to review lines, anomalies, and totals.</div>
            </div>
          )}
        </section>
      </div>

      {exportOpen && activeRun ? (
        <ExportDialog
          run={activeRun}
          onClose={() => setExportOpen(false)}
        />
      ) : null}

      {approveOpen && activeRun ? (
        <ApproveDialog
          run={activeRun}
          session={session}
          onClose={() => setApproveOpen(false)}
          onApproved={async () => {
            setApproveOpen(false);
            await Promise.all([
              queryClient.invalidateQueries({ queryKey: ["payroll-runs"] }),
              queryClient.invalidateQueries({ queryKey: ["today"] }),
              queryClient.invalidateQueries({ queryKey: ["approvals"] }),
            ]);
          }}
        />
      ) : null}
    </>
  );
}

function RunDetail({
  run,
  onApprove,
  onExport,
  busy,
}: {
  run: PayrollRun;
  onApprove: () => void;
  onExport: () => void;
  busy: boolean;
}) {
  const blocking = run.anomalies.filter((anomaly) => anomaly.severity === "error").length;
  const [payslipFor, setPayslipFor] = useState<string | null>(null);
  return (
    <>
      <div className="card-pad" style={{ borderBottom: "1px solid var(--line)" }}>
        <div className="row" style={{ alignItems: "flex-start" }}>
          <div>
            <div className="row" style={{ gap: 8 }}>
              <h2 style={{ margin: 0, fontSize: 20, letterSpacing: "-0.03em" }}>
                {run.kind} · {run.period.slice(0, 7)}
              </h2>
              <StatusPill tone={run.status === "approved" ? "ok" : "info"} label={run.status} />
            </div>
            <div className="muted" style={{ marginTop: 3 }}>
              {run.totals.employees} employee(s) · {run.lines.length} line(s)
            </div>
          </div>
          <div style={{ marginLeft: "auto", textAlign: "right" }}>
            <div className="small faint">Net pay</div>
            <div style={{ fontSize: 23, fontWeight: 650, letterSpacing: "-0.03em" }}>{formatIdr(run.totals.net)}</div>
          </div>
        </div>
        <div className="grid three-col" style={{ marginTop: 16 }}>
          <MiniStat label="Gross" value={formatIdr(run.totals.gross)} />
          <MiniStat label="Employee deductions" value={formatIdr(run.totals.employee_deductions)} />
          <MiniStat label="Employer cost" value={formatIdr(run.totals.employer_cost)} />
        </div>
        <div className="row" style={{ marginTop: 15, gap: 8 }}>
          <button className="btn primary" onClick={onApprove} disabled={busy || run.status !== "computed" || blocking > 0}>
            <LockKeyhole size={14} /> Sign off payroll
          </button>
          <button className="btn" onClick={onExport} disabled={busy}>
            Export review packet
          </button>
          <span className="small faint" style={{ marginLeft: "auto" }}>
            {blocking > 0 ? `${blocking} blocking anomaly(ies)` : "No blocking anomalies"}
          </span>
        </div>
      </div>

      {run.anomalies.length > 0 ? (
        <div className="card-pad" style={{ borderBottom: "1px solid var(--line)" }}>
          <div style={{ fontWeight: 600, marginBottom: 7 }}>Anomalies</div>
          <div className="grid" style={{ gap: 7 }}>
            {run.anomalies.map((anomaly, index) => (
              <div
                key={`${anomaly.code}-${index}`}
                className="row"
                style={{ alignItems: "flex-start", gap: 8, fontSize: 12.5, color: anomaly.severity === "error" ? "var(--danger)" : "var(--warning)" }}
              >
                <AlertTriangle size={14} style={{ marginTop: 2, flex: "0 0 auto" }} />
                <div>
                  <span className="mono">{anomaly.code}</span> · {anomaly.detail}
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      <div className="table" style={{ overflowX: "auto" }}>
        <table className="table">
          <thead>
            <tr>
              <th scope="col">Employee</th>
              <th scope="col" className="num">Gross</th>
              <th scope="col" className="num">BPJS</th>
              <th scope="col" className="num">PPh 21</th>
              <th scope="col" className="num">Deductions</th>
              <th scope="col" className="num">Net</th>
              <th scope="col" className="num">Payslip</th>
            </tr>
          </thead>
          <tbody>
            {run.lines.map((line) => (
              <tr key={line.employee_id}>
                <td>
                  <div style={{ fontWeight: 550 }}>{line.employee_name}</div>
                  <div className="small muted">base {formatIdr(line.base_salary)}</div>
                </td>
                <td className="num">{formatIdr(line.gross)}</td>
                <td className="num">
                  {formatIdr(
                    line.bpjs_kesehatan_employee + line.bpjs_jht_employee + line.bpjs_jp_employee,
                  )}
                </td>
                <td className="num">{formatIdr(line.pph21)}</td>
                <td className="num">{formatIdr(line.total_deductions)}</td>
                <td className="num" style={{ fontWeight: 650 }}>{formatIdr(line.net)}</td>
                <td className="num">
                  <button
                    className="btn ghost sm"
                    onClick={() => setPayslipFor(line.employee_id)}
                    aria-label={`View payslip for ${line.employee_name}`}
                  >
                    View
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card-pad small muted" style={{ borderTop: "1px solid var(--line)" }}>
        <span className="row" style={{ gap: 6 }}>
          <ShieldCheck size={13} /> No payment execution. Export is a review packet for payroll/finance.
        </span>
      </div>

      {payslipFor ? (
        <PayslipModal
          runId={run.id}
          employeeId={payslipFor}
          onClose={() => setPayslipFor(null)}
        />
      ) : null}
    </>
  );
}

function PayslipModal({
  runId,
  employeeId,
  onClose,
}: {
  runId: string;
  employeeId: string;
  onClose: () => void;
}) {
  const payslip = useQuery({
    queryKey: ["payslip", runId, employeeId],
    queryFn: () => command<PayslipView>("payslip", { run_id: runId, employee_id: employeeId }),
  });
  const data = payslip.data;
  return (
    <Modal
      title="Payslip"
      subtitle={data ? `${data.kind} · ${data.period.slice(0, 7)} · read-only` : "Loading payroll line…"}
      onClose={onClose}
      wide
    >
      {payslip.isLoading ? <div className="empty">Loading payslip…</div> : null}
      {payslip.isError ? <ErrorBox>{errorMessage(payslip.error)}</ErrorBox> : null}
      {data ? (
        <div className="grid" style={{ gap: 16 }}>
          <div className="row" style={{ alignItems: "flex-start", gap: 12 }}>
            <div>
              <div className="small faint">{data.company ?? "Company"}</div>
              <div style={{ fontSize: 19, fontWeight: 650, letterSpacing: "-0.02em" }}>
                {data.employee_name}
              </div>
              <div className="small muted">
                {[data.employee_no, data.job_title].filter(Boolean).join(" · ") || "Employee"}
              </div>
            </div>
            <div style={{ marginLeft: "auto", textAlign: "right" }}>
              <StatusPill
                tone={data.status === "approved" ? "ok" : data.status === "computed" ? "info" : "neutral"}
                label={data.status}
              />
              <div className="small faint" style={{ marginTop: 4 }}>
                {data.kind} · {data.period.slice(0, 7)}
              </div>
            </div>
          </div>

          <PayslipSection title="Earnings" items={data.earnings} total={data.gross} totalLabel="Gross pay" />
          <PayslipSection
            title="Employee deductions"
            items={data.deductions}
            total={data.total_deductions}
            totalLabel="Total deductions"
          />

          <div className="row" style={{ borderTop: "1px solid var(--line)", paddingTop: 12, justifyContent: "space-between" }}>
            <div style={{ fontWeight: 650 }}>Take-home pay</div>
            <div style={{ fontWeight: 700, fontSize: 18 }}>{formatIdr(data.net)}</div>
          </div>

          <div>
            <div className="small faint" style={{ marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.06em", fontSize: 10.5 }}>
              Employer contributions (not deducted)
            </div>
            {data.employer_contributions.length === 0 ? (
              <div className="small muted">No employer contributions on this line.</div>
            ) : (
              data.employer_contributions.map((item) => (
                <div className="row small" key={item.label} style={{ justifyContent: "space-between", padding: "3px 0" }}>
                  <span className="muted">{item.label}</span>
                  <span className="mono">{formatIdr(item.amount)}</span>
                </div>
              ))
            )}
            <div className="row small" style={{ justifyContent: "space-between", borderTop: "1px solid var(--line)", marginTop: 6, paddingTop: 6, fontWeight: 600 }}>
              <span>Employer cost</span>
              <span className="mono">{formatIdr(data.employer_cost)}</span>
            </div>
          </div>

          {data.notes.length > 0 ? (
            <div>
              <div className="small faint" style={{ marginBottom: 4 }}>Notes</div>
              {data.notes.map((note) => (
                <div className="small muted" key={note}>· {note}</div>
              ))}
            </div>
          ) : null}

          <div className="small faint">
            Reconciled from the stored payroll line. Read-only; this app never executes a payment.
          </div>
        </div>
      ) : null}
    </Modal>
  );
}

function PayslipSection({
  title,
  items,
  total,
  totalLabel,
}: {
  title: string;
  items: { label: string; amount: number }[];
  total: number;
  totalLabel: string;
}) {
  return (
    <div>
      <div className="small faint" style={{ marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.06em", fontSize: 10.5 }}>
        {title}
      </div>
      {items.length === 0 ? (
        <div className="small muted">None on this line.</div>
      ) : (
        items.map((item) => (
          <div className="row small" key={item.label} style={{ justifyContent: "space-between", padding: "3px 0" }}>
            <span className="muted">{item.label}</span>
            <span className="mono">{formatIdr(item.amount)}</span>
          </div>
        ))
      )}
      <div className="row small" style={{ justifyContent: "space-between", borderTop: "1px solid var(--line)", marginTop: 6, paddingTop: 6, fontWeight: 600 }}>
        <span>{totalLabel}</span>
        <span className="mono">{formatIdr(total)}</span>
      </div>
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="card card-pad" style={{ boxShadow: "none" }}>
      <div className="small faint">{label}</div>
      <div style={{ fontWeight: 620, marginTop: 3 }}>{value}</div>
    </div>
  );
}

function ApproveDialog({
  run,
  session,
  onClose,
  onApproved,
}: {
  run: PayrollRun;
  session: SessionView;
  onClose: () => void;
  onApproved: () => Promise<void>;
}) {
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await command("reauth", { password });
      await command("approve_payroll", { run_id: run.id });
      await onApproved();
    } catch (caught) {
      setError(message(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      title="Sign off this payroll run"
      subtitle={`${run.kind} ${run.period.slice(0, 7)} · ${run.totals.employees} employee(s)`}
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose} type="button">Cancel</button>
          <button className="btn primary" form="approve-form" type="submit" disabled={busy || !password}>
            {busy ? "Signing…" : "Approve and freeze"}
            <ArrowRight size={15} />
          </button>
        </>
      }
    >
      <form id="approve-form" onSubmit={submit} className="grid" style={{ gap: 12 }}>
        <div className="notice">
          <LockKeyhole size={15} />
          <div>
            Sign-off requires a fresh password. The run becomes immutable, the actor is{" "}
            <strong>{session.display_name}</strong>, and the audit receipt records the totals and payload
            hash. Corrections after this point supersede the run with a reason.
          </div>
        </div>
        <div className="detail-grid">
          <div className="fact"><div className="k">Gross</div><div className="v">{formatIdr(run.totals.gross)}</div></div>
          <div className="fact"><div className="k">Net</div><div className="v">{formatIdr(run.totals.net)}</div></div>
        </div>
        <Field label="Confirm your password">
          <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoFocus />
        </Field>
        {error ? <ErrorBox>{error}</ErrorBox> : null}
      </form>
    </Modal>
  );
}

function message(caught: unknown): string {
  if (typeof caught === "object" && caught && "message" in caught) {
    return String((caught as { message: unknown }).message);
  }
  return String(caught);
}


function ExportDialog({ run, onClose }: { run: PayrollRun; onClose: () => void }) {
  const [path, setPath] = useState(`payroll-${run.period.slice(0, 7)}.xlsx`);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const size = await command<number>("export_payroll", { run_id: run.id, path });
      setResult(`Wrote ${(size / 1024).toFixed(1)} KB to ${path}`);
    } catch (caught) {
      setError(message(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      title="Export the payroll review packet"
      subtitle={`${run.kind} ${run.period.slice(0, 7)} · ${run.totals.employees} employee(s)`}
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose} type="button">Close</button>
          <button className="btn primary" form="export-form" type="submit" disabled={busy || !path}>
            {busy ? "Writing…" : "Write XLSX"}
          </button>
        </>
      }
    >
      <form id="export-form" onSubmit={submit} className="grid" style={{ gap: 12 }}>
        <div className="notice">
          <ShieldCheck size={15} />
          <div>
            This is a review packet for payroll/finance, not a bank instruction. The workbook contains
            a summary sheet and one line per employee. The export is written to the audit chain.
          </div>
        </div>
        <Field label="Destination path" hint="Absolute path on this machine. In browser preview the file is simulated.">
          <input value={path} onChange={(event) => setPath(event.target.value)} autoFocus />
        </Field>
        {result ? (
          <div className="row small" style={{ gap: 6, color: "var(--success)" }}>
            <CheckCircle2 size={13} /> {result}
          </div>
        ) : null}
        {error ? <ErrorBox>{error}</ErrorBox> : null}
      </form>
    </Modal>
  );
}
