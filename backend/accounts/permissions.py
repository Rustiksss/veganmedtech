from allauth.account.models import EmailAddress
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import BasePermission

class BrowserSessionAuthentication(SessionAuthentication):
    def authenticate_header(self, request):
        return "Session"

class VerifiedUser(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        return bool(user.is_authenticated and user.is_active and EmailAddress.objects.filter(user=user, verified=True, email__iexact=user.email).exists())

class PatientOnly(VerifiedUser):
    def has_permission(self, request, view):
        return super().has_permission(request, view) and request.user.role == "patient"

class DoctorOnly(VerifiedUser):
    def has_permission(self, request, view):
        return super().has_permission(request, view) and request.user.role == "doctor" and request.user.doctor_approved
