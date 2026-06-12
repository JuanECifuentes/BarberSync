from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.notifications"
    verbose_name = "Notificaciones"

    def ready(self):
        import logging
        from django.utils import timezone
        
        logger = logging.getLogger(__name__)

        try:
            from apps.notifications import notifications
            
            original_send_reminder_task = notifications._send_reminder_task

            def wrapped_send_reminder_task(appointment_id: int, notif_type: str, recipient_type: str):
                from apps.scheduling.models import Appointment
                try:
                    appointment = Appointment.objects.get(pk=appointment_id)
                    if appointment.start_time < timezone.now():
                        logger.info(
                            f"Discarding/pruning reminder task {notif_type} for past appointment {appointment_id} (scheduled at {appointment.start_time}, now {timezone.now()})"
                        )
                        return
                except Appointment.DoesNotExist:
                    logger.warning(f"Appointment {appointment_id} does not exist. Discarding reminder task.")
                    return
                except Exception as e:
                    logger.error(f"Error checking appointment for reminder task: {e}")
                
                return original_send_reminder_task(appointment_id, notif_type, recipient_type)

            notifications._send_reminder_task = wrapped_send_reminder_task
            logger.info("Successfully patched _send_reminder_task to discard past appointment reminders.")
        except Exception as e:
            logger.error(f"Failed to patch _send_reminder_task: {e}")

