from django import forms
from django.contrib.auth import get_user_model

User = get_user_model()

class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['first_name', 'last_name']
        widgets = {
            'first_name': forms.TextInput(attrs={
                'class': 'w-full bg-neutral-900 border border-neutral-800 rounded-xl px-4 py-3 text-white placeholder-neutral-500 focus:outline-none focus:border-brand focus:ring-1 focus:ring-brand transition-all',
                'placeholder': 'Tu nombre',
            }),
            'last_name': forms.TextInput(attrs={
                'class': 'w-full bg-neutral-900 border border-neutral-800 rounded-xl px-4 py-3 text-white placeholder-neutral-500 focus:outline-none focus:border-brand focus:ring-1 focus:ring-brand transition-all',
                'placeholder': 'Tus apellidos',
            }),
        }
        labels = {
            'first_name': 'Nombres',
            'last_name': 'Apellidos',
        }

from .models import Organization, Barbershop

class OrganizationOnboardingForm(forms.ModelForm):
    class Meta:
        model = Organization
        fields = ['name', 'slug']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'w-full bg-neutral-900 border border-neutral-800 rounded-xl px-4 py-3 text-white placeholder-neutral-500 focus:outline-none focus:border-brand focus:ring-1 focus:ring-brand transition-all',
                'placeholder': 'Ej. Barbería El Maestro',
            }),
            'slug': forms.TextInput(attrs={
                'class': 'w-full bg-neutral-900 border border-neutral-800 rounded-xl px-4 py-3 text-white placeholder-neutral-500 focus:outline-none focus:border-brand focus:ring-1 focus:ring-brand transition-all',
                'placeholder': 'el-maestro',
            }),
        }
        labels = {
            'name': 'Nombre de la Organización',
            'slug': 'Identificador Único (URL)',
        }

class BarbershopOnboardingForm(forms.ModelForm):
    class Meta:
        model = Barbershop
        fields = ['name', 'slug']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'w-full bg-neutral-900 border border-neutral-800 rounded-xl px-4 py-3 text-white placeholder-neutral-500 focus:outline-none focus:border-brand focus:ring-1 focus:ring-brand transition-all',
                'placeholder': 'Ej. Sede Principal',
            }),
            'slug': forms.TextInput(attrs={
                'class': 'w-full bg-neutral-900 border border-neutral-800 rounded-xl px-4 py-3 text-white placeholder-neutral-500 focus:outline-none focus:border-brand focus:ring-1 focus:ring-brand transition-all',
                'placeholder': 'sede-principal',
            }),
        }
        labels = {
            'name': 'Nombre de la Sucursal',
            'slug': 'Identificador de la Sucursal',
        }

