"""Retention job for CSV import holding rows (personal data). Run daily from cron/systemd timer."""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.audit.services import record
from apps.personnel.models import ImportBatch


class Command(BaseCommand):
    help = "Delete expired previews and old committed import batches (they may hold personal data)."

    def add_arguments(self, parser):
        parser.add_argument("--committed-days", type=int, default=7)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        now = timezone.now()
        expired = ImportBatch.objects.filter(status=ImportBatch.Status.PREVIEW, expires_at__lte=now)
        old_done = ImportBatch.objects.filter(status=ImportBatch.Status.COMMITTED,
                                              created_at__lte=now - timedelta(days=opts["committed_days"]))
        counts = {"expired_previews": expired.count(), "old_committed": old_done.count()}
        if not opts["dry_run"]:
            with transaction.atomic():
                expired.delete()
                old_done.delete()
                record("personnel.import_purge", entity_type="import_batch", metadata=counts)
        self.stdout.write(f"{'Would purge' if opts['dry_run'] else 'Purged'}: {counts}")
