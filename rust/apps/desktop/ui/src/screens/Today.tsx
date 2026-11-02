import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  CalendarDays,
  CheckCircle2,
  FileText,
  ShieldCheck,
  Users,
  Wallet,
} from "lucide-react";
import { command, formatDate, formatDateTime, formatDays } from "../api";
import type { CandidateMessage, Reminder, SessionView, TodayView } from "../types";
import type { Surface } from "../nav";
import { Avatar, EmptyState, StatusPill } from "../components/ui";

function approvalIcon(kind: string) {
  if (kind === "payroll_sign_off") return Wallet;
  if (kind === "document") return FileText;
  if (kind === "leave") return CalendarDays;
  return ShieldCheck;
}

export function Today({
  session,
  onNavigate,
}: {
  session: SessionView;
  onNavigate: (surface: Surface) => void;
}) {
  const today = useQuery({ queryKey: ["today"], queryFn: () => command<TodayView>("today") });
  const reminders = useQuery({ queryKey: ["reminders"], queryFn: () => command<Reminder[]>("reminders") });
  const outbox = useQuery({ queryKey: ["outbox"], queryFn: () => command<CandidateMessage[]>("outbox_pending") });
  const data = today.data;
  const approvals = data?.approvals ?? [];
  const payrollApproval = approvals.find((approval) => approval.kind === "payroll_sign_off");
  const reminderList = reminders.data ?? [];
  const outboxList = outbox.data ?? [];

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Today</h1>
          <p>
            {session.display_name}, {approvals.length === 0 ? "nothing is waiting on you." : `${approvals.length} decision${approvals.length === 1 ? "" : "s"} need you.`}{" "}
            <span className="faint">{formatDate(new Date().toISOString())}</span>
          </p>
        </div>
        <div className="page-actions">
          <button className="btn" onClick={() => onNavigate("hire")}>
            Import a CV
          </button>
          <button className="btn primary" onClick={() => onNavigate("people")}>
            Add an employee
            <ArrowRight size={15} />
          </button>
        </div>
      </div>

      <div className="grid kpis">
        <div className="card kpi">
          <div className="label">
            <Users size={13} /> Headcount
          </div>
          <div className="value">{data?.headcount ?? "—"}</div>
          <div className="hint">active, probation, and notice</div>
        </div>
        <div className="card kpi">
          <div className="label">
            <ShieldCheck size={13} /> Decisions
          </div>
          <div className="value">{approvals.length}</div>
          <div className="hint">{approvals.filter((a) => a.priority === "urgent").length} urgent</div>
        </div>
        <div className="card kpi">
          <div className="label">
            <CheckCircle2 size={13} /> Onboarding
          </div>
          <div className="value">{data?.open_onboarding.length ?? "—"}</div>
          <div className="hint">in progress</div>
        </div>
        <div className="card kpi">
          <div className="label">
            <Wallet size={13} /> Payroll
          </div>
          <div className="value" style={{ fontSize: 20 }}>
            {payrollApproval ? "Needs sign-off" : "Clear"}
          </div>
          <div className="hint">no payment execution, ever</div>
        </div>
      </div>

      <div className="grid two-col">
        <div className="grid" style={{ alignContent: "start" }}>
          <section className="card">
            <div className="card-head">
              <h2>Decisions</h2>
              <span className="sub">one primary action per item</span>
              <button className="btn ghost sm" style={{ marginLeft: "auto" }} onClick={() => onNavigate("pay")}>
                Open payroll
              </button>
            </div>
            {approvals.length === 0 ? (
              <EmptyState title="Nothing waiting" body="New decisions appear here with the record they belong to." />
            ) : (
              approvals.map((approval) => {
                const Icon = approvalIcon(approval.kind);
                return (
                  <div className="list-row" key={approval.id}>
                    <span className={`icon-box ${approval.priority === "urgent" ? "urgent" : approval.priority === "high" ? "warn" : ""}`}>
                      <Icon size={15} />
                    </span>
                    <div className="grow">
                      <div className="title">{approval.title}</div>
                      <div className="meta">{approval.summary}</div>
                    </div>
                    <StatusPill
                      tone={approval.priority === "urgent" ? "bad" : approval.priority === "high" ? "warn" : "neutral"}
                      label={approval.priority}
                    />
                    <button
                      className="btn sm"
                      onClick={() =>
                        onNavigate(
                          approval.kind === "payroll_sign_off"
                            ? "pay"
                            : approval.kind === "leave" || approval.kind === "document"
                              ? "people"
                              : "hire",
                        )
                      }
                    >
                      Review
                    </button>
                  </div>
                );
              })
            )}
          </section>

          <section className="card">
            <div className="card-head">
              <h2>Onboarding in progress</h2>
              <span className="sub">chase the next step, not the whole plan</span>
            </div>
            {data && data.open_onboarding.length > 0 ? (
              data.open_onboarding.map((item) => (
                <div className="list-row" key={item}>
                  <Avatar name={item} />
                  <div className="grow">
                    <div className="title">{item.split(" — ")[0]}</div>
                    <div className="meta">{item.split(" — ")[1]}</div>
                  </div>
                  <button className="btn sm" onClick={() => onNavigate("people")}>
                    Open checklist
                  </button>
                </div>
              ))
            ) : (
              <EmptyState title="No open onboarding" body="Start a plan from the person's profile." />
            )}
          </section>
        </div>

        <aside className="grid" style={{ alignContent: "start" }}>
          {(reminderList.length > 0 || outboxList.length > 0) && (
            <section className="card">
              <div className="card-head">
                <h2>Needs attention</h2>
                <span className={`pill ${reminderList.some((item) => item.severity === "urgent") ? "bad" : "warn"}`}>
                  {reminderList.length + outboxList.length}
                </span>
              </div>
              {reminderList.map((item) => (
                <div className="list-row" key={`${item.kind}-${item.subject_id}`}>
                  <span className={`icon-box ${item.severity === "urgent" ? "urgent" : item.severity === "warning" ? "warn" : ""}`}>
                    <span style={{ fontWeight: 700, fontSize: 12 }}>!</span>
                  </span>
                  <div className="grow">
                    <div className="title">{item.title}</div>
                    <div className="meta">{item.detail}</div>
                  </div>
                  <StatusPill
                    tone={item.severity === "urgent" ? "bad" : item.severity === "warning" ? "warn" : "neutral"}
                    label={item.severity}
                  />
                </div>
              ))}
              {outboxList.map((item) => (
                <div className="list-row" key={item.id}>
                  <span className="icon-box warn">
                    <span style={{ fontWeight: 700, fontSize: 12 }}>✉</span>
                  </span>
                  <div className="grow">
                    <div className="title">Waiting to send: {item.kind}</div>
                    <div className="meta">{item.subject ?? item.body.slice(0, 80)} · {item.channel}</div>
                  </div>
                  <button className="btn sm" onClick={() => onNavigate("hire")}>
                    Open case
                  </button>
                </div>
              ))}
            </section>
          )}
          <section className="card">
            <div className="card-head">
              <h2>Audit receipts</h2>
              <span className="pill ok">{data?.recent_audit.length ?? 0} recent</span>
            </div>
            <div className="card-pad">
              <div className="timeline">
                {(data?.recent_audit ?? []).map((entry) => (
                  <div className="tl-row" key={entry.entry_id}>
                    <span className="tl-dot" />
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontWeight: 550 }}>{entry.action.replaceAll(".", " · ")}</div>
                      <div className="small muted">
                        {entry.actor.display_name ?? entry.actor.actor_id} · {formatDateTime(entry.created_at)}
                      </div>
                      <div className="mono faint" style={{ marginTop: 2 }}>
                        {entry.entry_hash.slice(0, 16)}…
                      </div>
                    </div>
                  </div>
                ))}
              </div>
              <button className="btn sm" style={{ width: "100%", marginTop: 12 }} onClick={() => onNavigate("settings")}>
                Verify chain and export
              </button>
            </div>
          </section>

          <section className="card card-pad">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <div>
                <div style={{ fontWeight: 600 }}>Leave balance snapshot</div>
                <div className="small muted">Ayu Lestari · 2026</div>
              </div>
              <span className="pill info">{formatDays(20)}</span>
            </div>
            <div className="bar ok" style={{ marginTop: 14 }}>
              <span style={{ width: "83%" }} />
            </div>
            <div className="small muted" style={{ marginTop: 8 }}>
              10 of 12 days remaining after one approved request.
            </div>
            <button className="btn sm" style={{ marginTop: 12 }} onClick={() => onNavigate("people")}>
              Record leave
            </button>
          </section>
        </aside>
      </div>
    </>
  );
}
