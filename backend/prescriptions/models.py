from django.conf import settings
from django.db import models


class DemoPrescription(models.Model):
    confirmation_id = models.UUIDField(unique=True)
    patient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="demo_prescriptions")
    doctor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="confirmed_demo_prescriptions")
    drug_id = models.CharField(max_length=40)
    drug_name = models.CharField(max_length=100)
    catalog_version = models.CharField(max_length=60)
    note = models.CharField(max_length=1000, blank=True)
    confirmed_at = models.DateTimeField(auto_now_add=True)
    synthetic = models.BooleanField(default=True)

    class Meta:
        ordering = ["-confirmed_at", "-id"]
        constraints = [models.CheckConstraint(condition=models.Q(synthetic=True), name="prescription_demo_only")]
        indexes = [models.Index(fields=["patient", "-confirmed_at", "-id"], name="prescription_patient_history")]
