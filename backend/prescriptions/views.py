import uuid
from django.core import signing
from django.db import transaction
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from accounts.models import User
from accounts.permissions import DoctorOnly, PatientOnly
from audit.events import record
from care.models import CareRelationship
from reports.views import AuditedView
from prescriptions import catalog
from prescriptions.models import DemoPrescription
from prescriptions.serializers import ProposalInput, ConfirmationInput, PrescriptionOutput

SALT = "demo-prescription-proposal-v1"
MAX_AGE = 30 * 60


def check_patient(request, patient_id):
    if not CareRelationship.objects.filter(doctor=request.user, patient_id=patient_id, active=True,
            patient__is_active=True, patient__role="patient").exists():
        record(request.user, "prescription.access", outcome="denied")
        raise NotFound()


def history(request, patient_id):
    items = DemoPrescription.objects.filter(patient_id=patient_id).select_related("doctor")
    record(request.user, "prescription.list", patient_id)
    return Response({"results": PrescriptionOutput(items, many=True).data, "synthetic": True})


class Catalog(AuditedView):
    permission_classes = [DoctorOnly]

    def get(self, request):
        return Response({"version": catalog.VERSION, "synthetic": True,
            "results": [{"id": key, "name": name} for key, name in catalog.DRUGS.items()]})


class Preview(AuditedView):
    permission_classes = [DoctorOnly]

    def post(self, request, patient_id):
        check_patient(request, patient_id)
        data = ProposalInput(data=request.data)
        data.is_valid(raise_exception=True)
        proposal = {"version": catalog.VERSION, "doctor": request.user.pk, "patient": patient_id,
            "confirmation_id": str(uuid.uuid4()), **data.validated_data}
        record(request.user, "prescription.preview", patient_id)
        return Response({"proposal_token": signing.dumps(proposal, salt=SALT), "patient_id": patient_id,
            "drug_name": catalog.DRUGS[proposal["drug_id"]], "note": proposal["note"],
            "catalog_version": catalog.VERSION, "synthetic": True})


class PatientPrescriptions(AuditedView):
    permission_classes = [DoctorOnly]

    def get(self, request, patient_id):
        check_patient(request, patient_id)
        return history(request, patient_id)

    def post(self, request, patient_id):
        check_patient(request, patient_id)
        data = ConfirmationInput(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            proposal = signing.loads(data.validated_data["proposal_token"], salt=SALT, max_age=MAX_AGE)
            if proposal["doctor"] != request.user.pk or proposal["patient"] != patient_id or proposal["version"] != catalog.VERSION:
                raise ValueError()
            confirmation_id = uuid.UUID(proposal["confirmation_id"])
            values = ProposalInput(data={"drug_id": proposal["drug_id"], "note": proposal["note"]})
            values.is_valid(raise_exception=True)
        except (signing.BadSignature, ValueError, KeyError, TypeError):
            raise ValidationError({"proposal_token": "Предложение недействительно или устарело. Подготовьте его заново."})
        with transaction.atomic():
            # Same lock as care_relationship: assignment cannot race this confirmation.
            User.objects.select_for_update().get(pk=patient_id)
            check_patient(request, patient_id)
            obj = DemoPrescription.objects.filter(confirmation_id=confirmation_id).first()
            created = obj is None
            if created:
                obj = DemoPrescription.objects.create(confirmation_id=confirmation_id, patient_id=patient_id,
                    doctor=request.user, drug_name=catalog.DRUGS[values.validated_data["drug_id"]],
                    catalog_version=catalog.VERSION, **values.validated_data)
                record(request.user, "prescription.create", obj.pk)
        return Response(PrescriptionOutput(obj).data, status=201 if created else 200)


class OwnPrescriptions(AuditedView):
    permission_classes = [PatientOnly]

    def get(self, request):
        return history(request, request.user.pk)
