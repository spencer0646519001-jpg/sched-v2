# Generated manually for server-side candidate preview persistence.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("scheduler_infra", "0005_refinerequest"),
    ]

    operations = [
        migrations.CreateModel(
            name="MonthlyCandidatePreview",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("year", models.PositiveIntegerField()),
                ("month", models.PositiveSmallIntegerField()),
                ("result_json", models.JSONField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="monthly_candidate_previews",
                        to="scheduler_infra.tenant",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="monthlycandidatepreview",
            constraint=models.CheckConstraint(
                condition=models.Q(("year__gte", 1)),
                name="sched_candidate_preview_year_gte_1",
            ),
        ),
        migrations.AddConstraint(
            model_name="monthlycandidatepreview",
            constraint=models.CheckConstraint(
                condition=models.Q(("month__gte", 1), ("month__lte", 12)),
                name="sched_candidate_preview_month_valid",
            ),
        ),
    ]
