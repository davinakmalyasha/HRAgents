# 06 — Authentication and security

**Status:** draft · **Scope:** HRAgents Desktop, single company per install

Security has three jobs here: keep HR data confidential at rest, bind every consequential action to
a named human, and leave tamper-evident evidence. Network auth, SSO, RBAC, tenant isolation, and
employee self-service are explicitly out of scope.

## 1. Product auth model

| Property | Decision |
|---|---|
| Roles | exactly one: `hr_operator` |
| Accounts | 1–3 local accounts, identical permissions |
| Tenant | none — one company per installation |
| Employee/manager/finance login | none, ever |
| Identity source | local only; no directory, SSO, or email-based identity |

- Every operator can do everything; there is no RBAC matrix to misconfigure. Authorization is
  “unlocked session + fresh re-auth for consequential acts”. No segregation of duties; gates and
  audit compensate.
- Accounts are created at first run or by an existing operator (re-auth required). No
  self-registration. A fourth account is refused by the core.
- Accounts are **disabled, never deleted**, so audit rows keep a valid actor; the last active
  operator cannot be disabled.

## 2. First run and credentials

Wizard: language → company profile → first operator (name, optional email, password) → recovery key
→ data location → optional demo data/providers. Works offline.

**Password policy**

- 12–128 characters, Unicode NFKC, no composition rules or forced rotation; blocklist (10k common,
  company name), zxcvbn ≥3, no reuse of the last 3, rehash on login if parameters weakened.
- **Argon2id:** m=64 MiB, t=3, p=1, 16-byte salt, 32-byte output, PHC string per account; calibrate
  to 250–500 ms on the reference machine.
- **Lockout:** 5 failures → 30 s, 8 → 5 min, 10 → 15 min, exponential to 60 min, per account and
  device; no permanent lock. Unknown accounts verify against a dummy hash in constant time.
- **No email reset.** Email is optional metadata. A reset needs the recovery key plus a
  re-authenticated operator; with one operator, the recovery key alone suffices.

**Recovery key:** 24 BIP39 words (256 bits), shown once, confirmed by re-entering 4 random words,
never stored in plaintext. It unwraps the master key, recovering all accounts and the database; use
and regeneration are audited. Losing both means permanent data loss — stated in the wizard.

## 3. Sessions, lock, and re-auth

| State | Meaning | Can do |
|---|---|---|
| Locked | no key material in memory | login, recovery |
| Unlocked | MK in memory, token valid | reads, reversible edits |
| Fresh | re-auth ≤5 min old | payroll sign-off, erasure, rejection override |

- Absolute session 12 h; idle lock 10 min default (5–60); re-auth freshness 5 min; sign-off grants
  are single-use.
- **Lock triggers:** idle, manual (`Cmd/Ctrl+Shift+L`, tray), sleep/suspend, OS session lock, and
  screensaver.
- **On lock:** zeroize MK and derived keys, close the SQLCipher pool, revoke the token, hide content,
  clear clipboard. Unlock needs the password; biometrics satisfy **re-auth** only while MK is
  resident (Windows Hello, macOS Touch ID; Linux password only).

**Session token storage**

| OS | Store | Protection |
|---|---|---|
| Windows | Credential Manager | DPAPI, current user |
| macOS | login Keychain | ACL to the app, user presence |
| Linux | Secret Service | gnome-keyring/KWallet; encrypted-file fallback with warning |

- 32-byte random token, device-bound, TTL ≤12 h, hash kept by the core; **never** in
  `localStorage`, `sessionStorage`, IndexedDB, or cookies. Deleted on lock/quit by default.
- Optional “stay signed in” (off) keeps the token plus a device-wrapped MK in the keychain for 7
  days; survives restart, **not** auto-lock; revoked on disable, password change, or recovery.
- **Re-auth** (password/biometric) is required for payroll sign-off/export, erasure/purge, rejection
  override at or above the merit floor, recovery-key reveal, rekey, restore, account disable/reset,
  and channel change.

## 4. Named-human gate

Every mutating command is classified in a Rust registry as `normal` or `consequential`.
Consequential commands take `Session<Fresh>`; all others take `Session<Unlocked>` (the §03
extractor). A startup test asserts that every consequential command has the guard, and the generated
TypeScript types contain no actor fields.

- **No actor in the request body.** The core derives `operator_id`, role, device, and session from
  the authenticated channel. IPC structs use `deny_unknown_fields`, so an injected `actor_id` is a
  deserialization error. Agents have no command surface at all: the LLM runs inside the core, its
  output is validated data, and any proposed action becomes a `proposal` row a human must execute.
- **Audit row:** seq, record id, UTC timestamp + business timezone, operator id/name snapshot,
  role, action, entity type/id, canonical payload hash (SHA-256), previous hash, entry hash, provenance
  (`app_version`, `device_id`, `session_id`, `ui_route`, `command`), re-auth method, result.
- Provenance values are enumerated (`operator_ui`, `operator_deeplink`, `system_job`, `migration`);
  `agent` is not a valid actor. System jobs write operational rows, never human decisions. The UI
  shows the audit receipt after every consequential action; exports embed it.

## 5. Data protection

**Key hierarchy** (nothing derived from a password is stored):

```
password ──Argon2id──> KEK_pw ──AES-256-GCM──> wraps MK
recovery ──Argon2id──> KEK_rk ──AES-256-GCM──> wraps MK
MK ──wraps──> random DB key | backup key
device key (DPAPI/Keychain) ──> wraps MK only for “stay signed in”
```

A small `keys.json` beside the DB holds per-account salts, Argon2 parameters, nonces, and wrapped
copies of MK, plus the recovery wrap — no plaintext secret. SQLCipher opens after any account
unwraps MK.

- **SQLCipher is mandatory:** AES-256-CBC + HMAC-SHA512 per page, 4096-byte pages, 32-byte raw key
  as `x'…'`, `cipher_memory_security=ON`, `secure_delete=ON`, encrypted WAL/temp. OS encryption
  (BitLocker/FileVault) is recommended, not relied on.
- **Rekey:** with 1–3 accounts the DB key is shared, so password change rewraps MK (instant); §04's
  `PRAGMA rekey` runs on MK rotation, not on every password change. Rotation re-wraps MK under both
  KEKs and the DB/backup keys, then rekeys the DB after a verified backup; the chain stays valid and
  a failure restores the backup.
- **Files:** data root 0700/0600, Windows DACL current SID only, inheritance removed; internal
  backups are SQLCipher copies, exports are sealed (§05).
- **Clipboard/capture:** sensitive copy clears after 60 s and skips clipboard history; optional
  capture blocking (Windows `WDA_EXCLUDEFROMCAPTURE`, macOS `sharingType = .none`) is off by default.
- **PII:** log/diagnostic redaction (NIK, NPWP, phone, email, accounts); provider payloads preview
  and redact identifiers unless “send full CV” is consented; local Ollama never leaves.
- **Memory:** `secrecy`/`zeroize`, best-effort `mlock`/`VirtualLock`, no key in JS, devtools off in
  release, core dumps off. Swap stays an OS duty — hence FDE.

## 6. Threat model

| Threat | Vector | Mitigation | Residual |
|---|---|---|---|
| Stolen laptop | offline disk access | SQLCipher + Argon2id + OS FDE | weak password, unlocked session |
| Local malware | reads memory/keychain | signed app, no shell, zeroization | admin malware impersonates user |
| Shared OS account | colleague uses same user | app login + auto-lock; separate users advised | same-user keychain access |
| Backup theft | copied `.hrbackup` | sealed backup, recovery-key wrap, ACL | weak export passphrase |
| Malicious document | parser exploit via CV | memory-safe parsers, type/size limits, no macros | parser 0-day |
| Prompt injection via CV | text instructs the model | delimit untrusted text, no model tools, schema validation, deterministic gates | subtle extraction bias |
| Provider leakage | CV/PII sent to LLM | consent, redaction, local model, no-training terms | provider logs |
| Update supply chain | tampered installer | Authenticode/Developer ID, minisign, pinned key, SBOM | stolen signing key |

## 7. Update and code-signing supply chain

- Binaries signed per §05; the updater manifest is signed with a minisign key whose public half is
  pinned in the app. Private keys live in an HSM/offline machine, never on a laptop or CI runner.
- **SBOM:** CycloneDX per release (Cargo + npm), attached to the release.
- **Gates:** `cargo audit`, `cargo deny` (licenses, bans, sources), `npm audit`/OSV, Dependabot,
  committed lockfiles, `--locked`, no git dependencies; new native crates need review.
- **Reproducibility:** `SOURCE_DATE_EPOCH`, pinned toolchain, vendored crates, rebuild-and-diff in
  CI; notarization may prevent bit-identical macOS artifacts, so this is best-effort.
- CI uses OIDC, protected environments, and two-person review for signing changes. Tauri CSP is
  strict, no remote content, `withGlobalTauri=false`, capabilities minimized per window.

## 8. Audit

| Event group | Examples |
|---|---|
| Session | login success/failure/lockout, lock, unlock, logout, re-auth |
| Accounts | create, disable, password reset, recovery-key use |
| Data | export, backup create/restore/delete, deletion/erasure |
| Decisions | payroll sign-off/export, rejection override, approval |
| System | migration, update/rollback, integrity failure, config change |

- Append-only: `BEFORE UPDATE/DELETE` triggers raise `ABORT`; the chain is
  `SHA-256(prev_hash || canonical_row)`, verified on every unlock and nightly. A local OS admin
  with the key can rewrite it; the external head anchor is the backstop.
- The head hash is copied into every backup manifest and diagnostic bundle; an optional monthly
  RFC 3161 timestamp anchors it externally. Failure puts the app in read-only mode with a banner —
  never a silent repair.
- **Retention:** audit metadata 5 years (IDs, hashes, actor, action — no CV content), legal hold
  supported. Purge needs fresh re-auth, is audited, and leaves a tombstone. Candidate data follows
  the 24-month product retention.
- **Export:** CSV + JSONL + PDF summary with the chain proof; re-auth required, export audited.

## 9. Acceptance criteria

- [ ] 5 wrong passwords trigger backoff; 10 trigger a 15-minute lock; unknown accounts take the
      same time as known ones.
- [ ] Auto-lock fires at the configured idle time, locks on sleep/OS lock, and hides content
      immediately; MK is zeroized and the DB pool closed.
- [ ] Payroll sign-off without fresh re-auth fails `E_REAUTH_REQUIRED`; with password/biometric it
      succeeds and the audit row records the method.
- [ ] Audit chain verifies after restart; a directly edited row fails verification.
- [ ] The DB has no `SQLite format 3` header or plaintext PII; a wrong key fails to open.
- [ ] Backup restore preserves operator accounts, audit sequence, and head hash.
- [ ] IPC rejects an `actor_id` field; no command schema contains one.
- [ ] No session token or MK appears in localStorage, sessionStorage, IndexedDB, or logs.
- [ ] Recovery key restores access on a clean machine; the old password then fails.

## 10. Risks and open decisions

| Item | Risk / question | Proposed default |
|---|---|---|
| SQLCipher vs OS-only | perf cost vs defence in depth | SQLCipher always; measure 5–15% overhead |
| Recovery-key loss | permanent data loss | mandatory acknowledgment + printed backup |
| Biometrics on Linux | no standard API | password only; document |
| Peer reset | who may reset another? | recovery key + re-auth |
| Shared OS account | no same-user isolation | separate OS users required |
| Clock trust | local clock can move | monotonic seq + RFC 3161 anchor |
