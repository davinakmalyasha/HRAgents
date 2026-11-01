# ADR 0007 — Tauri 2.12.x is the desktop shell, not Electron and not Tauri 3

**Status:** accepted · **Date:** 2026-11-01

## Context

The desktop edition replaces a FastAPI/Postgres server with one signed application that a
non-technical HR operator installs on a laptop. The shell choice fixes installer size, idle
memory, startup time, signing and update story, and — because the domain core is Rust — how
many runtimes ship. Electron bundles Chromium and Node: 80–150 MB installers, 250–400 MB idle,
and a second runtime to sign and patch. Tauri 2.12.x uses the OS webview and links the core
in-process: 15–30 MB installers, roughly 150–200 MB idle. Tauri 3 is not stable on 2026-11-01,
so adopting previews would put the updater and signing pipeline on an unsupported base.

## Decision

- Pin `tauri`/`tauri-build` **2.12.x**, `@tauri-apps/api` 2.12.x and plugins 2.x; commit
  `Cargo.lock` and `package-lock.json`; build with `--locked`.
- The UI is React 19 + Vite in WebView2 (Windows), WKWebView (macOS), WebKitGTK 4.1 (Linux).
  No bundled Chromium, no Electron, no Tauri 3 preview.
- The shell sits behind a thin adapter, so a future stable Tauri 3 upgrade is a shell change,
  not a core change.
- Capabilities are allowlisted per window; `withGlobalTauri=false`; no remote content;
  `tauri-plugin-shell` is not installed.

## Consequences

Easier: the ≤35 MB installer and ≤1.5 s cold-start budgets become reachable; the Rust core is
one workspace crate rather than a sidecar; signing, notarization and the signed updater are
first-party rather than assembled from Electron tooling.

Harder: Windows depends on the WebView2 Evergreen runtime (`embedBootstrapper` adds ~1.8 MB and
downloads on first install); Linux inherits WebKitGTK version variance; debugging spans webview
and Rust; and no Node APIs exist in the renderer, so frontend code cannot reach for them.

Out of scope: Electron, Tauri 3 until it is stable and its signing pipeline is retested, mobile
targets, PWA/service worker.

Guards: the CI artifact gate fails above 35 MB; `apps/desktop/tests/startup.rs` holds the 1.5 s
budget; `cargo test export_bindings && git diff --exit-code` catches binding drift; risk R7
tracks Tauri 3 and v2 advisories.
