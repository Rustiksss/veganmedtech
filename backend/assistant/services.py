from datetime import timedelta
from django.conf import settings
from django.db import transaction
from django.db.models import Case, When, Value, F
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, Throttled
from accounts.models import User
from allauth.account.models import EmailAddress
from audit.events import record
from config.errors import Conflict
from assistant.models import AssistantTurn, AssistantAttempt, AssistantNotification
from assistant.prompts import PROMPT_VERSION, messages_for
from assistant.client import complete, ProviderError
from assistant.alerting import POLICY_VERSION, parse_analysis

AUTOMATIC_DETECTION_ENABLED = False  # Template edits never activate a clinical rule.
PENDING_SECONDS = 25


def expire_pending(patient_id):
    AssistantTurn.objects.filter(patient_id=patient_id, status="pending",
        created_at__lt=timezone.now() - timedelta(seconds=PENDING_SECONDS)).update(
        status="interrupted", error_code="interrupted", finished_at=timezone.now(),
        analysis_status=Case(When(alerting_mode="demo", then=Value("failed")), default=F("analysis_status")))


def send(patient, key, text):
    with transaction.atomic():
        current = User.objects.select_for_update().get(pk=patient.pk)
        if not current.is_active or current.role != "patient" or not EmailAddress.objects.filter(
                user=current, email__iexact=current.email, verified=True).exists():
            raise PermissionDenied()
        expire_pending(patient.pk)
        existing = AssistantTurn.objects.filter(patient=patient, idempotency_key=key).first()
        if existing:
            if existing.text != text:
                raise Conflict()
            return existing, False
        now = timezone.now()
        attempts = AssistantAttempt.objects.filter(patient=patient)
        if attempts.filter(created_at__gt=now-timedelta(seconds=60)).count() >= 6 or attempts.filter(
                created_at__gt=now-timedelta(days=1)).count() >= 100:
            raise Throttled()
        if AssistantTurn.objects.filter(patient=patient, status="pending").exists():
            raise Throttled(detail="Дождитесь текущего ответа.")
        turn = AssistantTurn.objects.create(patient=patient, idempotency_key=key, text=text,
            model=settings.POLZA_MODEL, prompt_version=PROMPT_VERSION,
            alerting_mode=settings.ASSISTANT_ALERTING_MODE,
            policy_version=POLICY_VERSION if settings.ASSISTANT_ALERTING_MODE == "demo" else "")
        AssistantAttempt.objects.create(patient=patient)
        record(patient, "assistant.send", turn.pk)
    history = list(AssistantTurn.objects.filter(patient=patient, status="completed", id__lt=turn.pk)[:10])
    try:
        reply, usage = complete(messages_for(turn, history))
        values = {"status": "completed", "reply": reply, "usage": usage}
        if turn.alerting_mode == "demo":
            reply, status, signals = parse_analysis(reply, turn.text)
            values.update(reply=reply, analysis_status=status, analysis=signals)
    except ProviderError as exc:
        values = {"status": "failed", "error_code": exc.code}
        if turn.alerting_mode == "demo":
            values["analysis_status"] = "failed"
    with transaction.atomic():
        User.objects.select_for_update().get(pk=patient.pk)
        changed = AssistantTurn.objects.filter(pk=turn.pk, status="pending").update(**values, finished_at=timezone.now())
        if changed:
            if values.get("analysis_status") in {"matched", "uncertain"}:
                notification, created = AssistantNotification.objects.get_or_create(
                    turn=turn, defaults={"policy_version": turn.policy_version})
                if created:
                    record(None, "assistant.demo_signal", notification.pk, subject="service:demo")
            record(patient, "assistant.finish", turn.pk, outcome=values["status"])
    turn.refresh_from_db()
    return turn, True


def create_synthetic_notification(turn_id):
    """Internal delivery fixture only. Never called by messages API or the model."""
    with transaction.atomic():
        turn = AssistantTurn.objects.get(pk=turn_id)
        User.objects.select_for_update().get(pk=turn.patient_id)
        obj, created = AssistantNotification.objects.get_or_create(turn=turn)
        if created:
            record(None, "assistant.demo_event", obj.pk, subject="service:synthetic")
        return obj
