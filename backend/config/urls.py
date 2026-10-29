from django.urls import include, path
from config.views import index, ready, QuestionnaireModule
from accounts.views import MeView
from reports.views import OwnReports, PatientList, PatientReports, ReportDetail
from assistant.views import Messages, MessageDetail, Notifications, NotificationDetail

from prescriptions.views import Catalog, Preview, PatientPrescriptions, OwnPrescriptions

urlpatterns = [
    path("api/prescriptions/catalog", Catalog.as_view()),
    path("api/me/prescriptions", OwnPrescriptions.as_view()),
    path("api/patients/<int:patient_id>/prescriptions/preview", Preview.as_view()),
    path("api/patients/<int:patient_id>/prescriptions", PatientPrescriptions.as_view()),
    path("", index), path("health/ready", ready),
    path("_allauth/", include("allauth.headless.urls")),
    path("api/me", MeView.as_view()), path("api/patients", PatientList.as_view()),
    path("api/me/assistant/messages", Messages.as_view()),
    path("api/me/assistant/messages/<int:turn_id>", MessageDetail.as_view()),
    path("api/doctor/assistant-notifications", Notifications.as_view()),
    path("api/doctor/assistant-notifications/<int:notification_id>", NotificationDetail.as_view()),
    path("api/questionnaires/module", QuestionnaireModule.as_view()),
    path("api/me/self-reports", OwnReports.as_view()),
    path("api/patients/<int:patient_id>/self-reports", PatientReports.as_view()),
    path("api/patients/<int:patient_id>/self-reports/<int:report_id>", ReportDetail.as_view()),
]
