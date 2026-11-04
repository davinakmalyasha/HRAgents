import { useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  Briefcase,
  CheckCircle2,
  FileSearch,
  Mail,
  MapPin,
  ShieldAlert,
  Sparkles,
  Upload,
} from "lucide-react";
import { command, formatDate, shortRef } from "../api";
import { DocumentVault } from "./Documents";
import { ConsentLine } from "./Compliance";
import { FeedbackSection, MessageSection, OfferSection, ScheduleSection } from "./HireWorkflow";
import type {
  Application,
  Candidate,
  Document,
  Evaluation,
  Job,
  Rubric,
  SessionView,
} from "../types";
import { ErrorBox, Field, Modal, ScoreBar, StatusPill } from "../components/ui";

const DEMO_RUBRIC: Rubric = {
  id: "backend-v1",
  name: "Backend Engineer",
  dimensions: [
    { key: "skills", label: "Technical skills", weight_bp: 6000 },
    { key: "impact", label: "Impact and ownership", weight_bp: 4000 },
  ],
  merit_floor_bp: 6000,
  sigma_limit_bp: 500,
};

function stageTone(stage: Application["stage"]): "neutral" | "ok" | "warn" | "bad" | "info" {
  if (stage === "offer" || stage === "hired") return "ok";
  if (stage === "rejected" || stage === "withdrawn") return "bad";
  if (stage === "review" || stage === "interview") return "info";
  return "neutral";
}

export function Hire({ session }: { session: SessionView }) {
  const queryClient = useQueryClient();
  const [selectedApplication, setSelectedApplication] = useState<string | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [extractOpen, setExtractOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const jobs = useQuery({ queryKey: ["jobs"], queryFn: () => command<Job[]>("list_jobs") });
  const candidates = useQuery({ queryKey: ["candidates"], queryFn: () => command<Candidate[]>("list_candidates") });
  const applications = useQuery({
    queryKey: ["applications"],
    queryFn: () => command<Application[]>("list_applications", { job_id: null }),
  });

  const activeApplication = useMemo(() => {
    const list = applications.data ?? [];
    return list.find((application) => application.id === selectedApplication) ?? list[0] ?? null;
  }, [applications.data, selectedApplication]);

  const candidate = useMemo(
    () => (candidates.data ?? []).find((item) => item.id === activeApplication?.candidate_id) ?? null,
    [candidates.data, activeApplication],
  );

  const evaluation = useQuery({
    queryKey: ["evaluation", activeApplication?.id],
    queryFn: () => command<Evaluation | null>("evaluation_for", { application_id: activeApplication?.id }),
    enabled: Boolean(activeApplication),
  });

  async function refresh() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["applications"] }),
      queryClient.invalidateQueries({ queryKey: ["candidates"] }),
      queryClient.invalidateQueries({ queryKey: ["today"] }),
      queryClient.invalidateQueries({ queryKey: ["approvals"] }),
      queryClient.invalidateQueries({ queryKey: ["evaluation"] }),
    ]);
  }


  async function createDefaultJob() {
    setBusy(true);
    try {
      await command("create_job", { title: "General application", org_unit: "Company" });
      await queryClient.invalidateQueries({ queryKey: ["jobs"] });
    } catch (caught) {
      setError(typeof caught === "object" && caught && "message" in caught ? String((caught as { message: unknown }).message) : String(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Hire</h1>
          <p>One case file per candidate: CV, evidence, score, and a named decision.</p>
        </div>
        <div className="page-actions">
          {(jobs.data ?? []).length === 0 ? (
            <button className="btn" onClick={createDefaultJob} disabled={busy}>
              <Briefcase size={15} /> Create first job
            </button>
          ) : null}
          <button className="btn primary" onClick={() => setImportOpen(true)} disabled={(jobs.data ?? []).length === 0}>
            <Upload size={15} /> Import CV
          </button>
        </div>
      </div>

      {error ? <ErrorBox>{error}</ErrorBox> : null}

      <div className="split">
        <section className="card" style={{ overflow: "hidden" }}>
          <div className="card-head">
            <h2>Pipeline</h2>
            <span className="sub">{(applications.data ?? []).length} candidate(s)</span>
          </div>
          <div className="scroll-list">
            {(applications.data ?? []).length === 0 ? (
              <div className="empty">
                <div className="icon"><FileSearch size={18} /></div>
                <div style={{ fontWeight: 600, color: "var(--ink)" }}>No candidates yet</div>
                <div className="small" style={{ marginTop: 4 }}>Import a CV to open the first case file.</div>
              </div>
            ) : (
              (applications.data ?? []).map((application) => {
                const person = (candidates.data ?? []).find((item) => item.id === application.candidate_id);
                const job = (jobs.data ?? []).find((item) => item.id === application.job_id);
                return (
                  <button
                    key={application.id}
                    className="list-row"
                    style={{
                      width: "100%",
                      border: 0,
                      borderBottom: "1px solid var(--line)",
                      background: activeApplication?.id === application.id ? "var(--surface-muted)" : "transparent",
                      textAlign: "left",
                      cursor: "pointer",
                    }}
                    onClick={() => setSelectedApplication(application.id)}
                  >
                    <span className="icon-box">
                      <span style={{ fontWeight: 700, fontSize: 12 }}>{person?.full_name.slice(0, 1) ?? "?"}</span>
                    </span>
                    <span className="grow">
                      <span className="title" style={{ display: "block" }}>{person?.full_name ?? "Unknown candidate"}</span>
                      <span className="meta" style={{ display: "block" }}>{job?.title ?? "—"} · {person?.source ?? ""}</span>
                    </span>
                    <StatusPill tone={stageTone(application.stage)} label={application.stage} />
                  </button>
                );
              })
            )}
          </div>
          <div style={{ padding: 12, borderTop: "1px solid var(--line)" }}>
            <div className="small faint">Open jobs</div>
            <div className="row" style={{ flexWrap: "wrap", gap: 6, marginTop: 6 }}>
              {(jobs.data ?? []).map((job) => (
                <span className="pill" key={job.id}>{job.title}</span>
              ))}
            </div>
          </div>
        </section>

        <section className="card">
          {candidate && activeApplication ? (
            <>
              <div className="card-pad" style={{ borderBottom: "1px solid var(--line)" }}>
                <div className="row" style={{ alignItems: "flex-start" }}>
                  <div>
                    <div className="row" style={{ gap: 8 }}>
                      <h2 style={{ margin: 0, fontSize: 20, letterSpacing: "-0.03em" }}>{candidate.full_name}</h2>
                      <StatusPill
                        tone={candidate.consent === "granted" ? "ok" : candidate.consent === "withdrawn" ? "bad" : "warn"}
                        label={`consent ${candidate.consent}`}
                      />
                    </div>
                    <div className="muted" style={{ marginTop: 3 }}>{candidate.headline ?? "Candidate"}</div>
                    <div className="row small muted" style={{ gap: 14, marginTop: 9, flexWrap: "wrap" }}>
                      {candidate.email ? <span className="row" style={{ gap: 5 }}><Mail size={12} />{candidate.email}</span> : null}
                      {candidate.location ? <span className="row" style={{ gap: 5 }}><MapPin size={12} />{candidate.location}</span> : null}
                      <span>Applied {formatDate(activeApplication.created_at)}</span>
                    </div>
                  </div>
                  <div style={{ marginLeft: "auto", textAlign: "right" }}>
                    <div className="faint small">Application</div>
                    <div className="mono">{shortRef(activeApplication.id, "A")}</div>
                    <button className="btn sm" style={{ marginTop: 8 }} onClick={() => setExtractOpen(true)} disabled={busy}>
                      <Sparkles size={13} /> {evaluation.data ? "Re-run extraction" : "Extract & score"}
                    </button>
                  </div>
                </div>
              </div>

              <div className="card-pad">
                {evaluation.data ? (
                  <EvaluationPanel evaluation={evaluation.data} />
                ) : (
                  <div className="notice" style={{ marginBottom: 14 }}>
                    <Sparkles size={15} />
                    <div>
                      No evaluation yet. Run extraction to produce structured evidence and a deterministic score.
                      The model never decides; the Rust scorer does.
                    </div>
                  </div>
                )}

                <div className="row" style={{ marginTop: 18, gap: 8 }}>
                  <button
                    className="btn danger"
                    onClick={() => setRejectOpen(true)}
                    disabled={activeApplication.stage === "rejected" || candidate.consent !== "granted"}
                  >
                    <ShieldAlert size={15} /> Reject with reason
                  </button>
                  <button className="btn" onClick={() => document.getElementById("hire-schedule")?.scrollIntoView({ behavior: "smooth" })}>
                    Schedule interview
                  </button>
                  <button className="btn" onClick={() => document.getElementById("hire-messages")?.scrollIntoView({ behavior: "smooth" })}>
                    Draft message
                  </button>
                  <span className="small faint" style={{ marginLeft: "auto" }}>
                    Rejection above the merit floor needs re-authentication.
                  </span>
                </div>
              </div>

              <div className="card-head" style={{ borderTop: "1px solid var(--line)" }}>
                <h3>Consent and provenance</h3>
              </div>
              <div className="card-pad detail-grid">
                <Fact k="Source" v={candidate.source} />
                <div className="fact">
                  <div className="k">Consent</div>
                  <div className="v"><ConsentLine candidateId={candidate.id} consent={candidate.consent} /></div>
                </div>
                <Fact k="Candidate ref" v={shortRef(candidate.id, "C")} />
                <Fact k="Documents" v={`${candidate.document_ids.length} attached`} />
              </div>
              <div className="card-pad grid" id="hire-schedule" style={{ borderTop: "1px solid var(--line)", gap: 18 }}>
                <ScheduleSection application={activeApplication} onError={setError} />
                <OfferSection application={activeApplication} jobTitle={(jobs.data ?? []).find((job) => job.id === activeApplication.job_id)?.title ?? "Role"} onError={setError} />
              </div>
              <div className="card-pad grid" id="hire-messages" style={{ borderTop: "1px solid var(--line)", gap: 18 }}>
                <MessageSection application={activeApplication} candidate={candidate} onError={setError} />
                <FeedbackSection application={activeApplication} onError={setError} />
              </div>
              <div className="card-pad" style={{ borderTop: "1px solid var(--line)" }}>
                <DocumentVault
                  ownerType="candidate"
                  ownerId={candidate.id}
                  ownerLabel={candidate.full_name}
                  onError={setError}
                />
              </div>
            </>
          ) : (
            <div className="empty" style={{ padding: "70px 24px" }}>
              <div className="icon"><FileSearch size={18} /></div>
              <div style={{ fontWeight: 600, color: "var(--ink)" }}>Open a case file</div>
              <div className="small" style={{ marginTop: 4 }}>
                Import a CV or select a candidate to see evidence, score, and next actions.
              </div>
            </div>
          )}
        </section>
      </div>

      {importOpen ? (
        <ImportDialog
          jobs={jobs.data ?? []}
          onClose={() => setImportOpen(false)}
          onImported={async (application) => {
            setImportOpen(false);
            setSelectedApplication(application.id);
            await refresh();
          }}
        />
      ) : null}

      {extractOpen && activeApplication ? (
        <ExtractDialog
          applicationId={activeApplication.id}
          candidateId={candidate?.id ?? activeApplication.candidate_id}
          onClose={() => setExtractOpen(false)}
          onScored={async () => {
            setExtractOpen(false);
            await refresh();
          }}
        />
      ) : null}

      {rejectOpen && activeApplication && candidate ? (
        <RejectDialog
          candidate={candidate}
          applicationId={activeApplication.id}
          session={session}
          onClose={() => setRejectOpen(false)}
          onRejected={async () => {
            setRejectOpen(false);
            await refresh();
          }}
        />
      ) : null}
    </>
  );
}

function EvaluationPanel({ evaluation }: { evaluation: Evaluation }) {
  const score = evaluation.overall_bp / 100;
  const sigma = evaluation.sigma_bp / 100;
  return (
    <div className="grid" style={{ gap: 14 }}>
      <div className="row" style={{ alignItems: "flex-end", gap: 16 }}>
        <div className="score">
          <span className="big">{score.toFixed(1)}</span>
          <span className="pct">%</span>
        </div>
        <div style={{ paddingBottom: 6 }}>
          <StatusPill tone={score >= 60 ? "ok" : "warn"} label={score >= 60 ? "above merit floor" : "human review"} />
          <div className="small muted" style={{ marginTop: 4 }}>
            σ {sigma.toFixed(1)}% across {evaluation.runs} extraction run(s)
          </div>
        </div>
        <div style={{ marginLeft: "auto", textAlign: "right" }} className="small muted">
          rubric {evaluation.rubric_id}
          <div className="mono faint">{evaluation.id.slice(0, 8)}</div>
        </div>
      </div>

      <div className="grid" style={{ gap: 10 }}>
        {Object.entries(evaluation.dimension_scores).map(([key, value]) => (
          <div key={key}>
            <div className="row small" style={{ justifyContent: "space-between", marginBottom: 4 }}>
              <span style={{ fontWeight: 600 }}>{key.replaceAll("_", " ")}</span>
              <span className="muted">{(value / 100).toFixed(1)}%</span>
            </div>
            <ScoreBar value={value} />
          </div>
        ))}
      </div>

      <div>
        <div className="row" style={{ justifyContent: "space-between", marginBottom: 6 }}>
          <div style={{ fontWeight: 600 }}>Evidence</div>
          <span className="pill">{evaluation.evidence.length} excerpt(s)</span>
        </div>
        {evaluation.evidence.length === 0 ? (
          <div className="small muted">No evidence was recorded. The evaluation carries a missing-evidence flag.</div>
        ) : (
          <div className="grid" style={{ gap: 8 }}>
            {evaluation.evidence.map((item) => (
              <blockquote
                key={`${item.dimension}-${item.quote}`}
                style={{
                  margin: 0,
                  borderLeft: "3px solid var(--line-strong)",
                  background: "var(--surface-muted)",
                  borderRadius: "0 8px 8px 0",
                  padding: "9px 12px",
                }}
              >
                <div className="small" style={{ color: "var(--ink-soft)", fontWeight: 600 }}>
                  {item.dimension} · page {item.page ?? "—"} · confidence {(item.confidence_bp / 100).toFixed(0)}%
                </div>
                <div style={{ marginTop: 3 }}>“{item.quote}”</div>
              </blockquote>
            ))}
          </div>
        )}
        {evaluation.flags.length > 0 ? (
          <div className="row small" style={{ marginTop: 8, gap: 6, color: "var(--warning)" }}>
            <ShieldAlert size={13} /> Flags: {evaluation.flags.join(", ")}
          </div>
        ) : null}
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

function ImportDialog({
  jobs,
  onClose,
  onImported,
}: {
  jobs: Job[];
  onClose: () => void;
  onImported: (application: Application) => Promise<void>;
}) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [headline, setHeadline] = useState("");
  const [source, setSource] = useState("LinkedIn");
  const [jobId, setJobId] = useState(jobs[0]?.id ?? "");
  const [consent, setConsent] = useState<Candidate["consent"]>("granted");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await command<[Candidate, Application]>("import_candidate", {
        input: {
          full_name: name,
          email: email || null,
          phone: null,
          source,
          headline: headline || null,
          job_id: jobId,
          consent,
          document: null,
        },
      });
      await onImported(result[1]);
    } catch (caught) {
      setError(typeof caught === "object" && caught && "message" in caught ? String((caught as { message: unknown }).message) : String(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      title="Import a candidate"
      subtitle="Create the profile and open a case file. CV text extraction follows in the same case."
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose} type="button">Cancel</button>
          <button className="btn primary" form="import-form" type="submit" disabled={busy || !name || !jobId}>
            {busy ? "Importing…" : "Import and open"}
            <ArrowRight size={15} />
          </button>
        </>
      }
    >
      <form id="import-form" onSubmit={submit} className="form-grid">
        <Field label="Full name">
          <input value={name} onChange={(event) => setName(event.target.value)} required autoFocus />
        </Field>
        <Field label="Email">
          <input type="email" value={email} onChange={(event) => setEmail(event.target.value)} />
        </Field>
        <Field label="Headline">
          <input value={headline} onChange={(event) => setHeadline(event.target.value)} placeholder="Backend engineer · 6 years" />
        </Field>
        <Field label="Source">
          <select value={source} onChange={(event) => setSource(event.target.value)}>
            <option>LinkedIn</option>
            <option>Referral</option>
            <option>Job board</option>
            <option>Manual</option>
          </select>
        </Field>
        <Field label="Job">
          <select value={jobId} onChange={(event) => setJobId(event.target.value)} required>
            {jobs.map((job) => <option key={job.id} value={job.id}>{job.title}</option>)}
          </select>
        </Field>
        <Field label="Consent" hint="Processing and messaging are blocked until consent is granted.">
          <select value={consent} onChange={(event) => setConsent(event.target.value as Candidate["consent"])}>
            <option value="granted">Granted</option>
            <option value="pending">Pending</option>
            <option value="withdrawn">Withdrawn</option>
          </select>
        </Field>
        <div className="span-2">
          <div className="notice">
            <CheckCircle2 size={15} />
            <div>No auto-rejection. This import creates a case file; every decision stays with you.</div>
          </div>
        </div>
        {error ? <div className="span-2"><ErrorBox>{error}</ErrorBox></div> : null}
      </form>
    </Modal>
  );
}

function RejectDialog({
  candidate,
  applicationId,
  session,
  onClose,
  onRejected,
}: {
  candidate: Candidate;
  applicationId: string;
  session: SessionView;
  onClose: () => void;
  onRejected: () => Promise<void>;
}) {
  const [reason, setReason] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await command("reauth", { password });
      await command("reject_candidate", {
        application_id: applicationId,
        reason,
      });
      await onRejected();
    } catch (caught) {
      setError(typeof caught === "object" && caught && "message" in caught ? String((caught as { message: unknown }).message) : String(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      title={`Reject ${candidate.full_name}?`}
      subtitle="This is a consequential decision. It needs a reason and a fresh sign-in."
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose} type="button">Cancel</button>
          <button className="btn danger" form="reject-form" type="submit" disabled={busy || reason.trim().length < 10 || !password}>
            {busy ? "Recording…" : "Record rejection"}
          </button>
        </>
      }
    >
      <form id="reject-form" onSubmit={submit} className="grid" style={{ gap: 12 }}>
        <div className="notice">
          <ShieldAlert size={15} />
          <div>
            The score is above the merit floor. The audit receipt records {session.display_name}'s name, the reason, and
            the payload hash. Candidate consent must still be granted.
          </div>
        </div>
        <Field label="Reason" hint="At least 10 characters. This goes to the audit chain, not to the candidate.">
          <textarea value={reason} onChange={(event) => setReason(event.target.value)} autoFocus />
        </Field>
        <Field label="Confirm your password">
          <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} />
        </Field>
        {error ? <ErrorBox>{error}</ErrorBox> : null}
      </form>
    </Modal>
  );
}



function ExtractDialog({
  applicationId,
  candidateId,
  onClose,
  onScored,
}: {
  applicationId: string;
  candidateId: string;
  onClose: () => void;
  onScored: () => Promise<void>;
}) {
  const [text, setText] = useState(
    "Built a Rust ingestion pipeline handling 2M events per day. Reduced p99 latency from 900ms to 180ms across checkout. Led a three-engineer migration to Postgres and introduced SQL query budgets.",
  );
  const [fileName, setFileName] = useState<string | null>(null);
  const [fileBase64, setFileBase64] = useState<string | null>(null);
  const [fileMime, setFileMime] = useState("text/plain");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  async function onFile(file: File) {
    setError(null);
    const buffer = new Uint8Array(await file.arrayBuffer());
    let binary = "";
    const chunk = 8192;
    for (let i = 0; i < buffer.length; i += chunk) {
      binary += String.fromCharCode(...buffer.slice(i, i + chunk));
    }
    setFileName(file.name);
    setFileBase64(btoa(binary));
    setFileMime(file.type || "application/octet-stream");
    if (file.name.toLowerCase().endsWith(".txt") || file.type.startsWith("text/")) {
      try {
        setText(new TextDecoder().decode(buffer));
      } catch {
        /* keep pasted text */
      }
    } else {
      setText("");
    }
  }

  const isFile = Boolean(fileBase64 && /\.(pdf|docx)$/i.test(fileName ?? ""));

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (isFile) {
        const uploaded = await command<Document>("upload_document", {
          owner_type: "candidate",
          owner_id: candidateId,
          filename: fileName,
          mime_type: fileMime,
          base64: fileBase64,
        });
        await command("extract_and_evaluate", {
          application_id: applicationId,
          document_id: uploaded.id,
          rubric: DEMO_RUBRIC,
        });
      } else {
        await command("evaluate_from_text", {
          application_id: applicationId,
          document_text: text,
          rubric: DEMO_RUBRIC,
        });
      }
      await onScored();
    } catch (caught) {
      setError(typeof caught === "object" && caught && "message" in caught ? String((caught as { message: unknown }).message) : String(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      title="Extract evidence and score"
      subtitle="PDF, DOCX, or pasted text · deterministic offline extractor · every score needs a quote"
      onClose={onClose}
      wide
      footer={
        <>
          <button className="btn" onClick={onClose} type="button">Cancel</button>
          <button
            className="btn primary"
            form="extract-form"
            type="submit"
            disabled={busy || (!isFile && text.trim().length < 20)}
          >
            {busy ? "Extracting…" : "Run extraction"}
            <Sparkles size={15} />
          </button>
        </>
      }
    >
      <form id="extract-form" onSubmit={submit} className="grid" style={{ gap: 12 }}>
        <div className="row">
          <input
            ref={fileRef}
            type="file"
            accept=".txt,.md,.pdf,.docx"
            style={{ display: "none" }}
            aria-label="Choose a CV file"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) void onFile(file);
            }}
          />
          <button className="btn sm" type="button" onClick={() => fileRef.current?.click()}>
            <Upload size={13} /> {fileName ?? "Choose .txt / .pdf / .docx"}
          </button>
          {fileName ? (
            <span className="small faint">
              {/\.(pdf|docx)$/i.test(fileName)
                ? "parsed in Rust, then scored"
                : "read as text, then scored"}
            </span>
          ) : null}
        </div>
        {!isFile ? (
          <Field label="CV or portfolio text" hint="Paste the text you want scored. Prompt-injection text is treated as data.">
            <textarea value={text} onChange={(event) => setText(event.target.value)} style={{ minHeight: 160 }} />
          </Field>
        ) : (
          <div className="notice">
            <Sparkles size={15} />
            <div>
              {fileName} will be uploaded, parsed to text in Rust, and scored with evidence quotes
              pointing at the stored file.
            </div>
          </div>
        )}
        {error ? <ErrorBox>{error}</ErrorBox> : null}
      </form>
    </Modal>
  );
}
