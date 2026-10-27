from allauth.account.models import EmailAddress
from django.test import Client
from accounts.models import User
from care.models import CareRelationship

PASSWORD = "Synthetic-test-passphrase!42"

def user(email, role="patient", approved=False, verified=True):
    u = User.objects.create_user(email, PASSWORD, display_name="Вымышленный пользователь", role=role, doctor_approved=approved)
    EmailAddress.objects.create(user=u, email=u.email, primary=True, verified=verified)
    return u

def client_for(u):
    c = Client()
    c.force_login(u, backend="django.contrib.auth.backends.ModelBackend")
    return c

def fixtures():
    a = user("patient-a@example.test")
    b = user("patient-b@example.test")
    da = user("doctor-a@example.test", "doctor", True)
    db = user("doctor-b@example.test", "doctor", True)
    CareRelationship.objects.create(patient=a, doctor=da)
    CareRelationship.objects.create(patient=b, doctor=db)
    return a,b,da,db
