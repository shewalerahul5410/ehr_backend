from rest_framework.permissions import BasePermission


class IsAdmin(BasePermission):
    message = "You must be an admin to access this resource."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        return (
            hasattr(request.user, "profile")
            and request.user.profile.role in ["admin", "superdoctor"]
        )


class HasRole(BasePermission):
    allowed_roles = []

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.user.is_superuser:
            return True

        try:
            return request.user.profile.role in self.allowed_roles
        except Exception:
            return False


class IsSuperDoctor(HasRole):
    allowed_roles = ["superdoctor", "admin"]


class IsDoctor(HasRole):
    allowed_roles = ["doctor", "superdoctor", "admin"]


class IsNurse(HasRole):
    allowed_roles = ["nurse", "admin"]


class IsReceptionist(HasRole):
    allowed_roles = ["receptionist", "admin"]


class IsPatient(HasRole):
    allowed_roles = ["patient"]


class IsClinicalStaff(HasRole):
    allowed_roles = ["doctor", "nurse", "superdoctor", "admin"]


class IsAnyStaff(HasRole):
    allowed_roles = ["doctor", "nurse", "superdoctor", "receptionist", "admin"]
