"""Rename the stored sample-data labels from "DEMO"/"Demo" to "SAMPLE"/"Sample". Nothing is deleted; dry run unless --apply.

Older databases hold rows created by the sample seed under the old labels:

  units        <REGION>-ARMY-DEMO-A            -> <REGION>-ARMY-SAMPLE-A
  people       service number DEMO-0001        -> SAMPLE-0001, and the name "Demo Person NN" -> "Sample Person NN"
  assets       identifier DEMO-...             -> SAMPLE-... (and "Synthetic demo ..." descriptions, "Demo rifle" etc. makes)
  custody      authority reference "Demo order ..." -> "Sample order ..."
  accounts     full names containing "(Demo)" / "(Demo Person NN)" -> "(Sample)" / "(Sample Person NN)"

Append-only records (stock and PPE movements, soldier rounds, history, audit) are never touched: the database refuses it, and
rewriting a ledger would defeat its purpose. Rows that clash with an existing target value are skipped and reported.
Idempotent, so it is safe to run at every start-up (it runs before `seed_sample_data`, so the seed finds the new labels).

  python manage.py rename_sample_data            dry run: report only
  python manage.py rename_sample_data --apply    make the change
"""
import re

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import User
from apps.logistics.models import Asset
from apps.organization.models import OrganizationalUnit as OU
from apps.personnel.models import Personnel
from apps.weapons.models import WeaponCustody, WeaponDetail


def _swap(text):
    """Demo -> Sample inside a label, keeping the capitalisation style."""
    text = text.replace("DEMO", "SAMPLE").replace("Demo", "Sample")
    return re.sub(r"\bdemo\b", "sample", text)


class Command(BaseCommand):
    help = "Rename stored DEMO/Demo sample labels to SAMPLE/Sample (no deletion; dry run unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="make the change (default: dry run)")

    def handle(self, *args, **opts):
        apply = opts["apply"]
        done, skipped = {}, []

        def rename_unique(label, qs, field, new_of, taken_qs=None):
            """Change `field` row by row, skipping a row whose new value already exists (unique fields)."""
            n = 0
            for obj in qs:
                old = getattr(obj, field)
                new = new_of(old)
                if new == old:
                    continue
                if taken_qs is not None and taken_qs.filter(**{field: new}).exclude(pk=obj.pk).exists():
                    skipped.append(f"{label} {old}: {new} already exists")
                    continue
                n += 1
                if apply:
                    type(obj).objects.filter(pk=obj.pk).update(**{field: new})
            done[label] = done.get(label, 0) + n

        def rename_text(label, qs, field, new_of):
            n = 0
            for obj in qs:
                old = getattr(obj, field) or ""
                new = new_of(old)
                if new != old:
                    n += 1
                    if apply:
                        type(obj).objects.filter(pk=obj.pk).update(**{field: new})
            done[label] = done.get(label, 0) + n

        with transaction.atomic():
            rename_unique("unit codes", OU.objects.filter(code__contains="-DEMO-"), "code", _swap, OU.objects.all())
            rename_unique("service numbers", Personnel.objects.filter(service_number__startswith="DEMO-"), "service_number", _swap,
                          Personnel.objects.all())
            rename_text("person names", Personnel.objects.filter(full_name__startswith="Demo Person "), "full_name", _swap)
            for asset in Asset.objects.filter(identifier__startswith="DEMO-"):  # unique within a category
                new = _swap(asset.identifier)
                if Asset.objects.filter(category=asset.category, identifier=new).exclude(pk=asset.pk).exists():
                    skipped.append(f"asset {asset.identifier}: {new} already exists")
                    continue
                done["asset identifiers"] = done.get("asset identifiers", 0) + 1
                if apply:
                    Asset.objects.filter(pk=asset.pk).update(identifier=new)
            rename_text("asset descriptions", Asset.objects.filter(description__icontains="demo"), "description", _swap)
            rename_text("weapon makes", WeaponDetail.objects.filter(make_model__startswith="Demo "), "make_model", _swap)
            rename_text("custody authority references", WeaponCustody.objects.filter(authority_ref__startswith="Demo "), "authority_ref", _swap)
            rename_text("account names", User.objects.filter(full_name__icontains="(Demo"), "full_name", _swap)
            if not apply:
                transaction.set_rollback(True)

        verb = "renamed" if apply else "to rename"
        total = sum(done.values())
        self.stdout.write("Sample data labels: " + (", ".join(f"{n} {k}" for k, n in done.items() if n) or "nothing") + f" {verb}.")
        for line in skipped:
            self.stdout.write(f"  skipped {line}")
        if not apply and total:
            self.stdout.write("Dry run. Add --apply to make the change.")
