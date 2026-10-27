from allauth.account.adapter import DefaultAccountAdapter
from allauth.headless.adapter import DefaultHeadlessAdapter

class AccountAdapter(DefaultAccountAdapter):
    def save_user(self, request, user, form, commit=True):
        user = super().save_user(request, user, form, commit=False)
        user.email = form.cleaned_data["email"].strip().lower()
        user.display_name = form.cleaned_data["display_name"]
        user.role = form.cleaned_data["role"]
        user.doctor_approved = False
        user.is_staff = user.is_superuser = False
        if commit:
            user.save()
        return user

class HeadlessAdapter(DefaultHeadlessAdapter):
    def serialize_user(self, user):
        return {"id": user.pk, "display": user.display_name, "email": user.email,
                "role": user.role, "doctor_approved": user.doctor_approved, "has_usable_password": user.has_usable_password()}
