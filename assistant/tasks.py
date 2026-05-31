from celery import shared_task
from django.core.mail import send_mail
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone
import logging
import re
from datetime import datetime
import pytz
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
from bleach import clean

# Configure logging
logging.basicConfig(
    filename='jarvis_tasks.log',
    level=logging.INFO,
    format='{"time": "%(asctime)s", "level": "%(levelname)s", "message": "%(message)s"}'
)

@shared_task(bind=True, max_retries=3)
def send_task_notification(self, task_name, time_str, user_email=None, whatsapp_number=None):
    try:
        # Validate inputs
        task_name = clean(task_name, tags=[], strip=True)[:100]
        if not task_name:
            raise ValidationError("Task name cannot be empty")
        if not re.match(r'^\d{2}:\d{2}$', time_str):
            raise ValidationError("Invalid time format. Use HH:MM, e.g., 14:30")

        # Parse target time
        now = datetime.now(pytz.timezone('Asia/Karachi'))
        target_time = datetime.strptime(time_str, "%H:%M").replace(
            year=now.year, month=now.month, day=now.day, tzinfo=pytz.timezone('Asia/Karachi')
        )
        if target_time < now:
            target_time = target_time.replace(day=now.day + 1)

        # Calculate delay
        delay = (target_time - now).total_seconds()
        if delay > 0:
            send_task_notification.apply_async((task_name, time_str, user_email, whatsapp_number), countdown=delay)
            logging.info(f"Scheduled task notification: {task_name} at {time_str} to {user_email or 'no email'}, {whatsapp_number or 'no WhatsApp'}")
            return

        # Prepare notification
        subject = f"JARVIS Task Reminder: {task_name}"
        message = f"Reminder: Your task '{task_name}' is due now at {time_str} PKT."
        html_message = f"""
        <html>
            <body style="font-family: Arial, sans-serif; padding: 20px;">
                <h2>Reminder: {task_name}</h2>
                <p>This is a reminder for your task: <strong>{task_name}</strong></p>
                <p>Scheduled at: <strong>{time_str} PKT</strong></p>
                <p>Best regards,<br>JARVIS Assistant</p>
            </body>
        </html>
        """
        results = []

        # Send email
        if user_email:
            send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                [user_email],
                html_message=html_message,
                fail_silently=False
            )
            results.append(f"Email sent to {user_email}")

        # Send WhatsApp message
        if whatsapp_number:
            client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
            message = clean(message, tags=[], strip=True)[:1000]
            client.messages.create(
                body=message,
                from_=settings.TWILIO_WHATSAPP_NUMBER,
                to=f'whatsapp:{whatsapp_number}'
            )
            results.append(f"WhatsApp message sent to {whatsapp_number}")

        logging.info(f"Task notification sent: {task_name} at {time_str} to {user_email or 'no email'}, {whatsapp_number or 'no WhatsApp'}")
        return "; ".join(results) or "No notifications sent."
    except ValidationError as e:
        logging.error(f"Task notification validation error: {e}")
        raise self.retry(countdown=60, exc=e)
    except TwilioRestException as e:
        logging.error(f"Twilio error for task notification: {e}")
        raise self.retry(countdown=60, exc=e)
    except Exception as e:
        logging.error(f"Failed to send task notification: {e}")
        raise self.retry(countdown=60, exc=e)