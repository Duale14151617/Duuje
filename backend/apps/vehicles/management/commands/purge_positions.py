"""Step 2: delete the positions that a verified archive holds. Dry run unless --apply.

    python manage.py purge_positions --archive FILE --by "Maj. A. Warsame"                       # dry run: shows what would happen
    python manage.py purge_positions --archive FILE --by NAME --apply --confirm 1a2b3c4d --confirm-count 12345
    python manage.py purge_positions --archive FILE --by NAME --abandon                          # give the archive up, delete nothing

Checks before it deletes anything: the archive's signature and checksum; that the batch is in the ledger and still open; that the
cooling-off time has passed (POSITION_PURGE_COOL_OFF_HOURS); that every archived row is older than 30 days. A row that has changed since it
was archived (for example voided) is NOT deleted: it stays, and the next archive picks it up again. The database itself refuses any
delete that is not covered by this batch.
"""
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone

from apps.audit.services import record
from apps.vehicles import archive
from apps.vehicles.models import VehiclePosition, VehiclePositionArchive


class Command(BaseCommand):
    help = "Delete positions that a verified, ledgered archive holds (dry run unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument("--archive", required=True, help="Path of the archive file made by archive_positions.")
        parser.add_argument("--by", required=True, help="Name of the person running this.")
        parser.add_argument("--apply", action="store_true", help="Really delete. Without it nothing changes.")
        parser.add_argument("--confirm", default="", help="With --apply: the first 8 characters of the batch id.")
        parser.add_argument("--confirm-count", type=int, default=None, help="With --apply: the number of rows in the archive.")
        parser.add_argument("--abandon", action="store_true", help="Close the batch without deleting anything.")
        parser.add_argument("--chunk", type=int, default=1000)

    def handle(self, *args, **o):
        by = (o["by"] or "").strip()
        if not by or len(by) > 150:
            raise CommandError("--by must name the person running this command (1 to 150 characters).")
        if o["abandon"] and o["apply"]:
            raise CommandError("Use either --apply or --abandon, not both.")
        try:
            manifest, sig = archive.verify_archive(o["archive"])
        except archive.ArchiveError as exc:
            raise CommandError(str(exc))
        ledger = VehiclePositionArchive.objects.filter(pk=manifest["batch_id"]).first()
        if ledger is None:
            raise CommandError("This archive is not in the ledger of this system. It was not made here, or the ledger was restored from before it.")
        if (ledger.data_sha256, ledger.signature, ledger.row_count) != (manifest["data_sha256"], sig, manifest["row_count"]):
            raise CommandError("The archive does not match the ledger entry for its batch.")
        if ledger.status != "archived":
            raise CommandError(f"Batch {ledger.pk} is already {ledger.status}.")
        now = timezone.now()

        if o["abandon"]:
            ledger.status, ledger.closed_at, ledger.closed_by = "abandoned", now, by
            ledger.save(update_fields=["status", "closed_at", "closed_by"])
            record("vehicle.positions_archive_abandon", entity_type="vehicle_position_archive", entity_id=ledger.pk, metadata={"by": by})
            self.stdout.write("Batch closed as abandoned. Nothing was deleted.")
            return

        if ledger.range_end >= now - timedelta(days=archive.MIN_AGE_DAYS):
            raise CommandError(f"The archive holds positions newer than {archive.MIN_AGE_DAYS} days. Nothing can be purged.")
        ready = ledger.created_at + timedelta(hours=settings.POSITION_PURGE_COOL_OFF_HOURS)
        if o["apply"] and now < ready:
            raise CommandError(f"Cooling-off: purging is allowed after {ready:%Y-%m-%d %H:%M} UTC. Use the time to copy and check the archive.")
        try:
            rows = archive.read_rows(o["archive"], manifest)
        except archive.ArchiveError as exc:
            raise CommandError(str(exc))

        chunk = max(1, min(o["chunk"], 5000))
        plan = {"match": [], "changed": 0, "gone": 0}
        for i in range(0, len(rows), chunk):
            part = rows[i:i + chunk]
            live = {str(p.pk): p for p in VehiclePosition.objects.filter(pk__in=[r["id"] for r in part]).select_related("vehicle")}
            for r in part:
                p = live.get(r["id"])
                if p is None:
                    plan["gone"] += 1
                elif archive.serialize_row(p) == r:
                    plan["match"].append(r["id"])
                else:
                    plan["changed"] += 1
        self.stdout.write(f"Batch {ledger.pk}: {len(rows)} archived rows. In the database now: {len(plan['match'])} unchanged (would be deleted), "
                          f"{plan['changed']} changed since archiving (kept), {plan['gone']} already gone.")
        if not o["apply"]:
            self.stdout.write("Dry run: nothing was deleted. To delete, add --apply --confirm " + str(ledger.pk)[:8] + f" --confirm-count {len(rows)}")
            return
        if o["confirm"] != str(ledger.pk)[:8] or o["confirm_count"] != len(rows):
            raise CommandError(f"To delete, add --confirm {str(ledger.pk)[:8]} --confirm-count {len(rows)} (typed by the person responsible).")

        deleted, kept = 0, 0
        for i in range(0, len(rows), chunk):
            part = rows[i:i + chunk]
            with transaction.atomic():
                if connection.vendor == "postgresql":  # names the batch the database trigger will check; lasts for this transaction only
                    with connection.cursor() as cur:
                        cur.execute("SELECT set_config('policehq.purge_archive', %s, true)", [str(ledger.pk)])
                live = {str(p.pk): p for p in VehiclePosition.objects.select_for_update().filter(pk__in=[r["id"] for r in part]).select_related("vehicle")}
                ids = [r["id"] for r in part if r["id"] in live and archive.serialize_row(live[r["id"]]) == r]
                kept += sum(1 for r in part if r["id"] in live) - len(ids)
                if ids:
                    removed, _ = VehiclePosition.objects.filter(pk__in=ids).delete()
                    if removed != len(ids):
                        raise CommandError("A delete removed a different number of rows than expected. This step was rolled back.")
                    deleted += removed
            self.stdout.write(f"  {min(i + chunk, len(rows))}/{len(rows)} checked, {deleted} deleted")
        with transaction.atomic():
            ledger.status, ledger.closed_at, ledger.closed_by = "purged", timezone.now(), by
            ledger.purged_count, ledger.skipped_count = deleted, kept
            ledger.save(update_fields=["status", "closed_at", "closed_by", "purged_count", "skipped_count"])
            record("vehicle.positions_purge", entity_type="vehicle_position_archive", entity_id=ledger.pk,
                   metadata={"by": by, "deleted": deleted, "kept_changed": kept, "sha256": ledger.data_sha256})
        self.stdout.write(self.style.SUCCESS(f"Purged {deleted} positions. {kept} changed rows were kept for the next archive."))
