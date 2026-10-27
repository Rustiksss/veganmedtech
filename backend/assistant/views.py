import re
from django.core import signing
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from accounts.models import User
from accounts.permissions import PatientOnly, DoctorOnly
from audit.events import record
from care.models import CareRelationship
from reports.views import AuditedView
from assistant.models import AssistantTurn, AssistantNotification
from assistant.services import send, expire_pending
from assistant.alerting import mode_output

ERRORS = {
    "configuration": "ИИ-ассистент пока не настроен. Обратитесь к организатору.",
    "credentials": "Подключение ИИ временно недоступно. Обратитесь к организатору.",
    "balance": "ИИ временно недоступен. Организатору нужно проверить баланс сервиса.",
    "rate_limit": "Сервис ИИ занят. Повторите попытку позднее.",
    "timeout": "Ответ не получен вовремя. Проверьте историю перед повтором.",
    "interrupted": "Отправка прервалась. Можно явно повторить попытку.",
    "incomplete": "Полный ответ не получен. Можно повторить попытку.",
    "invalid_response": "Не удалось получить ответ ИИ. Можно повторить попытку.",
    "unavailable": "Сервис ИИ недоступен. Попробуйте позднее.",
}


class MessageInput(serializers.Serializer):
    text = serializers.CharField(min_length=1, max_length=2000, trim_whitespace=True)

    def to_internal_value(self, data):
        if not isinstance(data, dict) or set(data) - {"text"}:
            raise serializers.ValidationError({"fields": "Недопустимые поля."})
        return super().to_internal_value(data)


def output(turn):
    notification = AssistantNotification.objects.filter(turn_id=turn.pk).exists()
    doctor_available = CareRelationship.objects.filter(patient_id=turn.patient_id, active=True,
        doctor__is_active=True, doctor__role="doctor", doctor__doctor_approved=True,
        doctor__emailaddress__verified=True, doctor__emailaddress__email__iexact=F("doctor__email")).exists() if notification else False
    return {"id": turn.pk, "text": turn.text, "reply": turn.reply, "status": turn.status,
        "error": ERRORS.get(turn.error_code, ""), "created_at": turn.created_at,
        "finished_at": turn.finished_at, "analysis_status": turn.analysis_status,
        "analysis": turn.analysis, "policy_version": turn.policy_version, "turn_alerting_mode": turn.alerting_mode,
        "notification_status": "available" if doctor_available else "no_doctor" if notification else "none",
        **mode_output()}


def page(request, qs, scope, serialize):
    try:
        limit = int(request.query_params.get("limit", "30"))
        if not 1 <= limit <= 100:
            raise ValueError()
        cursor = request.query_params.get("cursor")
        if cursor:
            marker = signing.loads(cursor, salt="assistant-page", max_age=86400)
            if marker["scope"] != scope:
                raise ValueError()
            qs = qs.filter(id__lt=int(marker["id"]))
    except (ValueError, TypeError, KeyError, signing.BadSignature):
        raise ValidationError({"cursor": "Обновите список. Лимит — от 1 до 100."})
    items = list(qs.order_by("-id")[:limit+1])
    return Response({"results": [serialize(item) for item in items[:limit]],
        "next_cursor": signing.dumps({"scope": scope, "id": items[limit-1].pk}, salt="assistant-page")
        if len(items) > limit else None, **mode_output()})


class Messages(AuditedView):
    permission_classes = [PatientOnly]

    def get(self, request):
        with transaction.atomic():
            User.objects.select_for_update().get(pk=request.user.pk)
            expire_pending(request.user.pk)
            record(request.user, "assistant.list")
            return page(request, AssistantTurn.objects.filter(patient=request.user), f"chat:{request.user.pk}", output)

    def post(self, request):
        data = MessageInput(data=request.data)
        data.is_valid(raise_exception=True)
        key = request.headers.get("Idempotency-Key", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", key):
            raise ValidationError({"idempotency_key": "Нужен допустимый ключ отправки."})
        turn, created = send(request.user, key, data.validated_data["text"])
        with transaction.atomic():
            User.objects.select_for_update().get(pk=request.user.pk)
            request.user.refresh_from_db()
            self.check_permissions(request)
            return Response(output(turn), status=202 if turn.status == "pending" else 201 if created else 200)


class MessageDetail(AuditedView):
    permission_classes = [PatientOnly]

    def get(self, request, turn_id):
        with transaction.atomic():
            User.objects.select_for_update().get(pk=request.user.pk)
            expire_pending(request.user.pk)
            turn = AssistantTurn.objects.filter(pk=turn_id, patient=request.user).first()
            if not turn:
                raise NotFound()
            record(request.user, "assistant.read", turn.pk)
            return Response(output(turn))


def notification_output(obj, doctor):
    seen = obj.seen_by_id == doctor.pk
    return {"id": obj.pk, "patient_id": obj.turn.patient_id,
        "patient_name": obj.turn.patient.display_name, "text": obj.turn.text,
        "created_at": obj.created_at, "synthetic": True,
        "policy_version": obj.policy_version, "seen_at": obj.seen_at if seen else None,
        "analysis_status": obj.turn.analysis_status, "analysis": obj.turn.analysis}


def visible(doctor):
    patients = CareRelationship.objects.filter(doctor=doctor, active=True,
        patient__is_active=True, patient__role="patient").values("patient_id")
    return AssistantNotification.objects.filter(turn__patient_id__in=patients).select_related("turn__patient")


class Notifications(AuditedView):
    permission_classes = [DoctorOnly]

    def get(self, request):
        # Same lock as operator's relationship update, held through data/audit serialization.
        with transaction.atomic():
            ids = list(CareRelationship.objects.filter(doctor=request.user, active=True).values_list("patient_id", flat=True))
            list(User.objects.select_for_update().filter(pk__in=ids).order_by("pk"))
            request.user.refresh_from_db()
            self.check_permissions(request)
            record(request.user, "assistant.alert_list")
            return page(request, visible(request.user), f"alerts:{request.user.pk}", lambda x: notification_output(x, request.user))


class NotificationDetail(AuditedView):
    permission_classes = [DoctorOnly]

    def action(self, request, notification_id, mark=False):
        with transaction.atomic():
            patient_id = AssistantNotification.objects.filter(pk=notification_id).values_list("turn__patient_id", flat=True).first()
            if patient_id is None:
                raise NotFound()
            User.objects.select_for_update().get(pk=patient_id)
            request.user.refresh_from_db()
            self.check_permissions(request)
            obj = visible(request.user).filter(pk=notification_id).first()
            if obj is None:
                raise NotFound()
            if mark and obj.seen_by_id != request.user.pk:
                obj.seen_by = request.user
                obj.seen_at = timezone.now()
                obj.save(update_fields=["seen_by", "seen_at"])
            record(request.user, "assistant.alert_seen" if mark else "assistant.alert_read", obj.pk)
            return Response(notification_output(obj, request.user))

    def get(self, request, notification_id):
        try:
            return self.action(request, notification_id)
        except NotFound:
            record(request.user, "assistant.alert_read", outcome="denied")
            raise

    def post(self, request, notification_id):
        if request.data:
            raise ValidationError({"fields": "Тело должно быть пустым."})
        try:
            return self.action(request, notification_id, True)
        except NotFound:
            record(request.user, "assistant.alert_seen", outcome="denied")
            raise
