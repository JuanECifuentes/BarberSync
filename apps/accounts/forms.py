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
