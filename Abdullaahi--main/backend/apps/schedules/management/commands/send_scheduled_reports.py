from django.core.management.base import BaseCommand

from apps.schedules.services import run_due


class Command(BaseCommand):
    help = "Email every scheduled report that is due. Run it every 15-60 minutes (Render cron job, or any scheduler)."

    def handle(self, *args, **opts):
        done = run_due()
        for name, status, detail in done:
            self.stdout.write(f"{name}: {status} - {detail}")
        self.stdout.write(f"{len(done)} scheduled report(s) processed.")
