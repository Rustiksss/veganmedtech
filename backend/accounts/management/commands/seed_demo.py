import os
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from allauth.account.models import EmailAddress
from accounts.models import User
from care.models import CareRelationship
from audit.events import record

class Command(BaseCommand):
    help = "Opt-in: создать два вымышленных врача/пациента без перезаписи существующих данных."
    @transaction.atomic
    def handle(self, **options):
        password = os.environ.get("DEMO_PASSWORD", "")
        if not settings.DEV or len(password) < 12:
            raise CommandError("Нужны APP_DEV_MODE=1 и DEMO_PASSWORD длиной от 12 символов.")
        for suffix in ("a", "b"):
            users = []
            for role, name in [("doctor", "Учебный врач"), ("patient", "Учебный пациент")]:
                email = f"{role}-{suffix}@example.test"
                if User.objects.filter(email=email).exists():
                    users.append(None)
                    continue
                user = User.objects.create_user(email, password, display_name=f"{name} {suffix.upper()}", role=role, doctor_approved=role == "doctor")
                EmailAddress.objects.create(user=user, email=email, verified=True, primary=True)
                record(None, "demo.user.create", user.pk, subject="service:seed_demo")
                users.append(user)
            doctor, patient = users
            if doctor and patient:
                link = CareRelationship.objects.create(doctor=doctor, patient=patient)
                record(None, "care.assign", link.pk, subject="service:seed_demo")
        self.stdout.write("Вымышленные аккаунты подготовлены; существующие данные сохранены.")
