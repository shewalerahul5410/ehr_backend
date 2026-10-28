from django.core import signing

INVITATION_SALT = "core.patient.invitation"
INVITATION_MAX_AGE = 60 * 60 * 24  # 24 hours


def generate_invitation_token(patient_id, email):
    return signing.dumps(
        {
            "patient_id": str(patient_id),
            "email": email,
        },
        salt=INVITATION_SALT,
    )


def verify_invitation_token(token):
    return signing.loads(
        token,
        salt=INVITATION_SALT,
        max_age=INVITATION_MAX_AGE,
    )


STAFF_INVITATION_SALT = "core.staff.invitation"


def generate_staff_invitation_token(user_id, email):
    return signing.dumps(
        {
            "user_id": user_id,
            "email": email,
        },
        salt=STAFF_INVITATION_SALT,
    )


def verify_staff_invitation_token(token):
    return signing.loads(
        token,
        salt=STAFF_INVITATION_SALT,
        max_age=INVITATION_MAX_AGE,
    )
