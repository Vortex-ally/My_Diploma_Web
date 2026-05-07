from django import forms
from django.utils.text import slugify

from .models import Organization, Project, VolunteerReview


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ["name", "date", "hours", "max_volunteers", "description", "location", "price", "organization"]
        widgets = {
            "date": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "description": forms.Textarea(attrs={"rows": 3}),
        }


class VolunteerReviewForm(forms.ModelForm):
    class Meta:
        model = VolunteerReview
        fields = ["rating", "comment"]
        widgets = {
            "rating": forms.RadioSelect(choices=[(i, f"{i} ★") for i in range(1, 6)]),
            "comment": forms.Textarea(attrs={"rows": 3, "placeholder": "Ваш відгук про захід..."}),
        }


class OrganizationForm(forms.ModelForm):
    class Meta:
        model = Organization
        fields = ["name", "site_name", "description"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    def save(self, commit=True):
        instance = super().save(commit=False)
        if not instance.slug:
            base_slug = slugify(instance.name)
            slug = base_slug
            counter = 1
            while Organization.objects.filter(slug=slug).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            instance.slug = slug
        if commit:
            instance.save()
        return instance


class PaymentForm(forms.Form):
    card_number = forms.CharField(
        max_length=19,
        widget=forms.TextInput(attrs={"placeholder": "1234 5678 9012 3456", "maxlength": "19"}),
        label="Номер картки",
    )
    cardholder = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={"placeholder": "IVAN PETRENKO"}),
        label="Ім'я власника",
    )
    expiry = forms.CharField(
        max_length=5,
        widget=forms.TextInput(attrs={"placeholder": "MM/YY", "maxlength": "5"}),
        label="Термін дії",
    )
    cvv = forms.CharField(
        max_length=3,
        widget=forms.PasswordInput(attrs={"placeholder": "CVV", "maxlength": "3"}),
        label="CVV",
    )
