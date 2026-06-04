from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0011_access_request"),
    ]

    operations = [
        migrations.AlterField(
            model_name="accessrequest",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("approved", "Approved"),
                    ("rejected", "Rejected"),
                    ("revoked", "Revoked"),
                ],
                db_index=True,
                default="pending",
                max_length=20,
            ),
        ),
    ]
