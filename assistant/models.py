from django.db import models
from django.contrib.auth.models import User
import pytz

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    preferred_language = models.CharField(max_length=5, default='en-US', choices=[('en-US', 'English'), ('es-ES', 'Spanish')])
    timezone = models.CharField(max_length=50, default='Asia/Karachi', choices=[(tz, tz) for tz in pytz.all_timezones])
    whatsapp_number = models.CharField(max_length=20, blank=True, unique=True, help_text="Phone number in E.164 format, e.g., +1234567890")
    favorite_commands = models.JSONField(default=list, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['whatsapp_number']),
        ]

    def __str__(self):
        return f"{self.user.username}'s Profile"

class Task(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    task_name = models.CharField(max_length=100)
    due_time = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    completed = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=['user', 'due_time']),
        ]
        ordering = ['due_time']

    def __str__(self):
        return f"{self.task_name} (Due: {self.due_time})"

class CommandHistory(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    command = models.CharField(max_length=200)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['user', 'timestamp']),
        ]

    def __str__(self):
        return f"{self.user.username}: {self.command} at {self.timestamp}"