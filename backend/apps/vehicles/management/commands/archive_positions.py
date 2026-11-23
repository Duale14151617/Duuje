"""Step 1 of retiring old vehicle positions: write them to a signed, encrypted archive file. Deletes NOTHING.

    python manage.py archive_positions --out-dir /secure/archives --by "Maj. A. Warsame" [--older-than-days 365] [--max-rows 200000]

Takes the oldest positions (voided ones too) recorded before the cut-off, at most --max-rows at a time. Re-reads and verifies the file it
wrote, then records the batch in the ledger. Copy the file somewhere safe and off this server, then run `purge_positions`.
"""
import os
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.audit.services import record
from apps.vehicles import archive
from apps.vehicles.models import VehiclePosition, VehiclePositionArchive


class Command(BaseCommand):
    help = "Write old vehicle positions to a signed, encrypted archive file (deletes nothing)."

    def add_arguments(self, parser):
        parser.add_argument("--out-dir", required=True, help="Existing folder to write the archive into.")
        parser.add_argument("--by", required=True, help="Name of the person running this (written to the archive and the audit log).")
        parser.add_argument("--older-than-days", type=int, default=None, help=f"Default POSITION_RETENTION_DAYS. Minimum {archive.MIN_AGE_DAYS}.")
        parser.add_argument("--max-rows", type=int, default=archive.DEFAULT_MAX_ROWS)

    def handle(self, *args, **o):
        by = (o["by"] or "").strip()
        if not by or len(by) > 150:
            raise CommandError("--by must name the person running this command (1 to 150 characters).")
        days = o["older_than_days"] if o["older_than_days"] is not None else settings.POSITION_RETENTION_DAYS
        if days < archive.MIN_AGE_DAYS:
            raise CommandError(f"Positions newer than {archive.MIN_AGE_DAYS} days cannot be archived.")
        if not 1 <= o["max_rows"] <= 1_000_000:
            raise CommandError("--max-rows must be between 1 and 1,000,000.")
        out_dir = o["out_dir"]
        if not (os.path.isdir(out_dir) and os.access(out_dir, os.W_OK)):
            raise CommandError("--out-dir must be an existing folder this account can write to.")
        try:
            archive.signing_key()
        except archive.ArchiveError as exc:
            raise CommandError(str(exc))
        open_one = VehiclePositionArchive.objects.filter(status="archived").first()
        if open_one:
            raise CommandError(f"Batch {open_one.pk} ({open_one.file_name}) is archived but not purged yet. Purge it, or abandon it "
                               "with `purge_positions --abandon`, before making another.")
        cutoff = timezone.now() - timedelta(days=days)
        rows = list(VehiclePosition.objects.filter(recorded_at__lt=cutoff).select_related("vehicle").order_by("recorded_at", "id")[:o["max_rows"]])
        if not rows:
            self.stdout.write(f"Nothing to archive: no positions recorded before {cutoff:%Y-%m-%d}.")
            return
        try:
            path, manifest, sig = archive.build_archive(rows, out_dir=out_dir, by=by, cutoff=cutoff)
            checked, _ = archive.verify_archive(path)  # read it back before trusting it
            back = archive.read_rows(path, checked)
        except archive.ArchiveError as exc:
            raise CommandError(str(exc))
        if [r["id"] for r in back] != [str(r.pk) for r in rows]:
            os.remove(path)
            raise CommandError("The archive did not read back the same rows. It was removed; nothing was recorded.")
        with transaction.atomic():
            VehiclePositionArchive.objects.create(
                id=manifest["batch_id"], created_by=by, cutoff=cutoff, range_start=rows[0].recorded_at, range_end=rows[-1].recorded_at,
                row_count=len(rows), file_name=os.path.basename(path), data_sha256=manifest["data_sha256"], signature=sig,
                key_fingerprint=manifest["key_fingerprint"])
            record("vehicle.positions_archive", entity_type="vehicle_position_archive", entity_id=manifest["batch_id"],
                   metadata={"by": by, "rows": len(rows), "range_start": manifest["range_start"], "range_end": manifest["range_end"],
                             "sha256": manifest["data_sha256"], "file": os.path.basename(path)})
        self.stdout.write(self.style.SUCCESS(f"Archived {len(rows)} positions ({manifest['range_start'][:10]} to {manifest['range_end'][:10]})."))
        self.stdout.write(f"File:        {path}\nBatch id:    {manifest['batch_id']}\nSHA-256:     {manifest['data_sha256']}\nSigning key: {manifest['key_fingerprint']}")
        self.stdout.write("Nothing was deleted. Copy the file off this server, check it, then run purge_positions.")
