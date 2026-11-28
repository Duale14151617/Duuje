"""Signed archive and controlled purge of old vehicle positions."""
import io
import os
import tempfile
import zipfile
from datetime import timedelta

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.vehicles import archive
from apps.vehicles.models import VehiclePosition, VehiclePositionArchive
from apps.vehicles.tests.test_vehicles import VehicleBase

PRIVATE, PUBLIC = archive.keygen()
OTHER_PRIVATE, OTHER_PUBLIC = archive.keygen()


@override_settings(ARCHIVE_SIGNING_KEY=PRIVATE, ARCHIVE_PUBLIC_KEYS=[], POSITION_PURGE_COOL_OFF_HOURS=0, POSITION_RETENTION_DAYS=365)
class ArchivePurgeTests(VehicleBase):
    def setUp(self):
        super().setUp()
        self.v = self.veh()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old = [self.pos(days=400 - i) for i in range(5)]          # 400..396 days ago
        self.recent = [self.pos(days=2), self.pos(days=40)]            # inside the retention period / past 30 days but newer than 365

    def pos(self, days, **kw):
        return VehiclePosition.objects.create(vehicle=self.v, latitude="8.405500", longitude="48.483700", source="phone",
                                              recorded_at=timezone.now() - timedelta(days=days), created_by_username="officer", **kw)

    def out(self):
        return io.StringIO()

    def archive_run(self, **kw):
        o = self.out()
        call_command("archive_positions", out_dir=self.tmp.name, by="Maj. Test", stdout=o, **kw)
        return o.getvalue()

    def file(self):
        files = [f for f in os.listdir(self.tmp.name) if f.endswith(".zip")]
        self.assertEqual(len(files), 1, files)
        return os.path.join(self.tmp.name, files[0])

    def purge(self, path=None, **kw):
        o = self.out()
        call_command("purge_positions", archive=path or self.file(), by="Maj. Test", stdout=o, **kw)
        return o.getvalue()

    def confirmed(self, led, **kw):
        return dict(apply=True, confirm=str(led.pk)[:8], confirm_count=led.row_count, **kw)

    # ---- archive ------------------------------------------------------------------------------------------------------------
    def test_archive_writes_signed_file_records_ledger_and_deletes_nothing(self):
        out = self.archive_run()
        self.assertIn("Archived 5 positions", out)
        self.assertEqual(VehiclePosition.objects.count(), 7)
        led = VehiclePositionArchive.objects.get()
        self.assertEqual((led.status, led.row_count, led.created_by), ("archived", 5, "Maj. Test"))
        manifest, sig = archive.verify_archive(self.file())
        self.assertEqual(manifest["batch_id"], str(led.pk))
        self.assertEqual(sig, led.signature)
        rows = archive.read_rows(self.file(), manifest)
        self.assertEqual({r["id"] for r in rows}, {str(p.pk) for p in self.old})
        self.assertTrue(AuditEvent.objects.filter(action="vehicle.positions_archive").exists())

    def test_archive_is_encrypted(self):
        self.archive_run()
        with zipfile.ZipFile(self.file()) as z:
            self.assertNotIn(b"48.483700", z.read(archive.DATA))

    def test_archive_refusals(self):
        with self.assertRaises(CommandError):
            self.archive_run(older_than_days=10)
        with override_settings(ARCHIVE_SIGNING_KEY=""):
            with self.assertRaises(CommandError):
                self.archive_run()
        with self.assertRaises(CommandError):
            call_command("archive_positions", out_dir=self.tmp.name, by="  ", stdout=self.out())
        with self.assertRaises(CommandError):
            call_command("archive_positions", out_dir="/no/such/folder", by="X", stdout=self.out())
        self.archive_run()
        with self.assertRaises(CommandError):  # one open batch at a time
            self.archive_run()

    def test_nothing_to_archive(self):
        out = self.archive_run(older_than_days=500)
        self.assertIn("Nothing to archive", out)
        self.assertEqual(VehiclePositionArchive.objects.count(), 0)

    # ---- verification -------------------------------------------------------------------------------------------------------
    def rewrite(self, path, name, data):
        with zipfile.ZipFile(path) as z:
            parts = {n: z.read(n) for n in z.namelist()}
        parts[name] = data
        with zipfile.ZipFile(path, "w") as z:
            for n, b in parts.items():
                z.writestr(n, b)

    def test_tampering_and_wrong_key_are_caught(self):
        self.archive_run()
        path = self.file()
        archive.verify_archive(path)
        with zipfile.ZipFile(path) as z:
            data, manifest = z.read(archive.DATA), z.read(archive.MANIFEST)
        self.rewrite(path, archive.DATA, data[:-1] + bytes([data[-1] ^ 1]))
        with self.assertRaises(archive.ArchiveError):
            archive.verify_archive(path)
        self.rewrite(path, archive.DATA, data)
        archive.verify_archive(path)
        self.rewrite(path, archive.MANIFEST, manifest.replace(b'"row_count":5', b'"row_count":4'))
        with self.assertRaises(archive.ArchiveError):
            archive.verify_archive(path)
        self.rewrite(path, archive.MANIFEST, manifest)
        with override_settings(ARCHIVE_PUBLIC_KEYS=[OTHER_PUBLIC]):
            with self.assertRaises(archive.ArchiveError):
                archive.verify_archive(path)
        with override_settings(ARCHIVE_PUBLIC_KEYS=[OTHER_PUBLIC, PUBLIC]):  # a retired key may still be listed
            archive.verify_archive(path)

    def test_wrong_data_key_cannot_read_rows(self):
        self.archive_run()
        manifest, _ = archive.verify_archive(self.file())
        from cryptography.fernet import Fernet
        with override_settings(FIELD_ENCRYPTION_KEY=Fernet.generate_key().decode()):
            from apps.core import crypto
            crypto._multi_for.cache_clear()
            try:
                with self.assertRaises(archive.ArchiveError):
                    archive.read_rows(self.file(), manifest)
            finally:
                crypto._multi_for.cache_clear()

    # ---- purge --------------------------------------------------------------------------------------------------------------
    def test_dry_run_deletes_nothing(self):
        self.archive_run()
        out = self.purge()
        self.assertIn("5 unchanged (would be deleted)", out)
        self.assertIn("Dry run", out)
        self.assertEqual(VehiclePosition.objects.count(), 7)

    def test_apply_needs_both_confirmations(self):
        self.archive_run()
        led = VehiclePositionArchive.objects.get()
        with self.assertRaises(CommandError):
            self.purge(apply=True)
        with self.assertRaises(CommandError):
            self.purge(apply=True, confirm=str(led.pk)[:8], confirm_count=4)
        with self.assertRaises(CommandError):
            self.purge(apply=True, confirm="deadbeef", confirm_count=5)
        self.assertEqual(VehiclePosition.objects.count(), 7)

    def test_purge_deletes_only_archived_rows_and_closes_the_batch(self):
        self.archive_run()
        led = VehiclePositionArchive.objects.get()
        out = self.purge(**self.confirmed(led))
        self.assertIn("Purged 5 positions", out)
        self.assertEqual({p.pk for p in VehiclePosition.objects.all()}, {p.pk for p in self.recent})
        led.refresh_from_db()
        self.assertEqual((led.status, led.purged_count, led.skipped_count, led.closed_by), ("purged", 5, 0, "Maj. Test"))
        self.assertTrue(AuditEvent.objects.filter(action="vehicle.positions_purge").exists())
        with self.assertRaises(CommandError):  # the same archive cannot be used twice
            self.purge(**self.confirmed(led))
        self.archive_run(older_than_days=30)   # a new batch is allowed again once the old one is closed

    def test_cooling_off_blocks_apply_but_not_dry_run(self):
        self.archive_run()
        led = VehiclePositionArchive.objects.get()
        with override_settings(POSITION_PURGE_COOL_OFF_HOURS=24):
            self.assertIn("Dry run", self.purge())
            with self.assertRaises(CommandError):
                self.purge(**self.confirmed(led))
        self.assertEqual(VehiclePosition.objects.count(), 7)

    def test_row_changed_after_archiving_is_kept_and_archived_again_later(self):
        self.archive_run()
        led = VehiclePositionArchive.objects.get()
        changed = self.old[2]
        VehiclePosition.objects.filter(pk=changed.pk).update(voided_at=timezone.now(), voided_reason="Wrong spot", version=2)
        out = self.purge(**self.confirmed(led))
        self.assertIn("Purged 4 positions", out)
        self.assertEqual(list(VehiclePosition.objects.filter(pk=changed.pk).values_list("pk", flat=True)), [changed.pk])
        led.refresh_from_db()
        self.assertEqual((led.purged_count, led.skipped_count), (4, 1))
        for f in os.listdir(self.tmp.name):
            os.remove(os.path.join(self.tmp.name, f))
        self.archive_run()
        manifest, _ = archive.verify_archive(self.file())
        self.assertEqual([r["id"] for r in archive.read_rows(self.file(), manifest)], [str(changed.pk)])

    def test_archive_not_in_ledger_or_edited_ledger_is_refused(self):
        rows = list(VehiclePosition.objects.filter(pk__in=[p.pk for p in self.old]).select_related("vehicle").order_by("recorded_at", "id"))
        path, _, _ = archive.build_archive(rows, out_dir=self.tmp.name, by="Someone", cutoff=timezone.now())
        with self.assertRaises(CommandError) as e:
            self.purge(path, apply=True, confirm="x", confirm_count=5)
        self.assertIn("not in the ledger", str(e.exception))
        self.assertEqual(VehiclePosition.objects.count(), 7)

    def test_archive_signed_by_another_key_is_refused(self):
        self.archive_run()
        with override_settings(ARCHIVE_PUBLIC_KEYS=[OTHER_PUBLIC]):
            with self.assertRaises(CommandError):
                self.purge()

    def test_recent_rows_cannot_be_purged_even_if_archived(self):
        rows = list(VehiclePosition.objects.filter(pk__in=[p.pk for p in self.recent]).select_related("vehicle").order_by("recorded_at", "id"))
        path, manifest, sig = archive.build_archive(rows, out_dir=self.tmp.name, by="X", cutoff=timezone.now())
        led = VehiclePositionArchive.objects.create(
            id=manifest["batch_id"], created_by="X", cutoff=timezone.now(), range_start=rows[0].recorded_at, range_end=rows[-1].recorded_at,
            row_count=len(rows), file_name=os.path.basename(path), data_sha256=manifest["data_sha256"], signature=sig, key_fingerprint=manifest["key_fingerprint"])
        self.assertLess(rows[-1].recorded_at, timezone.now())
        # the newest of these rows is 2 days old: well inside the 30-day floor
        with self.assertRaises(CommandError):
            self.purge(path, **self.confirmed(led))
        self.assertEqual(VehiclePosition.objects.count(), 7)

    def test_abandon_closes_without_deleting(self):
        self.archive_run()
        out = self.purge(abandon=True)
        self.assertIn("abandoned", out)
        self.assertEqual(VehiclePosition.objects.count(), 7)
        self.assertEqual(VehiclePositionArchive.objects.get().status, "abandoned")
        self.assertTrue(AuditEvent.objects.filter(action="vehicle.positions_archive_abandon").exists())
        with self.assertRaises(CommandError):
            self.purge(abandon=True)

    def test_ledger_rows_cannot_be_deleted(self):
        self.archive_run()
        from apps.core.appendonly import AppendOnlyError
        with self.assertRaises(AppendOnlyError):
            VehiclePositionArchive.objects.get().delete()

    def test_keygen_makes_a_working_pair(self):
        priv, pub = archive.keygen()
        self.assertNotEqual(priv, pub)
        with override_settings(ARCHIVE_SIGNING_KEY=priv):
            self.archive_run()
            with override_settings(ARCHIVE_PUBLIC_KEYS=[pub]):
                archive.verify_archive(self.file())
