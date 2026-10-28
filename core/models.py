import uuid

from django.conf import settings
from django.db import models


class Patient(models.Model):

    class Gender(models.TextChoices):
        MALE = "M", "Male"
        FEMALE = "F", "Female"
        OTHER = "O", "Other"
        PREFER_NOT_TO_SAY = "N", "Prefer not to say"

    class Stage(models.TextChoices):
        RECEPTION = "reception", "Reception Intake"
        DOCTOR_REVIEW = "doctor_review", "Doctor Review"
        NURSE_CHECK = "nurse_check", "Nurse Check (Vitals & Blood)"
        ADMITTING_PROVIDER = "admitting_provider", "Admitting Provider (Super Doctor)"
        COMPLETED = "completed", "Completed / Discharged"

    class Priority(models.TextChoices):
        ROUTINE = "routine", "Routine"
        URGENT = "urgent", "Urgent"
        EMERGENCY = "emergency", "Emergency"

    class AdmissionDecision(models.TextChoices):
        NOT_DECIDED = "not_decided", "Under Evaluation"
        OUTPATIENT = "outpatient", "Discharged (Outpatient)"
        OBSERVATION = "observation", "Observation Ward"
        ADMITTED = "admitted", "Admitted Inpatient"
        TRANSFERRED = "transferred", "Specialist Transfer"

    patient_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
    )

    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    date_of_birth = models.DateField()
    gender = models.CharField(
        max_length=1,
        choices=Gender.choices,
    )

    phone_number = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)

    emergency_contact_name = models.CharField(
        max_length=150,
        blank=True,
    )
    emergency_contact_phone = models.CharField(
        max_length=20,
        blank=True,
    )

    # Workflow & Clinical Stage Tracking
    current_stage = models.CharField(
        max_length=30,
        choices=Stage.choices,
        default=Stage.RECEPTION,
    )
    priority = models.CharField(
        max_length=20,
        choices=Priority.choices,
        default=Priority.ROUTINE,
    )

    # Step 1: Reception Intake
    chief_complaint = models.TextField(blank=True, default="")
    # Past illnesses, family history, allergies collected at reception
    medical_history = models.TextField(blank=True, default="")
    assigned_doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="doctor_assigned_patients",
    )

    # Step 2: Doctor Review & Orders
    doctor_notes = models.TextField(blank=True, default="")
    diagnosis = models.CharField(max_length=255, blank=True, default="")
    treatment_plan = models.TextField(blank=True, default="")
    assigned_nurse = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="nurse_assigned_patients",
    )

    # Step 3: Nurse Assessment, Vitals & Blood Tests
    blood_group = models.CharField(max_length=10, blank=True, default="")
    blood_pressure = models.CharField(max_length=50, blank=True, default="")
    heart_rate = models.CharField(max_length=50, blank=True, default="")
    temperature = models.CharField(max_length=50, blank=True, default="")
    respiratory_rate = models.CharField(max_length=50, blank=True, default="")
    oxygen_saturation = models.CharField(max_length=50, blank=True, default="")
    blood_test_results = models.TextField(blank=True, default="")
    nurse_notes = models.TextField(blank=True, default="")
    assigned_admitting_provider = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="provider_assigned_patients",
    )

    # Step 4: Admitting Provider / Super Doctor Review & Final Disposition
    admission_decision = models.CharField(
        max_length=30,
        choices=AdmissionDecision.choices,
        default=AdmissionDecision.NOT_DECIDED,
    )
    admitting_notes = models.TextField(blank=True, default="")
    discharge_summary = models.TextField(blank=True, default="")

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_patients",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_archived = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.patient_id} - {self.first_name} {self.last_name}"


class Appointment(models.Model):

    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        CONFIRMED = "confirmed", "Confirmed"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    appointment_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    patient = models.ForeignKey(
        Patient,
        on_delete=models.PROTECT,
        related_name="appointments",
    )

    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="doctor_appointments",
    )

    scheduled_at = models.DateTimeField()
    description = models.TextField()

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.SCHEDULED,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_appointments",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["scheduled_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["doctor", "scheduled_at"],
                condition=~models.Q(status="cancelled"),
                name="unique_active_doctor_appointment_slot",
            ),
        ]

    def __str__(self):
        return f"{self.patient} - {self.scheduled_at}"


class UserProfile(models.Model):

    class Role(models.TextChoices):
        ADMIN = "admin", "Admin"
        SUPER_DOCTOR = "superdoctor", "Super Doctor (Admitting Provider)"
        DOCTOR = "doctor", "Doctor"
        NURSE = "nurse", "Nurse"
        RECEPTIONIST = "receptionist", "Receptionist"
        PATIENT = "patient", "Patient"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )

    last_otp_verified_date = models.DateField(
        null=True,
        blank=True,
    )

    patient = models.OneToOneField(
        Patient,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="user_profile",
    )

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.PATIENT,
    )

    def __str__(self):
        return f"{self.user.username} - {self.role}"


class LoginOTP(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="login_otps",
    )

    otp_hash = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    verified_at = models.DateTimeField(null=True, blank=True)
    attempt_count = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Login OTP for {self.user.username}"
