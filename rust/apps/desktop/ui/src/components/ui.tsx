import { useEffect, useId, useRef } from "react";
import type { ReactNode } from "react";
import { AlertTriangle, CheckCircle2, Circle, Info, X } from "lucide-react";

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

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
  const neutral = tone === "neutral" || tone === "info";
  return (
    <span className={`pill ${neutral ? "" : tone}`}>
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
      <label>
        <span className="field-label">{label}</span>
        {children}
      </label>
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
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  // Captured during render, before the effect moves focus into the dialog.
  const restoreRef = useRef<Element | null>(document.activeElement);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    const dialog = dialogRef.current;
    const initial =
      dialog?.querySelector<HTMLElement>("[data-autofocus]") ??
      dialog?.querySelector<HTMLElement>(
        "input:not([disabled]), select:not([disabled]), textarea:not([disabled])",
      ) ??
      dialog?.querySelector<HTMLElement>(FOCUSABLE);
    (initial ?? dialog)?.focus();

    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab" || !dialog) return;
      const items = Array.from(dialog.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
        (element) => element.offsetParent !== null,
      );
      if (items.length === 0) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      const target = restoreRef.current as HTMLElement | null;
      if (target?.isConnected) target.focus();
    };
  }, []);

  return (
    <div
      className="modal-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        className="modal"
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        style={wide ? { width: "min(760px, 100%)" } : undefined}
      >
        <div className="modal-head">
          <div>
            <h2 id={titleId}>{title}</h2>
            {subtitle ? <div className="small muted">{subtitle}</div> : null}
          </div>
          <button
            className="btn ghost sm"
            style={{ marginLeft: "auto" }}
            onClick={onClose}
            aria-label="Close dialog"
          >
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
    <div
      className={`bar ${tone}`}
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(pct)}
      aria-valuetext={`${pct.toFixed(1)} percent`}
    >
      <span style={{ width: `${pct}%` }} />
    </div>
  );
}

export function ErrorBox({ children }: { children: ReactNode }) {
  return (
    <div className="error-text" role="alert">
      {children}
    </div>
  );
}

export function Notice({ children }: { children: ReactNode }) {
  return (
    <div className="notice">
      <Info size={15} style={{ flex: "0 0 auto", marginTop: 1 }} />
      <div>{children}</div>
    </div>
  );
}
