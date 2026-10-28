from datetime import date
from django.utils import timezone
from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password


from .models import Patient, Appointment, UserProfile, DoctorAvailability
from .invitation_utils import (
    generate_invitation_token,
    verify_invitation_token,
    verify_staff_invitation_token,
)


class StaffUserSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    role = serializers.CharField(source="profile.role", read_only=True)
    has_password = serializers.SerializerMethodField()

    class Meta:
        model = get_user_model()
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "full_name",
            "role",
            "has_password",
        ]

    def get_has_password(self, obj):
        return obj.has_usable_password()

    def get_full_name(self, obj):
        name = f"{obj.first_name} {obj.last_name}".strip()
        return name if name else obj.username


class PatientSerializer(serializers.ModelSerializer):
    age = serializers.SerializerMethodField()
    created_by = serializers.PrimaryKeyRelatedField(read_only=True)
    assigned_doctor_name = serializers.SerializerMethodField()
    assigned_nurse_name = serializers.SerializerMethodField()
    assigned_admitting_provider_name = serializers.SerializerMethodField()
    invitation_link = serializers.SerializerMethodField()

    class Meta:
        model = Patient
        fields = [
            "patient_id",
            "first_name",
            "last_name",
            "date_of_birth",
            "age",
            "gender",
            "phone_number",
            "email",
            "address",
            "emergency_contact_name",
            "emergency_contact_phone",
            "current_stage",
            "priority",
            "chief_complaint",
            "medical_history",
            "assigned_doctor",
            "assigned_doctor_name",
            "doctor_notes",
            "diagnosis",
            "treatment_plan",
            "assigned_nurse",
            "assigned_nurse_name",
            "blood_group",
            "blood_pressure",
            "heart_rate",
            "temperature",
            "respiratory_rate",
            "oxygen_saturation",
            "blood_test_results",
            "nurse_notes",
            "assigned_admitting_provider",
            "assigned_admitting_provider_name",
            "admission_decision",
            "admitting_notes",
            "discharge_summary",
            "created_by",
            "created_at",
            "updated_at",
            "is_archived",
            "invitation_link",
        ]
        read_only_fields = [
            "patient_id",
            "age",
            "created_by",
            "created_at",
            "updated_at",
            "is_archived",
            "assigned_doctor_name",
            "assigned_nurse_name",
            "assigned_admitting_provider_name",
            "invitation_link",
        ]

    def get_age(self, obj):
        if not obj.date_of_birth:
            return None
        today = date.today()
        age = today.year - obj.date_of_birth.year
        if (today.month, today.day) < (
            obj.date_of_birth.month,
            obj.date_of_birth.day,
        ):
            age -= 1
        return age

    def get_assigned_doctor_name(self, obj):
        if obj.assigned_doctor:
            name = f"{obj.assigned_doctor.first_name} {obj.assigned_doctor.last_name}".strip()
            return name if name else obj.assigned_doctor.username
        return None

    def get_assigned_nurse_name(self, obj):
        if obj.assigned_nurse:
            name = f"{obj.assigned_nurse.first_name} {obj.assigned_nurse.last_name}".strip()
            return name if name else obj.assigned_nurse.username
        return None

    def get_assigned_admitting_provider_name(self, obj):
        if obj.assigned_admitting_provider:
            name = f"{obj.assigned_admitting_provider.first_name} {obj.assigned_admitting_provider.last_name}".strip()
            return name if name else obj.assigned_admitting_provider.username
        return None

    def get_invitation_link(self, obj):
        if not obj.email:
            return None
        token = generate_invitation_token(obj.patient_id, obj.email)
        return f"http://localhost:5173/set-password/?token={token}"

    def validate_date_of_birth(self, value):
        if value > date.today():
            raise serializers.ValidationError("Date of birth cannot be in the future.")
        return value

    def validate_email(self, value):
        if not value:
            return value

        existing_patient = Patient.objects.filter(
            email__iexact=value,
            is_archived=False,
        )

        if self.instance:
            existing_patient = existing_patient.exclude(pk=self.instance.pk)

        if existing_patient.exists():
            raise serializers.ValidationError(
                "A patient with this email already exists."
            )

        return value


class PatientWorkflowUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Patient
        fields = [
            "current_stage",
            "priority",
            "chief_complaint",
            "medical_history",
            "assigned_doctor",
            "doctor_notes",
            "diagnosis",
            "treatment_plan",
            "assigned_nurse",
            "blood_group",
            "blood_pressure",
            "heart_rate",
            "temperature",
            "respiratory_rate",
            "oxygen_saturation",
            "blood_test_results",
            "nurse_notes",
            "assigned_admitting_provider",
            "admission_decision",
            "admitting_notes",
            "discharge_summary",
        ]


class PatientRelatedField(serializers.RelatedField):
    def get_queryset(self):
        return Patient.objects.filter(is_archived=False)

    def to_internal_value(self, data):
        try:
            return Patient.objects.get(patient_id=data, is_archived=False)
        except Exception:
            try:
                return Patient.objects.get(pk=data, is_archived=False)
            except Exception:
                raise serializers.ValidationError("Active patient record not found.")

    def to_representation(self, value):
        return str(value.patient_id)


class AppointmentSerializer(serializers.ModelSerializer):
    patient_name = serializers.SerializerMethodField()
    doctor_name = serializers.SerializerMethodField()
    patient = PatientRelatedField(required=False)

    class Meta:
        model = Appointment
        fields = [
            "appointment_id",
            "patient",
            "patient_name",
            "doctor",
            "doctor_name",
            "scheduled_at",
            "description",
            "status",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "appointment_id",
            "patient_name",
            "doctor_name",
            "created_by",
            "created_at",
            "updated_at",
        ]

    def get_patient_name(self, obj):
        if obj.patient:
            return f"{obj.patient.first_name} {obj.patient.last_name}".strip()
        return "Unknown Patient"

    def get_doctor_name(self, obj):
        if obj.doctor:
            name = f"{obj.doctor.first_name} {obj.doctor.last_name}".strip()
            return name if name else obj.doctor.username
        return "Unknown Doctor"

    def validate_scheduled_at(self, value):
        if timezone.is_naive(value):
            value = timezone.make_aware(
                value,
                timezone.get_current_timezone(),
            )

        if value <= timezone.now():
            raise serializers.ValidationError(
                "Appointment must be scheduled in the future."
            )

        return value

    def validate_patient(self, value):
        if value and value.is_archived:
            raise serializers.ValidationError(
                "Cannot schedule an appointment for an archived patient."
            )
        return value

    def validate(self, data):
        doctor = data.get(
            "doctor",
            self.instance.doctor if self.instance else None,
        )

        scheduled_at = data.get(
            "scheduled_at",
            self.instance.scheduled_at if self.instance else None,
        )

        if doctor and scheduled_at:
            if timezone.is_naive(scheduled_at):
                scheduled_at = timezone.make_aware(
                    scheduled_at,
                    timezone.get_current_timezone(),
                )

            local_datetime = timezone.localtime(scheduled_at)
            appointment_date = local_datetime.date()
            appointment_time = local_datetime.time().replace(
                second=0,
                microsecond=0,
            )
            weekday = appointment_date.strftime("%A").lower()

            availability = DoctorAvailability.objects.filter(
                doctor=doctor,
                weekday=weekday,
                is_available=True,
            ).first()

            if not availability:
                raise serializers.ValidationError(
                    {
                        "scheduled_at": (
                            "This doctor is not available on the selected day."
                        )
                    }
                )

            slot_seconds = appointment_time.hour * 3600 + appointment_time.minute * 60
            start_seconds = (
                availability.start_time.hour * 3600
                + availability.start_time.minute * 60
            )
            end_seconds = (
                availability.end_time.hour * 3600 + availability.end_time.minute * 60
            )

            if (
                slot_seconds < start_seconds
                or slot_seconds + 3600 > end_seconds
                or slot_seconds % 3600 != start_seconds % 3600
                or local_datetime.second != 0
                or local_datetime.microsecond != 0
            ):
                raise serializers.ValidationError(
                    {
                        "scheduled_at": (
                            "Select a valid one-hour slot within the doctor's "
                            "working hours."
                        )
                    }
                )

            existing_appointments = Appointment.objects.filter(
                doctor=doctor,
                scheduled_at=scheduled_at,
            ).exclude(status=Appointment.Status.CANCELLED)

            if self.instance:
                existing_appointments = existing_appointments.exclude(
                    appointment_id=self.instance.appointment_id
                )

                if existing_appointments.exists():
                    raise serializers.ValidationError(
                        {
                            "scheduled_at": (
                                "This doctor already has an active appointment "
                                "scheduled at this time. Please select another slot."
                            )
                        }
                    )

                return data


class UserProfileSerializer(serializers.ModelSerializer):
    username = serializers.CharField(
        source="user.username",
        read_only=True,
    )
    email = serializers.EmailField(
        source="user.email",
        required=False,
    )
    first_name = serializers.CharField(
        source="user.first_name",
        required=False,
        allow_blank=True,
    )
    last_name = serializers.CharField(
        source="user.last_name",
        required=False,
        allow_blank=True,
    )
    patient_id = serializers.UUIDField(
        source="patient.patient_id",
        read_only=True,
    )

    class Meta:
        model = UserProfile
        fields = [
            "username",
            "email",
            "first_name",
            "last_name",
            "role",
            "patient_id",
        ]
        read_only_fields = [
            "username",
            "role",
            "patient_id",
        ]

    def update(self, instance, validated_data):
        user_data = validated_data.pop("user", {})
        user = instance.user
        if "first_name" in user_data:
            user.first_name = user_data["first_name"]
        if "last_name" in user_data:
            user.last_name = user_data["last_name"]
        if "email" in user_data:
            user.email = user_data["email"]
        user.save()
        return super().update(instance, validated_data)


class PatientSetPasswordSerializer(serializers.Serializer):
    token = serializers.CharField()
    password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
    )
    confirm_password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
    )

    def validate(self, attrs):
        if attrs["password"] != attrs["confirm_password"]:
            raise serializers.ValidationError(
                {"confirm_password": "Passwords do not match."}
            )

        try:
            invitation_data = verify_invitation_token(attrs["token"])
        except Exception:
            raise serializers.ValidationError(
                {"token": "Invalid or expired invitation link."}
            )

        patient_id = invitation_data.get("patient_id")
        email = invitation_data.get("email")

        try:
            patient = Patient.objects.get(
                patient_id=patient_id,
                email__iexact=email,
                is_archived=False,
            )
        except (Patient.DoesNotExist, ValueError, TypeError):
            raise serializers.ValidationError(
                {"token": "The invitation does not match an active patient record."}
            )

        User = get_user_model()
        if User.objects.filter(email__iexact=patient.email).exists():
            raise serializers.ValidationError(
                {
                    "email": "An account already exists for this email address. Please login directly."
                }
            )

        attrs["patient"] = patient
        validate_password(attrs["password"])

        return attrs

    def create(self, validated_data):
        patient = validated_data["patient"]
        User = get_user_model()

        username = patient.email
        # Ensure unique username
        counter = 1
        base_username = username
        while User.objects.filter(username=username).exists():
            username = f"{base_username}{counter}"
            counter += 1

        user = User.objects.create_user(
            username=username,
            email=patient.email,
            password=validated_data["password"],
            first_name=patient.first_name,
            last_name=patient.last_name,
        )

        UserProfile.objects.update_or_create(
            user=user,
            defaults={
                "role": UserProfile.Role.PATIENT,
                "patient": patient,
            },
        )

        return user


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
    )
    new_password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
    )
    confirm_password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
    )

    def validate(self, attrs):
        user = self.context["request"].user

        if not user.check_password(attrs["current_password"]):
            raise serializers.ValidationError(
                {"current_password": "Current password is incorrect."}
            )

        if attrs["new_password"] != attrs["confirm_password"]:
            raise serializers.ValidationError(
                {"confirm_password": "New passwords do not match."}
            )

        validate_password(attrs["new_password"], user=user)

        return attrs

    def save(self, **kwargs):
        user = self.context["request"].user
        user.set_password(self.validated_data["new_password"])
        user.save(update_fields=["password"])
        return user


class StaffInviteSerializer(serializers.Serializer):
    """Super doctor adds a doctor, nurse or receptionist and invites them by email."""

    INVITABLE_ROLES = [
        UserProfile.Role.DOCTOR,
        UserProfile.Role.NURSE,
        UserProfile.Role.RECEPTIONIST,
    ]

    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    email = serializers.EmailField()
    role = serializers.ChoiceField(choices=INVITABLE_ROLES)

    def validate_email(self, value):
        if get_user_model().objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value

    def create(self, validated_data):
        User = get_user_model()
        user = User(
            username=validated_data["email"],
            email=validated_data["email"],
            first_name=validated_data["first_name"],
            last_name=validated_data.get("last_name", ""),
        )
        user.set_unusable_password()
        user.save()
        UserProfile.objects.create(user=user, role=validated_data["role"])
        return user


class StaffSetPasswordSerializer(serializers.Serializer):
    """Accepts a staff invitation token and sets the invited user's first password."""

    token = serializers.CharField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    confirm_password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate(self, attrs):
        if attrs["password"] != attrs["confirm_password"]:
            raise serializers.ValidationError(
                {"confirm_password": "Passwords do not match."}
            )

        try:
            data = verify_staff_invitation_token(attrs["token"])
            user = get_user_model().objects.get(
                pk=data["user_id"], email__iexact=data["email"]
            )
        except Exception:
            raise serializers.ValidationError(
                {"token": "Invalid or expired invitation link."}
            )

        if user.has_usable_password():
            raise serializers.ValidationError(
                {"token": "This invitation was already used. Please login directly."}
            )

        validate_password(attrs["password"], user=user)
        attrs["user"] = user
        return attrs

    def create(self, validated_data):
        user = validated_data["user"]
        user.set_password(validated_data["password"])
        user.save(update_fields=["password"])
        return user


class OTPLoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
    )


class OTPVerifySerializer(serializers.Serializer):
    username = serializers.CharField()
    otp = serializers.CharField(
        min_length=6,
        max_length=6,
        trim_whitespace=False,
    )


class DoctorAvailabilitySerializer(serializers.ModelSerializer):
    doctor_name = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = DoctorAvailability
        fields = [
            "id",
            "doctor",
            "doctor_name",
            "weekday",
            "start_time",
            "end_time",
            "is_available",
            "created_at",
            "updated_at",
        ]

        read_only_fields = [
            "id",
            "doctor",
            "doctor_name",
            "created_at",
            "updated_at",
        ]

    def get_doctor_name(self, obj):
        name = f"{obj.doctor.first_name} {obj.doctor.last_name}".strip()
        return name if name else obj.doctor.username

    def validate(self, attrs):
        start_time = attrs.get(
            "start_time",
            self.instance.start_time if self.instance else None,
        )
        end_time = attrs.get(
            "end_time",
            self.instance.end_time if self.instance else None,
        )

        if start_time and end_time and start_time >= end_time:
            raise serializers.ValidationError(
                {"end_time": "End time must be later than start time."}
            )

        return attrs
