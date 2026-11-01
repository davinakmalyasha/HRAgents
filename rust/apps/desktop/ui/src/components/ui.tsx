import type { ReactNode } from "react";
import { AlertTriangle, CheckCircle2, Circle, Info, X } from "lucide-react";

export function errorMessage(error: unknown): string {
  if (typeof error === "object" && error && "message" in error) {
    return String((error as { message: unknown }).message);
  }
  return String(error);
}

export function Avatar({ name, size = 30 }: { name: string; size?: number }) {
  const initials = name
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");
  return (
    <span className="avatar" style={{ width: size, height: size, fontSize: size * 0.37 }}>
      {initials}
    </span>
  );
}

export function StatusPill({
  tone = "neutral",
  label,
}: {
  tone?: "neutral" | "ok" | "warn" | "bad" | "info";
  label: string;
}) {
  const Icon = tone === "ok" ? CheckCircle2 : tone === "warn" ? AlertTriangle : tone === "bad" ? AlertTriangle : tone === "info" ? Info : Circle;
  return (
    <span className={`pill ${tone === "neutral" ? "" : tone}`}>
      <Icon size={11} strokeWidth={2.4} aria-hidden />
      {label}
    </span>
  );
}

export function Field({
  label,
  hint,
  children,
  span = false,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
  span?: boolean;
}) {
  return (
    <div className={`field ${span ? "span-2" : ""}`}>
      <label>{label}</label>
      {children}
      {hint ? <span className="hint">{hint}</span> : null}
    </div>
  );
}

export function Modal({
  title,
  subtitle,
  onClose,
  children,
  footer,
  wide = false,
}: {
  title: string;
  subtitle?: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
}) {
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label={title}>
      <div className="modal" style={wide ? { width: "min(760px, 100%)" } : undefined}>
        <div className="modal-head">
          <div>
            <h2>{title}</h2>
            {subtitle ? <div className="small muted">{subtitle}</div> : null}
          </div>
          <button className="btn ghost sm" style={{ marginLeft: "auto" }} onClick={onClose} aria-label="Close">
            <X size={16} />
          </button>
        </div>
        <div className="modal-body">{children}</div>
        {footer ? <div className="modal-foot">{footer}</div> : null}
      </div>
    </div>
  );
}

export function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <div className="empty">
      <div className="icon">
        <Circle size={18} />
      </div>
      <div style={{ fontWeight: 600, color: "var(--ink)" }}>{title}</div>
      <div className="small" style={{ marginTop: 4 }}>{body}</div>
    </div>
  );
}

export function ScoreBar({ value, tone = "" }: { value: number; tone?: "" | "ok" | "warn" | "bad" }) {
  const pct = Math.max(0, Math.min(100, value / 100));
  return (
    <div className={`bar ${tone}`} aria-label={`Score ${pct.toFixed(1)} percent`}>
      <span style={{ width: `${pct}%` }} />
    </div>
  );
}

export function ErrorBox({ children }: { children: ReactNode }) {
  return <div className="error-text">{children}</div>;
}

export function Notice({ children }: { children: ReactNode }) {
  return (
    <div className="notice">
      <Info size={15} style={{ flex: "0 0 auto", marginTop: 1 }} />
      <div>{children}</div>
    </div>
  );
}
