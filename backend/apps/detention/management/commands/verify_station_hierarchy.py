import json

from django.core.management.base import BaseCommand, CommandError

from apps.detention import hierarchy


class Command(BaseCommand):
    help = ("Check, without changing anything, that every active police station has a correct parent (district or regional command) and region, "
            "its departments and a consistent custody setup. Use --strict to exit with an error when something is wrong.")

    def add_arguments(self, parser):
        parser.add_argument("--strict", action="store_true", help="Exit with an error if any ERROR finding exists")
        parser.add_argument("--json", action="store_true", help="Print the findings as JSON")

    def handle(self, *args, **opts):
        res = hierarchy.check()
        if opts["json"]:
            self.stdout.write(json.dumps(res, indent=2, default=str))
        else:
            for f in res["findings"]:
                line = f"[{f['severity'].upper():7}] {f['unit'] or '-':28} {f['code']}: {f['message']}"
                self.stdout.write(self.style.ERROR(line) if f["severity"] == "error" else self.style.WARNING(line) if f["severity"] == "warning" else line)
            self.stdout.write(f"{res['stations']} active stations checked: {res['errors']} errors, {res['warnings']} warnings, {res['info']} notes.")
        if opts["strict"] and res["errors"]:
            raise CommandError(f"{res['errors']} hierarchy errors found.")
