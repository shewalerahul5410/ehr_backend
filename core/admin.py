from django.contrib import admin
from .models import Patient, UserProfile


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = (
        "patient_id",
        "first_name",
        "last_name",
        "date_of_birth",
        "gender",
        "phone_number",
        "created_at",
    )

    search_fields = (
        "first_name",
        "last_name",
        "email",
        "phone_number",
    )

    list_filter = (
        "gender",
        "is_archived",
        "created_at",
    )

    readonly_fields = (
        "patient_id",
        "created_at",
        "updated_at",
    )


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role")
    search_fields = ("user__username", "user__email")
    list_filter = ("role",)
