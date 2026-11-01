# ADR 0012 — SQLCipher on by default, with an Argon2id key hierarchy and the OS keychain

**Status:** accepted · **Date:** 2026-11-01

## Context

The database holds salaries, NPWP numbers, identity documents and leave reasons. The realistic
threat is a stolen or resold laptop, and a copied `.db` bypasses OS full-disk encryption
entirely: BitLocker/FileVault is an operator-controlled assumption the application cannot
verify, and an administrator can disable it. The plan's open decision D2 defaults SQLCipher on
always, with no opt-out in v1.

## Decision

- SQLCipher is mandatory, via `bundled-sqlcipher-vendored-openssl`: AES-256-CBC with
  HMAC-SHA512 per 4096-byte page, a 32-byte raw key as `x'…'`, `cipher_memory_security=ON`,
  `secure_delete=ON`, and encrypted WAL and temp files.
- Key hierarchy: password → Argon2id (m=64 MiB, t=3, p=1) → `KEK_pw` → AES-256-GCM wraps `MK`;
  the 24-word BIP39 recovery key → `KEK_rk` → wraps `MK`; `MK` wraps a random database key and
  backup key. Nothing derived from a password is stored.
- `keys.json` beside the database holds per-account salts, Argon2 parameters, nonces and wrapped
  copies of `MK`. It contains no plaintext secret.
- The database key lives only in memory during an unlocked session; keychain storage
  (Credential Manager/DPAPI, login Keychain, Secret Service) holds the optional device wrap for
  "stay signed in", never in the database, `localStorage` or IndexedDB.
- A password change rewraps `MK` and is instant. `PRAGMA rekey` runs only on `MK` rotation,
  after a verified backup.
- A printed recovery key is mandatory at setup: a forgotten password without it is unrecoverable
  data loss, stated in the wizard.

## Consequences

Easier: a stolen file is useless without a password; backups are SQLCipher copies; there is no
separate transparent-encryption layer or key server to operate.

Harder: expect 5–15% overhead on I/O-bound work, so benchmarks gate every release; key loss is
permanent, so onboarding must force acknowledgment and a printed copy; Linux keychain
implementations vary and fall back to an encrypted file with a warning; three native surfaces
must be validated on all three platforms.

Out of scope: per-column encryption, HSM/KMS, key escrow, an unencrypted mode in v1,
transparent data encryption at the OS layer.

Guards: an acceptance test asserts the file has no `SQLite format 3` header and no plaintext
PII, and that a wrong key fails to open; an encrypted-versus-plain benchmark with a ≤10–15%
regression gate; a recovery-key restore on a clean machine; uninstall without the recovery key
cannot decrypt.
