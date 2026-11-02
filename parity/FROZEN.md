# Parity corpus freeze

Frozen for Gate 5 cutover reference. Regenerating fixtures must reproduce these hashes byte-for-byte; any divergence is a build failure, not a warning.

Python oracle commit: ee19c72

| Fixture | SHA-256 |
|---|---|
| audit_hashes.json | `17c922dc22cc108f6a357da6406acea09817dde8c8338cfb624764978eb9e6a3` |
| money.json | `21c4a7b70e2b10c6862370984f78c3c1e2b85ceff3f332f9710a9ba198afe765` |
| money_operations.json | `0b5e87b20737a0cac7ed85db32b0f82ad4cf666e5a31848b4cc2d4a75bf0404b` |
| payroll_absence.json | `b902af98a551c82dd74f0c38db1be2803ffd18199164eb2076569075e4ba924f` |
| payroll_bpjs.json | `b8674008df6797a7373abfd30cfc605a16da40c1b2a80bf063e2e3573e676846` |
| payroll_overtime.json | `796d894633b01ff1e7bc79fec63ad0a31c3f965b6760f44b31b7c9a075999b9c` |
| payroll_pph21.json | `970612d4d75fa0a9ee2c772b11dff2d79eeb780b4128190f4925763060332cad` |
| payroll_thr.json | `c629ec5eeda0877a927a89681a8542b67b164c836317a5b5bf4e205a52dfa8ea` |
| scoring_aggregate.json | `ec09a744d90f1a6351886c251263cbc0a6fe038ebc9a6fb71177d8fcf65098cd` |

Regenerate: `uv run python scripts/parity_export.py parity/fixtures`
