from django.conf import settings
from django.db import models

class CareRelationship(models.Model):
    patient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="care_links")
    doctor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="patient_links")
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["patient"], condition=models.Q(active=True), name="one_active_leading_doctor"),
            models.CheckConstraint(condition=~models.Q(patient=models.F("doctor")), name="different_care_participants")]
