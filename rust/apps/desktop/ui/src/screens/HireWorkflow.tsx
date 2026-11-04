import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CalendarDays,
  CheckCircle2,
  FileText,
  Mail,
  Send,
  Wallet as WalletIcon,
} from "lucide-react";
import { command, formatDate, formatDateTime, formatIdr } from "../api";
import type {
  Application,
  Candidate,
  CandidateMessage,
  FeedbackReport,
  InterviewSlot,
  Offer,
  ScheduleProposal,
} from "../types";
import { ErrorBox, Field, Modal, StatusPill } from "../components/ui";

function message(caught: unknown): string {
  if (typeof caught === "object" && caught && "message" in caught) {
    return String((caught as { message: unknown }).message);
  }
  return String(caught);
}

function toLocalInput(instant: string): string {
  const date = new Date(instant);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

// ---------------------------------------------------------------------------
// Scheduling
// ---------------------------------------------------------------------------

export function ScheduleSection({
  application,
  onError,
}: {
  application: Application;
  onError: (error: string | null) => void;
}) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const proposals = useQuery({
    queryKey: ["schedules", application.id],
    queryFn: () =>
      command<ScheduleProposal[]>("list_schedule_proposals", {
        application_id: application.id,
      }),
  });

  async function refresh() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["schedules", application.id] }),
      queryClient.invalidateQueries({ queryKey: ["today"] }),
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

  const list = proposals.data ?? [];

  return (
    <div>
      <div className="row" style={{ justifyContent: "space-between", marginBottom: 8 }}>
        <div style={{ fontWeight: 620 }}>
          Interviews <span className="pill">{list.length}</span>
        </div>
        <button className="btn sm" disabled={busy} onClick={() => setOpen(true)}>
          <CalendarDays size={13} /> Propose slots
        </button>
      </div>
      {list.length === 0 ? (
        <div className="small muted">No interview proposed yet.</div>
      ) : (
        <div className="grid" style={{ gap: 8 }}>
          {list.map((proposal) => (
            <div className="card card-pad" key={proposal.id}>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <StatusPill
                  tone={
                    proposal.status === "confirmed"
                      ? "ok"
                      : proposal.status === "proposed"
                        ? "info"
                        : "neutral"
                  }
                  label={proposal.status}
                />
                <span className="small faint">{formatDateTime(proposal.created_at)}</span>
              </div>
              <div className="grid" style={{ gap: 6, marginTop: 8 }}>
                {proposal.slots.map((slot, index) => (
                  <div className="row small" key={`${proposal.id}-${index}`} style={{ gap: 8 }}>
                    <span style={{ fontWeight: 550 }}>
                      {formatDateTime(slot.starts_at)} · {slot.duration_minutes} min · {slot.mode}
                      {slot.location ? ` · ${slot.location}` : ""}
                    </span>
                    {proposal.status === "proposed" ? (
                      <button
                        className="btn sm"
                        disabled={busy}
                        onClick={() =>
                          act(() => command("confirm_schedule", { proposal_id: proposal.id, index }))
                        }
                      >
                        Confirm this slot
                      </button>
                    ) : null}
                    {proposal.status === "confirmed" && proposal.confirmed_index === index ? (
                      <StatusPill tone="ok" label="confirmed" />
                    ) : null}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
      {open ? (
        <ScheduleDialog
          application={application}
          onClose={() => setOpen(false)}
          onProposed={async () => {
            setOpen(false);
            await refresh();
          }}
          onError={onError}
        />
      ) : null}
    </div>
  );
}

function ScheduleDialog({
  application,
  onClose,
  onProposed,
  onError,
}: {
  application: Application;
  onClose: () => void;
  onProposed: () => Promise<void>;
  onError: (error: string | null) => void;
}) {
  const now = new Date();
  now.setDate(now.getDate() + 2);
  now.setHours(10, 0, 0, 0);
  const [startsAt, setStartsAt] = useState(toLocalInput(now.toISOString()));
  const [duration, setDuration] = useState("60");
  const [mode, setMode] = useState<InterviewSlot["mode"]>("remote");
  const [location, setLocation] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await command("propose_schedule", {
        application_id: application.id,
        slots: [
          {
            starts_at: new Date(startsAt).toISOString(),
            duration_minutes: Number(duration),
            mode,
            location: location || null,
          },
        ],
      });
      await onProposed();
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
      title="Propose an interview"
      subtitle="Up to five slots; the candidate confirms one. Times are stored as UTC instants."
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose} type="button">Cancel</button>
          <button className="btn primary" form="schedule-form" type="submit" disabled={busy || !startsAt}>
            {busy ? "Proposing…" : "Propose slot"}
          </button>
        </>
      }
    >
      <form id="schedule-form" onSubmit={submit} className="form-grid">
        <Field label="Starts at" span>
          <input
            type="datetime-local"
            value={startsAt}
            onChange={(event) => setStartsAt(event.target.value)}
            required
          />
        </Field>
        <Field label="Duration (minutes)">
          <input
            type="number"
            min="15"
            max="480"
            value={duration}
            onChange={(event) => setDuration(event.target.value)}
          />
        </Field>
        <Field label="Mode">
          <select value={mode} onChange={(event) => setMode(event.target.value as InterviewSlot["mode"])}>
            <option value="remote">Remote</option>
            <option value="onsite">Onsite</option>
            <option value="phone">Phone</option>
          </select>
        </Field>
        {mode === "onsite" ? (
          <Field label="Location" span hint="Required for onsite interviews.">
            <input value={location} onChange={(event) => setLocation(event.target.value)} placeholder="Jakarta office, room 3" />
          </Field>
        ) : null}
        {error ? <div className="span-2"><ErrorBox>{error}</ErrorBox></div> : null}
      </form>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Offers
// ---------------------------------------------------------------------------

export function OfferSection({
  application,
  jobTitle,
  onError,
}: {
  application: Application;
  jobTitle: string;
  onError: (error: string | null) => void;
}) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [approveOpen, setApproveOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const offers = useQuery({
    queryKey: ["offers", application.id],
    queryFn: () => command<Offer[]>("list_offers", { application_id: application.id }),
  });

  async function refresh() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["offers", application.id] }),
      queryClient.invalidateQueries({ queryKey: ["today"] }),
      queryClient.invalidateQueries({ queryKey: ["applications"] }),
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

  const list = offers.data ?? [];

  return (
    <div>
      <div className="row" style={{ justifyContent: "space-between", marginBottom: 8 }}>
        <div style={{ fontWeight: 620 }}>
          Offers <span className="pill">{list.length}</span>
        </div>
        <button className="btn sm" disabled={busy} onClick={() => setOpen(true)}>
          <WalletIcon size={13} /> New offer
        </button>
      </div>
      {list.length === 0 ? (
        <div className="small muted">No offer yet. A draft needs HR approval before it can be sent.</div>
      ) : (
        <div className="grid" style={{ gap: 8 }}>
          {list.map((offer) => (
            <div className="card card-pad" key={offer.id}>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <div style={{ fontWeight: 600 }}>
                  {offer.position_title || jobTitle}{" "}
                  {offer.salary_sen != null ? `· ${formatIdr(offer.salary_sen)}` : ""}
                </div>
                <StatusPill
                  tone={
                    offer.status === "accepted"
                      ? "ok"
                      : offer.status === "draft"
                        ? "warn"
                        : offer.status === "declined" || offer.status === "expired"
                          ? "bad"
                          : "info"
                  }
                  label={offer.status}
                />
              </div>
              <div className="small muted" style={{ marginTop: 4 }}>
                {offer.start_date ? `starts ${formatDate(offer.start_date)}` : "no start date"}
                {offer.expires_on ? ` · expires ${formatDate(offer.expires_on)}` : ""}
              </div>
              <div className="row" style={{ gap: 6, marginTop: 8 }}>
                {offer.status === "draft" ? (
                  <button className="btn sm primary" disabled={busy} onClick={() => setApproveOpen(true)}>
                    Approve
                  </button>
                ) : null}
                {offer.status === "approved" ? (
                  <button className="btn sm" disabled={busy} onClick={() => act(() => command("send_offer", { offer_id: offer.id }))}>
                    Mark sent
                  </button>
                ) : null}
                {offer.status === "sent" ? (
                  <>
                    <button className="btn sm primary" disabled={busy} onClick={() => act(() => command("accept_offer", { offer_id: offer.id }))}>
                      Record acceptance
                    </button>
                    <button className="btn sm" disabled={busy} onClick={() => act(() => command("decline_offer", { offer_id: offer.id, reason: "candidate declined the offer" }))}>
                      Record decline
                    </button>
                  </>
                ) : null}
              </div>
              {approveOpen ? (
                <ApproveOfferDialog
                  offer={offer}
                  onClose={() => setApproveOpen(false)}
                  onApproved={async () => {
                    setApproveOpen(false);
                    await refresh();
                  }}
                  onError={onError}
                />
              ) : null}
            </div>
          ))}
        </div>
      )}
      {open ? (
        <OfferDialog
          application={application}
          jobTitle={jobTitle}
          onClose={() => setOpen(false)}
          onCreated={async () => {
            setOpen(false);
            await refresh();
          }}
          onError={onError}
        />
      ) : null}
    </div>
  );
}
function OfferDialog({
  application,
  jobTitle,
  onClose,
  onCreated,
  onError,
}: {
  application: Application;
  jobTitle: string;
  onClose: () => void;
  onCreated: () => Promise<void>;
  onError: (error: string | null) => void;
}) {
  const [title, setTitle] = useState(jobTitle);
  const [salary, setSalary] = useState("12000000");
  const [startDate, setStartDate] = useState("");
  const [expiresOn, setExpiresOn] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await command("create_offer", {
        application_id: application.id,
        position_title: title,
        salary_sen: salary ? Math.round(Number(salary) * 100) : null,
        start_date: startDate || null,
        expires_on: expiresOn || null,
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
      title="Draft an offer"
      subtitle="A draft until an HR operator approves it with a fresh password."
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose} type="button">Cancel</button>
          <button className="btn primary" form="offer-form" type="submit" disabled={busy || !title}>
            {busy ? "Saving…" : "Save draft"}
          </button>
        </>
      }
    >
      <form id="offer-form" onSubmit={submit} className="form-grid">
        <Field label="Position" span>
          <input value={title} onChange={(event) => setTitle(event.target.value)} required />
        </Field>
        <Field label="Monthly salary (IDR)">
          <input type="number" min="0" value={salary} onChange={(event) => setSalary(event.target.value)} />
        </Field>
        <Field label="Start date">
          <input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} />
        </Field>
        <Field label="Expires on">
          <input type="date" value={expiresOn} onChange={(event) => setExpiresOn(event.target.value)} />
        </Field>
        {error ? <div className="span-2"><ErrorBox>{error}</ErrorBox></div> : null}
      </form>
    </Modal>
  );
}

function ApproveOfferDialog({
  offer,
  onClose,
  onApproved,
  onError,
}: {
  offer: Offer;
  onClose: () => void;
  onApproved: () => Promise<void>;
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
      await command("approve_offer", { offer_id: offer.id });
      await onApproved();
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
      title="Approve this offer?"
      subtitle={`${offer.position_title}${offer.salary_sen != null ? ` · ${formatIdr(offer.salary_sen)}` : ""}`}
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose} type="button">Cancel</button>
          <button className="btn primary" form="approve-offer-form" type="submit" disabled={busy || !password}>
            {busy ? "Approving…" : "Approve"}
          </button>
        </>
      }
    >
      <form id="approve-offer-form" onSubmit={submit} className="grid" style={{ gap: 12 }}>
        <div className="notice">
          <CheckCircle2 size={15} />
          <div>Approval is a named-human gate: it needs your password and lands on the audit chain.</div>
        </div>
        <Field label="Confirm your password">
          <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoFocus />
        </Field>
        {error ? <ErrorBox>{error}</ErrorBox> : null}
      </form>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Messaging
// ---------------------------------------------------------------------------

export function MessageSection({
  application,
  candidate,
  onError,
}: {
  application: Application;
  candidate: Candidate;
  onError: (error: string | null) => void;
}) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const messages = useQuery({
    queryKey: ["messages", application.id],
    queryFn: () => command<CandidateMessage[]>("list_messages", { application_id: application.id }),
  });

  async function refresh() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["messages", application.id] }),
      queryClient.invalidateQueries({ queryKey: ["today"] }),
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

  const list = messages.data ?? [];

  return (
    <div>
      <div className="row" style={{ justifyContent: "space-between", marginBottom: 8 }}>
        <div style={{ fontWeight: 620 }}>
          Messages <span className="pill">{list.length}</span>
        </div>
        <button className="btn sm" disabled={busy} onClick={() => setOpen(true)}>
          <Mail size={13} /> Draft message
        </button>
      </div>
      {list.length === 0 ? (
        <div className="small muted">
          No messages yet. Drafts need a preview and a queued approval before they count as sent.
        </div>
      ) : (
        <div className="grid" style={{ gap: 8 }}>
          {list.map((item) => (
            <div className="card card-pad" key={item.id}>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <div style={{ fontWeight: 600 }}>
                  {item.direction === "inbound" ? "← Reply" : `→ ${item.kind}`}
                  <span className="small faint" style={{ marginLeft: 6 }}>{item.channel}</span>
                </div>
                <StatusPill
                  tone={item.status === "sent" ? "ok" : item.status === "queued" ? "info" : "neutral"}
                  label={`${item.direction} · ${item.status}`}
                />
              </div>
              {item.subject ? <div style={{ fontWeight: 550, marginTop: 4 }}>{item.subject}</div> : null}
              <div className="small" style={{ marginTop: 4, whiteSpace: "pre-wrap" }}>{item.body}</div>
              <div className="small faint" style={{ marginTop: 4 }}>{formatDateTime(item.created_at)}</div>
              {item.status === "draft" ? (
                <button className="btn sm" style={{ marginTop: 8 }} disabled={busy} onClick={() => act(() => queueWithReauth(item.id))}>
                  Queue (needs password)
                </button>
              ) : null}
              {item.status === "queued" ? (
                <button className="btn sm" style={{ marginTop: 8 }} disabled={busy} onClick={() => act(() => command("mark_message_sent", { message_id: item.id }))}>
                  <Send size={13} /> Mark sent
                </button>
              ) : null}
            </div>
          ))}
        </div>
      )}
      {open ? (
        <MessageDialog
          application={application}
          candidate={candidate}
          onClose={() => setOpen(false)}
          onDrafted={async () => {
            setOpen(false);
            await refresh();
          }}
          onError={onError}
        />
      ) : null}
    </div>
  );
}

async function queueWithReauth(messageId: string): Promise<unknown> {
  const password = window.prompt("Confirm your password to queue this message:");
  if (!password) throw new Error("Queueing needs your password.");
  await command("reauth", { password });
  return command("queue_message", { message_id: messageId });
}

function MessageDialog({
  application,
  candidate,
  onClose,
  onDrafted,
  onError,
}: {
  application: Application;
  candidate: Candidate;
  onClose: () => void;
  onDrafted: () => Promise<void>;
  onError: (error: string | null) => void;
}) {
  const [channel, setChannel] = useState<CandidateMessage["channel"]>("email");
  const [subject, setSubject] = useState(`Next steps for your application`);
  const [body, setBody] = useState(
    `Hi ${candidate.full_name},\n\nThank you for your time so far. We would like to invite you to the next step.\n\nBest regards,\nHR`,
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await command("draft_message", {
        candidate_id: candidate.id,
        application_id: application.id,
        kind: "interview",
        channel,
        subject: channel === "email" ? subject : null,
        body,
      });
      await onDrafted();
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
      title="Draft a message"
      subtitle="Preview first. Queueing needs your password; nothing sends itself."
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose} type="button">Cancel</button>
          <button className="btn primary" form="message-form" type="submit" disabled={busy || body.trim().length < 10}>
            {busy ? "Saving…" : "Save draft"}
          </button>
        </>
      }
    >
      <form id="message-form" onSubmit={submit} className="grid" style={{ gap: 12 }}>
        <Field label="Channel">
          <select value={channel} onChange={(event) => setChannel(event.target.value as CandidateMessage["channel"])}>
            <option value="email">Email</option>
            <option value="whatsapp">WhatsApp</option>
            <option value="phone">Phone note</option>
            <option value="note">Internal note</option>
          </select>
        </Field>
        {channel === "email" ? (
          <Field label="Subject">
            <input value={subject} onChange={(event) => setSubject(event.target.value)} />
          </Field>
        ) : null}
        <Field label="Body" hint="At least 10 characters. This exact text is what gets queued.">
          <textarea value={body} onChange={(event) => setBody(event.target.value)} style={{ minHeight: 140 }} />
        </Field>
        {error ? <ErrorBox>{error}</ErrorBox> : null}
      </form>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Feedback
// ---------------------------------------------------------------------------

export function FeedbackSection({
  application,
  onError,
}: {
  application: Application;
  onError: (error: string | null) => void;
}) {
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);

  const feedback = useQuery({
    queryKey: ["feedback", application.id],
    queryFn: () => command<FeedbackReport | null>("feedback_for", { application_id: application.id }),
  });

  async function generate() {
    setBusy(true);
    onError(null);
    try {
      await command("generate_feedback", { application_id: application.id });
      await queryClient.invalidateQueries({ queryKey: ["feedback", application.id] });
      await queryClient.invalidateQueries({ queryKey: ["today"] });
    } catch (caught) {
      onError(message(caught));
    } finally {
      setBusy(false);
    }
  }

  const report = feedback.data;

  return (
    <div>
      <div className="row" style={{ justifyContent: "space-between", marginBottom: 8 }}>
        <div style={{ fontWeight: 620 }}>Candidate feedback</div>
        <button className="btn sm" disabled={busy} onClick={generate}>
          <FileText size={13} /> {report ? "Regenerate" : "Generate"} from evaluation
        </button>
      </div>
      {!report ? (
        <div className="small muted">
          No feedback yet. It is generated from the reviewed evaluation: summary plus strengths and
          growth areas. No scores, no sigma, no internal notes.
        </div>
      ) : (
        <div className="card card-pad">
          <div style={{ fontWeight: 600 }}>{report.candidate_name} · {report.job_title}</div>
          <div className="small" style={{ marginTop: 6, whiteSpace: "pre-wrap" }}>{report.summary}</div>
          {report.strengths.length > 0 ? (
            <div className="small" style={{ marginTop: 8 }}>
              <strong>Strengths:</strong> {report.strengths.join(", ")}
            </div>
          ) : null}
          {report.growth_areas.length > 0 ? (
            <div className="small" style={{ marginTop: 4 }}>
              <strong>Areas to develop:</strong> {report.growth_areas.join(", ")}
            </div>
          ) : null}
          <div className="small faint" style={{ marginTop: 6 }}>
            Generated {formatDateTime(report.created_at)} · candidate-safe text only
          </div>
        </div>
      )}
    </div>
  );
}
