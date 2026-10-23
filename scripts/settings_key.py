"""Generate a Fernet key for sealing provider credentials.

Put the printed value in `.env` as `HRAGENTS_SETTINGS_ENCRYPTION_KEY`. To
rotate, prepend a new key to the comma-separated list, restart, re-save the
providers you care about from the dashboard, then remove the old key.

    uv run python scripts/settings_key.py
"""

from __future__ import annotations

from cryptography.fernet import Fernet


def main() -> int:
    print("# Add these to .env (or your secret store) and restart the app.")
    print(f"HRAGENTS_SETTINGS_ENCRYPTION_KEY={Fernet.generate_key().decode()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
