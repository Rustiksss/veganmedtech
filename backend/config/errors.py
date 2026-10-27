from rest_framework.exceptions import APIException
from rest_framework.views import exception_handler

class Conflict(APIException):
    status_code = 409
    default_detail = "Этот ключ уже использован для другой записи."
    default_code = "conflict"

def api_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        return None
    messages = {400: "Проверьте введённые данные.", 401: "Войдите в аккаунт.",
        403: "Недостаточно прав. Обновите страницу или войдите снова.",
        404: "Запись недоступна.", 409: "Этот ключ уже использован для другой записи.",
        429: "Слишком много попыток. Попробуйте позднее."}
    original = response.data
    response.data = {"error": {"code": getattr(exc, "default_code", "request_error"),
        "message": messages.get(response.status_code, "Запрос не выполнен.")}}
    if response.status_code == 400 and isinstance(original, dict):
        response.data["error"]["fields"] = original
    return response
