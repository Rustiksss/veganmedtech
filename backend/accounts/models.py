from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.db.models.functions import Lower

class UserManager(BaseUserManager):
    use_in_migrations = True
    def create_user(self, email, password=None, **extra):
        if not email:
            raise ValueError("Email обязателен")
        user = self.model(email=email.strip().lower(), **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user
    def create_superuser(self, email, password=None, **extra):
        extra.update(is_staff=True, is_superuser=True)
        return self.create_user(email, password, **extra)

class User(AbstractUser):
    username = None
    first_name = None
    last_name = None
    email = models.EmailField(unique=True)
    display_name = models.CharField(max_length=60)
    role = models.CharField(max_length=10, choices=[("patient", "Пациент"), ("doctor", "Врач")], default="patient")
    doctor_approved = models.BooleanField(default=False)
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []
    objects = UserManager()
    class Meta:
        constraints = [models.UniqueConstraint(Lower("email"), name="user_email_case_unique"),
            models.CheckConstraint(condition=models.Q(role__in=["patient", "doctor"]), name="valid_user_role"),
            models.CheckConstraint(condition=models.Q(doctor_approved=False) | models.Q(role="doctor"), name="only_doctor_approved")]
    def save(self, *args, **kwargs):
        self.email = self.email.strip().lower()
        super().save(*args, **kwargs)
    def get_full_name(self):
        return self.display_name
    def get_short_name(self):
        return self.display_name
