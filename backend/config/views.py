from django.db import connection, DatabaseError
from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET
from rest_framework.views import APIView
from accounts.permissions import PatientOnly


class QuestionnaireModule(APIView):
    permission_classes = [PatientOnly]

    def get(self, request):
        # The canonical source stays outside the collected public static root.
        response = HttpResponse(
            (settings.ROOT / "frontend/static/js/questionnaires.js").read_bytes(),
            content_type="application/javascript; charset=utf-8",
        )
        response["Cache-Control"] = "no-store"
        return response

@require_GET
@ensure_csrf_cookie
def index(request):
    return render(request, "index.html")

@require_GET
def ready(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM django_migrations LIMIT 1")
            cursor.fetchone()
        return JsonResponse({"ready": True})
    except DatabaseError:
        return JsonResponse({"ready": False}, status=503)

def csrf_failure(request, reason=""):
    return JsonResponse({"error": {"code": "csrf", "message": "Обновите страницу и повторите действие."}}, status=403)
