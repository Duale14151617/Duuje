"""Re-encrypt every encrypted column under the first key in FIELD_ENCRYPTION_KEY.

    FIELD_ENCRYPTION_KEY="NEW,OLD"  ->  python manage.py rotate_encryption_key            (dry run: counts only)
                                        python manage.py rotate_encryption_key --apply    (writes)

Safe to run while the system is in use and safe to repeat: every listed key can still read, rows already under the new key are skipped,
each row is locked and re-read before it is rewritten, and timestamps are left alone. Append-only tables (the database refuses updates)
are reported, and their rows keep working as long as the old key stays listed.
"""
from collections import Counter

from cryptography.fernet import InvalidToken
from django.apps import apps as django_apps
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, models, transaction

from apps.core import crypto


def _encrypted_fields():
    for model in django_apps.get_models():
        for field in model._meta.concrete_fields:
            if field.name.endswith("_enc") and isinstance(field, (models.TextField, models.BinaryField)):
                yield model, field


def _raw(value):
    return value.encode() if isinstance(value, str) else bytes(value)


def _store(field, token):
    return token.decode() if isinstance(field, models.TextField) else token


class Command(BaseCommand):
    help = "Re-encrypt stored data under the first key in FIELD_ENCRYPTION_KEY. Dry run unless --apply."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Write the re-encrypted values (default: only count).")

    def handle(self, *args, apply=False, **options):
        configured = crypto.keys()
        if len(configured) < 2:
            self.stdout.write("Only one key is configured, so there is nothing to rotate. To rotate, set "
                              "FIELD_ENCRYPTION_KEY=<new key>,<current key> and run this again.")
            return
        totals = Counter()
        for model, field in _encrypted_fields():
            stats = self._table(model, field, apply)
            totals.update(stats)
            label = f"{model._meta.label}.{field.name}"
            self.stdout.write(f"{label:55} current={stats['current']:<6} to_rotate={stats['stale']:<6} "
                              f"rotated={stats['rotated']:<6} blocked={stats['blocked']:<4} unreadable={stats['undecryptable']}")
        remaining = totals["stale"] - totals["rotated"]
        self.stdout.write("")
        self.stdout.write(f"{'Rewrote' if apply else 'Would rewrite'} {totals['stale'] if not apply else totals['rotated']} value(s); "
                          f"{totals['current']} already under the new key.")
        if totals["undecryptable"]:
            raise CommandError(f"{totals['undecryptable']} value(s) cannot be read with ANY listed key. Do not remove any key: "
                               "find the missing key (or restore from backup) before going further.")
        if not apply:
            self.stdout.write("Dry run only. Re-run with --apply to write.")
        elif remaining:
            self.stdout.write(self.style.WARNING(
                f"{remaining} value(s) are still under an older key (append-only tables cannot be rewritten). KEEP the old key(s) listed."))
        else:
            self.stdout.write(self.style.SUCCESS("Everything is under the new key. Before removing the old key(s) from FIELD_ENCRYPTION_KEY, "
                                                 "make sure FIELD_HMAC_KEY is set to the OLD key (it protects weapon-ID matching)."))

    def _table(self, model, field, apply):
        name, stats = field.name, Counter()
        manager = model._base_manager
        for pk, value in manager.values_list("pk", name).iterator(chunk_size=200):
            if not value:
                continue
            raw = _raw(value)
            if crypto.is_current(raw):
                stats["current"] += 1
                continue
            try:
                crypto.rotate(raw)
            except InvalidToken:
                stats["undecryptable"] += 1
                continue
            stats["stale"] += 1
            if not apply:
                continue
            try:
                with transaction.atomic():
                    locked = manager.select_for_update().filter(pk=pk).values_list(name, flat=True).first()
                    if not locked or crypto.is_current(_raw(locked)):
                        stats["stale"] -= 1  # changed (or already rotated) since it was read
                        continue
                    manager.filter(pk=pk).update(**{name: _store(field, crypto.rotate(_raw(locked)))})
                stats["rotated"] += 1
            except InvalidToken:
                stats["undecryptable"] += 1
            except DatabaseError:
                stats["blocked"] += 1  # append-only trigger or similar: this table cannot be rewritten
                break
        return stats
