from rest_framework.decorators import (
    api_view,
    permission_classes,
)
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from rest_framework.generics import (
    ListCreateAPIView,
    RetrieveUpdateAPIView,
    RetrieveUpdateDestroyAPIView,
    ListAPIView,
)
from rest_framework.views import APIView
from rest_framework.exceptions import PermissionDenied, ValidationError
from django.core.mail import send_mail
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from .models import Patient, Appointment, UserProfile
from .permissions import (
    IsClinicalStaff,
    IsReceptionist,
    IsPatient,
    IsDoctor,
    IsNurse,
    IsSuperDoctor,
    IsAdmin,
    IsAnyStaff,
)
from .serializers import (
    PatientSerializer,
    PatientWorkflowUpdateSerializer,
    AppointmentSerializer,
    UserProfileSerializer,
    StaffUserSerializer,
    PatientSetPasswordSerializer,
    ChangePasswordSerializer,
    StaffInviteSerializer,
    StaffSetPasswordSerializer,
    OTPLoginSerializer,
)

import secrets
from datetime import timedelta

from django.contrib.auth import authenticate
from django.contrib.auth.hashers import make_password, check_password
from rest_framework_simplejwt.tokens import RefreshToken

from .models import Patient, Appointment, UserProfile, LoginOTP
from .serializers import OTPLoginSerializer, OTPVerifySerializer


from .invitation_utils import (
    generate_invitation_token,
    generate_staff_invitation_token,
    verify_staff_invitation_token,
)
from .workflow import check_workflow_update, visible_patients, get_role

# Roles allowed to register patients and send patient invitations
FRONT_DESK_ROLES = [
    UserProfile.Role.RECEPTIONIST,
    UserProfile.Role.SUPER_DOCTOR,
    UserProfile.Role.ADMIN,
]


@api_view(["GET"])
@permission_classes([AllowAny])
def health_check(request):
    return Response(
        {
            "status": "success",
            "message": "EHR Management System API is running smoothly!",
        },
        status=status.HTTP_200_OK,
    )


class StaffListAPIView(ListAPIView):
    """
    Returns available staff members (doctors, nurses, superdoctors)
    so dropdowns can be populated dynamically for appointments and patient assignment.
    """

    serializer_class = StaffUserSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        User = get_user_model()
        role = self.request.query_params.get("role")
        queryset = User.objects.filter(is_active=True).select_related("profile")

        if role:
            # Assignment dropdowns: only staff who have activated their account
            return queryset.filter(profile__role=role.lower()).exclude(
                password__startswith="!"
            )

        # By default return all clinical & reception staff
        return queryset.filter(
            profile__role__in=[
                UserProfile.Role.DOCTOR,
                UserProfile.Role.SUPER_DOCTOR,
                UserProfile.Role.NURSE,
                UserProfile.Role.RECEPTIONIST,
                UserProfile.Role.ADMIN,
            ]
        )


class PatientListCreateAPIView(ListCreateAPIView):
    serializer_class = PatientSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        queryset = Patient.objects.filter(is_archived=False).select_related(
            "assigned_doctor",
            "assigned_nurse",
            "assigned_admitting_provider",
            "created_by",
        )

        if not user.is_superuser:
            role = (
                getattr(user.profile, "role", None)
                if hasattr(user, "profile")
                else None
            )

            # Patient only sees their own record
            if role == UserProfile.Role.PATIENT:
                if hasattr(user, "profile") and user.profile.patient:
                    return queryset.filter(patient_id=user.profile.patient.patient_id)
                return queryset.none()

        queryset = visible_patients(user, queryset)

        # Staff filtering
        stage = self.request.query_params.get("stage")
        if stage:
            queryset = queryset.filter(current_stage=stage)

        search = self.request.query_params.get("search")
        if search:
            queryset = (
                queryset.filter(first_name__icontains=search)
                | queryset.filter(last_name__icontains=search)
                | queryset.filter(email__icontains=search)
                | queryset.filter(phone_number__icontains=search)
            )

        return queryset

    def perform_create(self, serializer):
        user = self.request.user
        role = getattr(user.profile, "role", None) if hasattr(user, "profile") else None

        if not user.is_superuser and role not in FRONT_DESK_ROLES:
            raise PermissionDenied("Only reception can register patients.")

        patient = serializer.save(created_by=user)

        # Attempt to send invitation email if patient has an email address
        if patient.email:
            try:
                token = generate_invitation_token(patient.patient_id, patient.email)
                setup_url = f"http://localhost:5173/set-password/?token={token}"
                send_mail(
                    subject="Your EHR Patient Account Invitation",
                    message=(
                        f"Hello {patient.first_name} {patient.last_name},\n\n"
                        "Welcome to our Hospital EHR System. Your patient profile has been created.\n"
                        "Please use the link below to set your password and access your dashboard:\n\n"
                        f"{setup_url}\n\n"
                        "This link is valid for 24 hours.\n\n"
                        "Best regards,\nHospital Care Team"
                    ),
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[patient.email],
                    fail_silently=True,
                )
            except Exception:
                pass


class PatientDetailAPIView(RetrieveUpdateDestroyAPIView):
    serializer_class = PatientSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = "patient_id"

    def get_queryset(self):
        user = self.request.user
        queryset = Patient.objects.filter(is_archived=False).select_related(
            "assigned_doctor",
            "assigned_nurse",
            "assigned_admitting_provider",
            "created_by",
        )

        if not user.is_superuser:
            role = (
                getattr(user.profile, "role", None)
                if hasattr(user, "profile")
                else None
            )
            if role == UserProfile.Role.PATIENT:
                if hasattr(user, "profile") and user.profile.patient:
                    return queryset.filter(patient_id=user.profile.patient.patient_id)
                return queryset.none()

        return visible_patients(user, queryset)

    def perform_destroy(self, instance):
        user = self.request.user
        role = getattr(user.profile, "role", None) if hasattr(user, "profile") else None
        if not user.is_superuser and role not in [
            UserProfile.Role.ADMIN,
            UserProfile.Role.RECEPTIONIST,
        ]:
            raise PermissionDenied(
                "Only administrators and receptionists can archive patient records."
            )

        instance.is_archived = True
        instance.save(update_fields=["is_archived", "updated_at"])


class PatientWorkflowUpdateAPIView(APIView):
    """
    Dedicated endpoint for role-based patient stage progression:
    - Reception -> Doctor Review
    - Doctor Review -> Nurse Check (Vitals & Blood)
    - Nurse Check -> Admitting Provider (Super Doctor)
    - Admitting Provider -> Completed / Discharged
    """

    permission_classes = [IsAuthenticated]

    def patch(self, request, patient_id):
        try:
            patient = Patient.objects.get(patient_id=patient_id, is_archived=False)
        except Patient.DoesNotExist:
            return Response(
                {"detail": "Patient not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        check_workflow_update(request.user, patient, request.data)

        serializer = PatientWorkflowUpdateSerializer(
            patient,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        updated_patient = serializer.save()

        full_serializer = PatientSerializer(updated_patient)
        return Response(full_serializer.data, status=status.HTTP_200_OK)


class SendPatientInvitationAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, patient_id):
        try:
            patient = Patient.objects.get(
                patient_id=patient_id,
                is_archived=False,
            )
        except Patient.DoesNotExist:
            return Response(
                {"detail": "Patient record not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if get_role(request.user) not in FRONT_DESK_ROLES:
            raise PermissionDenied("Only reception can send patient invitations.")

        if not patient.email:
            return Response(
                {"email": "Patient email is required to send an invitation."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        User = get_user_model()
        if User.objects.filter(email__iexact=patient.email).exists():
            return Response(
                {"email": "A user account with this email already exists."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        token = generate_invitation_token(patient.patient_id, patient.email)
        setup_url = f"http://localhost:5173/set-password/?token={token}"

        try:
            send_mail(
                subject="Your EHR Patient Account Invitation",
                message=(
                    f"Hello {patient.first_name} {patient.last_name},\n\n"
                    "Your patient account invitation is ready.\n"
                    "Use the link below to set your password. "
                    "This link expires in 24 hours:\n\n"
                    f"{setup_url}\n\n"
                    "If you were not expecting this invitation, please contact the clinic."
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[patient.email],
                fail_silently=True,
            )
        except Exception:
            pass

        return Response(
            {
                "detail": "Patient invitation generated and sent successfully.",
                "setup_url": setup_url,
                "token": token,
            },
            status=status.HTTP_200_OK,
        )


class PatientSetPasswordAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        # Staff invitations use a different token; fall back to the patient flow
        try:
            verify_staff_invitation_token(request.data.get("token", ""))
            serializer_class = StaffSetPasswordSerializer
        except Exception:
            serializer_class = PatientSetPasswordSerializer

        serializer = serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            user = serializer.save()

            return Response(
                {
                    "detail": "Password set successfully! You can now log in.",
                    "username": user.username,
                    "email": user.email,
                    "role": user.profile.role,
                },
                status=status.HTTP_201_CREATED,
            )


class ChangePasswordAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(
            {"detail": "Password changed successfully."},
            status=status.HTTP_200_OK,
        )


class CurrentUserProfileAPIView(RetrieveUpdateAPIView):
    serializer_class = UserProfileSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        user_profile, created = UserProfile.objects.get_or_create(
            user=self.request.user,
            defaults={"role": UserProfile.Role.PATIENT},
        )
        return user_profile


class AppointmentListCreateAPIView(ListCreateAPIView):
    serializer_class = AppointmentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = Appointment.objects.select_related(
            "patient",
            "doctor",
            "created_by",
        ).all()

        user = self.request.user
        if not user.is_superuser:
            role = (
                getattr(user.profile, "role", None)
                if hasattr(user, "profile")
                else None
            )

            if role == UserProfile.Role.PATIENT:
                if not hasattr(user, "profile") or not user.profile.patient:
                    return queryset.none()
                return queryset.filter(patient=user.profile.patient)

            if role == UserProfile.Role.DOCTOR:
                queryset = queryset.filter(doctor=user)

        # Filters
        status_value = self.request.query_params.get("status")
        doctor_id = self.request.query_params.get("doctor_id")
        patient_id = self.request.query_params.get("patient_id")

        if status_value and status_value != "ALL":
            queryset = queryset.filter(status=status_value.lower())

        if doctor_id and doctor_id != "ALL":
            queryset = queryset.filter(doctor__id=doctor_id)

        if patient_id and patient_id != "ALL":
            queryset = queryset.filter(patient__patient_id=patient_id)

        return queryset

    def perform_create(self, serializer):
        user = self.request.user
        role = getattr(user.profile, "role", None) if hasattr(user, "profile") else None

        # If patient is booking, assign their own patient record
        if role == UserProfile.Role.PATIENT:
            if not hasattr(user, "profile") or not user.profile.patient:
                raise ValidationError(
                    "Your patient record is not linked to your user account."
                )
            appointment = serializer.save(
                created_by=user,
                patient=user.profile.patient,
            )
        else:
            appointment = serializer.save(created_by=user)

        # Send confirmation email
        if appointment.patient and appointment.patient.email:
            try:
                doctor_name = (
                    f"{appointment.doctor.first_name} {appointment.doctor.last_name}".strip()
                    or appointment.doctor.username
                )
                send_mail(
                    subject="EHR Appointment Scheduled",
                    message=(
                        f"Hello {appointment.patient.first_name},\n\n"
                        "Your appointment has been scheduled successfully.\n\n"
                        f"Doctor: {doctor_name}\n"
                        f"Date and time: {timezone.localtime(appointment.scheduled_at):%d %b %Y, %I:%M %p} (IST)\n"
                        f"Reason: {appointment.description}\n"
                        f"Status: {appointment.status}\n\n"
                        "Thank you for choosing our EHR Healthcare System."
                    ),
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[appointment.patient.email],
                    fail_silently=True,
                )
            except Exception:
                pass


class AppointmentDetailAPIView(RetrieveUpdateAPIView):
    serializer_class = AppointmentSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = "appointment_id"

    def get_queryset(self):
        queryset = Appointment.objects.select_related(
            "patient",
            "doctor",
            "created_by",
        )

        user = self.request.user
        if user.is_superuser:
            return queryset

        role = getattr(user.profile, "role", None) if hasattr(user, "profile") else None

        if role == UserProfile.Role.PATIENT:
            if not hasattr(user, "profile") or not user.profile.patient:
                return queryset.none()
            return queryset.filter(patient=user.profile.patient)

        if role == UserProfile.Role.DOCTOR:
            return queryset.filter(doctor=user)

        return queryset


class StaffInviteAPIView(APIView):
    """Super doctor adds a doctor, nurse or receptionist and emails them a set-password link."""

    permission_classes = [IsSuperDoctor]

    def post(self, request):
        serializer = StaffInviteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        setup_url = send_staff_invitation(user)

        return Response(
            {
                "detail": f"Invitation sent to {user.email}.",
                "setup_url": setup_url,
                "staff": StaffUserSerializer(user).data,
            },
            status=status.HTTP_201_CREATED,
        )


class StaffResendInviteAPIView(APIView):
    permission_classes = [IsSuperDoctor]

    def post(self, request, user_id):
        User = get_user_model()
        try:
            user = User.objects.get(
                pk=user_id, profile__role__in=StaffInviteSerializer.INVITABLE_ROLES
            )
        except User.DoesNotExist:
            return Response(
                {"detail": "Staff member not found."}, status=status.HTTP_404_NOT_FOUND
            )

        if user.has_usable_password():
            return Response(
                {"detail": "This staff member has already activated their account."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        setup_url = send_staff_invitation(user)
        return Response(
            {"detail": f"Invitation re-sent to {user.email}.", "setup_url": setup_url}
        )


def send_staff_invitation(user):
    token = generate_staff_invitation_token(user.pk, user.email)
    setup_url = f"http://localhost:5173/set-password/?token={token}"
    try:
        send_mail(
            subject="Your EHR Staff Account Invitation",
            message=(
                f"Hello {user.first_name},\n\n"
                f"You have been added to the EHR Healthcare system as {user.profile.get_role_display()}.\n"
                "Use the link below to set your password. This link expires in 24 hours:\n\n"
                f"{setup_url}\n\n"
                "Your username is your email address."
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=True,
        )
    except Exception:
        pass
    return setup_url


class OTPLoginAPIView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = OTPLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        username = serializer.validated_data["username"].strip()
        password = serializer.validated_data["password"]

        # Allow signing in with the account email as well as the username.
        if "@" in username:
            matched_user = (
                get_user_model().objects.filter(email__iexact=username).first()
            )
            if matched_user is not None:
                username = matched_user.username

        user = authenticate(
            request,
            username=username,
            password=password,
        )

        if user is None or not user.is_active:
            return Response(
                {"detail": "Invalid username or password."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        if not user.email:
            return Response(
                {"detail": "No email address is configured for this account."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Invalidate previous OTPs before issuing a new one.
        LoginOTP.objects.filter(
            user=user,
            is_used=False,
        ).update(is_used=True)

        otp = f"{secrets.randbelow(1_000_000):06d}"

        otp_record = LoginOTP.objects.create(
            user=user,
            otp_hash=make_password(otp),
            expires_at=timezone.now() + timedelta(minutes=5),
        )

        try:
            send_mail(
                subject="Your EHR Login Verification Code",
                message=(
                    f"Hello {user.first_name or user.username},\n\n"
                    f"Your EHR login verification code is: {otp}\n\n"
                    "This code expires in 5 minutes. "
                    "Do not share it with anyone."
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                fail_silently=False,
            )
        except Exception:
            otp_record.delete()
            return Response(
                {"detail": "Unable to send the verification code. Please try again."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response(
            {
                "detail": "Verification code sent to your registered email.",
                "username": user.username,
            },
            status=status.HTTP_200_OK,
        )


class OTPVerifyAPIView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = OTPVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        username = serializer.validated_data["username"]
        otp = serializer.validated_data["otp"]

        User = get_user_model()

        try:
            user = User.objects.get(username=username, is_active=True)
        except User.DoesNotExist:
            return Response(
                {"detail": "Invalid or expired verification code."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        otp_record = LoginOTP.objects.filter(
            user=user,
            is_used=False,
            expires_at__gt=timezone.now(),
        ).first()

        if otp_record is None:
            return Response(
                {"detail": "Invalid or expired verification code."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if otp_record.attempt_count >= 5:
            otp_record.is_used = True
            otp_record.save(update_fields=["is_used"])
            return Response(
                {"detail": "Too many attempts. Please request a new code."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        if not check_password(otp, otp_record.otp_hash):
            otp_record.attempt_count += 1
            otp_record.save(update_fields=["attempt_count"])

            return Response(
                {"detail": "Invalid or expired verification code."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        otp_record.is_used = True
        otp_record.verified_at = timezone.now()
        otp_record.save(update_fields=["is_used", "verified_at"])

        UserProfile.objects.filter(user=user).update(
            last_otp_verified_date=timezone.localdate()
        )
        refresh = RefreshToken.for_user(user)

        return Response(
            {
                "detail": "Login successful.",
                "access": str(refresh.access_token),
                "refresh": str(refresh),
            },
            status=status.HTTP_200_OK,
        )
