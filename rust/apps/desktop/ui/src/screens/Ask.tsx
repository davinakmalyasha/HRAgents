import { useRef, useState } from "react";
import { ArrowRight, BookOpen, CornerDownLeft, MessageSquare, ShieldCheck } from "lucide-react";
import type { Surface } from "../nav";

interface Message {
  role: "operator" | "assistant";
  body: string;
  citation?: string;
  handoff?: { label: string; surface: Surface };
}

const SUGGESTIONS = [
  "How many annual leave days does Ayu have left?",
  "What is the probation period for a new hire?",
  "Can we reject a candidate above the merit floor?",
  "What does payroll need before sign-off?",
];

const ANSWERS: { match: RegExp; body: string; citation: string; handoff?: { label: string; surface: Surface } }[] = [
  {
    match: /leave|annual|balance/i,
    body:
      "Ayu Lestari has 10 of 12 annual-leave days left for 2026: 12 entitled, 2 approved and used, 0 pending. Leave is recorded by HR on the person's behalf; there is no employee login in this edition.",
    citation: "Annual leave policy · §3 Accrual and carry-over · verified 2026-01-01",
    handoff: { label: "Open Ayu's leave record", surface: "people" },
  },
  {
    match: /probation|new hire|contract/i,
    body:
      "The standard probation period is three months, with one extension of up to three months only in writing. A fixed-term contract must state its end date and the reason for the term; expiry reminders are generated 30 days ahead.",
    citation: "Employment contract policy · §2 Probation and fixed-term contracts",
    handoff: { label: "Open People", surface: "people" },
  },
  {
    match: /reject|merit|floor|candidate/i,
    body:
      "Yes, but never automatically. A rejection at or above the merit floor is a gated decision: it needs an authenticated HR operator, a reason of at least 10 characters, and a fresh password. The audit chain stores the operator, reason, and payload hash. Consent must still be granted.",
    citation: "Hiring policy · §6 Gated rejection · ADR-0002 and ADR-0011",
    handoff: { label: "Open the candidate case file", surface: "hire" },
  },
  {
    match: /payroll|salary|sign.?off|bpjs|tax/i,
    body:
      "Payroll needs seven verified statutory tables (BPJS Kesehatan, JHT, JP, JKK, JKM, PPh 21 TER, PTKP), a complete payroll profile for each employee, and no blocking anomalies. Sign-off requires a fresh password and freezes the run. The app never executes a payment; it exports a review packet.",
    citation: "Payroll runbook · §1 Pre-flight and §4 Sign-off",
    handoff: { label: "Open Pay", surface: "pay" },
  },
  {
    match: /consent|withdraw|gdpr|pdpa|erase/i,
    body:
      "Withdrawing consent stops processing immediately: scoring, messaging, and offers are blocked, and the withdrawal is audited. Erasure is a separate gated action: approval and execution are both named, retention holds block it, and audit rows and statutory payroll records survive.",
    citation: "Data governance · §2 Consent and §5 Erasure",
    handoff: { label: "Open Settings", surface: "settings" },
  },
];

export function Ask({ onNavigate }: { onNavigate: (surface: Surface) => void }) {
  const [messages, setMessages] = useState<Message[]>([
    {
      role: "assistant",
      body:
        "Ask about policy, leave balances, payroll readiness, or a decision. I answer from the local policy corpus and cite the source. I never decide, send, or change a record on my own.",
      citation: "Local policy corpus · 4 documents indexed",
    },
  ]);
  const [input, setInput] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  function ask(question: string) {
    const value = question.trim();
    if (!value) return;
    const answer: { body: string; citation: string; handoff?: { label: string; surface: Surface } } =
      ANSWERS.find((item) => item.match.test(value)) ?? {
        body:
          "I could not find a policy source for that question. Try asking about leave, probation, rejection gates, payroll sign-off, or consent. I will not guess a statutory figure.",
        citation: "No matching source in the local corpus",
      };
    setMessages((current) => [
      ...current,
      { role: "operator", body: value },
      { role: "assistant", body: answer.body, citation: answer.citation, handoff: answer.handoff },
    ]);
    setInput("");
    requestAnimationFrame(() => scrollRef.current?.scrollTo({ top: 99999, behavior: "smooth" }));
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Ask</h1>
          <p>Policy answers with citations, scoped to this company's local documents.</p>
        </div>
        <div className="page-actions">
          <span className="pill"><ShieldCheck size={11} /> read-only</span>
        </div>
      </div>

      <div className="grid two-col">
        <section className="card chat">
          <div className="card-head">
            <MessageSquare size={15} />
            <h2>Policy assistant</h2>
            <span className="sub">cites, never decides</span>
          </div>
          <div className="chat-scroll" ref={scrollRef}>
            {messages.map((message, index) => (
              <div key={`${message.role}-${index}`}>
                <div className={`bubble ${message.role}`}>{message.body}</div>
                {message.citation ? <div className="citation">{message.citation}</div> : null}
                {message.handoff ? (
                  <button
                    className="btn sm"
                    style={{ marginTop: 7 }}
                    onClick={() => onNavigate(message.handoff!.surface)}
                  >
                    {message.handoff.label} <ArrowRight size={13} />
                  </button>
                ) : null}
              </div>
            ))}
            {messages.length === 1 ? (
              <div className="grid" style={{ gap: 8 }}>
                <div className="small faint">Try one of these</div>
                <div className="row" style={{ flexWrap: "wrap", gap: 8 }}>
                  {SUGGESTIONS.map((suggestion) => (
                    <button
                      key={suggestion}
                      className="btn sm"
                      style={{ height: "auto", padding: "7px 10px", whiteSpace: "normal", textAlign: "left" }}
                      onClick={() => ask(suggestion)}
                    >
                      {suggestion}
                    </button>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
          <form
            className="chat-input"
            onSubmit={(event) => {
              event.preventDefault();
              ask(input);
            }}
          >
            <input
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder="Ask about leave, probation, payroll, or a decision…"
              aria-label="Ask a policy question"
            />
            <button className="btn primary" type="submit" disabled={!input.trim()}>
              Ask <CornerDownLeft size={13} />
            </button>
          </form>
        </section>

        <aside className="grid" style={{ alignContent: "start" }}>
          <section className="card">
            <div className="card-head">
              <BookOpen size={15} />
              <h2>Suggested questions</h2>
            </div>
            <div style={{ padding: 10 }}>
              {SUGGESTIONS.map((suggestion) => (
                <button
                  key={suggestion}
                  className="list-row"
                  style={{ width: "100%", border: 0, background: "transparent", textAlign: "left", cursor: "pointer", borderRadius: 8 }}
                  onClick={() => ask(suggestion)}
                >
                  <span className="grow">
                    <span style={{ fontWeight: 520 }}>{suggestion}</span>
                  </span>
                  <ArrowRight size={14} className="faint" />
                </button>
              ))}
            </div>
          </section>

          <section className="card card-pad">
            <div style={{ fontWeight: 620 }}>What Ask can see</div>
            <ul className="small muted" style={{ margin: "8px 0 0", paddingLeft: 18, lineHeight: 1.7 }}>
              <li>Policy documents imported into this company's local database.</li>
              <li>Counts and balances returned by a read-only tool.</li>
              <li>No payroll amounts beyond what your session can already open.</li>
              <li>No network call unless you configured a provider; the offline test provider works without one.</li>
            </ul>
          </section>

          <div className="notice">
            <ShieldCheck size={15} />
            <div>
              Prompt injection from a CV is treated as data. The assistant has no command surface and
              cannot approve, reject, erase, or export.
            </div>
          </div>
        </aside>
      </div>
    </>
  );
}
