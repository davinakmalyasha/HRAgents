import { useState } from "react";
import { ArrowRight, KeyRound, ShieldCheck } from "lucide-react";
import { command, isDesktop } from "../api";
import type { SessionView } from "../types";
import { ErrorBox, Field, errorMessage } from "../components/ui";

export function Recovery({ onRecovered }: { onRecovered: (session: SessionView) => void }) {
  const [key, setKey] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const normalizedKey = key.replace(/[\s-]/g, "").toLowerCase();
  const validKey = normalizedKey.length === 64;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const session = await command<SessionView>("recover_with_key", {
        key: normalizedKey,
        username,
        password,
      });
      onRecovered(session);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login">
      <aside className="login-brand">
        <div>
          <div className="row" style={{ gap: 10 }}>
            <span className="brand-mark" style={{ background: "var(--surface)", color: "var(--ink)" }}>
              HR
            </span>
            <div>
              <div style={{ fontWeight: 650 }}>HRAgents</div>
              <div style={{ fontSize: 11, color: "var(--on-dark-muted)" }}>Desktop edition</div>
            </div>
          </div>
          <h2 style={{ marginTop: 64 }}>Recover this installation.</h2>
          <p>
            The database is encrypted and cannot be opened with the key on this machine. The
            recovery key opens it once; the app then protects the key for this OS user.
          </p>
          <div className="login-points">
            <div className="login-point">
              <KeyRound size={17} />
              <span>The recovery key is 64 hexadecimal characters, exported from Settings.</span>
            </div>
            <div className="login-point">
              <ShieldCheck size={17} />
              <span>The recovery is written to the audit chain under the operator who signs in.</span>
            </div>
          </div>
        </div>
        <div className="small" style={{ color: "var(--on-dark-muted)" }}>
          Apache-2.0 · data stays encrypted on this machine
        </div>
      </aside>

      <main className="login-form-wrap">
        <form className="login-form" onSubmit={submit}>
          <div className="row" style={{ justifyContent: "space-between", marginBottom: 22 }}>
            <span className="pill">
              <KeyRound size={11} /> recovery mode
            </span>
            {!isDesktop ? <span className="preview-badge">Browser preview</span> : null}
          </div>
          <h1>Recover this installation</h1>
          <p className="lede">
            Enter the recovery key you stored offline, then sign in with your HR operator account.
            Nothing is reset and no data is replaced.
          </p>

          <Field label="Recovery key" hint="64 hexadecimal characters. Spaces and dashes are ignored.">
            <input
              value={key}
              onChange={(event) => setKey(event.target.value)}
              className="mono"
              autoComplete="off"
              spellCheck={false}
              maxLength={80}
              placeholder="0123456789abcdef…"
              aria-label="Recovery key"
              required
            />
          </Field>
          <Field label="Username">
            <input
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              autoComplete="username"
              required
            />
          </Field>
          <Field label="Password">
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
              required
            />
          </Field>

          {error ? <ErrorBox>{error}</ErrorBox> : null}

          <button
            className="btn primary"
            type="submit"
            disabled={busy || !validKey || !username.trim() || !password}
            style={{ width: "100%", marginTop: 16 }}
          >
            {busy ? "Recovering…" : "Recover and sign in"}
            <ArrowRight size={15} />
          </button>

          <div className="login-foot">
            The key is re-protected for this OS user and a <span className="mono">security.recovered</span>{" "}
            audit entry is written. Keep the exported key: without it this database cannot be
            opened again.
          </div>
        </form>
      </main>
    </div>
  );
}
