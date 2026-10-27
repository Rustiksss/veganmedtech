from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from allauth.account.models import EmailAddress
from accounts.models import User
from audit.events import record
from care.models import CareRelationship

class Command(BaseCommand):
    help = "Назначить или отозвать ведущего врача. Только для оператора контейнера."
    def add_arguments(self, parser):
        parser.add_argument("operation", choices=["assign", "revoke"])
        parser.add_argument("patient_email")
        parser.add_argument("doctor_email", nargs="?")
    @transaction.atomic
    def handle(self, operation, patient_email, doctor_email=None, **options):
        patient = User.objects.select_for_update().filter(email__iexact=patient_email.strip(), role="patient", is_active=True).first()
        if not patient or not EmailAddress.objects.filter(user=patient, verified=True).exists():
            raise CommandError("Нужен активный пациент с подтверждённым адресом.")
        current = CareRelationship.objects.filter(patient=patient, active=True).first()
        doctor = None
        if operation == "assign":
            doctor = User.objects.filter(email__iexact=(doctor_email or "").strip(), role="doctor", doctor_approved=True, is_active=True).first()
            if not doctor or not EmailAddress.objects.filter(user=doctor, verified=True).exists():
                raise CommandError("Нужен допущенный врач с подтверждённым адресом.")
            if current and current.doctor_id == doctor.pk:
                self.stdout.write("Связь уже установлена.")
                return
        if current:
            current.active = False
            current.save(update_fields=["active"])
            record(None, "care.revoke", current.pk, subject="service:operator")
        if doctor:
            link = CareRelationship.objects.create(patient=patient, doctor=doctor)
            record(None, "care.assign", link.pk, subject="service:operator")
        self.stdout.write("Связь обновлена.")
