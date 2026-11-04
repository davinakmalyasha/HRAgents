import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, CalendarDays, Check, Plus } from "lucide-react";
import { command, formatDate, formatIdr } from "../api";
import type {
  Employee,
  Goal,
  OffboardingPlan,
  PayrollRun,
  ReviewAssignment,
  ReviewCycle,
} from "../types";
import { ErrorBox, Field, Modal, StatusPill } from "../components/ui";

export function GrowthTab({
  employee,
  onError,
}: {
  employee: Employee;
  onError: (error: string | null) => void;
}) {
  const queryClient = useQueryClient();
  const [cycleName, setCycleName] = useState("2026 H2 review");
  const [startsOn, setStartsOn] = useState("2026-07-01");
  const [endsOn, setEndsOn] = useState("2026-12-31");
  const [reviewer, setReviewer] = useState("Budi Santoso");
  const [goalTitle, setGoalTitle] = useState("");
  const [busy, setBusy] = useState(false);

  const cycles = useQuery({
    queryKey: ["review-cycles"],
    queryFn: () => command<ReviewCycle[]>("list_review_cycles"),
  });
  const assignments = useQuery({
    queryKey: ["review-assignments"],
    queryFn: () => command<ReviewAssignment[]>("list_review_assignments", { cycle_id: null }),
  });
  const goals = useQuery({
    queryKey: ["goals", employee.id],
    queryFn: () => command<Goal[]>("list_goals", { employee_id: employee.id }),
  });

  async function refresh() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["review-cycles"] }),
      queryClient.invalidateQueries({ queryKey: ["review-assignments"] }),
      queryClient.invalidateQueries({ queryKey: ["goals"] }),
      queryClient.invalidateQueries({ queryKey: ["today"] }),
    ]);
  }

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    onError(null);
    try {
      await action();
      await refresh();
    } catch (caught) {
      onError(
        typeof caught === "object" && caught && "message" in caught
          ? String((caught as { message: unknown }).message)
          : String(caught),
      );
    } finally {
      setBusy(false);
    }
  }

  const employeeAssignments = (assignments.data ?? []).filter(
    (assignment) => assignment.employee_id === employee.id,
  );
  const activeCycle = (cycles.data ?? [])[0];

  return (
    <div className="grid" style={{ gap: 18 }}>
      <div>
        <div className="row" style={{ justifyContent: "space-between", marginBottom: 8 }}>
          <div style={{ fontWeight: 620 }}>Review cycles</div>
          <span className="pill">{(cycles.data ?? []).length} cycle(s)</span>
        </div>
        {(cycles.data ?? []).length === 0 ? (
          <div className="small muted">No review cycle yet. Create one to assign reviewers.</div>
        ) : (
          <div className="card">
            {(cycles.data ?? []).map((cycle) => (
              <div className="list-row" key={cycle.id}>
                <span className="icon-box"><CalendarDays size={15} /></span>
                <div className="grow">
                  <div className="title">{cycle.name}</div>
                  <div className="meta">
                    {formatDate(cycle.starts_on)} → {formatDate(cycle.ends_on)}
                  </div>
                </div>
                <StatusPill
                  tone={cycle.status === "active" ? "ok" : cycle.status === "closed" ? "neutral" : "warn"}
                  label={cycle.status}
                />
                {cycle.status === "draft" ? (
                  <button
                    className="btn sm"
                    disabled={busy}
                    onClick={() =>
                      run(() =>
                        command("set_review_cycle_status", { cycle_id: cycle.id, activate: true }),
                      )
                    }
                  >
                    Activate
                  </button>
                ) : null}
              </div>
            ))}
          </div>
        )}
        <form
          className="form-grid"
          style={{ marginTop: 10 }}
          onSubmit={(event) => {
            event.preventDefault();
            void run(() =>
              command("create_review_cycle", {
                name: cycleName,
                starts_on: startsOn,
                ends_on: endsOn,
              }),
            );
          }}
        >
          <Field label="Cycle name">
            <input value={cycleName} onChange={(event) => setCycleName(event.target.value)} />
          </Field>
          <Field label="Reviewer">
            <input value={reviewer} onChange={(event) => setReviewer(event.target.value)} />
          </Field>
          <Field label="Starts">
            <input type="date" value={startsOn} onChange={(event) => setStartsOn(event.target.value)} />
          </Field>
          <Field label="Ends">
            <input type="date" value={endsOn} onChange={(event) => setEndsOn(event.target.value)} />
          </Field>
          <div className="span-2 row">
            <button className="btn" type="submit" disabled={busy || !cycleName}>
              <Plus size={14} /> Create cycle
            </button>
            <button
              className="btn primary"
              type="button"
              disabled={busy || !activeCycle || !reviewer}
              onClick={() =>
                void run(() =>
                  command("create_review_assignment", {
                    cycle_id: activeCycle?.id,
                    employee_id: employee.id,
                    reviewer_name: reviewer,
                    form: null,
                  }),
                )
              }
            >
              Assign reviewer
            </button>
          </div>
        </form>
      </div>

      <div>
        <div style={{ fontWeight: 620, marginBottom: 8 }}>Review forms for {employee.full_name}</div>
        {employeeAssignments.length === 0 ? (
          <div className="small muted">No assignment yet.</div>
        ) : (
          <div className="card">
            {employeeAssignments.map((assignment) => (
              <div className="list-row" key={assignment.id}>
                <div className="grow">
                  <div className="title">{assignment.reviewer_name}</div>
                  <div className="meta">
                    {assignment.form.questions.length} questions · {assignment.status}
                  </div>
                </div>
                <StatusPill
                  tone={assignment.status === "summarized" ? "ok" : assignment.status === "pending" ? "warn" : "info"}
                  label={assignment.status}
                />
                {assignment.status === "pending" ? (
                  <button
                    className="btn sm"
                    disabled={busy}
                    onClick={() =>
                      run(() =>
                        command("send_review_assignment", { assignment_id: assignment.id }),
                      )
                    }
                  >
                    Send form
                  </button>
                ) : null}
                {assignment.status === "sent" ? (
                  <button
                    className="btn sm"
                    disabled={busy}
                    onClick={() =>
                      void run(() =>
                        command("submit_review_response", {
                          assignment_id: assignment.id,
                          answers: {
                            outcomes: {
                              rating: null,
                              text: "Signed off the desktop migration and mentored two engineers.",
                              yes_no: null,
                            },
                            collaboration: { rating: 4, text: null, yes_no: null },
                          },
                        }),
                      )
                    }
                  >
                    Import response
                  </button>
                ) : null}
                {assignment.status === "submitted" ? (
                  <button
                    className="btn sm"
                    disabled={busy}
                    onClick={() => run(() => command("summarize_review", { assignment_id: assignment.id }))}
                  >
                    Summarize
                  </button>
                ) : null}
              </div>
            ))}
          </div>
        )}
      </div>

      <div>
        <div style={{ fontWeight: 620, marginBottom: 8 }}>Goals</div>
        <div className="card">
          {(goals.data ?? []).map((goal) => (
            <div className="list-row" key={goal.id}>
              <div className="grow">
                <div className="title">{goal.title}</div>
                <div className="bar" style={{ marginTop: 5 }}>
                  <span style={{ width: `${goal.progress_bp / 100}%` }} />
                </div>
              </div>
              <span className="small muted">{(goal.progress_bp / 100).toFixed(0)}%</span>
              <StatusPill tone={goal.status === "completed" ? "ok" : "info"} label={goal.status} />
              {goal.status === "active" ? (
                <button
                  className="btn sm"
                  disabled={busy}
                  onClick={() =>
                    run(() =>
                      command("update_goal_progress", {
                        goal_id: goal.id,
                        progress_bp: Math.min(10_000, goal.progress_bp + 2_500),
                      }),
                    )
                  }
                >
                  Update progress
                </button>
              ) : null}
            </div>
          ))}
          <form
            className="row"
            style={{ padding: 12, borderTop: "1px solid var(--line)" }}
            onSubmit={(event) => {
              event.preventDefault();
              void run(() =>
                command("create_goal", { employee_id: employee.id, title: goalTitle }),
              ).then(() => setGoalTitle(""));
            }}
          >
            <input
              value={goalTitle}
              onChange={(event) => setGoalTitle(event.target.value)}
              placeholder="New goal"
              style={{ flex: 1, height: 34, border: "1px solid var(--line)", borderRadius: 8, padding: "0 10px" }}
            />
            <button className="btn" type="submit" disabled={busy || !goalTitle}>
              <Plus size={14} /> Add goal
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}

export function OffboardingTab({
  employee,
  onError,
}: {
  employee: Employee;
  onError: (error: string | null) => void;
}) {
  const queryClient = useQueryClient();
  const [lastDay, setLastDay] = useState("2026-12-31");
  const [busy, setBusy] = useState(false);
  const [finishOpen, setFinishOpen] = useState(false);

  const plan = useQuery({
    queryKey: ["offboarding", employee.id],
    queryFn: () => command<OffboardingPlan | null>("offboarding_for", { employee_id: employee.id }),
  });
  const runs = useQuery({
    queryKey: ["payroll-runs"],
    queryFn: () => command<PayrollRun[]>("payroll_runs"),
  });

  async function refresh() {
    await queryClient.invalidateQueries({ queryKey: ["offboarding", employee.id] });
    await queryClient.invalidateQueries({ queryKey: ["today"] });
  }

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    onError(null);
    try {
      await action();
      await refresh();
    } catch (caught) {
      onError(
        typeof caught === "object" && caught && "message" in caught
          ? String((caught as { message: unknown }).message)
          : String(caught),
      );
    } finally {
      setBusy(false);
    }
  }

  if (!plan.data) {
    return (
      <div className="empty" style={{ padding: "34px 12px" }}>
        <div className="icon"><ArrowRight size={18} /></div>
        <div style={{ fontWeight: 600, color: "var(--ink)" }}>No offboarding plan</div>
        <div className="small" style={{ marginTop: 4, marginBottom: 12 }}>
          Start the checklist for {employee.full_name}. The final paycheck and every handover step are gated.
        </div>
        <div className="row" style={{ justifyContent: "center" }}>
          <input
            type="date"
            value={lastDay}
            onChange={(event) => setLastDay(event.target.value)}
            style={{ height: 34, border: "1px solid var(--line)", borderRadius: 8, padding: "0 8px" }}
          />
          <button
            className="btn primary"
            disabled={busy}
            onClick={() =>
              run(() =>
                command("start_offboarding", { employee_id: employee.id, last_day: lastDay }),
              )
            }
          >
            <Plus size={15} /> Start offboarding
          </button>
        </div>
      </div>
    );
  }

  const value = plan.data;
  const done = value.steps.filter((step) => step.status === "done").length;
  return (
    <div className="grid" style={{ gap: 12 }}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div>
          <div style={{ fontWeight: 620 }}>Last day {formatDate(value.last_day)}</div>
          <div className="small muted">
            {done} of {value.steps.length} steps complete · final pay{" "}
            {value.final_pay_run_id ? "recorded" : "not recorded"}
          </div>
        </div>
        <StatusPill tone={value.status === "completed" ? "ok" : "info"} label={value.status.replaceAll("_", " ")} />
      </div>
      {value.steps.map((step) => (
        <div className="check-step" key={step.key}>
          <button
            className={`check ${step.status === "done" ? "done" : ""}`}
            disabled={busy || step.status === "done" || value.status === "completed"}
            onClick={() =>
              run(() =>
                command("complete_offboarding_step", {
                  employee_id: employee.id,
                  step_key: step.key,
                }),
              )
            }
            aria-label={`Mark ${step.title} complete`}
          >
            {step.status === "done" ? <Check size={13} /> : null}
          </button>
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 550 }}>{step.title}</div>
            <div className="small muted">owner {step.owner}</div>
          </div>
          <StatusPill tone={step.status === "done" ? "ok" : "neutral"} label={step.status} />
        </div>
      ))}
      <div className="row" style={{ gap: 8 }}>
        <select
          value={value.final_pay_run_id ?? ""}
          onChange={(event) =>
            run(() =>
              command("record_offboarding_final_pay", {
                employee_id: employee.id,
                run_id: event.target.value,
              }),
            )
          }
          style={{ height: 34, border: "1px solid var(--line)", borderRadius: 8, padding: "0 8px", flex: 1 }}
        >
          <option value="">Record final payroll run…</option>
          {(runs.data ?? []).map((run) => (
            <option key={run.id} value={run.id}>
              {run.kind} {run.period.slice(0, 7)} · {formatIdr(run.totals.net)}
            </option>
          ))}
        </select>
        <button
          className="btn primary"
          disabled={busy || value.status === "completed"}
          onClick={() => setFinishOpen(true)}
        >
          Finish offboarding
        </button>
      </div>
      {finishOpen ? (
        <FinishOffboardingDialog
          employee={employee}
          onClose={() => setFinishOpen(false)}
          onFinished={async () => {
            setFinishOpen(false);
            await refresh();
          }}
        />
      ) : null}
    </div>
  );
}

function FinishOffboardingDialog({
  employee,
  onClose,
  onFinished,
}: {
  employee: Employee;
  onClose: () => void;
  onFinished: () => Promise<void>;
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
      await command("finish_offboarding", { employee_id: employee.id });
      await onFinished();
    } catch (caught) {
      setError(
        typeof caught === "object" && caught && "message" in caught
          ? String((caught as { message: unknown }).message)
          : String(caught),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      title={`Finish ${employee.full_name}'s offboarding?`}
      subtitle="A named human gate. Required steps and final pay must already be complete."
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose} type="button">Cancel</button>
          <button className="btn primary" form="finish-offboarding" type="submit" disabled={busy || !password}>
            {busy ? "Finishing…" : "Finish and freeze"}
          </button>
        </>
      }
    >
      <form id="finish-offboarding" onSubmit={submit} className="grid" style={{ gap: 12 }}>
        <Field label="Confirm your password">
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoFocus
          />
        </Field>
        {error ? <ErrorBox>{error}</ErrorBox> : null}
      </form>
    </Modal>
  );
}
