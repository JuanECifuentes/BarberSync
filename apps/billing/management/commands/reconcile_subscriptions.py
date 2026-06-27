"""
Management command: reconcile_subscriptions

Dispara la tarea `apps.billing.tasks.reconcile_subscriptions` que consulta
las APIs externas de Stripe y Wompi para confirmar pagos cuyos webhooks
se perdieron y sincronizar las suscripciones PENDING.
"""

from django.core.management.base import BaseCommand

from apps.billing.tasks import reconcile_subscriptions


class Command(BaseCommand):
    help = (
        "Reconcilia suscripciones en estado PENDING consultando directamente "
        "a las APIs de Stripe y Wompi para detectar pagos exitosos cuyo "
        "webhook se perdió."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--min-age",
            type=int,
            default=300,
            help="Edad mínima (segundos) de la suscripción PENDING a reconciliar.",
        )
        parser.add_argument(
            "--async",
            action="store_true",
            help="Encola la reconciliación en django_q en lugar de ejecutarla síncrono.",
        )

    def handle(self, *args, **opts):
        min_age = opts["min_age"]
        if opts["async"]:
            try:
                from django_q.tasks import async_task
            except ImportError:
                self.stderr.write("django_q no está disponible; ejecutando síncrono.")
                async_task = None
            if async_task:
                async_task(reconcile_subscriptions, min_age)
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Reconciliación encolada en django_q (min_age={min_age}s)."
                    )
                )
                return

        summary = reconcile_subscriptions(min_age)
        self.stdout.write(
            self.style.SUCCESS(
                "Reconciliación completada:\n"
                f"  Checked        : {summary['checked']}\n"
                f"  Activated      : {summary['activated']}\n"
                f"  Still pending  : {summary['still_pending']}\n"
                f"  Errors         : {summary['errors']}"
            )
        )
