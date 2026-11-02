import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Building2,
  CheckCircle2,
  Database,
  HardDriveDownload,
  KeyRound,
  Lock,
  ShieldCheck,
  Users,
} from "lucide-react";
import { command, formatDateTime, isDesktop } from "../api";
import type { AuditVerification, OperatorView, RateTable, SessionView } from "../types";
import { ErrorBox, Field, Modal, StatusPill } from "../components/ui";
import { ComplianceSection } from "./Compliance";

export function Settings({ session }: { session: SessionView }) {
  const [verifyResult, setVerifyResult] = useState<AuditVerification | null>(null);
  const [verifyError, setVerifyError] = useState<string | null>(null);
  const [recoveryOpen, setRecoveryOpen] = useState(false);
  const [complianceError, setComplianceError] = useState<string | null>(null);
  const [backupPath, setBackupPath] = useState("hragents-backup.hrbackup");
  const [exportPath, setExportPath] = useState("audit-export.json");
  const [exportResult, setExportResult] = useState<string | null>(null);
  const [backupResult, setBackupResult] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const operators = useQuery({ queryKey: ["operators"], queryFn: () => command<OperatorView[]>("list_operators") });
  const tables = useQuery({ queryKey: ["rate-tables"], queryFn: () => command<RateTable[]>("rate_tables") });
  const required = new Set(["bpjs_kesehatan", "bpjs_ketenagakerjaan_jht", "bpjs_ketenagakerjaan_jp", "bpjs_jkk", "bpjs_jkm", "pph21_ter", "pph21_ptkp"]);
  const verifiedRequired = (tables.data ?? []).filter((table) => table.verified && required.has(table.kind)).length;

  async function verify() {
    setBusy(true);
    setVerifyError(null);
    try {
      setVerifyResult(await command<AuditVerification>("audit_verify"));
    } catch (caught) {
      setVerifyError(message(caught));
    } finally {
      setBusy(false);
    }
  }

  async function backup() {
    setBusy(true);
    setBackupResult(null);
    try {
      const size = await command<number>("backup_set", { path: backupPath });
      setBackupResult(`Encrypted backup set written: ${(size / 1024).toFixed(0)} KB (database + documents + key). Store it offline.`);
    } catch (caught) {
      setBackupResult(message(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Settings</h1>
          <p>Company, operators, statutory tables, backup, and the audit chain.</p>
        </div>
        <div className="page-actions">
          <span className="pill"><Lock size={11} /> local-only install</span>
        </div>
      </div>

      <div className="grid two-col">
        <div className="grid" style={{ alignContent: "start" }}>
          <section className="card">
            <div className="card-head">
              <Building2 size={15} />
              <h2>Company</h2>
            </div>
            <div className="card-pad detail-grid">
              <Fact k="Legal name" v={session.display_name === "Rina" ? "Nusantara Labs" : "This installation"} />
              <Fact k="Timezone" v="Asia/Jakarta" />
              <Fact k="Currency" v="IDR · integer sen" />
              <Fact k="Role model" v="one hr_operator role" />
            </div>
          </section>

          <section className="card">
            <div className="card-head">
              <Users size={15} />
              <h2>Operators</h2>
              <span className="sub">same permissions, separate names</span>
            </div>
            {(operators.data ?? []).map((operator) => (
              <div className="list-row" key={operator.id}>
                <span className="icon-box"><KeyRound size={15} /></span>
                <div className="grow">
                  <div className="title">{operator.display_name}</div>
                  <div className="meta">@{operator.username} · {operator.role}</div>
                </div>
                <StatusPill tone={operator.active ? "ok" : "bad"} label={operator.active ? "active" : "disabled"} />
                <span className="small faint">{formatDateTime(operator.created_at)}</span>
              </div>
            ))}
            <div className="card-pad small muted">
              Up to three HR operators share one role. Every audit entry records which person acted.
              There is no admin, manager, finance, employee, or candidate login.
            </div>
          </section>

          <section className="card">
            <div className="card-head">
              <ShieldCheck size={15} />
              <h2>Audit chain</h2>
              <span className="sub">SHA-256 · append-only</span>
            </div>
            <div className="card-pad grid" style={{ gap: 10 }}>
              <div className="row">
                <button className="btn" onClick={verify} disabled={busy}>
                  Verify chain
                </button>
                <span className="small faint">Runs on demand and on unlock.</span>
              </div>
              {verifyResult ? (
                <div className="notice">
                  <CheckCircle2 size={15} />
                  <div>
                    Verified {verifyResult.entries} entries.
                    <div className="mono" style={{ marginTop: 3 }}>
                      head {verifyResult.head_hash?.slice(0, 24)}…
                    </div>
                  </div>
                </div>
              ) : null}
              {verifyError ? <ErrorBox>{verifyError}</ErrorBox> : null}
              <div className="row" style={{ gap: 8 }}>
                <input
                  value={exportPath}
                  onChange={(event) => setExportPath(event.target.value)}
                  placeholder="audit-export.json"
                  aria-label="Audit export path"
                  style={{ flex: 1, height: 34, border: "1px solid var(--line)", borderRadius: 8, padding: "0 10px" }}
                />
                <button
                  className="btn sm"
                  disabled={busy || !exportPath}
                  onClick={async () => {
                    setBusy(true);
                    setExportResult(null);
                    try {
                      const size = await command<number>("export_audit", { path: exportPath, limit: null });
                      setExportResult(`Exported ${(size / 1024).toFixed(1)} KB to ${exportPath}`);
                    } catch (caught) {
                      setExportResult(
                        typeof caught === "object" && caught && "message" in caught
                          ? String((caught as { message: unknown }).message)
                          : String(caught),
                      );
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  Export audit JSON
                </button>
              </div>
              {exportResult ? <div className="small muted">{exportResult}</div> : null}
              <div className="small muted">
                Each entry hashes its content and the previous hash. A changed row invalidates every
                later hash. Audit rows survive erasure and payroll retention.
              </div>
            </div>
          </section>

          <section className="card">
            <div className="card-head">
              <HardDriveDownload size={15} />
              <h2>Backup</h2>
              <span className="sub">Database + documents + key, hashed</span>
            </div>
            <div className="card-pad grid" style={{ gap: 10 }}>
              <Field label="Backup path" hint={isDesktop ? "One encrypted archive with the database, documents, and key." : "Browser preview does not write a file."}>
                <input value={backupPath} onChange={(event) => setBackupPath(event.target.value)} />
              </Field>
              <button className="btn" onClick={backup} disabled={busy || !backupPath}>
                Create encrypted backup set
              </button>
              {backupResult ? <div className="small muted">{backupResult}</div> : null}
            </div>
          </section>
        </div>

        <aside className="grid" style={{ alignContent: "start" }}>
          <section className="card">
            <div className="card-head">
              <Database size={15} />
              <h2>Statutory rate tables</h2>
              <span className="sub">{verifiedRequired}/7 verified</span>
            </div>
            {(tables.data ?? []).length === 0 ? (
              <div className="card-pad small muted">
                No rate tables yet. Payroll refuses to compute until the seven required tables are
                entered, effective-dated, and verified against a source.
              </div>
            ) : (
              <table className="table">
                <thead>
                  <tr><th scope="col">Kind</th><th scope="col">Effective</th><th scope="col">Status</th></tr>
                </thead>
                <tbody>
                  {(tables.data ?? []).map((table) => (
                    <tr key={table.id}>
                      <td>{table.kind.replaceAll("_", " ")}</td>
                      <td className="small">{table.effective_from}</td>
                      <td><StatusPill tone={table.verified ? "ok" : "warn"} label={table.verified ? "verified" : "unverified"} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <section className="card card-pad">
            <div style={{ fontWeight: 620 }}>Security posture</div>
            <div className="grid" style={{ gap: 9, marginTop: 10 }}>
              <SecurityRow label="Local login + app lock" enabled />
              <SecurityRow label="Re-auth for payroll, erasure, rejection" enabled />
              <SecurityRow label="No payment execution" enabled />
              <SecurityRow label="No employee/manager logins" enabled />
              <SecurityRow label="No telemetry by default" enabled />
              <SecurityRow
                label="SQLCipher database at rest"
                enabled={isDesktop}
                note={isDesktop ? "on" : "browser preview"}
              />
              <SecurityRow
                label="Encrypted documents + backups"
                enabled={isDesktop}
                note={isDesktop ? "ChaCha20-Poly1305" : "browser preview"}
              />
              <SecurityRow
                label="Protected install key"
                enabled={isDesktop}
                note={isDesktop ? "DPAPI / mode 0600" : "browser preview"}
              />
            </div>
            <div className="notice" style={{ marginTop: 10 }}>
              <KeyRound size={15} />
              <div>
                The database, uploaded documents, and backups are encrypted with a per-install key.
                Copy <span className="mono">hragents.key</span> somewhere safe and separate from the
                database: without it, the data cannot be recovered — there is no back door.
              </div>
            </div>
          </section>

          <section className="card card-pad">
            <div style={{ fontWeight: 620 }}>Recovery key</div>
            <div className="small muted" style={{ marginTop: 4 }}>
              Export the 64-character key for offline storage, or re-protect the key file with the
              current Windows user. Both actions require your password.
            </div>
            <button className="btn sm" style={{ marginTop: 10 }} onClick={() => setRecoveryOpen(true)}>
              <KeyRound size={13} /> Manage recovery key
            </button>
          </section>

          <section className="card card-pad">
            <div style={{ fontWeight: 620 }}>Updates</div>
            <div className="small muted" style={{ marginTop: 4 }}>
              Everything works offline. No account, no subscription, no update server.
            </div>
            <UpdateChecker />
          </section>

          <section className="card card-pad">
            <div style={{ fontWeight: 620 }}>Session</div>
            <div className="small muted" style={{ marginTop: 6 }}>
              {session.display_name} · {session.role}
            </div>
            <div className="small faint" style={{ marginTop: 3 }}>
              Signed in {formatDateTime(session.started_at)}
            </div>
            <div className="small faint">
              Re-auth fresh: {session.reauth_fresh ? "yes" : "no"}
            </div>
            <div className="notice" style={{ marginTop: 10 }}>
              <Lock size={14} />
              <div>Idle lock after 10 minutes. Use Ctrl+Shift+L to lock immediately.</div>
            </div>
          </section>
        </aside>
      </div>

      <div className="page-head" style={{ marginTop: 26 }}>
        <div>
          <h1 style={{ fontSize: 20 }}>Compliance</h1>
          <p>Retention, erasure, and breach response. Nothing here sends data anywhere.</p>
        </div>
      </div>
      {complianceError ? <ErrorBox>{complianceError}</ErrorBox> : null}
      <ComplianceSection onError={setComplianceError} />
      {recoveryOpen ? <RecoveryKeyModal onClose={() => setRecoveryOpen(false)} /> : null}
    </>
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

function UpdateChecker() {
  return (
    <div className="small muted" style={{ marginTop: 8 }}>
      Automatic updates are off in this free edition — there is no hosted update server and no
      telemetry. To upgrade, install a newer build from the same source you got this one.
      Your database and audit chain stay compatible.
    </div>
  );
}

function SecurityRow({ label, enabled, note }: { label: string; enabled: boolean; note?: string }) {
  return (
    <div className="row" style={{ justifyContent: "space-between", gap: 8 }}>
      <span className="row small" style={{ gap: 7 }}>
        {enabled ? <CheckCircle2 size={13} style={{ color: "var(--success)" }} /> : <Lock size={13} className="faint" />}
        {label}
      </span>
      <span className="small faint">{note ?? (enabled ? "on" : "off")}</span>
    </div>
  );
}

function message(caught: unknown): string {
  if (typeof caught === "object" && caught && "message" in caught) {
    return String((caught as { message: unknown }).message);
  }
  return String(caught);
}


function RecoveryKeyModal({ onClose }: { onClose: () => void }) {
  const [password, setPassword] = useState("");
  const [key, setKey] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function exportKey(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const value = await command<string>("recovery_key", { password });
      setKey(value);
    } catch (caught) {
      setError(message(caught));
    } finally {
      setBusy(false);
    }
  }

  async function rewrapKey() {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await command("rewrap_install_key", { password });
      setNotice("The key file is now protected by the current OS user.");
    } catch (caught) {
      setError(message(caught));
    } finally {
      setBusy(false);
    }
  }

  async function copyKey() {
    if (!key) return;
    try {
      await navigator.clipboard.writeText(key);
      setNotice("Recovery key copied to the clipboard.");
    } catch {
      setNotice("Copy failed; select the key text and copy it manually.");
    }
  }

  return (
    <Modal
      title="Recovery key"
      subtitle="Anyone with this key and the database can read the data. Store it offline."
      onClose={onClose}
    >
      <form className="grid" style={{ gap: 12 }} onSubmit={exportKey}>
        <Field label="Your password" hint="Required before the key can be shown or rewrapped.">
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="current-password"
            required
          />
        </Field>
        {error ? <ErrorBox>{error}</ErrorBox> : null}
        {notice ? <div className="small muted">{notice}</div> : null}
        {key ? (
          <div className="grid" style={{ gap: 6 }}>
            <div className="small" style={{ fontWeight: 600 }}>Recovery key</div>
            <div className="row" style={{ gap: 6 }}>
              <input readOnly value={key} className="mono" aria-label="Recovery key" />
              <button className="btn sm" type="button" onClick={copyKey}>
                Copy
              </button>
            </div>
            <div className="small faint">
              Keep this in a password manager or offline safe. It is the only way to open the data
              if this Windows user or machine is lost.
            </div>
          </div>
        ) : null}
        <div className="row" style={{ gap: 8 }}>
          <button className="btn primary" type="submit" disabled={busy || !password}>
            {busy ? "Checking…" : "Show recovery key"}
          </button>
          <button className="btn" type="button" disabled={busy || !password} onClick={rewrapKey}>
            Re-protect key file
          </button>
        </div>
      </form>
    </Modal>
  );
}
