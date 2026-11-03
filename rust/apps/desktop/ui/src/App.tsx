import { Suspense, lazy, useDeferredValue, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Briefcase,
  Lock,
  LogOut,
  MessageSquare,
  Search,
  Settings as SettingsIcon,
  ShieldCheck,
  Sun,
  Users,
  Wallet,
} from "lucide-react";
import { command, isDesktop } from "./api";
import type { AppInfo, SearchHit, SessionView, TodayView } from "./types";
import type { Surface } from "./nav";
import { Login } from "./screens/Login";

// Today is the landing surface but it is only needed after login, so it loads
// on demand like the other surfaces. Login stays in the main bundle because a
// logged-out first paint needs it immediately.
const Today = lazy(() => import("./screens/Today").then((module) => ({ default: module.Today })));
const Recovery = lazy(() =>
  import("./screens/Recovery").then((module) => ({ default: module.Recovery })),
);
import { Avatar, ErrorBox, Field, Modal } from "./components/ui";

// Landing screens stay in the main bundle; the rest load on first visit.
const Hire = lazy(() => import("./screens/Hire").then((module) => ({ default: module.Hire })));
const People = lazy(() => import("./screens/People").then((module) => ({ default: module.People })));
const Pay = lazy(() => import("./screens/Pay").then((module) => ({ default: module.Pay })));
const Attendance = lazy(() => import("./screens/Attendance").then((module) => ({ default: module.Attendance })));
const Reports = lazy(() => import("./screens/Reports").then((module) => ({ default: module.Reports })));
const Ask = lazy(() => import("./screens/Ask").then((module) => ({ default: module.Ask })));
const Settings = lazy(() => import("./screens/Settings").then((module) => ({ default: module.Settings })));

const PRELOAD: Partial<Record<Surface, () => void>> = {
  today: () => void import("./screens/Today"),
  hire: () => void import("./screens/Hire"),
  people: () => void import("./screens/People"),
  pay: () => void import("./screens/Pay"),
  attendance: () => void import("./screens/Attendance"),
  reports: () => void import("./screens/Reports"),
  ask: () => void import("./screens/Ask"),
  settings: () => void import("./screens/Settings"),
};

const NAV: { id: Surface; label: string; icon: typeof Sun }[] = [
  { id: "today", label: "Today", icon: Sun },
  { id: "hire", label: "Hire", icon: Briefcase },
  { id: "people", label: "People", icon: Users },
  { id: "pay", label: "Pay", icon: Wallet },
  { id: "attendance", label: "Attendance", icon: Users },
  { id: "reports", label: "Reports", icon: Wallet },
  { id: "ask", label: "Ask", icon: MessageSquare },
  { id: "settings", label: "Settings", icon: SettingsIcon },
];

export function App() {
  const queryClient = useQueryClient();
  const [surface, setSurface] = useState<Surface>("today");
  const [search, setSearch] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const gPrefix = useRef<number | null>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  const info = useQuery({ queryKey: ["app-info"], queryFn: () => command<AppInfo>("app_info") });
  const session = useQuery({
    queryKey: ["session"],
    queryFn: () => command<SessionView>("current_session"),
    retry: false,
    // The backend enforces a 10-minute idle lock; poll so the UI actually
    // shows the lock screen instead of waiting for the next failed command.
    refetchInterval: 60_000,
  });
  const today = useQuery({
    queryKey: ["today"],
    queryFn: () => command<TodayView>("today"),
    enabled: Boolean(session.data) && !session.data?.locked,
  });
  const deferredSearch = useDeferredValue(search);
  const results = useQuery({
    queryKey: ["search", deferredSearch],
    queryFn: () => command<SearchHit[]>("search", { query: deferredSearch }),
    enabled: deferredSearch.trim().length > 1 && Boolean(session.data),
  });

  useEffect(() => {
    function inEditable(target: EventTarget | null): boolean {
      const element = target as HTMLElement | null;
      if (!element) return false;
      const tag = element.tagName?.toLowerCase() ?? "";
      return tag === "input" || tag === "textarea" || tag === "select" || element.isContentEditable;
    }

    function onKey(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        searchRef.current?.focus();
        setSearchOpen(true);
        return;
      }
      if ((event.ctrlKey || event.metaKey) && event.shiftKey && event.key.toLowerCase() === "l") {
        event.preventDefault();
        if (session.data && !session.data.locked) {
          void command("lock").then(() => {
            void queryClient.invalidateQueries({ queryKey: ["session"] });
          });
        }
        return;
      }
      if (inEditable(event.target)) return;
      if (event.key === "/") {
        event.preventDefault();
        searchRef.current?.focus();
        setSearchOpen(true);
        return;
      }
      if (event.key === "?") {
        event.preventDefault();
        setShortcutsOpen(true);
        return;
      }
      if (event.key.toLowerCase() === "g") {
        gPrefix.current = Date.now();
        return;
      }
      if (gPrefix.current !== null && Date.now() - gPrefix.current < 1200) {
        gPrefix.current = null;
        const destination: Record<string, Surface> = {
          t: "today",
          h: "hire",
          p: "people",
          y: "pay",
          a: "ask",
          s: "settings",
        };
        const next = destination[event.key.toLowerCase()];
        if (next) {
          event.preventDefault();
          setSurface(next);
          setSearchOpen(false);
          setSearch("");
        }
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [queryClient, session.data]);

  if (info.isLoading) {
    return <div className="empty" style={{ minHeight: "100vh", display: "grid", placeItems: "center" }}>Opening HRAgents…</div>;
  }

  if (info.data?.recovery_required) {
    return (
      <Suspense fallback={<div className="empty" style={{ minHeight: "100vh", display: "grid", placeItems: "center" }}>Opening HRAgents…</div>}>
        <Recovery
          onRecovered={(recovered) => {
            queryClient.setQueryData(["session"], recovered);
            queryClient.setQueryData<AppInfo>(["app-info"], (current) =>
              current ? { ...current, recovery_required: false } : current,
            );
            void queryClient.invalidateQueries({ queryKey: ["today"] });
          }}
        />
      </Suspense>
    );
  }

  if (!session.data) {
    return (
      <Login
        setupRequired={info.data?.setup_required ?? true}
        company={info.data?.company ?? null}
        onSignedIn={async () => {
          await Promise.all([
            queryClient.invalidateQueries({ queryKey: ["session"] }),
            queryClient.invalidateQueries({ queryKey: ["app-info"] }),
            queryClient.invalidateQueries({ queryKey: ["today"] }),
          ]);
        }}
      />
    );
  }

  if (session.data.locked) {
    return <LockScreen session={session.data} onUnlocked={() => queryClient.invalidateQueries({ queryKey: ["session"] })} />;
  }

  const approvals = today.data?.approvals.length ?? 0;

  function navigate(next: Surface) {
    setSurface(next);
    setSearchOpen(false);
    setSearch("");
  }

  return (
    <div className="app">
      <a className="skip-link" href="#main-content">Skip to content</a>
      <aside className="rail">
        <div className="brand">
          <span className="brand-mark">HR</span>
          <div>
            <div className="brand-name">HRAgents</div>
            <div className="brand-sub">{info.data?.company ?? "HR cockpit"}</div>
          </div>
        </div>
        <nav className="rail-nav" aria-label="Primary">
          <div className="rail-label">Workspace</div>
          {NAV.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              className={`nav-item ${surface === id ? "active" : ""}`}
              onClick={() => navigate(id)}
              aria-label={label}
              title={label}
              onMouseEnter={() => PRELOAD[id]?.()}
              onFocus={() => PRELOAD[id]?.()}
              aria-current={surface === id ? "page" : undefined}
            >
              <Icon size={17} strokeWidth={1.9} />
              <span>{label}</span>
              {id === "today" && approvals > 0 ? <span className="count">{approvals}</span> : null}
            </button>
          ))}
        </nav>

        <div className="rail-footer">
          <div className="operator-chip">
            <Avatar name={session.data.display_name} />
            <div className="who" style={{ minWidth: 0 }}>
              <div style={{ fontWeight: 600, fontSize: 12.5 }}>{session.data.display_name}</div>
              <div style={{ fontSize: 11 }} className="muted">HR operator</div>
            </div>
          </div>
          <div className="row" style={{ gap: 4, padding: "4px 4px 0" }}>
            <button
              className="btn ghost sm"
              style={{ flex: 1 }}
              onClick={() => {
                void command("lock").then(() => queryClient.invalidateQueries({ queryKey: ["session"] }));
              }}
            >
              <Lock size={13} /> <span>Lock</span>
            </button>
            <button
              className="btn ghost sm"
              style={{ flex: 1 }}
              onClick={async () => {
                await command("logout");
                await queryClient.invalidateQueries();
              }}
            >
              <LogOut size={13} /> <span>Sign out</span>
            </button>
          </div>
        </div>
      </aside>

      <main className="main" id="main-content" tabIndex={-1}>
        <header className="topbar">
          <div className="search">
            <Search size={15} className="search-icon" />
            <input
              ref={searchRef}
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
                setSearchOpen(true);
              }}
              onFocus={() => setSearchOpen(true)}
              onKeyDown={(event) => {
                if (event.key === "Escape") {
                  event.preventDefault();
                  setSearchOpen(false);
                  setSearch("");
                  event.currentTarget.blur();
                }
              }}
              placeholder="Search people, candidates, documents…"
              aria-label="Global search"
            />
            <span className="kbd" style={{ position: "absolute", right: 8, top: 8 }}>Ctrl K</span>
            {searchOpen && search.trim().length > 1 ? (
              <div className="card" style={{ position: "absolute", top: 42, left: 0, right: 0, zIndex: 40, overflow: "hidden" }}>
                {(results.data ?? []).length === 0 ? (
                  <div className="card-pad small muted">{results.isLoading ? "Searching…" : "No matches"}</div>
                ) : (
                  (results.data ?? []).map((hit) => (
                    <button
                      key={`${hit.kind}-${hit.id}`}
                      className="list-row"
                      style={{ width: "100%", border: 0, background: "transparent", textAlign: "left", cursor: "pointer" }}
                      onClick={() => navigate(hit.kind === "candidate" ? "hire" : "people")}
                    >
                      <span className="icon-box"><Search size={13} /></span>
                      <span className="grow">
                        <span className="title" style={{ display: "block" }}>{hit.title}</span>
                        <span className="meta" style={{ display: "block" }}>{hit.subtitle}</span>
                      </span>
                      <span className="pill">{hit.kind}</span>
                    </button>
                  ))
                )}
              </div>
            ) : null}
          </div>
          {!isDesktop ? <span className="preview-badge">Browser preview · demo data</span> : null}
          <div className="topbar-actions">
            <span className="pill ok"><ShieldCheck size={11} /> audited</span>
            <button className="btn ghost sm" onClick={() => setShortcutsOpen(true)} aria-label="Keyboard shortcuts">
              <span className="kbd">?</span> shortcuts
            </button>
            <span className="small faint">Ctrl+Shift+L to lock</span>
          </div>
        </header>

        <div className="content" onClick={() => setSearchOpen(false)}>
          <Suspense fallback={<div className="empty">Loading…</div>}>
            {surface === "today" ? <Today session={session.data} onNavigate={navigate} /> : null}
            {surface === "hire" ? <Hire session={session.data} /> : null}
            {surface === "people" ? <People /> : null}
            {surface === "pay" ? <Pay session={session.data} /> : null}
            {surface === "attendance" ? <Attendance /> : null}
            {surface === "reports" ? <Reports /> : null}
            {surface === "ask" ? <Ask onNavigate={navigate} /> : null}
            {surface === "settings" ? <Settings session={session.data} /> : null}
          </Suspense>
        </div>
      </main>

      {shortcutsOpen ? (
        <Modal
          title="Keyboard shortcuts"
          subtitle="Press ? anywhere outside a text field to reopen this list."
          onClose={() => setShortcutsOpen(false)}
        >
          <div className="grid" style={{ gap: 14 }}>
            <ShortcutGroup title="Search">
              <Shortcut keys="Ctrl K" label="Focus search" />
              <Shortcut keys="/" label="Focus search" />
            </ShortcutGroup>
            <ShortcutGroup title="Navigate">
              <Shortcut keys="G then T" label="Go to Today" />
              <Shortcut keys="G then H" label="Go to Hire" />
              <Shortcut keys="G then P" label="Go to People" />
              <Shortcut keys="G then Y" label="Go to Pay" />
              <Shortcut keys="G then A" label="Go to Ask" />
              <Shortcut keys="G then S" label="Go to Settings" />
            </ShortcutGroup>
            <ShortcutGroup title="Session">
              <Shortcut keys="Ctrl Shift L" label="Lock the app" />
              <Shortcut keys="Esc" label="Close a dialog" />
            </ShortcutGroup>
          </div>
        </Modal>
      ) : null}
    </div>
  );
}

function LockScreen({ session, onUnlocked }: { session: SessionView; onUnlocked: () => Promise<unknown> }) {
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await command("unlock", { password });
      await onUnlocked();
    } catch (caught) {
      setError(typeof caught === "object" && caught && "message" in caught ? String((caught as { message: unknown }).message) : String(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ minHeight: "100vh", display: "grid", placeItems: "center", padding: 24 }}>
      <form className="card card-pad" style={{ width: "min(380px, 100%)" }} onSubmit={submit}>
        <div className="row" style={{ marginBottom: 14 }}>
          <span className="icon-box"><Lock size={16} /></span>
          <div>
            <div style={{ fontWeight: 650 }}>HRAgents is locked</div>
            <div className="small muted">{session.display_name} · HR operator</div>
          </div>
        </div>
        <Field label="Password">
          <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoFocus />
        </Field>
        {error ? <ErrorBox>{error}</ErrorBox> : null}
        <button className="btn primary" type="submit" disabled={busy || !password} style={{ width: "100%", marginTop: 12 }}>
          {busy ? "Unlocking…" : "Unlock"}
        </button>
        <div className="small faint" style={{ marginTop: 10 }}>
          Unlock needs the password. Biometrics can satisfy re-auth for a fresh action, never unlock the database.
        </div>
      </form>
    </div>
  );
}

function Shortcut({ keys, label }: { keys: string; label: string }) {
  return (
    <div className="row" style={{ justifyContent: "space-between", gap: 10 }}>
      <span className="small">{label}</span>
      <span className="kbd">{keys}</span>
    </div>
  );
}

function ShortcutGroup({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="grid" style={{ gap: 6 }}>
      <div className="small faint" style={{ textTransform: "uppercase", letterSpacing: "0.06em", fontSize: 10.5 }}>
        {title}
      </div>
      {children}
    </div>
  );
}
