from django.db import migrations
from django.utils import timezone

from apps.ranks.catalogue import apply_official_ranks


def forward(apps, schema_editor):
    Branch = apps.get_model("organization", "ServiceBranch")
    army = Branch.objects.filter(code="ARMY").first()
    if army is None:  # fresh install: `seed_reference_data` creates the branch and then the same catalogue
        return
    # Idempotent: adds PA-17 (Commander of the Puntland Defense Forces) and PA-18 (President / Commander-in-Chief).
    apply_official_ranks(apps.get_model("ranks", "Rank"), apps.get_model("personnel", "Personnel"), army, timezone.now())


class Migration(migrations.Migration):
    dependencies = [("ranks", "0003_official_puntland_army_ranks")]
    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
