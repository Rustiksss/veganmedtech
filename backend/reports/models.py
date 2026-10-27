from django.conf import settings
from django.db import models
from django.db.models.functions import Length

class SelfReport(models.Model):
    patient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="self_reports")
    observed_at = models.DateTimeField()
    text = models.CharField(max_length=2000)
    created_at = models.DateTimeField(auto_now_add=True)
    idempotency_key = models.CharField(max_length=100)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["patient", "idempotency_key"], name="report_patient_key_unique")]
        indexes = [models.Index(fields=["patient", "-observed_at", "-id"], name="report_history_order")]
        ordering = ["-observed_at", "-id"]
