"""Run the messaging bridge once, or forever with ``--loop``.

Poll the inbox and carry the queued outbox.

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
from hr_agents.models import Channel
from hr_agents.services.periodic import run_periodic


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
                f"failed {send['failed']}, skipped {send['skipped']}, "
                f"deferred {send.get('deferred', 0)}, "
                f"unrecorded {send.get('unrecorded', 0)}"
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
    applications = summary.get("applications")
    if applications and applications.get("mode") == "live":
        lines.append(
            f"applications via {applications['provider']}: "
            f"drafted {applications['drafted']}, "
            f"duplicates {applications['duplicates']}, "
            f"replies {applications['skipped_is_reply']}, "
            f"no-attachment {applications['skipped_no_attachments']}"
        )
    whatsapp = summary.get("whatsapp")
    if whatsapp:
        if whatsapp.get("mode") == "sandbox":
            lines.append(f"whatsapp sandbox: {whatsapp['queued']} message(s) queued, none sent")
        elif whatsapp.get("mode") == "unavailable":
            lines.append("whatsapp: no sending provider configured")
        else:
            lines.append(
                f"whatsapp via {whatsapp['provider']}: sent {whatsapp['sent']}, "
                f"failed {whatsapp['failed']}, skipped {whatsapp['skipped']}, "
                f"deferred {whatsapp.get('deferred', 0)}, "
                f"unrecorded {whatsapp.get('unrecorded', 0)}"
            )
    telegram = summary.get("telegram")
    if telegram:
        if telegram.get("mode") == "sandbox":
            lines.append(f"telegram sandbox: {telegram['queued']} message(s) queued, none sent")
        elif telegram.get("mode") == "unavailable":
            lines.append("telegram: no bot configured")
        else:
            lines.append(
                f"telegram via {telegram['provider']}: sent {telegram['sent']}, "
                f"failed {telegram['failed']}, skipped {telegram['skipped']}, "
                f"deferred {telegram.get('deferred', 0)}, "
                f"unrecorded {telegram.get('unrecorded', 0)}"
            )
    return "\n".join(lines) or "nothing to do"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--send", action="store_true", help="dispatch queued email messages")
    parser.add_argument("--receive", action="store_true", help="poll the inbox for replies")
    parser.add_argument(
        "--whatsapp",
        action="store_true",
        help="dispatch queued WhatsApp messages through the Cloud API",
    )
    parser.add_argument(
        "--telegram",
        action="store_true",
        help="dispatch queued Telegram messages through the Bot API",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_DISPATCH_LIMIT,
        help=f"maximum messages to dispatch per run (default: {DEFAULT_DISPATCH_LIMIT})",
    )
    parser.add_argument("--json", action="store_true", help="print the run summary as JSON")
    parser.add_argument(
        "--loop",
        action="store_true",
        help="run every --interval-seconds until SIGTERM (drains the running pass)",
    )
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=300.0,
        help="wait between passes in --loop (default: 300)",
    )
    args = parser.parse_args(argv)

    if args.loop:
        return run_periodic(lambda: run_once(args), interval_seconds=args.interval_seconds)
    return run_once(args)


def run_once(args: argparse.Namespace) -> int:
    both = not (args.send or args.receive or args.whatsapp or args.telegram)
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

    if args.whatsapp or both:
        sender = messaging.whatsapp
        if sender is None:
            summary["whatsapp"] = {
                "mode": "unavailable",
                "detail": "no sending WhatsApp provider is configured",
            }
        elif not messaging.live:
            queued = communications.list_queued(channel=Channel.WHATSAPP)
            summary["whatsapp"] = {"mode": "sandbox", "queued": len(queued)}
        else:
            from hr_agents.messaging.whatsapp_cloud import WhatsAppCloudDispatcher

            report = WhatsAppCloudDispatcher(
                communications=communications, sender=sender
            ).dispatch_pending(limit=args.limit)
            failed = failed or not report.ok
            summary["whatsapp"] = {"mode": "live", **report.model_dump()}

    if args.telegram or both:
        telegram = messaging.telegram
        if telegram is None:
            summary["telegram"] = {
                "mode": "unavailable",
                "detail": "no Telegram bot is configured",
            }
        elif not messaging.live:
            queued = communications.list_queued(channel=Channel.TELEGRAM)
            summary["telegram"] = {"mode": "sandbox", "queued": len(queued)}
        else:
            from hr_agents.messaging.telegram import TelegramDispatcher

            report = TelegramDispatcher(
                communications=communications, sender=telegram
            ).dispatch_pending(limit=args.limit)
            failed = failed or not report.ok
            summary["telegram"] = {"mode": "live", **report.model_dump()}

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
            recruiting = app.state.recruiting  # type: ignore[attr-defined]
            from hr_agents.messaging.application_ingest import ApplicationIngestor

            app_ingestor = ApplicationIngestor(
                drafts=messaging.drafts,
                documents=recruiting.documents,
                jobs=recruiting.jobs,
                communications=communications,
                directory=messaging.directory,
                audit=app.state.audit,  # type: ignore[attr-defined]
            )
            applications = app_ingestor.ingest(polled)
            summary["applications"] = {"mode": "live", **applications.model_dump()}

    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True, default=str))
    else:
        print(_render(summary))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
