from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from allauth.account.models import EmailAddress
from accounts.models import User
from audit.events import record

class Command(BaseCommand):
    help = "Одобрить или отозвать допуск врача. Только для оператора контейнера."
    def add_arguments(self, parser):
        parser.add_argument("operation", choices=["approve", "revoke"])
        parser.add_argument("email")
    @transaction.atomic
    def handle(self, operation, email, **options):
        user = User.objects.select_for_update().filter(email__iexact=email.strip(), role="doctor", is_active=True).first()
        if not user or not EmailAddress.objects.filter(user=user, verified=True).exists():
            raise CommandError("Нужен активный врач с подтверждённым адресом.")
        approved = operation == "approve"
        if user.doctor_approved != approved:
            user.doctor_approved = approved
            user.save(update_fields=["doctor_approved"])
            record(None, "doctor." + operation, user.pk, subject="service:operator")
        self.stdout.write("Статус допуска установлен.")
