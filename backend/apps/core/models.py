from django.db import models


class Heartbeat(models.Model):
    """The last time something outside the app said "I ran": the nightly backup, the scheduler that sends reports and reminders.
    The health check page reads these to say when a job has gone quiet. One row per job name."""

    name = models.CharField(max_length=40, primary_key=True)
    at = models.DateTimeField()
    detail = models.CharField(max_length=200, blank=True)

    class Meta:
        db_table = "heartbeats"
