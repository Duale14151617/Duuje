"""After the official rank list replaced the provisional one, list people still holding a retired rank.

Prints counts per retired rank only (no names or personal data). Re-ranking is done by authorised users through the
normal change-rank action, because no mapping from the provisional list to the official list was supplied."""
from django.core.management.base import BaseCommand
from django.db.models import Count

from apps.personnel.models import Personnel


class Command(BaseCommand):
    help = "Count personnel who still hold an inactive (retired) rank, per rank."

    def handle(self, *args, **opts):
        rows = (Personnel.objects.filter(rank__active=False).values("rank__branch__code", "rank__code", "rank__name_en")
                .annotate(n=Count("id")).order_by("rank__branch__code", "rank__code"))
        total = 0
        for r in rows:
            total += r["n"]
            self.stdout.write(f'{r["rank__branch__code"]} {r["rank__code"]} {r["rank__name_en"]}: {r["n"]}')
        self.stdout.write(f"total personnel on retired ranks: {total}")
