from django.test import TestCase,override_settings
from accounts.tests.helpers import fixtures,client_for
from audit.models import AuditEvent

@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],ACCOUNT_RATE_LIMITS=False)
class AuditTests(TestCase):
    def test_audit_without_sensitive_text_and_private_cache(self):
        a,b,da,db=fixtures();c=client_for(a);doctor=client_for(da)
        marker="SYNTHETIC_PRIVATE_MARKER_0008"
        data={"observed_at":"2026-10-20T11:00:00Z","text":marker}
        response=c.post("/api/me/self-reports",data,content_type="application/json",HTTP_IDEMPOTENCY_KEY="audit")
        self.assertEqual(response.status_code,201)
        doctor.get(f"/api/patients/{a.pk}/self-reports")
        doctor.get(f"/api/patients/{b.pk}/self-reports")
        for event in AuditEvent.objects.values():
            self.assertNotIn(marker,str(event));self.assertTrue(event["created_at"])
        self.assertTrue(AuditEvent.objects.filter(action="report.create",outcome="success").exists())
        self.assertTrue(AuditEvent.objects.filter(action="report.read",outcome="denied").exists())
        for path in ["/api/me","/api/me/self-reports","/api/audit"]:
            self.assertEqual(c.get(path)["Cache-Control"],"no-store")
        self.assertEqual(c.get("/api/audit").status_code,404)
