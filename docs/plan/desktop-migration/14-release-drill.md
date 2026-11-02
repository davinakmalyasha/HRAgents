# 14 — Release drill (Gate 6 preparation)

**Status:** draft · **Gate:** 6 candidate · **Date:** 2026-11-02

Gate 6 (per `09-sequence.md`) is the signed, installable release candidate at
week 32 and the public release at week 38. This document is the rehearsal
script: clean-VM install, backup/restore drill, rollback rehearsal, and the
honest signing/notarization status. Nothing here claims Gate 6 is passed.

## 1. Signing status — free edition: none, by design

This edition is deliberately free and self-contained. There is **no code-signing
certificate, no paid developer account, and no hosted update server**, and none is
required to build, install, or run the app.

| Item | Status |
|---|---|
| Windows Authenticode / Azure Trusted Signing | **Not used.** Installer is unsigned; the first run shows "unknown publisher" once and the user chooses *Run anyway*. |
| Apple Developer ID / notarization | **Not used.** macOS build is unsigned for local/team use. |
| Updater minisign keypair / hosted `latest.json` | **Not used.** Automatic updates are disabled; upgrading means installing a newer build. `tauri.conf.json` has no updater plugin. |
| Installer elevation | **None.** NSIS `installMode` is `currentUser`, so no admin password is needed. |

What this costs the product: no one-click trusted install for strangers and no
background auto-update. For one HR team on its own laptop — the edition's whole
use case — neither matters. If the product is ever distributed widely, signing
becomes a paid distribution decision, not a technical blocker.

## 1b. Earlier paid-distribution notes (not part of this free edition)

The following were drafted for a future paid-distribution track and are **not
required** for this build: Authenticode enrollment, Apple notarization, a pinned
minisign pubkey, and a staged `latest.json` rollout. They are kept below only as
a reference for that future decision.

## 2. Clean-VM install checklist

Run on a fresh VM snapshot per OS (Windows 11 / 10 22H2, macOS 13+, Ubuntu
22.04+). Record OS build, WebView2/WebKit version, installer SHA-256.

- [ ] Installer size ≤35 MB (target 22–30 MB); no full WebView2 runtime payload.
- [ ] Windows: WebView2 `embedBootstrapper` path — offline VM shows guidance, online VM downloads Evergreen.
- [ ] First-run wizard works offline: language → company → first operator → recovery key → data location → demo data → providers (skip = offline mode).
- [ ] Data lands in the OS root only (`%LOCALAPPDATA%\HRAgents`, `~/Library/Application Support/com.hragents.desktop`, `~/.local/share/hragents`).
- [ ] Second launch focuses the running instance and exits 0 (single-instance; no second DB writer).
- [ ] Cold start ≤1.5 s, first paint ≤500 ms on 4-core/8 GB SSD reference.
- [ ] Uninstall keeps data by default and prints the path; destructive mode needs checkbox + typed confirmation + recovery key.

## 3. Backup / restore drill

- [ ] Trigger each backup kind: first run, daily (keep 7), before update/restore/rekey/erasure, manual `.hrbackup` export.
- [ ] Verify at creation: `rusqlite::backup` copy integrity; sealed `.hrbackup` manifest (schema, counts, audit head, SHA-256).
- [ ] Restore rehearsal (never merges): verify signature/hash/schema → password (+ recovery key if foreign) → snapshot current DB → restore to temp → verify audit → atomic swap → restart.
- [ ] Confirm accounts and audit history survive restore; audit verifies after restart.

## 4. Rollback rehearsal

Tauri cannot downgrade in place (§05). Rehearse the supported path:

1. Install signed build N−1, create data, back up.
2. Install signed build N (migration runs: backup first → migrate in one transaction → `quick_check` → audit verify).
3. Simulate a failed migration; confirm automatic restore of the pre-update backup and relaunch of the cached previous installer from `updates/cache/` (kept 7 days).
4. Manual “Roll back”: reinstall cached N−1, restore pre-update backup, re-verify audit.
5. Confirm a newer-schema DB refuses to open on the older binary (no silent downgrade).

## 5. What blocks Gate 6

- [ ] Enroll signing: Authenticode (Azure Trusted Signing or OV) + Apple Developer ID; generate the updater minisign keypair in an HSM with dual control; pin the real pubkey (rotation drill per §05 risk table).
- [ ] (Future paid track only) Host a signed `latest.json` with staged rollout if the product is ever distributed widely. Not required for the free edition.
- [ ] Prove bad-signature rejection and staged-rollout bucketing (`SHA-256(device_id + version)`).
- [ ] Run this drill green on all three OS targets with installer ≤35 MB and all performance budgets green.
- [ ] Confirm diagnostic bundles (`.hrdiag`) contain no PII/secrets (fixture test) before any crash-report upload is enabled.
- [ ] Legal/licensing review (Phase 5 exit dependency per `09-sequence.md`).
