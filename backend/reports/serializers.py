from rest_framework import serializers
from reports.models import SelfReport

class ReportInput(serializers.Serializer):
    observed_at = serializers.DateTimeField()
    text = serializers.CharField(min_length=1, max_length=2000, trim_whitespace=True)
    def to_internal_value(self, data):
        extra = set(data) - set(self.fields)
        if extra:
            raise serializers.ValidationError({"fields": "Запрос содержит недопустимые поля."})
        return super().to_internal_value(data)

class ReportOutput(serializers.ModelSerializer):
    author_id = serializers.IntegerField(source="patient_id")
    class Meta:
        model = SelfReport
        fields = ["id", "author_id", "observed_at", "text", "created_at"]
