# Operator runbooks

Short, tested procedures for the failures an operator actually meets. They
assume the Compose deployment from [`deployment.md`](../deployment.md); the
commands also work without Docker if you substitute `uv run`.

- [Provider failure](provider-failure.md) — a model, mail, WhatsApp, Telegram
  or calendar provider is down, rate-limited, or was rotated incorrectly.
- [Incident response](incident-response.md) — a suspected data breach, a
  compromised key, or a corrupt audit chain.
- [Upgrade](upgrade.md) — back up, migrate, deploy, verify, and the only rollback
  that is safe for a forward-only migration.
