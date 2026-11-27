import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.db.models import F, Q


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("organization", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="ReportType",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("code", models.CharField(max_length=48, unique=True)),
                ("kind", models.CharField(choices=[("report", "Report"), ("request", "Request")], max_length=8)),
                ("name_en", models.CharField(max_length=120)),
                ("name_so", models.CharField(blank=True, max_length=120)),
                ("figure_keys", models.JSONField(blank=True, default=list)),
                ("separation_of_duties", models.BooleanField(default=True)),
                ("active", models.BooleanField(default=True)),
                ("version", models.PositiveIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"db_table": "report_types", "ordering": ["code"]},
        ),
        migrations.CreateModel(
            name="Submission",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("title", models.CharField(max_length=200)),
                ("period_start", models.DateField()),
                ("period_end", models.DateField()),
                ("body", models.TextField(blank=True)),
                ("figures", models.JSONField(blank=True, default=dict)),
                ("status", models.CharField(choices=[("draft", "Draft"), ("submitted", "Submitted"), ("under_review", "Under Review"), ("approved", "Approved"), ("rejected", "Rejected"), ("returned", "Returned"), ("amended", "Amended")], db_index=True, default="draft", max_length=12)),
                ("version", models.PositiveIntegerField(default=1)),
                ("current_revision", models.PositiveIntegerField(default=0)),
                ("submitter_username", models.CharField(max_length=150)),
                ("submitted_at", models.DateTimeField(blank=True, null=True)),
                ("decided_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("org_unit", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to="organization.organizationalunit")),
                ("report_type", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="submissions", to="workflows.reporttype")),
                ("reviewer", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("submitter", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "submissions", "ordering": ["-updated_at", "id"]},
        ),
        migrations.AddConstraint(
            model_name="submission",
            constraint=models.CheckConstraint(condition=Q(period_end__gte=F("period_start")), name="submission_period_valid"),
        ),
        migrations.CreateModel(
            name="SubmissionRevision",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("revision_no", models.PositiveIntegerField()),
                ("title", models.CharField(max_length=200)),
                ("period_start", models.DateField()),
                ("period_end", models.DateField()),
                ("body", models.TextField(blank=True)),
                ("figures", models.JSONField(blank=True, default=dict)),
                ("submitted_by_username", models.CharField(max_length=150)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("submission", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="revisions", to="workflows.submission")),
                ("submitted_by", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "submission_revisions", "ordering": ["revision_no"]},
        ),
        migrations.AddConstraint(
            model_name="submissionrevision",
            constraint=models.UniqueConstraint(fields=("submission", "revision_no"), name="revision_unique_per_submission"),
        ),
        migrations.AddField(
            model_name="submission",
            name="approved_revision",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="workflows.submissionrevision"),
        ),
        migrations.CreateModel(
            name="ApprovalAction",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("revision_no", models.PositiveIntegerField(default=0)),
                ("action", models.CharField(max_length=16)),
                ("from_status", models.CharField(blank=True, max_length=12)),
                ("to_status", models.CharField(max_length=12)),
                ("actor_username", models.CharField(max_length=150)),
                ("comment", models.CharField(blank=True, max_length=1000)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("actor", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("submission", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="actions", to="workflows.submission")),
            ],
            options={"db_table": "approval_actions", "ordering": ["created_at", "id"]},
        ),
        migrations.CreateModel(
            name="Notification",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("kind", models.CharField(max_length=24)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("read_at", models.DateTimeField(blank=True, null=True)),
                ("recipient", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("submission", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="workflows.submission")),
            ],
            options={"db_table": "notifications", "ordering": ["-created_at", "id"]},
        ),
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(fields=["recipient", "read_at"], name="notif_recipient_read_idx"),
        ),
    ]
