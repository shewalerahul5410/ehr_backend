"""
Role-based rules for the hospital care workflow.

Flow:
    reception ──(receptionist)──> doctor_review
    doctor_review ──(doctor)──> nurse_check          (needs vitals / blood work)
    nurse_check ──(nurse)──> doctor_review           (vitals done, back to doctor)
    doctor_review ──(doctor)──> admitting_provider   (serious case, admit)
    doctor_review ──(doctor)──> completed            (not serious, discharge)
    admitting_provider ──(superdoctor)──> completed  (final decision)

Each role may only edit its own fields, only while the patient is in its stage,
and doctors / nurses only for patients assigned to them.
"""

from rest_framework.exceptions import PermissionDenied, ValidationError

from .models import Patient, UserProfile

Stage = Patient.Stage
Role = UserProfile.Role

# Fields each role may write through the workflow endpoint
ROLE_FIELDS = {
    Role.RECEPTIONIST: {"chief_complaint", "medical_history", "priority", "assigned_doctor"},
    Role.DOCTOR: {
        "diagnosis",
        "doctor_notes",
        "treatment_plan",
        "priority",
        "assigned_nurse",
        "assigned_admitting_provider",
    },
    Role.NURSE: {
        "blood_group",
        "blood_pressure",
        "heart_rate",
        "temperature",
        "respiratory_rate",
        "oxygen_saturation",
        "blood_test_results",
        "nurse_notes",
    },
    Role.SUPER_DOCTOR: {"admission_decision", "admitting_notes", "discharge_summary"},
}

# Stage the patient must be in for the role to edit it
ROLE_STAGE = {
    Role.RECEPTIONIST: Stage.RECEPTION,
    Role.DOCTOR: Stage.DOCTOR_REVIEW,
    Role.NURSE: Stage.NURSE_CHECK,
    Role.SUPER_DOCTOR: Stage.ADMITTING_PROVIDER,
}

# Allowed (from_stage, to_stage) moves per role
ROLE_TRANSITIONS = {
    Role.RECEPTIONIST: {(Stage.RECEPTION, Stage.DOCTOR_REVIEW)},
    Role.DOCTOR: {
        (Stage.DOCTOR_REVIEW, Stage.NURSE_CHECK),
        (Stage.DOCTOR_REVIEW, Stage.ADMITTING_PROVIDER),
        (Stage.DOCTOR_REVIEW, Stage.COMPLETED),
    },
    Role.NURSE: {(Stage.NURSE_CHECK, Stage.DOCTOR_REVIEW)},
    Role.SUPER_DOCTOR: {(Stage.ADMITTING_PROVIDER, Stage.COMPLETED)},
}

# Something must be filled in before moving to the next stage
TRANSITION_REQUIREMENTS = {
    Stage.DOCTOR_REVIEW: ("assigned_doctor", "Assign a doctor before sending the patient to doctor review."),
    Stage.NURSE_CHECK: ("assigned_nurse", "Assign a nurse before sending the patient for vitals."),
    Stage.ADMITTING_PROVIDER: (
        "assigned_admitting_provider",
        "Assign a super doctor before admitting the patient.",
    ),
}


def get_role(user):
    # The profile role wins, so a super doctor who is also a Django superuser
    # still follows the super doctor rules
    profile = getattr(user, "profile", None)
    if profile:
        return profile.role
    return Role.ADMIN if user.is_superuser else None


def check_workflow_update(user, patient, data):
    """Raise PermissionDenied / ValidationError if this user may not apply `data`."""
    role = get_role(user)

    if role == Role.ADMIN:
        return

    if role not in ROLE_FIELDS:
        raise PermissionDenied("You do not have permission to update patient clinical workflows.")

    if role == Role.DOCTOR and patient.assigned_doctor_id != user.id:
        raise PermissionDenied("This patient is not assigned to you.")
    if role == Role.NURSE and patient.assigned_nurse_id != user.id:
        raise PermissionDenied("This patient is not assigned to you.")

    if patient.current_stage != ROLE_STAGE[role]:
        raise PermissionDenied(
            f"Patient is in '{patient.get_current_stage_display()}'. "
            "You can only update patients in your own stage."
        )

    blocked = set(data.keys()) - ROLE_FIELDS[role] - {"current_stage"}
    if blocked:
        raise PermissionDenied(f"Your role cannot edit: {', '.join(sorted(blocked))}.")

    next_stage = data.get("current_stage")
    if next_stage and next_stage != patient.current_stage:
        if (patient.current_stage, next_stage) not in ROLE_TRANSITIONS[role]:
            raise PermissionDenied("You cannot move the patient to that stage.")

        requirement = TRANSITION_REQUIREMENTS.get(next_stage)
        if requirement:
            field, message = requirement
            if not data.get(field) and not getattr(patient, f"{field}_id"):
                raise ValidationError({"detail": message})


def visible_patients(user, queryset):
    """Doctors and nurses only see patients assigned to them."""
    role = get_role(user)
    if role == Role.DOCTOR:
        return queryset.filter(assigned_doctor=user)
    if role == Role.NURSE:
        return queryset.filter(assigned_nurse=user)
    return queryset
