import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Event
from unittest.mock import patch, MagicMock
from django.db import close_old_connections, OperationalError
from django.test import TestCase, TransactionTestCase, Client, override_settings
from django.utils import timezone
from accounts.tests.helpers import fixtures, client_for, user
from care.models import CareRelationship
from audit.models import AuditEvent
from assistant.client import complete, ProviderError, MAX_BYTES
from assistant.models import AssistantTurn, AssistantAttempt, AssistantNotification
from assistant.prompts import SYSTEM_PROMPT
from assistant.services import send, create_synthetic_notification, AUTOMATIC_DETECTION_ENABLED

URL = "/api/me/assistant/messages"
ALERTS = "/api/doctor/assistant-notifications"
CONFIG = dict(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"], ACCOUNT_RATE_LIMITS=False,
              POLZA_API_KEY="synthetic-placeholder", POLZA_MODEL="deepseek/deepseek-v4-flash")


@override_settings(**CONFIG, ASSISTANT_ALERTING_MODE="off")
class AssistantTests(TestCase):
    def setUp(self):
        self.a, self.b, self.da, self.db = fixtures()
        self.c = client_for(self.a)

    def post(self, text="Как добавить наблюдение?", key="first", client=None, **extra):
        return (client or self.c).post(URL, {"text": text, **extra}, content_type="application/json", HTTP_IDEMPOTENCY_KEY=key)

    @patch("assistant.services.complete", return_value=("Откройте «Новая запись».", {"total_tokens": 12}))
    def test_persistent_history_idempotency_and_private_headers(self, api):
        r=self.post(); self.assertEqual(r.status_code,201);self.assertEqual(r.json()["status"],"completed")
        again=self.post();self.assertEqual(again.status_code,200);self.assertEqual(r.json(),again.json());api.assert_called_once()
        self.assertEqual(self.post(text="Другое",key="first").status_code,409)
        items=client_for(self.a).get(URL).json()["results"]
        self.assertEqual(len(items),1);self.assertEqual(items[0]["reply"],"Откройте «Новая запись».")
        self.assertEqual(self.c.get(URL)["Cache-Control"],"no-store")
        self.assertEqual(self.c.get(f'{URL}/{r.json()["id"]}').status_code,200)

    @patch("assistant.services.complete", return_value=("Продолжим.", {}))
    def test_context_only_own_last_ten_completed_pairs(self, api):
        for i in range(12):
            AssistantTurn.objects.create(patient=self.a,idempotency_key=str(i),text=f"Пара {i}",reply=f"Ответ {i}",status="completed",model="x",prompt_version="x")
        AssistantTurn.objects.create(patient=self.b,idempotency_key="other",text="PRIVATE_OTHER",reply="OTHER_REPLY",status="completed",model="x",prompt_version="x")
        self.post(text="Текущий текст")
        messages=api.call_args.args[0];self.assertEqual(len(messages),22)
        self.assertEqual(messages[0],{"role":"system","content":SYSTEM_PROMPT})
        self.assertEqual(messages[1]["content"],"Пара 2");self.assertEqual(messages[-1]["content"],"Текущий текст")
        self.assertNotIn("PRIVATE_OTHER",str(messages));self.assertNotIn(self.a.email,str(messages))

    @patch("assistant.services.complete", return_value=("Учебный ответ.", {}))
    def test_roles_ownership_csrf_and_unverified(self, api):
        own=self.post().json()["id"]
        for c,code in [(Client(),401),(client_for(self.da),403),(client_for(user("unverified@example.test",verified=False)),403)]:
            self.assertEqual(c.get(URL).status_code,code)
            self.assertEqual(self.post(client=c).status_code,code)
        self.assertEqual(client_for(self.b).get(f"{URL}/{own}").status_code,404)
        self.assertEqual(self.post(patient_id=self.b.pk,doctor_id=self.db.pk,role="doctor").status_code,400)
        c=Client(enforce_csrf_checks=True);c.force_login(self.a,backend="django.contrib.auth.backends.ModelBackend")
        self.assertEqual(self.post(client=c).status_code,403)
        self.assertEqual(api.call_count,1)

    @patch("assistant.services.complete")
    def test_input_validation_no_provider(self, api):
        for text in ["", "   ", "x"*2001]:self.assertEqual(self.post(text=text).status_code,400)
        for key in ["", "!bad", "x"*101]:self.assertEqual(self.post(key=key).status_code,400)
        for body in [[],{"text":"Hello","messages":[]}]:
            self.assertEqual(self.c.post(URL,body,content_type="application/json",HTTP_IDEMPOTENCY_KEY="x").status_code,400)
        api.assert_not_called()

    @patch("assistant.services.complete", return_value=("Один ответ.", {}))
    def test_signed_cursor_is_scoped_and_limit_validated(self, api):
        for i in range(3):self.post(key=str(i))
        data=self.c.get(URL+'?limit=2').json();self.assertEqual(len(data['results']),2)
        cursor=data['next_cursor'];self.assertEqual(len(self.c.get(URL,{'cursor':cursor}).json()['results']),1)
        self.assertEqual(client_for(self.b).get(URL,{'cursor':cursor}).status_code,400)
        for params in [{'limit':'bad'},{'limit':0},{'limit':101},{'cursor':'broken'}]:self.assertEqual(self.c.get(URL,params).status_code,400)

    @patch("assistant.services.complete", side_effect=ProviderError("timeout"))
    def test_error_is_persisted_without_automatic_paid_retry(self, api):
        first=self.post();self.assertEqual(first.json()['status'],'failed');self.assertFalse(first.json()['reply'])
        self.post();self.assertEqual(api.call_count,1)
        self.post(key='conscious-retry');self.assertEqual(api.call_count,2)
        self.assertEqual(AssistantTurn.objects.count(),2)

    @patch("assistant.services.complete", return_value=("Ответ.",{}))
    def test_limits_across_requests_and_daily_limit(self, api):
        for i in range(6):self.assertEqual(self.post(key=str(i)).status_code,201)
        self.assertEqual(self.post(key='seven').status_code,429)
        self.assertEqual(self.post(key='0').status_code,200)
        AssistantAttempt.objects.all().delete()
        AssistantAttempt.objects.bulk_create([AssistantAttempt(patient=self.a) for _ in range(100)])
        AssistantAttempt.objects.update(created_at=timezone.now()-timedelta(hours=2))
        self.assertEqual(self.post(key='daily').status_code,429)

    @patch("assistant.services.complete")
    def test_pending_recovery_and_no_parallel_generation(self, api):
        turn=AssistantTurn.objects.create(patient=self.a,idempotency_key='active',text='text',model='x',prompt_version='x')
        self.assertEqual(self.post(text='text',key='active').status_code,202)
        self.assertEqual(self.post(key='second').status_code,429);api.assert_not_called()
        AssistantTurn.objects.filter(pk=turn.pk).update(created_at=timezone.now()-timedelta(seconds=26))
        data=self.c.get(f'{URL}/{turn.pk}').json();self.assertEqual(data['status'],'interrupted')
        self.assertEqual(self.post(text='text',key='active').json()['status'],'interrupted');api.assert_not_called()

    @patch("assistant.services.complete", return_value=("Это не отправлено врачу.", {}))
    def test_template_does_not_activate_detection(self, api):
        policy=json.loads((Path(__file__).parents[1]/'alert_policy.template.json').read_text())
        self.assertFalse(AUTOMATIC_DETECTION_ENABLED);self.assertFalse(policy['automatic_detection_enabled'])
        self.assertEqual(policy['criteria'],[]);self.assertEqual(policy['sources'],[])
        self.assertEqual(policy['status'],'draft');self.assertIsNone(policy['medical_approval']['reviewer'])
        self.post(text='Вымышленный сценарий: опасные мысли о самоповреждении.')
        self.assertEqual(AssistantNotification.objects.count(),0)

    @patch("assistant.services.complete", return_value=("Ответ.",{}))
    def test_notification_current_doctor_only_reassignment_and_seen(self, api):
        turn=self.post().json()['id'];n=create_synthetic_notification(turn)
        self.assertEqual(create_synthetic_notification(turn).pk,n.pk)
        doctor=client_for(self.da);other=client_for(self.db)
        self.assertEqual(len(doctor.get(ALERTS).json()['results']),1)
        self.assertEqual(other.get(f'{ALERTS}/{n.pk}').status_code,404)
        self.assertEqual(self.c.get(ALERTS).status_code,403)
        self.assertEqual(self.c.get(f'{ALERTS}/{n.pk}').status_code,403)
        self.assertEqual(doctor.post(f'{ALERTS}/{n.pk}',{},content_type='application/json').status_code,200)
        first=doctor.get(f'{ALERTS}/{n.pk}').json()['seen_at'];self.assertTrue(first)
        self.assertEqual(doctor.post(f'{ALERTS}/{n.pk}',{},content_type='application/json').json()['seen_at'],first)
        CareRelationship.objects.filter(patient=self.a).update(active=False)
        self.assertEqual(doctor.get(f'{ALERTS}/{n.pk}').status_code,404)
        self.assertEqual(doctor.post(f'{ALERTS}/{n.pk}',{},content_type='application/json').status_code,404)
        CareRelationship.objects.create(patient=self.a,doctor=self.db)
        self.assertIsNone(other.get(f'{ALERTS}/{n.pk}').json()['seen_at'])
        self.assertEqual(len(doctor.get(ALERTS).json()['results']),0)
        self.db.doctor_approved=False;self.db.save()
        self.assertEqual(other.get(ALERTS).status_code,403)

    @patch("assistant.services.complete", return_value=("Ответ.",{}))
    def test_notification_failure_rolls_back_and_retries_without_duplicates(self, api):
        turn=self.post().json()['id']
        with patch('assistant.services.record',side_effect=OperationalError('synthetic')):
            with self.assertRaises(OperationalError):create_synthetic_notification(turn)
        self.assertEqual(AssistantNotification.objects.count(),0)
        n=create_synthetic_notification(turn)
        self.assertEqual(create_synthetic_notification(turn).pk,n.pk)
        CareRelationship.objects.filter(patient=self.a).update(active=False)
        self.assertEqual(client_for(self.da).get(ALERTS).json()['results'],[])
        self.assertTrue(AssistantNotification.objects.filter(pk=n.pk).exists())

    @patch("assistant.services.complete", return_value=("Ответ.",{}))
    def test_audit_no_chat_text_and_no_public_synthetic_creation(self, api):
        marker='PRIVATE_CHAT_MARKER';turn=self.post(text=marker).json()['id'];n=create_synthetic_notification(turn)
        doctor=client_for(self.da);doctor.get(ALERTS);doctor.get(f'{ALERTS}/{n.pk}')
        self.assertNotIn(marker,str(list(AuditEvent.objects.values())))
        self.assertEqual(self.c.post(ALERTS,{'turn_id':turn},content_type='application/json').status_code,403)
        self.assertEqual(doctor.post(ALERTS,{'turn_id':turn},content_type='application/json').status_code,405)
        self.assertEqual(doctor.post(f'{ALERTS}/{n.pk}',{'doctor_id':self.db.pk},content_type='application/json').status_code,400)
        self.assertTrue(AuditEvent.objects.filter(action='assistant.alert_list').exists())


@override_settings(**CONFIG, ASSISTANT_ALERTING_MODE="off")
class ConcurrentTests(TransactionTestCase):
    def test_two_workers_share_user_lock_and_rate_limit(self):
        a,b,da,db=fixtures();entered=Event();release=Event()
        def provider(messages):entered.set();release.wait(5);return 'Ответ',{}
        def worker(key):
            close_old_connections()
            try:return send(a,key,'Первый текст')[0].pk
            finally:close_old_connections()
        with patch('assistant.services.complete',side_effect=provider) as api, ThreadPoolExecutor(max_workers=2) as pool:
            future=pool.submit(worker,'same');self.assertTrue(entered.wait(5))
            duplicate=pool.submit(worker,'same').result(timeout=5)
            self.assertEqual(api.call_count,1)
            from rest_framework.exceptions import Throttled
            with self.assertRaises(Throttled):worker('other')
            release.set();self.assertEqual(future.result(timeout=5),duplicate)
        self.assertEqual(AssistantTurn.objects.count(),1);self.assertEqual(AssistantAttempt.objects.count(),1)


@override_settings(**CONFIG, ASSISTANT_ALERTING_MODE="off")
class ClientTests(TestCase):
    def test_deadline_includes_dns_and_does_not_send_after_expiry(self):
        release=Event()
        with patch('assistant.client.TIMEOUT',.03), patch('assistant.client.http.client.HTTPSConnection') as ctor:
            ctor.return_value.connect.side_effect=lambda:release.wait(1)
            try:
                with self.assertRaises(ProviderError) as exc:complete([])
                self.assertEqual(exc.exception.code,'timeout')
            finally:
                release.set()
            # After DNS completes the worker checks its expired deadline before request().
            import time;time.sleep(.03)
            ctor.return_value.request.assert_not_called()

    def response(self, value=None, raw=None, status=200):
        obj=MagicMock();obj.status=status
        obj.isclosed.return_value=False;obj.length=None
        obj.read1.side_effect=[raw if raw is not None else json.dumps(value).encode(),b'']
        return obj

    def closing_response(self, body, *, fragment=8192, advertised_extra=0):
        import errno
        import http.client
        import io

        class Fragments(io.BytesIO):
            def read1(self, size=-1):
                return super().read(min(size, fragment))

        class ClosingSocket:
            def __init__(self):
                length=len(body)+advertised_extra
                self.fp=Fragments(b'HTTP/1.1 200 OK\r\nContent-Length: '+str(length).encode()+b'\r\nConnection: close\r\n\r\n'+body)
                self.closed_timeout_calls=0

            def makefile(self, *args):
                return self.fp

            def settimeout(self, value):
                if self.fp.closed:
                    self.closed_timeout_calls+=1
                    raise OSError(errno.EBADF, 'Synthetic closed socket')

        sock=ClosingSocket();response=http.client.HTTPResponse(sock);response.begin()
        return sock,response

    @patch('assistant.client.http.client.HTTPSConnection')
    def test_real_http_response_close_and_fragmented_content(self, ctor):
        for fragment in [8192,7]:
            with self.subTest(fragment=fragment):
                sock,response=self.closing_response(json.dumps(self.valid()).encode(),fragment=fragment)
                ctor.return_value.sock=sock;ctor.return_value.getresponse.return_value=response
                reply,usage=complete([])
                self.assertEqual(reply,'Учебный ответ.')
                self.assertEqual(usage,{'total_tokens':10})
                self.assertTrue(response.isclosed())
                self.assertEqual(sock.closed_timeout_calls,0)

    @patch('assistant.client.http.client.HTTPSConnection')
    def test_incomplete_framing_rejects_even_valid_json(self, ctor):
        sock,response=self.closing_response(json.dumps(self.valid()).encode(),fragment=7,advertised_extra=17)
        ctor.return_value.sock=sock;ctor.return_value.getresponse.return_value=response
        with self.assertRaises(ProviderError) as exc:complete([])
        self.assertEqual(exc.exception.code,'incomplete')
        self.assertEqual(sock.closed_timeout_calls,0)

    def valid(self):
        return {'model':'deepseek/deepseek-v4-flash','choices':[{'message':{'content':'Учебный ответ.'},'finish_reason':'stop'}], 'usage':{'total_tokens':10,'secret':'NO'}}

    @patch('assistant.client.http.client.HTTPSConnection')
    def test_contract_fixed_tls_origin_caps_and_usage(self, ctor):
        connection=ctor.return_value;connection.getresponse.return_value=self.response(self.valid())
        reply,usage=complete([{'role':'user','content':'Текст'}]);self.assertEqual(reply,'Учебный ответ.');self.assertEqual(usage,{'total_tokens':10})
        self.assertEqual(ctor.call_args.args,('polza.ai',));self.assertIsNotNone(ctor.call_args.kwargs['context'])
        args=connection.request.call_args;self.assertEqual(args.args[:2],('POST','/api/v1/chat/completions'))
        body=json.loads(args.kwargs['body']);self.assertEqual(body['max_tokens'],512);self.assertFalse(body['stream'])
        self.assertEqual(body['provider']['max_price'],{'prompt':6,'completion':12});self.assertEqual(body['reasoning']['effort'],'none')
        self.assertNotIn('tools',body);connection.close.assert_called_once()

    @patch('assistant.client.http.client.HTTPSConnection')
    def test_upstream_statuses_do_not_leak_bodies(self, ctor):
        for status,code in [(401,'credentials'),(402,'balance'),(429,'rate_limit'),(500,'unavailable'),(302,'unavailable')]:
            ctor.return_value.getresponse.return_value=self.response(raw=b'PRIVATE_UPSTREAM_KEY',status=status)
            with self.assertRaises(ProviderError) as exc:complete([])
            self.assertEqual(str(exc.exception),code);self.assertNotIn('PRIVATE',str(exc.exception))

    @patch('assistant.client.http.client.HTTPSConnection')
    def test_invalid_responses_and_model_substitution(self, ctor):
        malformed=[[],{}, {'choices':[]}, {'choices':[[]]}, {'choices':[{'message':[]}]}]
        for change in [{'model':'expensive/model'},{'usage':[]},{'choices':[{'message':{'content':''},'finish_reason':'stop'}]}, {'choices':[{'message':{'content':'x'*4097},'finish_reason':'stop'}]}]:
            item=self.valid();item.update(change);malformed.append(item)
        for item in malformed:
            # An empty usage array is treated as absent; nonempty arrays are rejected.
            if isinstance(item,dict) and item.get('usage')==[]:item['usage']=[1]
            ctor.return_value.getresponse.return_value=self.response(item)
            with self.assertRaises(ProviderError):complete([])
        ctor.return_value.getresponse.return_value=self.response(raw=b'x'*(MAX_BYTES+1))
        with self.assertRaises(ProviderError):complete([])
        ctor.return_value.getresponse.return_value=self.response(raw=b'{broken')
        with self.assertRaises(ProviderError):complete([])

    @patch('assistant.client.http.client.HTTPSConnection')
    def test_timeout_incomplete_network_and_missing_key(self, ctor):
        ctor.return_value.connect.side_effect=TimeoutError()
        with self.assertRaises(ProviderError) as exc:complete([])
        self.assertEqual(exc.exception.code,'timeout')
        ctor.return_value.connect.side_effect=OSError('PRIVATE')
        with self.assertRaises(ProviderError) as exc:complete([])
        self.assertEqual(exc.exception.code,'unavailable')
        ctor.return_value.connect.side_effect=None
        value=self.valid();value['choices'][0]['finish_reason']='length'
        ctor.return_value.getresponse.return_value=self.response(value)
        with self.assertRaises(ProviderError) as exc:complete([])
        self.assertEqual(exc.exception.code,'incomplete')
        with override_settings(POLZA_API_KEY=''):
            with self.assertRaises(ProviderError) as exc:complete([])
            self.assertEqual(exc.exception.code,'configuration')
