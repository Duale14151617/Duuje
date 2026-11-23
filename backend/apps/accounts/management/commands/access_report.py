import json
import os

from django.core.management.base import BaseCommand, CommandError

from apps.accounts import access_report as ar
from apps.audit.services import record


class Command(BaseCommand):
    help = ("Report every user with their username, roles, scope and what they can do (markdown, csv or json). Read-only. "
            "The report lists who can access what, so store the file safely.")

    def add_arguments(self, parser):
        parser.add_argument("--format", choices=["md", "csv", "json"], default="md")
        parser.add_argument("--output", help="write to this file (created readable by the owner only) instead of printing")
        parser.add_argument("--active-only", action="store_true", help="leave out disabled users")

    def handle(self, *args, **opts):
        report = ar.build(include_inactive=not opts["active_only"])
        body = {"md": ar.to_markdown, "csv": ar.to_csv, "json": lambda r: json.dumps(r, indent=2, ensure_ascii=False)}[opts["format"]](report)
        if opts["output"]:
            try:
                fd = os.open(opts["output"], os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
                    f.write(body)
            except OSError as exc:
                raise CommandError(f"Cannot write {opts['output']}: {exc}")
            self.stdout.write(f"Wrote {opts['output']}")
        else:
            self.stdout.write(body)
        record("access.report", entity_type="access_report",
               metadata={"format": opts["format"], "users": report["summary"]["users"], "via": "management_command"})
