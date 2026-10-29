from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from django.core import signing
from django.db import close_old_connections
from django.test import Client, TestCase, TransactionTestCase, override_settings
from allauth.account.models import EmailAddress
from accounts.tests.helpers import fixtures, client_for, user
from audit.models import AuditEvent
from care.models import CareRelationship
from prescriptions import catalog
from prescriptions.models import DemoPrescription
from prescriptions.views import SALT

FAST = {"PASSWORD_HASHERS": ["django.contrib.auth.hashers.MD5PasswordHasher"], "ACCOUNT_RATE_LIMITS": False}


@override_settings(**FAST)
class PrescriptionTests(TestCase):
    def setUp(self):
        self.a, self.b, self.da, self.db = fixtures()
        self.c = client_for(self.a)
        self.d = client_for(self.da)
        self.path = f"/api/patients/{self.a.pk}/prescriptions"

    def preview(self, body=None, client=None, path=None):
        return (client or self.d).post((path or self.path) + "/preview", body or {"drug_id": "aviandr", "note": "Вымышленный комментарий"}, content_type="application/json")

    def confirm(self, token, client=None, path=None, **extra):
        return (client or self.d).post(path or self.path, {"proposal_token": token, "confirmed": True, **extra}, content_type="application/json")

    def test_catalog_and_each_drug_persisted(self):
        response = self.d.get("/api/prescriptions/catalog")
        self.assertEqual(response.status_code, 200)
        drugs = response.json()["results"]
        self.assertEqual(len(drugs), 11)
        self.assertEqual(drugs[0], {"id": "aviandr", "name": "Авиандр"})
        for drug in drugs:
            preview = self.preview({"drug_id": drug["id"]}).json()
            count = DemoPrescription.objects.count()
            result = self.confirm(preview["proposal_token"])
            self.assertEqual(result.status_code, 201, result.content)
            self.assertEqual(DemoPrescription.objects.count(), count + 1)
            self.assertEqual(result.json()["drug_name"], drug["name"])
            self.assertTrue(result.json()["synthetic"])
            self.assertEqual(result.json()["catalog_version"], catalog.VERSION)

    def test_preview_no_write_confirm_repeat_and_new_sessions(self):
        self.assertEqual(self.c.get("/api/me/prescriptions").json()["results"], [])
        preview = self.preview().json()
        self.assertFalse(DemoPrescription.objects.exists())
        first = self.confirm(preview["proposal_token"])
        second = self.confirm(preview["proposal_token"])
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json(), second.json())
        self.assertEqual(DemoPrescription.objects.count(), 1)
        self.assertEqual(AuditEvent.objects.filter(action="prescription.create", actor=self.da).count(), 1)
        self.assertEqual(client_for(self.a).get("/api/me/prescriptions").json()["results"], [first.json()])
        self.assertEqual(client_for(self.da).get(self.path).json()["results"], [first.json()])
        self.assertEqual(client_for(self.b).get("/api/me/prescriptions").json()["results"], [])
        self.assertEqual(first.json()["note"], "Вымышленный комментарий")

    def test_unauthenticated_and_role_boundaries(self):
        token = self.preview().json()["proposal_token"]
        for client, status in [(Client(), 401), (self.c, 403)]:
            for method, path, body in [("get", "/api/prescriptions/catalog", None), ("get", self.path, None),
                    ("post", self.path + "/preview", {"drug_id": "aviandr"}),
                    ("post", self.path, {"proposal_token": token, "confirmed": True})]:
                response = getattr(client, method)(path, body, content_type="application/json") if body else getattr(client, method)(path)
                self.assertEqual(response.status_code, status, response.content)
        self.assertEqual(self.d.get("/api/me/prescriptions").status_code, 403)
        self.assertEqual(self.c.post("/api/me/prescriptions", {"drug_id": "aviandr"}, content_type="application/json").status_code, 405)

    def test_unapproved_unverified_and_disabled_doctor(self):
        for attr in ["doctor_approved", "email_verified", "is_active"]:
            doctor = user(attr + "@example.test", "doctor", True)
            c = client_for(doctor)
            if attr == "email_verified":
                EmailAddress.objects.filter(user=doctor).update(verified=False)
            else:
                setattr(doctor, attr, False); doctor.save()
            self.assertIn(c.get("/api/prescriptions/catalog").status_code, [401, 403])

    def test_foreign_patient_and_other_doctor(self):
        token = self.preview().json()["proposal_token"]
        foreign = f"/api/patients/{self.b.pk}/prescriptions"
        for client, path in [(self.d, foreign), (client_for(self.db), self.path)]:
            self.assertEqual(client.get(path).status_code, 404)
            self.assertEqual(self.preview(client=client, path=path).status_code, 404)
            self.assertEqual(self.confirm(token, client=client, path=path).status_code, 404)
        self.assertFalse(DemoPrescription.objects.exists())

    def test_revocation_after_preview_and_history(self):
        token = self.preview().json()["proposal_token"]
        self.confirm(token)
        next_token = self.preview().json()["proposal_token"]
        CareRelationship.objects.filter(patient=self.a).update(active=False)
        self.assertEqual(self.confirm(next_token).status_code, 404)
        self.assertEqual(self.confirm(token).status_code, 404)
        self.assertEqual(self.d.get(self.path).status_code, 404)
        self.assertEqual(DemoPrescription.objects.count(), 1)
        self.assertEqual(len(self.c.get("/api/me/prescriptions").json()["results"]), 1)

    def test_wrong_patient_or_doctor_bound_to_signed_proposal(self):
        token = self.preview().json()["proposal_token"]
        CareRelationship.objects.filter(patient=self.b).update(active=False)
        CareRelationship.objects.create(patient=self.b, doctor=self.da)
        self.assertEqual(self.confirm(token, path=f"/api/patients/{self.b.pk}/prescriptions").status_code, 400)
        CareRelationship.objects.filter(patient=self.a).update(active=False)
        CareRelationship.objects.create(patient=self.a, doctor=self.db)
        self.assertEqual(self.confirm(token, client=client_for(self.db)).status_code, 400)

    def test_tamper_expiry_and_catalog_version(self):
        token = self.preview().json()["proposal_token"]
        self.assertEqual(self.confirm(token + "x").status_code, 400)
        with patch("django.core.signing.time.time", return_value=1):
            old_token = self.preview().json()["proposal_token"]
        self.assertEqual(self.confirm(old_token).status_code, 400)
        with patch("prescriptions.catalog.VERSION", "demo-next-version"):
            self.assertEqual(self.confirm(token).status_code, 400)
        self.assertFalse(DemoPrescription.objects.exists())

    def test_strict_validation_and_exact_confirmation(self):
        for body in [{"drug_id": "unknown"}, {"drug_id": "aviandr", "note": "x" * 1001},
                {"drug_id": "aviandr", "patient_id": self.b.pk}, {"drug_id": "aviandr", "doctor_id": self.db.pk}]:
            self.assertEqual(self.preview(body).status_code, 400)
        token = self.preview({"drug_id": "aviandr", "note": "  <script>demo</script>  "}).json()["proposal_token"]
        for value in [False, "true", 1, None]:
            self.assertEqual(self.confirm(token, confirmed=value).status_code, 400)
        self.assertEqual(self.d.post(self.path, {"proposal_token": token}, content_type="application/json").status_code, 400)
        self.assertEqual(self.confirm(token, drug_id="ibuprofen").status_code, 400)
        result = self.confirm(token)
        self.assertEqual(result.status_code, 201)
        self.assertEqual(result.json()["note"], "<script>demo</script>")
        self.assertEqual(result.json()["drug_name"], "Авиандр")

    def test_maximum_unicode_comment_can_be_confirmed(self):
        for note in ["я" * 1000, "😀" * 1000]:
            proposal = self.preview({"drug_id": "aviandr", "note": note})
            self.assertEqual(proposal.status_code, 200)
            response = self.confirm(proposal.json()["proposal_token"])
            self.assertEqual(response.status_code, 201, response.content)
            self.assertEqual(response.json()["note"], note)

    def test_audit_failure_rolls_back_and_error_has_no_payload(self):
        token = self.preview().json()["proposal_token"]
        with patch("prescriptions.views.record", side_effect=RuntimeError("sensitive-synthetic-note")):
            response = self.confirm(token)
        self.assertEqual(response.status_code, 500)
        self.assertNotIn(b"sensitive-synthetic-note", response.content)
        self.assertFalse(DemoPrescription.objects.exists())
        self.assertEqual(self.confirm(token).status_code, 201)

    def test_csrf_required(self):
        c = Client(enforce_csrf_checks=True)
        c.force_login(self.da, backend="django.contrib.auth.backends.ModelBackend")
        self.assertEqual(c.post(self.path + "/preview", {"drug_id": "aviandr"}, content_type="application/json").status_code, 403)


@override_settings(**FAST)
class ConcurrentConfirmation(TransactionTestCase):
    def test_two_confirmations_create_one_record_and_audit(self):
        a, b, da, db = fixtures()
        path = f"/api/patients/{a.pk}/prescriptions"
        clients = [client_for(da), client_for(da)]
        token = clients[0].post(path + "/preview", {"drug_id": "aviandr"}, content_type="application/json").json()["proposal_token"]
        barrier = Barrier(2)
        def send(client):
            close_old_connections(); barrier.wait()
            try:
                response = client.post(path, {"proposal_token": token, "confirmed": True}, content_type="application/json")
                return response.status_code, response.json()
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            result = list(pool.map(send, clients))
        self.assertEqual(sorted(r[0] for r in result), [200, 201], result)
        self.assertEqual(result[0][1], result[1][1])
        self.assertEqual(DemoPrescription.objects.count(), 1)
        self.assertEqual(AuditEvent.objects.filter(action="prescription.create").count(), 1)
