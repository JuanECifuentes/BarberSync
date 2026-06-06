from django import forms
from django.contrib.auth import get_user_model

User = get_user_model()


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name"]
        widgets = {
            "first_name": forms.TextInput(
                attrs={
                    "class": "w-full bg-neutral-900 border border-neutral-800 rounded-xl px-4 py-3 text-white placeholder-neutral-500 focus:outline-none focus:border-brand focus:ring-1 focus:ring-brand transition-all",
                    "placeholder": "Tu nombre",
                }
            ),
            "last_name": forms.TextInput(
                attrs={
                    "class": "w-full bg-neutral-900 border border-neutral-800 rounded-xl px-4 py-3 text-white placeholder-neutral-500 focus:outline-none focus:border-brand focus:ring-1 focus:ring-brand transition-all",
                    "placeholder": "Tus apellidos",
                }
            ),
        }
        labels = {
            "first_name": "Nombres",
            "last_name": "Apellidos",
        }


from .models import Organization, Barbershop


class OrganizationOnboardingForm(forms.ModelForm):
    class Meta:
        model = Organization
        fields = ["name"]
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": "w-full bg-neutral-900 border border-neutral-800 rounded-xl px-4 py-3 text-white placeholder-neutral-500 focus:outline-none focus:border-brand focus:ring-1 focus:ring-brand transition-all",
                    "placeholder": "Ej. Barbería El Maestro",
                }
            ),
        }
        labels = {
            "name": "Nombre de la Organización",
        }


class BarbershopOnboardingForm(forms.ModelForm):
    class Meta:
        model = Barbershop
        fields = ["name", "maps_location", "maps_instructions"]
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": "w-full bg-neutral-900 border border-neutral-800 rounded-xl px-4 py-3 text-white placeholder-neutral-500 focus:outline-none focus:border-brand focus:ring-1 focus:ring-brand transition-all",
                    "placeholder": "Ej. Sede Principal",
                }
            ),
            "maps_location": forms.HiddenInput(),
            "maps_instructions": forms.Textarea(
                attrs={
                    "class": "w-full bg-neutral-900 border border-neutral-800 rounded-xl px-4 py-3 text-white placeholder-neutral-500 focus:outline-none focus:border-brand focus:ring-1 focus:ring-brand transition-all resize-none",
                    "placeholder": "Ej. Frente al parque, entrada por la esquina.",
                    "rows": 2,
                }
            ),
        }
        labels = {
            "name": "Nombre de la Sucursal",
            "maps_location": "Ubicación en el mapa",
            "maps_instructions": "Indicaciones de llegada (opcional)",
        }
