import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Plus, ShieldCheck } from "lucide-react";
import { command, formatDateTime } from "../api";
import type {
  BreachIncident,
  ErasureRequest,
  RetentionDueItem,
  RetentionHold,
  RetentionPolicy,
} from "../types";
import { ErrorBox, Field, Modal, StatusPill } from "../components/ui";

function message(caught: unknown): string {
  if (typeof caught === "object" && caught && "message" in caught) {
    return String((caught as { message: unknown }).message);
  }
  return String(caught);
}

export function ComplianceSection({ onError }: { onError: (error: string | null) => void }) {
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [erasureOpen, setErasureOpen] = useState(false);
  const [breachOpen, setBreachOpen] = useState(false);
  const [holdOpen, setHoldOpen] = useState(false);
  const [executeOpen, setExecuteOpen] = useState<ErasureRequest | null>(null);

  const policies = useQuery({
    queryKey: ["retention-policies"],
    queryFn: () => command<RetentionPolicy[]>("list_retention_policies"),
  });
  const sweep = useQuery({
    queryKey: ["retention-sweep"],
    queryFn: () =>
      command<RetentionDueItem[]>("retention_sweep", {
        today: new Date().toISOString().slice(0, 10),
      }),
  });
  const holds = useQuery({
    queryKey: ["retention-holds"],
    queryFn: () => command<RetentionHold[]>("list_retention_holds"),
  });
  const erasures = useQuery({
    queryKey: ["erasure-requests"],
    queryFn: () => command<ErasureRequest[]>("list_erasure_requests"),
  });
  const breaches = useQuery({
    queryKey: ["breaches"],
    queryFn: () => command<BreachIncident[]>("list_breaches"),
  });

  async function refresh() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["retention-policies"] }),
      queryClient.invalidateQueries({ queryKey: ["retention-sweep"] }),
      queryClient.invalidateQueries({ queryKey: ["retention-holds"] }),
      queryClient.invalidateQueries({ queryKey: ["erasure-requests"] }),
      queryClient.invalidateQueries({ queryKey: ["breaches"] }),
      queryClient.invalidateQueries({ queryKey: ["today"] }),
      queryClient.invalidateQueries({ queryKey: ["candidates"] }),
    ]);
  }

  async function act(action: () => Promise<unknown>) {
    setBusy(true);
    onError(null);
    try {
      await action();
      await refresh();
    } catch (caught) {
      onError(message(caught));
    } finally {
      setBusy(false);
    }
  }

  const due = sweep.data ?? [];
  const unblocked = due.filter((item) => !item.blocked_by_hold);

  return (
    <div className="grid" style={{ gap: 18 }}>
      <section className="card">
        <div className="card-head">
          <ShieldCheck size={15} />
          <h2>Retention</h2>
          <span className="sub">
            {(policies.data ?? []).filter((policy) => policy.active).length} active policies ·{" "}
            {unblocked.length} due
          </span>
          <span style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
            {(policies.data ?? []).length === 0 ? (
              <button
                className="btn sm"
                disabled={busy}
                onClick={() => act(() => command("seed_retention_policies", {}))}
              >
                Seed default policies
              </button>
            ) : null}
            <button className="btn sm" disabled={busy} onClick={() => setHoldOpen(true)}>
              <Plus size={13} /> Hold
            </button>
          </span>
        </div>
        {(policies.data ?? []).length === 0 ? (
          <div className="card-pad small muted">
            No retention policies yet. Seed the defaults: candidates purge after 24 months, payroll
            archives after 10 years, audit rows are never erased.
          </div>
        ) : (
          <table className="table">
            <thead>
              <tr><th>Record</th><th>Keep</th><th>Then</th><th>Basis</th></tr>
            </thead>
            <tbody>
              {(policies.data ?? []).map((policy) => (
                <tr key={policy.id}>
                  <td>{policy.record_type.replaceAll("_", " ")}</td>
                  <td className="small">{policy.retention_months} months</td>
                  <td><StatusPill tone="info" label={policy.action} /></td>
                  <td className="small muted">{policy.legal_basis}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {due.length > 0 ? (
          <div className="card-pad" style={{ borderTop: "1px solid var(--line)" }}>
            <div style={{ fontWeight: 600, marginBottom: 6 }}>Due under policy</div>
            {due.map((item) => (
              <div className="list-row" key={`${item.record_type}-${item.subject_id}`}>
                <span className={`icon-box ${item.blocked_by_hold ? "warn" : ""}`}>
                  <AlertTriangle size={15} />
                </span>
                <div className="grow">
                  <div className="title">{item.subject_name}</div>
                  <div className="meta">
                    {item.record_type} · created {item.record_created} · due {item.due_on} ·{" "}
                    {item.action}
                  </div>
                </div>
                {item.blocked_by_hold ? (
                  <StatusPill tone="warn" label="on hold" />
                ) : (
                  <StatusPill tone="bad" label="due" />
                )}
              </div>
            ))}
          </div>
        ) : null}
        {(holds.data ?? []).length > 0 ? (
          <div className="card-pad" style={{ borderTop: "1px solid var(--line)" }}>
            <div style={{ fontWeight: 600, marginBottom: 6 }}>Holds</div>
            {(holds.data ?? []).map((hold) => (
              <div className="list-row" key={hold.id}>
                <div className="grow">
                  <div className="title">{hold.reason}</div>
                  <div className="meta">
                    {hold.subject_type} {hold.subject_id.slice(0, 8)} · by {hold.created_by.slice(0, 8)}
                    {hold.until ? ` · until ${hold.until}` : " · indefinite"}
                  </div>
                </div>
                <button
                  className="btn sm"
                  disabled={busy}
                  onClick={() => act(() => command("release_retention_hold", { hold_id: hold.id }))}
                >
                  Release
                </button>
              </div>
            ))}
          </div>
        ) : null}
      </section>

      <section className="card">
        <div className="card-head">
          <h2>Erasure requests</h2>
          <span className="sub">approve → execute, both named, holds block</span>
          <button className="btn sm" style={{ marginLeft: "auto" }} disabled={busy} onClick={() => setErasureOpen(true)}>
            <Plus size={13} /> New request
          </button>
        </div>
        {(erasures.data ?? []).length === 0 ? (
          <div className="card-pad small muted">
            No erasure requests. Execution purges candidate PII (or clears employee contact
            fields); audit rows and payroll records always survive.
          </div>
        ) : (
          (erasures.data ?? []).map((request) => (
            <div className="list-row" key={request.id}>
              <div className="grow">
                <div className="title">
                  {request.subject_type} · {request.subject_id.slice(0, 8)}
                </div>
                <div className="meta">
                  {request.reason} · requested {formatDateTime(request.requested_at)}
                  {request.retained.length > 0 ? ` · retained: ${request.retained.join(", ")}` : ""}
                </div>
              </div>
              <StatusPill
                tone={
                  request.status === "completed"
                    ? "ok"
                    : request.status === "pending"
                      ? "warn"
                      : request.status === "approved"
                        ? "info"
                        : "bad"
                }
                label={request.status}
              />
              {request.status === "pending" ? (
                <span className="row" style={{ gap: 6 }}>
                  <button className="btn sm primary" disabled={busy} onClick={() => act(() => command("approve_erasure", { request_id: request.id }))}>
                    Approve
                  </button>
                  <button className="btn sm" disabled={busy} onClick={() => act(() => command("reject_erasure", { request_id: request.id, reason: "not eligible for erasure" }))}>
                    Reject
                  </button>
                </span>
              ) : null}
              {request.status === "approved" ? (
                <button className="btn sm primary" disabled={busy} onClick={() => setExecuteOpen(request)}>
                  Execute
                </button>
              ) : null}
            </div>
          ))
        )}
      </section>

      <section className="card">
        <div className="card-head">
          <h2>Breach incidents</h2>
          <span className="sub">report → contain → notify → close</span>
          <button className="btn sm" style={{ marginLeft: "auto" }} disabled={busy} onClick={() => setBreachOpen(true)}>
            <Plus size={13} /> Report
          </button>
        </div>
        {(breaches.data ?? []).length === 0 ? (
          <div className="card-pad small muted">No incidents reported.</div>
        ) : (
          (breaches.data ?? []).map((breach) => (
            <div className="list-row" key={breach.id}>
              <span className={`icon-box ${breach.severity === "critical" || breach.severity === "high" ? "urgent" : breach.severity === "medium" ? "warn" : ""}`}>
                <AlertTriangle size={15} />
              </span>
              <div className="grow">
                <div className="title">{breach.title}</div>
                <div className="meta">
                  {breach.severity} · {breach.description} · {breach.steps.length} containment step(s)
                </div>
              </div>
              <StatusPill
                tone={breach.status === "closed" ? "ok" : breach.status === "open" ? "bad" : "info"}
                label={breach.status}
              />
              <span className="row" style={{ gap: 6 }}>
                {breach.status === "open" ? (
                  <button className="btn sm" disabled={busy} onClick={() => act(() => command("contain_breach", { breach_id: breach.id, step: "Device locked and credentials rotated" }))}>
                    Contain
                  </button>
                ) : null}
                {breach.status === "contained" ? (
                  <button className="btn sm" disabled={busy} onClick={() => act(() => command("mark_breach_notified", { breach_id: breach.id }))}>
                    Mark notified
                  </button>
                ) : null}
                {(breach.status === "contained" || breach.status === "notified") && (
                  <button className="btn sm" disabled={busy} onClick={() => act(() => command("close_breach", { breach_id: breach.id }))}>
                    Close
                  </button>
                )}
              </span>
            </div>
          ))
        )}
      </section>

      {erasureOpen ? (
        <ErasureDialog
          onClose={() => setErasureOpen(false)}
          onCreated={async () => {
            setErasureOpen(false);
            await refresh();
          }}
          onError={onError}
        />
      ) : null}
      {breachOpen ? (
        <BreachDialog
          onClose={() => setBreachOpen(false)}
          onCreated={async () => {
            setBreachOpen(false);
            await refresh();
          }}
          onError={onError}
        />
      ) : null}
      {holdOpen ? (
        <HoldDialog
          onClose={() => setHoldOpen(false)}
          onCreated={async () => {
            setHoldOpen(false);
            await refresh();
          }}
          onError={onError}
        />
      ) : null}
      {executeOpen ? (
        <ExecuteDialog
          request={executeOpen}
          onClose={() => setExecuteOpen(null)}
          onExecuted={async () => {
            setExecuteOpen(null);
            await refresh();
          }}
          onError={onError}
        />
      ) : null}
    </div>
  );
}

function ErasureDialog({
  onClose,
  onCreated,
  onError,
}: {
  onClose: () => void;
  onCreated: () => Promise<void>;
  onError: (error: string | null) => void;
}) {
  const [subjectType, setSubjectType] = useState("candidate");
  const [subjectId, setSubjectId] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await command("create_erasure_request", {
        subject_type: subjectType,
        subject_id: subjectId,
        reason,
      });
      await onCreated();
    } catch (caught) {
      const text = message(caught);
      setError(text);
      onError(text);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      title="Request erasure"
      subtitle="Needs a reason of 10+ characters. Approval and execution are separate named gates."
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose} type="button">Cancel</button>
          <button className="btn primary" form="erasure-form" type="submit" disabled={busy || !subjectId || reason.trim().length < 10}>
            {busy ? "Saving…" : "Create request"}
          </button>
        </>
      }
    >
      <form id="erasure-form" onSubmit={submit} className="grid" style={{ gap: 12 }}>
        <Field label="Subject type">
          <select value={subjectType} onChange={(event) => setSubjectType(event.target.value)}>
            <option value="candidate">Candidate</option>
            <option value="employee">Employee</option>
          </select>
        </Field>
        <Field label="Subject ID" hint="Paste the full record ID from the directory or pipeline.">
          <input value={subjectId} onChange={(event) => setSubjectId(event.target.value)} required />
        </Field>
        <Field label="Reason">
          <textarea value={reason} onChange={(event) => setReason(event.target.value)} style={{ minHeight: 80 }} />
        </Field>
        {error ? <ErrorBox>{error}</ErrorBox> : null}
      </form>
    </Modal>
  );
}

function ExecuteDialog({
  request,
  onClose,
  onExecuted,
  onError,
}: {
  request: ErasureRequest;
  onClose: () => void;
  onExecuted: () => Promise<void>;
  onError: (error: string | null) => void;
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
      await command("execute_erasure", { request_id: request.id });
      await onExecuted();
    } catch (caught) {
      const text = message(caught);
      setError(text);
      onError(text);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      title="Execute erasure?"
      subtitle={`${request.subject_type} ${request.subject_id.slice(0, 8)} · holds block, audit survives`}
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose} type="button">Cancel</button>
          <button className="btn danger" form="execute-form" type="submit" disabled={busy || !password}>
            {busy ? "Executing…" : "Execute now"}
          </button>
        </>
      }
    >
      <form id="execute-form" onSubmit={submit} className="grid" style={{ gap: 12 }}>
        <div className="notice">
          <CheckCircle2 size={15} />
          <div>
            This purges candidate PII (or clears employee contact fields) immediately. Payroll
            records and audit rows survive. A retention hold blocks it.
          </div>
        </div>
        <Field label="Confirm your password">
          <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoFocus />
        </Field>
        {error ? <ErrorBox>{error}</ErrorBox> : null}
      </form>
    </Modal>
  );
}

function BreachDialog({
  onClose,
  onCreated,
  onError,
}: {
  onClose: () => void;
  onCreated: () => Promise<void>;
  onError: (error: string | null) => void;
}) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [severity, setSeverity] = useState("medium");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await command("report_breach", { title, description, severity });
      await onCreated();
    } catch (caught) {
      const text = message(caught);
      setError(text);
      onError(text);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      title="Report an incident"
      subtitle="Open → contained → notified → closed. Notification itself happens outside the app."
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose} type="button">Cancel</button>
          <button className="btn primary" form="breach-form" type="submit" disabled={busy || title.trim().length < 5 || description.trim().length < 10}>
            {busy ? "Saving…" : "Report"}
          </button>
        </>
      }
    >
      <form id="breach-form" onSubmit={submit} className="grid" style={{ gap: 12 }}>
        <Field label="Title">
          <input value={title} onChange={(event) => setTitle(event.target.value)} autoFocus />
        </Field>
        <Field label="What happened">
          <textarea value={description} onChange={(event) => setDescription(event.target.value)} style={{ minHeight: 90 }} />
        </Field>
        <Field label="Severity">
          <select value={severity} onChange={(event) => setSeverity(event.target.value)}>
            <option value="low">Low</option>
            <option value="medium">Medium</option>
            <option value="high">High</option>
            <option value="critical">Critical</option>
          </select>
        </Field>
        {error ? <ErrorBox>{error}</ErrorBox> : null}
      </form>
    </Modal>
  );
}

function HoldDialog({
  onClose,
  onCreated,
  onError,
}: {
  onClose: () => void;
  onCreated: () => Promise<void>;
  onError: (error: string | null) => void;
}) {
  const [subjectType, setSubjectType] = useState("candidate");
  const [subjectId, setSubjectId] = useState("");
  const [reason, setReason] = useState("");
  const [until, setUntil] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await command("create_retention_hold", {
        subject_type: subjectType,
        subject_id: subjectId,
        reason,
        until: until || null,
      });
      await onCreated();
    } catch (caught) {
      const text = message(caught);
      setError(text);
      onError(text);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      title="Place a retention hold"
      subtitle="Blocks erasure and retention purges for one subject until released or expired."
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose} type="button">Cancel</button>
          <button className="btn primary" form="hold-form" type="submit" disabled={busy || !subjectId || reason.trim().length < 5}>
            {busy ? "Saving…" : "Place hold"}
          </button>
        </>
      }
    >
      <form id="hold-form" onSubmit={submit} className="grid" style={{ gap: 12 }}>
        <Field label="Subject type">
          <select value={subjectType} onChange={(event) => setSubjectType(event.target.value)}>
            <option value="candidate">Candidate</option>
            <option value="employee">Employee</option>
          </select>
        </Field>
        <Field label="Subject ID">
          <input value={subjectId} onChange={(event) => setSubjectId(event.target.value)} required />
        </Field>
        <Field label="Reason">
          <input value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Tax audit" />
        </Field>
        <Field label="Until (optional)">
          <input type="date" value={until} onChange={(event) => setUntil(event.target.value)} />
        </Field>
        {error ? <ErrorBox>{error}</ErrorBox> : null}
      </form>
    </Modal>
  );
}

export function ConsentLine({ candidateId, consent }: { candidateId: string; consent: string }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function withdraw() {
    const reason = window.prompt("Why is consent being withdrawn? (min 5 characters)");
    if (!reason || reason.trim().length < 5) return;
    setBusy(true);
    setError(null);
    try {
      await command("withdraw_consent", {
        subject_type: "candidate",
        subject_id: candidateId,
        reason,
      });
      window.location.reload();
    } catch (caught) {
      setError(message(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <span className="row" style={{ gap: 6 }}>
      <StatusPill
        tone={consent === "granted" ? "ok" : consent === "withdrawn" ? "bad" : "warn"}
        label={`consent ${consent}`}
      />
      {consent === "granted" ? (
        <button className="btn sm ghost" disabled={busy} onClick={withdraw}>
          Withdraw
        </button>
      ) : null}
      {error ? <span className="small" style={{ color: "var(--danger)" }}>{error}</span> : null}
    </span>
  );
}
