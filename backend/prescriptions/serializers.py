from rest_framework import serializers
from prescriptions import catalog
from prescriptions.models import DemoPrescription


class StrictInput(serializers.Serializer):
    def to_internal_value(self, data):
        if not isinstance(data, dict) or set(data) - set(self.fields):
            raise serializers.ValidationError({"fields": "Запрос содержит недопустимые поля."})
        return super().to_internal_value(data)


class ProposalInput(StrictInput):
    drug_id = serializers.ChoiceField(choices=list(catalog.DRUGS))
    note = serializers.CharField(max_length=1000, required=False, default="", allow_blank=True, trim_whitespace=True)


class ConfirmationInput(StrictInput):
    proposal_token = serializers.CharField(max_length=20000, trim_whitespace=False)
    confirmed = serializers.BooleanField()

    def validate_confirmed(self, value):
        if self.initial_data.get("confirmed") is not True:
            raise serializers.ValidationError("Нужно явное подтверждение врача.")
        return value


class PrescriptionOutput(serializers.ModelSerializer):
    doctor_name = serializers.CharField(source="doctor.display_name")

    class Meta:
        model = DemoPrescription
        fields = ["id", "patient_id", "doctor_id", "doctor_name", "drug_id", "drug_name", "catalog_version", "note", "confirmed_at", "synthetic"]
