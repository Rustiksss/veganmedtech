from rest_framework.response import Response
from rest_framework.views import APIView
from care.models import CareRelationship

class MeView(APIView):
    def get(self, request):
        u = request.user
        link = CareRelationship.objects.filter(patient=u, active=True, doctor__doctor_approved=True, doctor__is_active=True).select_related("doctor").first() if u.role == "patient" else None
        return Response({"id": u.pk, "name": u.display_name, "role": u.role,
            "doctor_approved": u.doctor_approved,
            "leading_doctor": {"id": link.doctor_id, "name": link.doctor.display_name} if link else None})
