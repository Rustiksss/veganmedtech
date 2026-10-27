from io import StringIO
from django.core.management import call_command, CommandError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from accounts.models import User
from accounts.tests.helpers import fixtures, client_for, user, PASSWORD
from audit.models import AuditEvent
from care.models import CareRelationship
from reports.models import SelfReport
from django.utils import timezone

@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],ACCOUNT_RATE_LIMITS=False)
class AccessTests(TestCase):
    def setUp(self):
        self.a,self.b,self.da,self.db=fixtures()
        self.ca,self.cb,self.cda,self.cdb=map(client_for,(self.a,self.b,self.da,self.db))
        self.report=SelfReport.objects.create(patient=self.b,observed_at=timezone.now(),text="Вымышленная запись",idempotency_key="b")
    def test_anonymous_and_roles(self):
        self.assertEqual(self.client.get("/api/me").status_code,401)
        self.assertEqual(self.ca.get("/api/patients").status_code,403)
        self.assertEqual(self.cda.post("/api/me/self-reports",{},content_type="application/json").status_code,403)
        self.assertEqual(self.cda.get("/api/patients").json()["results"][0]["id"],self.a.pk)
    def test_foreign_and_missing_patient_indistinguishable(self):
        paths=[f"/api/patients/{self.b.pk}/self-reports", "/api/patients/999999/self-reports"]
        responses=[self.cda.get(p) for p in paths]
        self.assertEqual([r.status_code for r in responses],[404,404])
        self.assertEqual(responses[0].json(),responses[1].json())
        self.assertEqual(self.ca.get(paths[0]).status_code,403)
    def test_nested_report_parent_mismatch(self):
        response=self.cda.get(f"/api/patients/{self.a.pk}/self-reports/{self.report.pk}")
        self.assertEqual(response.status_code,404)
        self.assertEqual(self.cdb.get(f"/api/patients/{self.b.pk}/self-reports/{self.report.pk}").status_code,200)
    def test_revoke_relationship_old_session(self):
        call_command("care_relationship","revoke",self.a.email,stdout=StringIO())
        self.assertEqual(self.cda.get(f"/api/patients/{self.a.pk}/self-reports").status_code,404)
        self.assertEqual(self.ca.get("/api/me/self-reports").status_code,200)
        self.assertTrue(AuditEvent.objects.filter(action="care.revoke",subject="service:operator").exists())
    def test_pending_doctor_and_approval_revoke(self):
        pending=user("pending@example.test","doctor")
        c=client_for(pending)
        self.assertEqual(c.get("/api/me").status_code,200)
        self.assertEqual(c.get("/api/patients").status_code,403)
        call_command("doctor_access","approve",pending.email,stdout=StringIO())
        self.assertEqual(c.get("/api/patients").status_code,200)
        count=AuditEvent.objects.filter(action="doctor.approve").count()
        call_command("doctor_access","approve",pending.email,stdout=StringIO())
        self.assertEqual(AuditEvent.objects.filter(action="doctor.approve").count(),count)
        call_command("doctor_access","revoke",pending.email,stdout=StringIO())
        self.assertEqual(c.get("/api/patients").status_code,403)
    def test_disabled_user_old_session(self):
        User.objects.filter(pk=self.da.pk).update(is_active=False)
        self.assertEqual(self.cda.get("/api/patients").status_code,401)
    def test_invalid_operator_requests_and_single_link(self):
        for args in [("doctor_access","approve",self.a.email),("care_relationship","assign",self.da.email,self.db.email),("care_relationship","assign",self.a.email,self.b.email)]:
            with self.assertRaises(CommandError):call_command(*args,stdout=StringIO())
        with self.assertRaises(IntegrityError), transaction.atomic():
            CareRelationship.objects.create(patient=self.a,doctor=self.db)
        call_command("care_relationship","assign",self.a.email,self.db.email,stdout=StringIO())
        self.assertEqual(CareRelationship.objects.filter(patient=self.a,active=True).count(),1)
        self.assertEqual(self.cda.get(f"/api/patients/{self.a.pk}/self-reports").status_code,404)
        self.assertEqual(self.cdb.get(f"/api/patients/{self.a.pk}/self-reports").status_code,200)
    def test_seed_is_opt_in_and_does_not_overwrite(self):
        from unittest.mock import patch
        with patch.dict("os.environ",{"DEMO_PASSWORD":PASSWORD}),override_settings(DEV=True):
            self.a.display_name="Существующее имя";self.a.save()
            call_command("seed_demo",stdout=StringIO());call_command("seed_demo",stdout=StringIO())
        self.a.refresh_from_db();self.assertEqual(self.a.display_name,"Существующее имя")
        self.assertEqual(User.objects.count(),4)
