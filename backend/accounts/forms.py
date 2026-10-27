from django import forms

class SignupFields(forms.Form):
    display_name = forms.CharField(min_length=1, max_length=60, strip=True)
    role = forms.ChoiceField(choices=[("patient", "Пациент"), ("doctor", "Врач")])
    def signup(self, request, user):
        pass
