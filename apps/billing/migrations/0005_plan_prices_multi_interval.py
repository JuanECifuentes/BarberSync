"""Data migration: provision 3-month and 12-month prices for all plans."""

from django.db import migrations


def _round_cop(value: int) -> int:
    # Redondea a múltiplos de 1000 COP (precios presentables).
    return max(1000, int(round(value / 1000.0)) * 1000)


def _monthly_minor(row):
    return int(row["amount_minor"])


def seed_multi_interval_prices(apps, schema_editor):
    PlanPrice = apps.get_model("billing", "PlanPrice")
    Plan = apps.get_model("billing", "Plan")

    # 3 meses: 5% dto   | 12 meses: 15% dto
    DISCOUNTS = {3: 0.95, 12: 0.85}

    plan_code_by_id = dict(Plan.objects.values_list("id", "code"))
    monthly = list(
        PlanPrice.objects.filter(
            interval="month", interval_count=1, is_current=True
        ).values("id", "plan_id", "provider", "currency", "amount_minor")
    )

    for row in monthly:
        base = _monthly_minor(row)
        currency = row["currency"]
        provider = row["provider"]
        plan_id = row["plan_id"]
        plan_code = plan_code_by_id.get(plan_id, "").lower()
        existing_ppid_lookup = PlanPrice.objects.get(pk=row["id"]).provider_price_id

        for months, factor in DISCOUNTS.items():
            if currency == "COP":
                new_amount = _round_cop(int(base * months * factor))
            else:
                new_amount = max(100, round(base * months * factor))

            interval_label = "quarter" if months == 3 else "year"
            ppid = existing_ppid_lookup.replace("_month", f"_{interval_label}")
            # Para Stripe trimestral/anual el admin debe crear precios específicos
            # en el Dashboard y sustituir el placeholder por el price_... real.
            # Si no se modificó (ej: el ppid original no contenía _month),
            # forzamos un placeholder explícito para evitar cobrar el plan mensual.
            if provider == "stripe" and (
                not ppid.startswith("price_1") or ppid == existing_ppid_lookup
            ):
                ppid = (
                    f"price_replace_me_{plan_code}_{currency.lower()}_{interval_label}"
                )

            PlanPrice.objects.update_or_create(
                plan_id=plan_id,
                provider=provider,
                currency=currency,
                interval="month",
                interval_count=months,
                is_current=True,
                defaults={
                    "amount_minor": new_amount,
                    "provider_price_id": ppid,
                },
            )


def remove_multi_interval_prices(apps, schema_editor):
    PlanPrice = apps.get_model("billing", "PlanPrice")
    PlanPrice.objects.filter(interval="month", interval_count__in=(3, 12)).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0004_subscription_pending_and_interval_count"),
    ]

    operations = [
        migrations.RunPython(
            seed_multi_interval_prices,
            reverse_code=remove_multi_interval_prices,
        ),
    ]
