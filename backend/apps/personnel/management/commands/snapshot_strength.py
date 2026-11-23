from django.core.management.base import BaseCommand

from apps.personnel.strength_trend import take_snapshot


class Command(BaseCommand):
    help = "Record today's headcount snapshot (aggregates only) for the strength trend. Safe to run more than once a day."

    def handle(self, *args, **options):
        snap = take_snapshot()
        self.stdout.write(f"{snap.date}: serving {snap.serving_all}, total {snap.total_all}")
