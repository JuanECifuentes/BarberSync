# Generated for BarberSync: multi-interval billing and pending subscriptions.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0003_subscription_wompi_transaction_id_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="planprice",
            name="interval_count",
            field=models.PositiveIntegerField(
                default=1,
                help_text="Cantidad de intervalos por ciclo (1, 3 o 12 para month).",
            ),
        ),
        migrations.AlterField(
            model_name="subscription",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "En checkout"),
                    ("trialing", "En prueba"),
                    ("active", "Activa"),
                    ("past_due", "Pago pendiente"),
                    ("canceled", "Cancelada"),
                    ("expired", "Expirada"),
                ],
                max_length=15,
                default="trialing",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="planprice",
            name="unique_active_price_per_plan_provider",
        ),
        migrations.AddConstraint(
            model_name="planprice",
            constraint=models.UniqueConstraint(
                condition=models.Q(is_current=True),
                fields=("plan", "provider", "currency", "interval", "interval_count"),
                name="unique_active_price_per_plan_provider_interval",
            ),
        ),
        migrations.AddIndex(
            model_name="planprice",
            index=models.Index(
                fields=["plan", "provider", "interval", "interval_count", "is_current"],
                name="bp_interval_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="subscription",
            index=models.Index(
                fields=["status", "provider", "organization"],
                name="bs_sub_status_org_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="subscription",
            index=models.Index(
                fields=["status", "provider", "user"],
                name="bs_sub_status_user_idx",
            ),
        ),
    ]
