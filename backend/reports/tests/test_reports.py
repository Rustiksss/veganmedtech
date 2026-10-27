from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from accounts.tests.helpers import fixtures,client_for,user
from audit.models import AuditEvent
from reports.models import SelfReport

FAST={"PASSWORD_HASHERS":["django.contrib.auth.hashers.MD5PasswordHasher"],"ACCOUNT_RATE_LIMITS":False}
BODY={"observed_at":"2026-10-20T10:00:00Z","text":"Вымышленное наблюдение"}

@override_settings(**FAST)
class ReportTests(TestCase):
    def setUp(self):
        self.a,self.b,self.da,self.db=fixtures()
        self.c=client_for(self.a);self.d=client_for(self.da)
    def post(self,body=BODY,key="one"):
        return self.c.post("/api/me/self-reports",body,content_type="application/json",HTTP_IDEMPOTENCY_KEY=key)
    def test_create_and_read_independent_session(self):
        self.assertEqual(self.c.get("/api/me/self-reports").json()["results"],[])
        response=self.post();self.assertEqual(response.status_code,201,response.content)
        data=response.json();self.assertEqual(data["author_id"],self.a.pk)
        self.assertIn("created_at",data)
        another=client_for(self.a)
        self.assertEqual(another.get("/api/me/self-reports").json()["results"][0],data)
        self.assertEqual(self.d.get(f"/api/patients/{self.a.pk}/self-reports").json()["results"][0],data)
        self.assertEqual(client_for(self.b).get("/api/me/self-reports").json()["results"],[])
    def test_boundaries_trim_validation_and_extra_fields(self):
        for text in ["", " ","x"*2001]:self.assertEqual(self.post({**BODY,"text":text}).status_code,400)
        self.assertEqual(self.post({**BODY,"observed_at":"bad"}).status_code,400)
        for field in ["patient_id","doctor_id","role","created_at"]:
            self.assertEqual(self.post({**BODY,field:self.b.pk}).status_code,400)
        self.assertEqual(self.post({**BODY,"text":" x "},"min").status_code,201)
        self.assertEqual(SelfReport.objects.get(idempotency_key="min").text,"x")
        self.assertEqual(self.post({**BODY,"text":"x"*2000},"max").status_code,201)
        self.assertEqual(self.post(key="").status_code,400)
    def test_repeat_conflict_and_user_scope(self):
        first=self.post();second=self.post()
        self.assertEqual(second.status_code,200)
        self.assertEqual(first.json(),second.json())
        self.assertEqual(self.post({**BODY,"text":"Другой текст"}).status_code,409)
        other=client_for(self.b).post("/api/me/self-reports",BODY,content_type="application/json",HTTP_IDEMPOTENCY_KEY="one")
        self.assertEqual(other.status_code,201)
        self.assertEqual(SelfReport.objects.filter(patient=self.a).count(),1)
        self.assertEqual(AuditEvent.objects.filter(action="report.create",actor=self.a).count(),1)
    def test_history_cursor_stable_order_and_isolation(self):
        for i in range(5):self.post({**BODY,"text":str(i)},str(i))
        first=self.c.get("/api/me/self-reports?limit=2").json()
        second=self.c.get("/api/me/self-reports",{"cursor":first["next_cursor"],"limit":2}).json()
        third=self.c.get("/api/me/self-reports",{"cursor":second["next_cursor"],"limit":2}).json()
        ids=[r["id"] for page in [first,second,third] for r in page["results"]]
        self.assertEqual(ids,sorted(ids,reverse=True));self.assertEqual(len(set(ids)),5)
        self.assertIsNone(third["next_cursor"])
        self.assertEqual(client_for(self.b).get("/api/me/self-reports",{"cursor":first["next_cursor"]}).status_code,400)
        for query in ["limit=0","limit=101","limit=x","cursor=invalid"]:self.assertEqual(self.c.get("/api/me/self-reports?"+query).status_code,400)
    def test_audit_failure_rolls_back_report(self):
        with patch("reports.views.record",side_effect=RuntimeError("synthetic-audit-failure")):
            response=self.post()
        self.assertEqual(response.status_code,500)
        self.assertFalse(SelfReport.objects.exists())
        self.assertNotIn(b"synthetic-audit-failure",response.content)

@override_settings(**FAST)
class ConcurrentReports(TransactionTestCase):
    def test_simultaneous_requests_and_email_uniqueness(self):
        from django.db import IntegrityError
        from threading import Barrier
        a=user("race@example.test")
        clients=[client_for(a),client_for(a)]
        barrier=Barrier(2)
        def send(c):
            close_old_connections();barrier.wait()
            try:
                response=c.post("/api/me/self-reports",BODY,content_type="application/json",HTTP_IDEMPOTENCY_KEY="race")
                return response.status_code,response.json()
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(send,clients))
        self.assertEqual(sorted(r[0] for r in results),[200,201],results)
        self.assertEqual(results[0][1],results[1][1])
        self.assertEqual(SelfReport.objects.count(),1)
        self.assertEqual(AuditEvent.objects.filter(action="report.create").count(),1)
        barrier=Barrier(2)
        def create(email):
            close_old_connections();barrier.wait()
            try:
                user(email);return "created"
            except IntegrityError:return "duplicate"
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:out=list(pool.map(create,["SAME@example.test","same@EXAMPLE.test"]))
        self.assertEqual(sorted(out),["created","duplicate"])
