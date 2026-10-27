from django.conf import settings
from django.db import models

class AuditEvent(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True)
    subject = models.CharField(max_length=50, blank=True)
    action = models.CharField(max_length=50)
    object_id = models.CharField(max_length=100, blank=True)
    outcome = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ["id"]
