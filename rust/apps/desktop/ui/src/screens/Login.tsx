import { useState } from "react";
import { ArrowRight, KeyRound, ShieldCheck } from "lucide-react";
import { command, isDesktop } from "../api";
import type { SessionView } from "../types";
import { ErrorBox, Field } from "../components/ui";

export function Login({
  setupRequired,
  company,
  onSignedIn,
}: {
  setupRequired: boolean;
  company: string | null;
  onSignedIn: (session: SessionView) => void;
}) {
  const [companyName, setCompanyName] = useState(company ?? "Nusantara Labs");
  const [operatorName, setOperatorName] = useState("Rina");
  const [username, setUsername] = useState("rina");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const session = setupRequired
        ? await command<SessionView>("setup_first_run", {
            input: {
              company_name: companyName,
              operator_name: operatorName,
              username,
              password,
            },
          })
        : await command<SessionView>("login", { username, password });
      onSignedIn(session);
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
    <div className="login">
      <aside className="login-brand">
        <div>
          <div className="row" style={{ gap: 10 }}>
            <span className="brand-mark" style={{ background: "var(--surface)", color: "var(--ink)" }}>HR</span>
            <div>
              <div style={{ fontWeight: 650 }}>HRAgents</div>
              <div style={{ fontSize: 11, color: "var(--on-dark-muted)" }}>Desktop edition</div>
            </div>
          </div>
          <h2 style={{ marginTop: 64 }}>
            The audit-grade HR cockpit for the HR department of one.
          </h2>
          <p>
            Hiring, onboarding, people records, leave, payroll preparation, and compliance — on your
            laptop, with a named decision behind every outcome.
          </p>
          <div className="login-points">
            <div className="login-point">
              <ShieldCheck size={17} />
              <span>Every consequential action needs an HR operator and a reason.</span>
            </div>
            <div className="login-point">
              <KeyRound size={17} />
              <span>Local login, app lock, and re-authentication for payroll and erasure.</span>
            </div>
            <div className="login-point">
              <CheckCircle />
              <span>No payment execution. No employee or manager logins. One company per install.</span>
            </div>
          </div>
        </div>
        <div className="small" style={{ color: "var(--on-dark-muted)" }}>
          Apache-2.0 · data stays on this machine
        </div>
      </aside>

      <main className="login-form-wrap">
        <form className="login-form" onSubmit={submit}>
          <div className="row" style={{ justifyContent: "space-between", marginBottom: 22 }}>
            <span className="pill info">HR operator only</span>
            {!isDesktop ? <span className="preview-badge">Browser preview</span> : null}
          </div>
          <h1>{setupRequired ? "Set up this installation" : "Welcome back"}</h1>
          <p className="lede">
            {setupRequired
              ? "Create the company and the first HR operator. This account is local to this laptop."
              : `Sign in to ${company ?? "your HR cockpit"}.`}
          </p>

          {setupRequired ? (
            <>
              <Field label="Company name">
                <input value={companyName} onChange={(event) => setCompanyName(event.target.value)} required />
              </Field>
              <Field label="Your name">
                <input value={operatorName} onChange={(event) => setOperatorName(event.target.value)} required />
              </Field>
            </>
          ) : null}

          <Field label="Username">
            <input
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              autoComplete="username"
              required
            />
          </Field>
          <Field label="Password" hint={setupRequired ? "At least 12 characters. There is no email reset." : undefined}>
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete={setupRequired ? "new-password" : "current-password"}
              placeholder={isDesktop ? "" : "Use any password in browser preview"}
              required
            />
          </Field>

          {error ? <ErrorBox>{error}</ErrorBox> : null}

          <button className="btn primary" type="submit" disabled={busy} style={{ width: "100%", marginTop: 16 }}>
            {busy ? "Working…" : setupRequired ? "Create installation" : "Sign in"}
            <ArrowRight size={15} />
          </button>

          <div className="login-foot">
            This app holds payroll and identity data. Lock it when you step away
            <span className="kbd" style={{ marginLeft: 5 }}>Ctrl</span>
            <span className="kbd">Shift</span>
            <span className="kbd">L</span>.
            {!isDesktop ? " Browser preview uses demo data and does not touch a database." : null}
          </div>
        </form>
      </main>
    </div>
  );
}

function CheckCircle() {
  return <ShieldCheck size={17} />;
}
