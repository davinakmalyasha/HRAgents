"""Generate a VAPID key pair for Web Push.

The private key stays on this host; the public key is served to the browser as
the application server key. Run once per deployment and keep both values in the
operator's `.env` (never commit them).

    uv run python scripts/vapid_keys.py
    uv run python scripts/vapid_keys.py --subject mailto:ops@example.com
"""

from __future__ import annotations

import argparse

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid, b64urlencode


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a VAPID key pair for Web Push")
    parser.add_argument(
        "--subject",
        default="mailto:ops@example.com",
        help="contact the browser vendor may use; mailto: or https:// URL",
    )
    args = parser.parse_args()

    vapid = Vapid()
    vapid.generate_keys()
    private_pem = vapid.private_pem()
    public_raw = vapid.public_key.public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    public_key = b64urlencode(public_raw)

    print("# Add these to .env (or your secret store) and restart the app.")
    escaped = private_pem.decode().strip().replace("\n", "\\n")
    print(f'HRAGENTS_VAPID_PRIVATE_KEY="{escaped}"')
    print(f"HRAGENTS_VAPID_PUBLIC_KEY={public_key}")
    print(f"HRAGENTS_VAPID_SUBJECT={args.subject}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
