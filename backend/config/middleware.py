import smtplib
from django.db import DatabaseError
from django.http import JsonResponse
from django.utils.deprecation import MiddlewareMixin

class SafeResponsesMiddleware(MiddlewareMixin):
    def process_request(self, request):
        allowed = {"auth/session", "auth/signup", "auth/login", "auth/email/verify", "auth/email/verify/resend", "auth/password/request", "auth/password/reset", "account/password/change"}
        prefix = "/_allauth/browser/v1/"
        if request.path.startswith("/_allauth/") and (not request.path.startswith(prefix) or request.path[len(prefix):] not in allowed):
            return JsonResponse({"error": {"code": "not_found", "message": "Страница недоступна."}}, status=404)

    def process_exception(self, request, exception):
        if isinstance(exception, (DatabaseError, smtplib.SMTPException, ConnectionError, TimeoutError, OSError)):
            return JsonResponse({"error": {"code": "unavailable", "message": "Сервис временно недоступен. Повторите попытку позднее."}}, status=503)
        return JsonResponse({"error": {"code": "internal_error", "message": "Не удалось выполнить запрос."}}, status=500)

    def process_response(self, request, response):
        if not request.path.startswith("/static/"):
            response["Cache-Control"] = "no-store"
        response["X-Frame-Options"] = "DENY"
        return response
