import json
from unittest.mock import patch
from smtplib import SMTPException
from django.core import mail
from django.test import TestCase, Client, override_settings
from django.contrib.auth.hashers import make_password, check_password
from allauth.account.models import EmailConfirmationHMAC, EmailAddress
from accounts.models import User
from accounts.tests.helpers import user, client_for, PASSWORD

AUTH = "/_allauth/browser/v1/"
FAST = {"PASSWORD_HASHERS": ["django.contrib.auth.hashers.MD5PasswordHasher"], "EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend", "ACCOUNT_RATE_LIMITS": False}

@override_settings(**FAST)
class AccountTests(TestCase):
    def post(self, path, body, client=None):
        return (client or self.client).post(AUTH+path, body, content_type="application/json")
    def signup(self, **extra):
        data = {"email":"new@example.test", "password":PASSWORD, "display_name":"Вымышленное имя", "role":"patient"}
        data.update(extra)
        return self.post("auth/signup", data)
    def test_patient_signup_is_unverified_and_private(self):
        response = self.signup()
        self.assertEqual(response.status_code, 401, response.content)
        u = User.objects.get(email="new@example.test")
        self.assertEqual(u.display_name, "Вымышленное имя")
        self.assertFalse(u.doctor_approved)
        self.assertFalse(EmailAddress.objects.get(user=u).verified)
        self.assertEqual(self.client.get("/api/me").status_code, 401)
        self.assertEqual(len(mail.outbox), 1)
    def test_doctor_signup_does_not_grant_privileges(self):
        self.signup(role="doctor", doctor_approved=True, is_staff=True, is_superuser=True, doctor_id=123)
        u=User.objects.get(email="new@example.test")
        self.assertEqual(u.role,"doctor")
        self.assertFalse(u.doctor_approved or u.is_staff or u.is_superuser)
    def test_authenticated_login_and_signup_conflict_preserves_account(self):
        """TEST-001-38: a repeated form cannot replace the authenticated user."""
        other = user("other-login@example.test", "doctor", True)
        for role, approved in [("patient", False), ("doctor", False), ("doctor", True)]:
            with self.subTest(role=role, approved=approved):
                current = user(f"current-{role}-{approved}@example.test", role, approved)
                client = client_for(current)
                before = list(User.objects.order_by("pk").values())
                for operation, body in [
                    ("auth/login", {"email": other.email, "password": PASSWORD}),
                    ("auth/signup", {"email": "replacement@example.test", "password": PASSWORD,
                        "display_name": "Другая вымышленная роль", "role": "doctor" if role == "patient" else "patient"}),
                ]:
                    response = self.post(operation, body, client)
                    self.assertEqual(response.status_code, 409)
                    self.assertEqual(response.json(), {"status": 409})
                    me = client.get("/api/me")
                    self.assertEqual(me.status_code, 200)
                    self.assertEqual((me.json()["id"], me.json()["role"], me.json()["doctor_approved"]),
                        (current.pk, role, approved))
                    self.assertEqual(list(User.objects.order_by("pk").values()), before)
    def test_signup_validation(self):
        for data in [{"email":"invalid"}, {"password":"123"}, {"display_name":" "}, {"role":"admin"}, {"display_name":"x"*61}]:
            with self.subTest(data=list(data)):
                self.assertEqual(self.signup(**data).status_code,400)
        self.assertEqual(User.objects.count(),0)
    def test_case_insensitive_duplicate_and_enumeration(self):
        user("new@example.test")
        response=self.signup(email="NEW@EXAMPLE.TEST")
        self.assertIn(response.status_code,[200,401])
        self.assertEqual(User.objects.filter(email__iexact="new@example.test").count(),1)
        self.assertFalse(response.json().get("errors"))
    def test_verify_and_login_then_logout_invalidates_cookie(self):
        u=user("unverified@example.test",verified=False)
        c=Client()
        self.assertEqual(self.post("auth/login",{"email":u.email,"password":PASSWORD},c).status_code,401)
        key=EmailConfirmationHMAC(EmailAddress.objects.get(user=u)).key
        response=self.post("auth/email/verify",{"key":key},c)
        self.assertIn(response.status_code,[200,401],response.content)
        self.assertTrue(EmailAddress.objects.get(user=u).verified)
        self.assertIn(self.post("auth/email/verify",{"key":key},c).status_code,[400,409])
        self.assertEqual(self.post("auth/login",{"email":u.email.upper(),"password":PASSWORD},c).status_code,200)
        cookie=c.cookies["sessionid"].value
        self.assertEqual(c.get("/api/me").status_code,200)
        c.delete(AUTH+"auth/session")
        c.cookies["sessionid"]=cookie
        self.assertEqual(c.get("/api/me").status_code,401)
    def test_invalid_and_expired_confirmation(self):
        self.assertEqual(self.post("auth/email/verify",{"key":"invalid"}).status_code,400)
        u=user("expired@example.test",verified=False)
        key=EmailConfirmationHMAC(EmailAddress.objects.get(user=u)).key
        with patch("django.core.signing.time.time",return_value=99999999999):
            self.assertEqual(self.post("auth/email/verify",{"key":key}).status_code,400)
        self.assertFalse(EmailAddress.objects.get(user=u).verified)
    def test_password_reset_enumeration(self):
        u=user("reset@example.test")
        known=self.post("auth/password/request",{"email":u.email})
        unknown=self.post("auth/password/request",{"email":"missing@example.test"})
        self.assertEqual(known.status_code,unknown.status_code)
        self.assertEqual(known.json(),unknown.json())
    def test_password_reset_and_reuse(self):
        from allauth.account.forms import default_token_generator
        from allauth.account.utils import user_pk_to_url_str
        u=user("reset@example.test")
        old=client_for(u)
        key=user_pk_to_url_str(u)+"-"+default_token_generator.make_token(u)
        response=self.post("auth/password/reset",{"key":key,"password":"Another-synthetic-secret!77"})
        self.assertIn(response.status_code,[200,401],response.content)
        u.refresh_from_db()
        self.assertTrue(u.check_password("Another-synthetic-secret!77"))
        self.assertFalse(u.check_password(PASSWORD))
        self.assertEqual(old.get("/api/me").status_code,401)
        self.assertEqual(self.post("auth/password/reset",{"key":key,"password":PASSWORD}).status_code,400)
    def test_password_reset_invalid_and_expired(self):
        from allauth.account.forms import default_token_generator
        from allauth.account.utils import user_pk_to_url_str
        u=user("expire-reset@example.test")
        key=user_pk_to_url_str(u)+"-"+default_token_generator.make_token(u)
        self.assertEqual(self.post("auth/password/reset",{"key":"invalid","password":PASSWORD}).status_code,400)
        with override_settings(PASSWORD_RESET_TIMEOUT=0), patch("django.contrib.auth.tokens.PasswordResetTokenGenerator._now") as now:
            from datetime import datetime
            now.return_value=datetime(2099,1,1)
            self.assertEqual(self.post("auth/password/reset",{"key":key,"password":PASSWORD}).status_code,400)
    def test_change_password_invalidates_other_sessions(self):
        u=user("change@example.test")
        c=client_for(u);other=client_for(u)
        old_cookie=c.cookies["sessionid"].value
        response=self.post("account/password/change",{"current_password":PASSWORD,"new_password":"Changed-synthetic-secret!73"},c)
        self.assertIn(response.status_code,[200,401],response.content)
        self.assertEqual(other.get("/api/me").status_code,401)
        c.cookies["sessionid"]=old_cookie
        self.assertEqual(c.get("/api/me").status_code,401)
    def test_mail_failure_safe_response(self):
        u=user("mail-failure@example.test")
        with patch("django.core.mail.message.EmailMessage.send",side_effect=SMTPException("secret-marker-not-to-log")):
            response=self.post("auth/password/request",{"email":u.email})
        self.assertEqual(response.status_code,503)
        self.assertNotIn(b"secret-marker",response.content)
    def test_csrf_for_anonymous_and_authenticated_changes(self):
        u=user("csrf@example.test")
        c=Client(enforce_csrf_checks=True)
        c.get("/")
        body={"email":u.email,"password":PASSWORD}
        self.assertEqual(self.post("auth/login",body,c).status_code,403)
        token=c.cookies["csrftoken"].value
        response=c.post(AUTH+"auth/login",body,content_type="application/json",HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(c.delete(AUTH+"auth/session").status_code,403)
        token=c.cookies["csrftoken"].value
        self.assertEqual(c.post("/api/me/self-reports",{},content_type="application/json",HTTP_X_CSRFTOKEN=token,HTTP_ORIGIN="https://untrusted.example").status_code,403)
    def test_cookie_and_secure_settings(self):
        c=Client();c.get("/")
        from django.conf import settings
        self.assertTrue(settings.SESSION_COOKIE_HTTPONLY)
        self.assertEqual(settings.SESSION_COOKIE_SAMESITE,"Lax")
        self.assertEqual(settings.SESSION_COOKIE_SECURE,not settings.DEV)
        self.assertEqual(settings.CSRF_COOKIE_SECURE,not settings.DEV)
    def test_no_admin_app_or_extra_account_api(self):
        for path in ["/admin/login/","/_allauth/app/v1/auth/login","/_allauth/browser/v1/account/email","/misc_materials/","/backend/config/settings.py","/docs/","/tests/"]:
            self.assertEqual(self.client.get(path).status_code,404,path)
    @override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.Argon2PasswordHasher"])
    def test_real_password_hash_is_argon2id(self):
        encoded=make_password(PASSWORD)
        self.assertTrue(encoded.startswith("argon2$argon2id$"))
        self.assertTrue(check_password(PASSWORD,encoded))
    @override_settings(ACCOUNT_RATE_LIMITS={"login_failed":"2/m/ip,2/m/key"})
    def test_rate_limits_shared_cache_and_forged_proxy(self):
        from django.core.cache import cache
        from django.core.management import call_command
        call_command("createcachetable",verbosity=0)
        cache.clear()
        u=user("limited@example.test")
        first=Client();second=Client()
        for c in (first,second):
            response=c.post(AUTH+"auth/login",{"email":u.email,"password":"wrong"},content_type="application/json",HTTP_X_FORWARDED_FOR="8.8.8.8")
            self.assertEqual(response.status_code,400)
        response=Client().post(AUTH+"auth/login",{"email":u.email,"password":PASSWORD},content_type="application/json",HTTP_X_FORWARDED_FOR="1.1.1.1")
        self.assertIn(response.status_code,[400,429])
        cache.clear()

    def test_rate_cache_does_not_evict_live_counters(self):
        from django.core.cache import cache
        from django.core.management import call_command
        call_command("createcachetable",verbosity=0)
        cache.clear()
        old_max=cache._max_entries
        cache._max_entries=1
        try:
            cache.set("synthetic-live-1",1,60)
            cache.set("synthetic-live-2",2,60)
            cache.set("synthetic-live-3",3,60)
            self.assertEqual(cache.get("synthetic-live-1"),1)
            self.assertEqual(cache.get("synthetic-live-2"),2)
        finally:
            cache._max_entries=old_max
            cache.clear()


@override_settings(**FAST, SECURE_SSL_REDIRECT=True,
    SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
    SESSION_COOKIE_SECURE=True, CSRF_COOKIE_SECURE=True,
    ALLOWED_HOSTS=["94.103.3.149", "127.0.0.1"],
    CSRF_TRUSTED_ORIGINS=["https://94.103.3.149"])
class ProxyTests(TestCase):
    def test_https_login_requires_csrf_and_correct_origin(self):
        u = user("proxy-patient@example.test")
        c = Client(enforce_csrf_checks=True)
        headers = dict(HTTP_HOST="94.103.3.149", HTTP_X_FORWARDED_PROTO="https")
        self.assertEqual(c.get("/", **headers).status_code, 200)
        self.assertTrue(c.cookies['csrftoken']['secure'])
        body = dict(email=u.email, password=PASSWORD)
        path = AUTH + 'auth/login'
        self.assertEqual(c.post(path, body, content_type='application/json', **headers).status_code, 403)
        token = c.cookies['csrftoken'].value
        self.assertEqual(c.post(path, body, content_type='application/json', HTTP_X_CSRFTOKEN=token,
            HTTP_ORIGIN='https://untrusted.example', **headers).status_code, 403)
        response = c.post(path, body, content_type='application/json', HTTP_X_CSRFTOKEN=token,
            HTTP_ORIGIN='https://94.103.3.149', **headers)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(c.cookies['sessionid']['secure'])
        self.assertTrue(c.cookies['sessionid']['httponly'])
        self.assertEqual(c.get('/api/me', **headers).status_code, 200)

    def test_redirect_host_and_private_readiness(self):
        self.assertEqual(self.client.get('/', HTTP_HOST='94.103.3.149').status_code, 301)
        self.assertEqual(self.client.get('/', HTTP_HOST='untrusted.example', HTTP_X_FORWARDED_PROTO='https').status_code, 400)
        self.assertEqual(self.client.get('/health/ready', HTTP_HOST='127.0.0.1').status_code, 200)
        self.assertEqual(self.client.get('/api/me', HTTP_HOST='94.103.3.149', HTTP_X_FORWARDED_PROTO='https').status_code, 401)

    def test_opt_in_settings_and_single_replaced_client_ip_header(self):
        import os, runpy
        from pathlib import Path
        from django.core.exceptions import ImproperlyConfigured
        from django.test import RequestFactory
        from allauth.core.internal.httpkit import get_client_ip
        path = Path(__file__).resolve().parents[2] / 'config/settings.py'
        with patch.dict(os.environ, APP_DEV_MODE='0', APP_TRUST_PROXY='1', APP_BASE_URL='https://94.103.3.149'):
            loaded = runpy.run_path(str(path))
        self.assertEqual(loaded['SECURE_PROXY_SSL_HEADER'], ('HTTP_X_FORWARDED_PROTO', 'https'))
        self.assertEqual(loaded['ALLAUTH_TRUSTED_CLIENT_IP_HEADER'], 'X-Real-IP')
        self.assertTrue(loaded['SESSION_COOKIE_SECURE'])
        with patch.dict(os.environ, APP_DEV_MODE='1', APP_TRUST_PROXY='1'):
            with self.assertRaises(ImproperlyConfigured):
                runpy.run_path(str(path))
        with patch.dict(os.environ, APP_DEV_MODE='1', APP_TRUST_PROXY='0'):
            local = runpy.run_path(str(path))
        self.assertIsNone(local['SECURE_PROXY_SSL_HEADER'])
        self.assertIsNone(local['ALLAUTH_TRUSTED_CLIENT_IP_HEADER'])
        factory = RequestFactory()
        with override_settings(ALLAUTH_TRUSTED_CLIENT_IP_HEADER='X-Real-IP'):
            for forged in ('1.1.1.1', '8.8.8.8, 1.1.1.1'):
                request = factory.get('/', HTTP_X_REAL_IP='203.0.113.27', HTTP_X_FORWARDED_FOR=forged)
                self.assertEqual(get_client_ip(request), '203.0.113.27')


@override_settings(**FAST)
class QuestionnaireModuleTests(TestCase):
    path = '/api/questionnaires/module'

    def test_only_verified_active_patient_can_read_module(self):
        self.assertEqual(self.client.get(self.path).status_code, 401)
        for role, approved, verified in [('patient', False, False), ('doctor', False, True), ('doctor', True, True)]:
            with self.subTest(role=role, approved=approved, verified=verified):
                u = user(f'module-{role}-{approved}@example.test', role, approved, verified=verified)
                response = client_for(u).get(self.path + '?role=patient&patient_id=1')
                self.assertEqual(response.status_code, 403)
                self.assertNotIn(b'CompassQuestionnaires', response.content)
        patient = user('module-active@example.test')
        c = client_for(patient)
        from django.conf import settings
        expected = (settings.ROOT / 'frontend/static/js/questionnaires.js').read_bytes()
        response = c.get(self.path)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, expected)
        self.assertEqual(response['Cache-Control'], 'no-store')
        self.assertTrue(response['Content-Type'].startswith('application/javascript'))
        patient.is_active = False; patient.save(update_fields=['is_active'])
        self.assertEqual(c.get(self.path).status_code, 401)

    def test_confirmation_revocation_is_checked_on_next_request(self):
        patient = user('module-revoked@example.test')
        c = client_for(patient)
        response = c.get(self.path)
        self.assertEqual(response.status_code, 200)
        EmailAddress.objects.filter(user=patient).update(verified=False)
        self.assertEqual(c.get(self.path).status_code, 403)

    def test_page_does_not_embed_questionnaire_module_and_other_methods_are_rejected(self):
        response = self.client.get('/')
        self.assertNotContains(response, 'js/questionnaires')
        self.assertEqual(client_for(user('module-method@example.test')).post(self.path).status_code, 405)
