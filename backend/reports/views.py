import re
from django.core import signing
from django.db import IntegrityError, transaction
from django.db.models import Q
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from accounts.permissions import DoctorOnly, PatientOnly
from accounts.models import User
from audit.events import record
from care.models import CareRelationship
from config.errors import Conflict
from reports.models import SelfReport
from reports.serializers import ReportInput, ReportOutput

class AuditedView(APIView):
    def permission_denied(self, request, message=None, code=None):
        record(request.user, "access.denied", outcome="denied")
        super().permission_denied(request, message, code)


def doctor_patient(request, patient_id):
    link = CareRelationship.objects.filter(doctor=request.user, patient_id=patient_id, active=True, patient__is_active=True).first()
    if not link:
        record(request.user, "report.read", outcome="denied")
        raise NotFound()
    return link.patient_id


def history(request, patient_id):
    try:
        limit = int(request.query_params.get("limit", "30"))
        if not 1 <= limit <= 100:
            raise ValueError()
    except (ValueError, TypeError):
        raise ValidationError({"limit": "Допустимо от 1 до 100."})
    qs = SelfReport.objects.filter(patient_id=patient_id)
    token = request.query_params.get("cursor")
    if token:
        try:
            marker = signing.loads(token, salt="report-history", max_age=86400)
            if marker["patient"] != patient_id:
                raise ValueError()
            qs = qs.filter(Q(observed_at__lt=marker["time"]) | Q(observed_at=marker["time"], id__lt=marker["id"]))
        except (signing.BadSignature, ValueError, KeyError, TypeError):
            raise ValidationError({"cursor": "Курсор недействителен. Обновите историю."})
    items = list(qs[:limit + 1])
    next_cursor = None
    if len(items) > limit:
        last = items[limit - 1]
        next_cursor = signing.dumps({"patient": patient_id, "time": last.observed_at.isoformat(), "id": last.pk}, salt="report-history")
    record(request.user, "report.list", patient_id)
    return Response({"results": ReportOutput(items[:limit], many=True).data, "next_cursor": next_cursor})

class OwnReports(AuditedView):
    permission_classes = [PatientOnly]
    def get(self, request):
        return history(request, request.user.pk)
    def post(self, request):
        data = ReportInput(data=request.data)
        data.is_valid(raise_exception=True)
        key = request.headers.get("Idempotency-Key", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", key):
            raise ValidationError({"idempotency_key": "Передайте допустимый ключ отправки."})
        values = data.validated_data
        try:
            with transaction.atomic():
                obj = SelfReport.objects.create(patient=request.user, idempotency_key=key, **values)
                record(request.user, "report.create", obj.pk)
            created = True
        except IntegrityError:
            obj = SelfReport.objects.filter(patient=request.user, idempotency_key=key).first()
            if obj is None:
                raise
            if obj.text != values["text"] or obj.observed_at != values["observed_at"]:
                raise Conflict()
            created = False
        return Response(ReportOutput(obj).data, status=201 if created else 200)

class PatientList(AuditedView):
    permission_classes = [DoctorOnly]
    def get(self, request):
        users = User.objects.filter(care_links__doctor=request.user, care_links__active=True, role="patient", is_active=True).order_by("id")
        record(request.user, "patient.list")
        return Response({"results": [{"id": u.pk, "name": u.display_name} for u in users]})

class PatientReports(AuditedView):
    permission_classes = [DoctorOnly]
    def get(self, request, patient_id):
        return history(request, doctor_patient(request, patient_id))

class ReportDetail(AuditedView):
    permission_classes = [DoctorOnly]
    def get(self, request, patient_id, report_id):
        doctor_patient(request, patient_id)
        obj = SelfReport.objects.filter(pk=report_id, patient_id=patient_id).first()
        if obj is None:
            record(request.user, "report.read", outcome="denied")
            raise NotFound()
        record(request.user, "report.read", obj.pk)
        return Response(ReportOutput(obj).data)
