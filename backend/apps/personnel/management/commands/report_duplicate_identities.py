"""List people who appear on more than one service's roll under the same name and phone (existing data check).

  python manage.py report_duplicate_identities

The creation checks only stop NEW duplicates. Run this once after deploying them to find ones that already exist (for
example the same person entered once in Army and once in Police). It prints record ids and services, never names or phone
numbers, so the output is safe to paste into a ticket; look the people up in the application.
"""
from collections import defaultdict

from django.core.management.base import BaseCommand

from apps.personnel.models import Personnel


class Command(BaseCommand):
    help = "Report people entered under the same name and phone in more than one service (ids only)."

    def handle(self, *args, **opts):
        groups = defaultdict(list)
        rows = Personnel.objects.exclude(phone_key="").values_list("id", "name_key", "phone_key", "branch__code", "status")
        for pid, name_key, phone_key, branch, status in rows:
            groups[(name_key, phone_key)].append((str(pid), branch, status))
        found = 0
        for members in groups.values():
            if len({b for _, b, _ in members}) > 1:
                found += 1
                self.stdout.write("Possible duplicate identity: " + "; ".join(f"{b}/{s} {pid}" for pid, b, s in members))
        self.stdout.write(self.style.SUCCESS(f"{found} possible cross-service duplicate(s) found.") if not found
                          else self.style.WARNING(f"{found} possible cross-service duplicate(s) found."))
