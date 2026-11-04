import { useRef, useState } from "react";
import { ArrowRight, BookOpen, CornerDownLeft, MessageSquare, ShieldCheck, Sparkles } from "lucide-react";
import { command } from "../api";
import type { AskResponse } from "../types";
import type { Surface as NavSurface } from "../nav";
import { ErrorBox } from "../components/ui";

interface Message {
  role: "operator" | "assistant";
  body: string;
  citation?: string;
  providerUsed?: boolean;
}

const SUGGESTIONS = [
  "What is the probation period for a new hire?",
  "Can we reject a candidate above the merit floor?",
  "What does payroll need before sign-off?",
  "What happens when consent is withdrawn?",
];

export function Ask({ onNavigate }: { onNavigate: (surface: NavSurface) => void }) {
  const [messages, setMessages] = useState<Message[]>([
    {
      role: "assistant",
      body:
        "Ask about policy, leave, probation, payroll readiness, or a decision. I answer from the local policy corpus and cite the source. I never decide, send, or change a record on my own.",
      citation: "Local policy corpus · 5 documents indexed",
    },
  ]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  void onNavigate;

  async function ask(question: string) {
    const value = question.trim();
    if (!value || busy) return;
    setBusy(true);
    setError(null);
    setMessages((current) => [...current, { role: "operator", body: value }]);
    setInput("");
    try {
      const answer = await command<AskResponse>("ask_assistant", { question: value });
      const citation = answer.citations.length > 0
        ? answer.citations.map((hit) => hit.title).join(" · ")
        : "No matching source in the local corpus";
      setMessages((current) => [
        ...current,
        { role: "assistant", body: answer.body, citation, providerUsed: answer.provider_used },
      ]);
    } catch (caught) {
      setError(typeof caught === "object" && caught && "message" in caught ? String((caught as { message: unknown }).message) : String(caught));
    } finally {
      setBusy(false);
      requestAnimationFrame(() => scrollRef.current?.scrollTo({ top: 99999, behavior: "smooth" }));
    }
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
                {message.providerUsed ? (
                  <div className="citation"><Sparkles size={11} /> phrased with DeepSeek V4.1 Flash · citations unchanged</div>
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
            <button className="btn primary" type="submit" disabled={!input.trim() || busy}>
              {busy ? "Asking…" : <>Ask <CornerDownLeft size={13} /></>}
            </button>
          </form>
          {error ? <ErrorBox>{error}</ErrorBox> : null}
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
              <li>Policy rules built into this company's local corpus, with citations.</li>
              <li>Counts and balances returned by a read-only tool.</li>
              <li>No payroll amounts beyond what your session can already open.</li>
              <li>Offline by default; with a provider key, DeepSeek V4.1 Flash may rephrase the answer — citations never change.</li>
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
