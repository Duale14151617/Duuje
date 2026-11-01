from django.db import migrations
from django.utils import timezone

from apps.ranks.catalogue import apply_official_ranks


def forward(apps, schema_editor):
    Branch = apps.get_model("organization", "ServiceBranch")
    army = Branch.objects.filter(code="ARMY").first()
    if army is None:  # fresh install: `seed_reference_data` creates the branch and then the same catalogue
        return
    apply_official_ranks(apps.get_model("ranks", "Rank"), apps.get_model("personnel", "Personnel"), army, timezone.now())


class Migration(migrations.Migration):
    """Replaces the provisional US-style Army ranks with the 16 official ones without orphaning any personnel record:
    ranks that people hold are kept (deactivated), unused provisional drafts are removed. Not reversible by design
    (the provisional list was a placeholder); restore the pre-upgrade backup to go back."""

    dependencies = [("ranks", "0002_alter_rank_category"), ("personnel", "0001_initial")]
    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
