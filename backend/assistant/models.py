from django.conf import settings
from django.db import models


class AssistantTurn(models.Model):
    patient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    idempotency_key = models.CharField(max_length=100)
    text = models.TextField(max_length=2000)
    reply = models.TextField(blank=True, max_length=4096)
    status = models.CharField(max_length=16, default="pending", choices=[
        ("pending", "Выполняется"), ("completed", "Ответ получен"),
        ("failed", "Ошибка"), ("interrupted", "Вызов прерван")])
    error_code = models.CharField(max_length=30, blank=True)
    model = models.CharField(max_length=200)
    prompt_version = models.CharField(max_length=50)
    alerting_mode = models.CharField(max_length=8, default="off", db_default="off", choices=[("off", "Выключен"), ("demo", "Демонстрация")])
    analysis_status = models.CharField(max_length=16, default="not_evaluated", db_default="not_evaluated", choices=[
        ("not_evaluated", "Не выполнялся"), ("matched", "Возможный сигнал"),
        ("no_match", "Совпадений нет"), ("uncertain", "Неоднозначно"), ("failed", "Проверка не выполнена")])
    policy_version = models.CharField(max_length=50, blank=True, db_default="")
    analysis = models.JSONField(default=list, db_default=[])
    usage = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True)

    class Meta:
        ordering = ["-id"]
        constraints = [
            models.UniqueConstraint(fields=["patient", "idempotency_key"], name="assistant_patient_key"),
            models.UniqueConstraint(fields=["patient"], condition=models.Q(status="pending"), name="assistant_one_pending"),
            models.CheckConstraint(condition=models.Q(status__in=["pending", "completed", "failed", "interrupted"]), name="assistant_valid_status"),
            models.CheckConstraint(condition=models.Q(alerting_mode__in=["off", "demo"]), name="assistant_valid_alert_mode"),
            models.CheckConstraint(condition=models.Q(analysis_status__in=["not_evaluated", "matched", "no_match", "uncertain", "failed"]), name="assistant_valid_analysis"),
        ]


class AssistantAttempt(models.Model):
    patient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["patient", "created_at"])]


class AssistantNotification(models.Model):
    turn = models.OneToOneField(AssistantTurn, on_delete=models.PROTECT)
    synthetic = models.BooleanField(default=True)
    policy_version = models.CharField(max_length=50, default="synthetic-delivery-v1")
    created_at = models.DateTimeField(auto_now_add=True)
    seen_at = models.DateTimeField(null=True)
    seen_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True)

    class Meta:
        ordering = ["-id"]
        constraints = [models.CheckConstraint(condition=models.Q(synthetic=True), name="assistant_synthetic_only")]
