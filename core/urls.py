from django.urls import path
from .views import (
    AppointmentDetailAPIView,
    AppointmentListCreateAPIView,
    CurrentUserProfileAPIView,
    PatientDetailAPIView,
    PatientListCreateAPIView,
    PatientWorkflowUpdateAPIView,
    SendPatientInvitationAPIView,
    PatientSetPasswordAPIView,
    ChangePasswordAPIView,
    StaffListAPIView,
    StaffInviteAPIView,
    StaffResendInviteAPIView,
    health_check,
    OTPLoginAPIView,
    OTPVerifyAPIView,
    DoctorAvailabilityListCreateAPIView,
    AvailableAppointmentSlotsAPIView,
    DoctorAvailabilityDetailAPIView,
)

urlpatterns = [
    path("health/", health_check, name="health_check"),
    path("staff/", StaffListAPIView.as_view(), name="staff_list"),
    path("staff/invite/", StaffInviteAPIView.as_view(), name="staff_invite"),
    path(
        "staff/<int:user_id>/resend-invite/",
        StaffResendInviteAPIView.as_view(),
        name="staff_resend_invite",
    ),
    path("patients/", PatientListCreateAPIView.as_view(), name="patient_list_create"),
    path(
        "patients/<uuid:patient_id>/",
        PatientDetailAPIView.as_view(),
        name="patient_detail",
    ),
    path(
        "patients/<uuid:patient_id>/workflow/",
        PatientWorkflowUpdateAPIView.as_view(),
        name="patient_workflow_update",
    ),
    path(
        "patients/<uuid:patient_id>/send-invitation/",
        SendPatientInvitationAPIView.as_view(),
        name="send_patient_invitation",
    ),
    path(
        "appointments/",
        AppointmentListCreateAPIView.as_view(),
        name="appointment_list_create",
    ),
    path(
        "appointments/<uuid:appointment_id>/",
        AppointmentDetailAPIView.as_view(),
        name="appointment_detail",
    ),
    path("auth/me/", CurrentUserProfileAPIView.as_view(), name="user_profile"),
    path(
        "auth/set-password/",
        PatientSetPasswordAPIView.as_view(),
        name="patient_set_password",
    ),
    path(
        "auth/change-password/",
        ChangePasswordAPIView.as_view(),
        name="change_password",
    ),
    path("auth/login/", OTPLoginAPIView.as_view(), name="otp_login"),
    path("auth/verify-otp/", OTPVerifyAPIView.as_view(), name="otp_verify"),
    path(
        "doctor-availability/",
        DoctorAvailabilityListCreateAPIView.as_view(),
        name="doctor-availability",
    ),
    path(
        "available-slots/",
        AvailableAppointmentSlotsAPIView.as_view(),
        name="available-slots",
    ),
    path(
        "doctor-availability/<int:id>/",
        DoctorAvailabilityDetailAPIView.as_view(),
        name="doctor-availability-detail",
    ),
]
