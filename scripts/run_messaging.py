"""Run the messaging bridge once: poll the inbox and carry the queued outbox.

Builds the same service containers as the API server, so the configured storage
backend and the resolved email provider both apply. Sending is a no-op while
``HRAGENTS_MESSAGING_SANDBOX`` is on (the default): the run prints what *would*
be sent and leaves every message queued. Exit code is nonzero when a dispatch or
a poll fails.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from hr_agents.main import create_app
from hr_agents.messaging import MessagingServices, TransportError
from hr_agents.messaging.outbox import DEFAULT_DISPATCH_LIMIT


def _render(summary: dict[str, Any]) -> str:
    lines: list[str] = []
    send = summary.get("send")
    if send:
        if send.get("mode") == "sandbox":
            preview = send["preview"]
            lines.append(
                "sandbox: transport disabled, "
                f"{preview['ready']} of {preview['queued']} queued message(s) ready, "
                f"{preview['missing_recipient']} missing a recipient"
            )
        else:
            lines.append(
                f"dispatch via {send['provider']}: sent {send['sent']}, "
                f"failed {send['failed']}, skipped {send['skipped']}"
            )
    receive = summary.get("receive")
    if receive:
        if receive.get("mode") == "disabled":
            lines.append("inbound polling disabled (no email_receive provider configured)")
        else:
            lines.append(
                f"inbound via {receive['provider']}: matched {receive['matched']}, "
                f"unmatched {receive['unmatched']}, duplicates {receive['duplicates']}"
            )
    return "\n".join(lines) or "nothing to do"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--send", action="store_true", help="dispatch queued messages")
    parser.add_argument("--receive", action="store_true", help="poll the inbox for replies")
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_DISPATCH_LIMIT,
        help=f"maximum messages to dispatch per run (default: {DEFAULT_DISPATCH_LIMIT})",
    )
    parser.add_argument("--json", action="store_true", help="print the run summary as JSON")
    args = parser.parse_args(argv)

    both = not (args.send or args.receive)
    app = create_app()
    messaging: MessagingServices = app.state.messaging  # type: ignore[attr-defined]
    communications = app.state.recruiting.communications  # type: ignore[attr-defined]
    summary: dict[str, Any] = {}
    failed = False

    if args.send or both:
        dispatcher = messaging.dispatcher(communications)
        if not messaging.live:
            summary["send"] = {
                "mode": "sandbox",
                "provider": messaging.provider_id,
                "preview": dispatcher.preview(limit=args.limit).model_dump(),
            }
        else:
            try:
                report = dispatcher.dispatch_pending(limit=args.limit)
            except TransportError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 2
            failed = failed or not report.ok
            summary["send"] = {"mode": "live", **report.model_dump()}

    if args.receive or both:
        receiver = messaging.receiver
        if receiver is None:
            summary["receive"] = {"mode": "disabled"}
        else:
            ingestor = messaging.ingestor(communications, audit=app.state.audit)  # type: ignore[attr-defined]
            try:
                polled = receiver.poll()
            except TransportError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 2
            report = ingestor.ingest(polled)
            summary["receive"] = {"mode": "live", **report.model_dump()}

    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True, default=str))
    else:
        print(_render(summary))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
