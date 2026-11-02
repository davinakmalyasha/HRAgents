# Parity corpus freeze

Frozen for Gate 5 cutover reference. Regenerating fixtures must reproduce these hashes byte-for-byte; any divergence is a build failure, not a warning.

Python oracle commit: ee19c72

Hashes are of the LF-normalized files; the exporter writes `newline="\n"` so Windows and Linux produce identical bytes.

| Fixture | SHA-256 |
|---|---|
| audit_hashes.json | `422ac5bbfd71ff9ec93a850608fc17862053f29c9168913d1497efe5adfe1616` |
| money.json | `41348f364b2259726abc42a62cd714037264f4f4988ffc592968c2d435468081` |
| money_operations.json | `ac8556741ff872cc961a998c0850a54fbdbf7b2055424383a31e9f884899ba83` |
| payroll_1000.json | `e4ac27aa081b19949f4b859aed987ebd72c1144e542fb8a81be79a277c254531` |
| payroll_absence.json | `b902af98a551c82dd74f0c38db1be2803ffd18199164eb2076569075e4ba924f` |
| payroll_bpjs.json | `b8674008df6797a7373abfd30cfc605a16da40c1b2a80bf063e2e3573e676846` |
| payroll_final.json | `d708eb7246ca55d4729b41606793c526847e4b83c057131f1eb5f99a26680e0d` |
| payroll_monthly_full.json | `bf104853914dc4521e0d3abe7e0782a19ee8f3d3290b7fe5166043b576320540` |
| payroll_overtime.json | `796d894633b01ff1e7bc79fec63ad0a31c3f965b6760f44b31b7c9a075999b9c` |
| payroll_pph21.json | `ac71e8d60995c0d3d57e6bd93aa5e4114aef8aa6424a8a29211b48956880d619` |
| payroll_thr.json | `c629ec5eeda0877a927a89681a8542b67b164c836317a5b5bf4e205a52dfa8ea` |
| payroll_thr_full.json | `15e56388204b7c10832e4438b69b24a131ffb00942e14cf14c338a5280cef410` |
| scoring_aggregate.json | `ec99f798b6f1c2f8ebdfb1e2fc2549e82ce4f410e3a891bfbe3cef6645076b9a` |

Regenerate: `uv run python scripts/parity_export.py parity/fixtures`
