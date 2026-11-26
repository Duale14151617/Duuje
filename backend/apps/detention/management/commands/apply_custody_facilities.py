from django.core.management.base import BaseCommand
from django.db import transaction

from apps.detention import facilities


class Command(BaseCommand):
    help = ("Create a jail center record for every active army station that has none, and one generic prison record per region. "
            "New records are NOT VERIFIED: an administrator must confirm each one before anyone can be held in it. "
            "Safe to run again: it only adds what is missing and never edits an existing record.")

    def handle(self, *args, **opts):
        from django.conf import settings

        if not settings.CUSTODY_ENABLED:
            self.stdout.write("Custody is switched off (CUSTODY_ENABLED=0): nothing done.")
            return
        with transaction.atomic():
            jails, prisons = facilities.ensure_defaults()
        self.stdout.write(self.style.SUCCESS(f"Custody facilities ready: {jails} jail centers and {prisons} prisons added (all start as not verified)."))
