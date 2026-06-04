from django.conf import settings
from django.db import migrations
from django.db import models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("core", "0010_remove_unused_metadata_models"),
    ]

    operations = [
        migrations.CreateModel(
            name="AccessRequest",
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
                ("username", models.CharField(db_index=True, max_length=150)),
                ("email", models.EmailField(db_index=True, max_length=254)),
                ("first_name", models.CharField(max_length=150)),
                ("last_name", models.CharField(max_length=150)),
                (
                    "requested_use_case",
                    models.CharField(db_index=True, max_length=80),
                ),
                (
                    "requested_lab",
                    models.CharField(blank=True, max_length=80, null=True),
                ),
                (
                    "requested_role",
                    models.CharField(
                        choices=[("view", "View"), ("admin", "Admin")],
                        default="view",
                        max_length=20,
                    ),
                ),
                ("message", models.TextField(blank=True, null=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("approved", "Approved"),
                            ("rejected", "Rejected"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                (
                    "reviewed_at",
                    models.DateTimeField(blank=True, db_index=True, null=True),
                ),
                ("review_note", models.TextField(blank=True, null=True)),
                (
                    "approved_group",
                    models.CharField(blank=True, max_length=255, null=True),
                ),
                (
                    "keycloak_user_id",
                    models.CharField(blank=True, max_length=80, null=True),
                ),
                (
                    "reviewed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="reviewed_access_requests",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "reviewed_by_identity",
                    models.CharField(blank=True, max_length=255, null=True),
                ),
            ],
            options={
                "db_table": "core_access_request",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="accessrequest",
            index=models.Index(
                fields=["status", "created_at"],
                name="core_access_status_created_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="accessrequest",
            index=models.Index(
                fields=["requested_use_case", "requested_lab"],
                name="core_access_project_lab_idx",
            ),
        ),
    ]
