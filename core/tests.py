from datetime import date, timedelta
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase
from rest_framework import status

from core.models import Patient, Appointment, UserProfile
from core.invitation_utils import generate_invitation_token

User = get_user_model()


class EHRWorkflowTests(APITestCase):
    def setUp(self):
        # 1. Create Receptionist
        self.receptionist_user = User.objects.create_user(
            username="test_receptionist",
            email="receptionist@hospital.com",
            password="Password@123",
        )
        UserProfile.objects.create(
            user=self.receptionist_user,
            role=UserProfile.Role.RECEPTIONIST,
        )

        # 2. Create Doctor
        self.doctor_user = User.objects.create_user(
            username="test_doctor",
            email="doctor@hospital.com",
            password="Password@123",
        )
        UserProfile.objects.create(
            user=self.doctor_user,
            role=UserProfile.Role.DOCTOR,
        )

        # 3. Create Nurse
        self.nurse_user = User.objects.create_user(
            username="test_nurse",
            email="nurse@hospital.com",
            password="Password@123",
        )
        UserProfile.objects.create(
            user=self.nurse_user,
            role=UserProfile.Role.NURSE,
        )

        # 4. Create Super Doctor (Admitting Provider)
        self.superdoctor_user = User.objects.create_user(
            username="test_superdoctor",
            email="superdoctor@hospital.com",
            password="Password@123",
        )
        UserProfile.objects.create(
            user=self.superdoctor_user,
            role=UserProfile.Role.SUPER_DOCTOR,
        )

    def test_full_hospital_workflow_and_patient_journey(self):
        """
        Tests complete hospital workflow:
        1. Receptionist registers patient and generates invitation link.
        2. Patient sets password with token and logs in.
        3. Patient schedules an appointment.
        4. Doctor reviews patient, adds diagnosis, forwards to nurse.
        5. Nurse records vitals and blood test, forwards to super doctor.
        6. Super doctor decides admission and completes patient care.
        """
        # Step 1: Receptionist registers patient
        self.client.force_authenticate(user=self.receptionist_user)

        patient_data = {
            "first_name": "Arthur",
            "last_name": "Dent",
            "date_of_birth": "1985-03-11",
            "gender": "M",
            "email": "arthur.dent@galaxy.com",
            "phone_number": "+1-555-4242",
            "priority": "urgent",
            "chief_complaint": "Persistent chest pain and panic.",
            "assigned_doctor": self.doctor_user.id,
            "current_stage": "doctor_review",
        }

        create_res = self.client.post("/api/v1/patients/", patient_data, format="json")
        self.assertEqual(create_res.status_code, status.HTTP_201_CREATED)
        patient_id = create_res.data["patient_id"]
        invitation_link = create_res.data["invitation_link"]
        self.assertIsNotNone(invitation_link)
        self.assertIn("token=", invitation_link)

        # Step 2: Patient sets password via public invitation link
        self.client.force_authenticate(user=None)  # unauthenticated visitor

        token = generate_invitation_token(patient_id, "arthur.dent@galaxy.com")
        set_pw_res = self.client.post(
            "/api/v1/auth/set-password/",
            {
                "token": token,
                "password": "SecurePassword@123",
                "confirm_password": "SecurePassword@123",
            },
            format="json",
        )
        self.assertEqual(set_pw_res.status_code, status.HTTP_201_CREATED)

        # Verify patient user account was created
        patient_user = User.objects.get(email="arthur.dent@galaxy.com")
        self.assertEqual(patient_user.profile.role, UserProfile.Role.PATIENT)
        self.assertEqual(str(patient_user.profile.patient.patient_id), str(patient_id))

        # Step 3: Patient logs in and schedules an appointment
        self.client.force_authenticate(user=patient_user)

        scheduled_time = (timezone.now() + timedelta(days=2)).isoformat()
        appt_res = self.client.post(
            "/api/v1/appointments/",
            {
                "doctor": self.doctor_user.id,
                "scheduled_at": scheduled_time,
                "description": "Follow-up consultation on chest pain.",
            },
            format="json",
        )
        self.assertEqual(appt_res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(appt_res.data["doctor"], self.doctor_user.id)

        # Verify patient only sees their own record
        patient_list_res = self.client.get("/api/v1/patients/")
        self.assertEqual(patient_list_res.status_code, status.HTTP_200_OK)
        results = patient_list_res.data if isinstance(patient_list_res.data, list) else patient_list_res.data["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["email"], "arthur.dent@galaxy.com")

        # Step 4: Doctor reviews patient, adds diagnosis, forwards to nurse
        self.client.force_authenticate(user=self.doctor_user)

        doctor_patch_res = self.client.patch(
            f"/api/v1/patients/{patient_id}/workflow/",
            {
                "diagnosis": "Mild Cardiac Arrhythmia",
                "doctor_notes": "ECG required. Check cardiac enzymes and blood panel.",
                "treatment_plan": "Nurse to take vitals, blood draw for CBC & troponin.",
                "assigned_nurse": self.nurse_user.id,
                "current_stage": "nurse_check",
            },
            format="json",
        )
        self.assertEqual(doctor_patch_res.status_code, status.HTTP_200_OK)
        self.assertEqual(doctor_patch_res.data["current_stage"], "nurse_check")
        self.assertEqual(doctor_patch_res.data["diagnosis"], "Mild Cardiac Arrhythmia")

        # Step 5: Nurse records vitals and blood test, sends back to the doctor
        self.client.force_authenticate(user=self.nurse_user)

        nurse_patch_res = self.client.patch(
            f"/api/v1/patients/{patient_id}/workflow/",
            {
                "blood_pressure": "130/85 mmHg",
                "heart_rate": "88 bpm",
                "temperature": "98.9 F",
                "blood_group": "A+",
                "oxygen_saturation": "99%",
                "blood_test_results": "CBC normal, troponin negative, glucose 95 mg/dL.",
                "nurse_notes": "Vitals stable. Patient rested in bed 4.",
                "current_stage": "doctor_review",
            },
            format="json",
        )
        self.assertEqual(nurse_patch_res.status_code, status.HTTP_200_OK)
        self.assertEqual(nurse_patch_res.data["current_stage"], "doctor_review")
        self.assertEqual(nurse_patch_res.data["blood_pressure"], "130/85 mmHg")

        # Step 5b: Doctor reviews vitals and admits the patient to the super doctor
        self.client.force_authenticate(user=self.doctor_user)
        admit_res = self.client.patch(
            f"/api/v1/patients/{patient_id}/workflow/",
            {
                "assigned_admitting_provider": self.superdoctor_user.id,
                "current_stage": "admitting_provider",
            },
            format="json",
        )
        self.assertEqual(admit_res.status_code, status.HTTP_200_OK)
        self.assertEqual(admit_res.data["current_stage"], "admitting_provider")

        # Step 6: Super Doctor (Admitting Provider) reviews and decides admission
        self.client.force_authenticate(user=self.superdoctor_user)

        super_doc_res = self.client.patch(
            f"/api/v1/patients/{patient_id}/workflow/",
            {
                "admission_decision": "outpatient",
                "admitting_notes": "Troponin negative, vitals normalized. Inpatient admission not indicated.",
                "discharge_summary": "Discharged with beta-blocker prescription. Follow-up in 1 week.",
                "current_stage": "completed",
            },
            format="json",
        )
        self.assertEqual(super_doc_res.status_code, status.HTTP_200_OK)
        self.assertEqual(super_doc_res.data["current_stage"], "completed")
        self.assertEqual(super_doc_res.data["admission_decision"], "outpatient")

    def test_permissions_and_conflict_validation(self):
        # Unauthenticated request to patients list
        self.client.force_authenticate(user=None)
        unauth_res = self.client.get("/api/v1/patients/")
        self.assertEqual(unauth_res.status_code, status.HTTP_401_UNAUTHORIZED)

        # Conflict check for appointments
        self.client.force_authenticate(user=self.receptionist_user)
        patient = Patient.objects.create(
            first_name="Ford",
            last_name="Prefect",
            date_of_birth=date(1980, 1, 1),
            gender="M",
            created_by=self.receptionist_user,
        )

        time_slot = (timezone.now() + timedelta(days=3)).replace(minute=0, second=0, microsecond=0)
        Appointment.objects.create(
            patient=patient,
            doctor=self.doctor_user,
            scheduled_at=time_slot,
            description="Slot 1",
            created_by=self.receptionist_user,
        )

        # Try to schedule conflicting appointment at the exact same slot
        conflict_res = self.client.post(
            "/api/v1/appointments/",
            {
                "patient": patient.patient_id,
                "doctor": self.doctor_user.id,
                "scheduled_at": time_slot.isoformat(),
                "description": "Conflicting Slot",
            },
            format="json",
        )
        self.assertEqual(conflict_res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(
            "scheduled_at" in conflict_res.data or "non_field_errors" in conflict_res.data
        )


class RoleWorkflowPermissionTests(APITestCase):
    def make_user(self, name, role):
        user = User.objects.create_user(username=name, email=f"{name}@h.com", password="Password@123")
        UserProfile.objects.create(user=user, role=role)
        return user

    def setUp(self):
        self.reception = self.make_user("rec", UserProfile.Role.RECEPTIONIST)
        self.doctor = self.make_user("doc", UserProfile.Role.DOCTOR)
        self.other_doctor = self.make_user("doc2", UserProfile.Role.DOCTOR)
        self.nurse = self.make_user("nurse", UserProfile.Role.NURSE)
        self.superdoctor = self.make_user("super", UserProfile.Role.SUPER_DOCTOR)
        self.patient = Patient.objects.create(
            first_name="Ford",
            last_name="Prefect",
            date_of_birth=date(1980, 1, 1),
            gender="M",
            created_by=self.reception,
        )
        self.url = f"/api/v1/patients/{self.patient.patient_id}/workflow/"

    def patch(self, user, data):
        self.client.force_authenticate(user=user)
        return self.client.patch(self.url, data, format="json")

    def test_reception_must_assign_doctor_before_sending(self):
        res = self.patch(self.reception, {"current_stage": "doctor_review"})
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

        res = self.patch(self.reception, {"assigned_doctor": self.doctor.id, "current_stage": "doctor_review"})
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_roles_cannot_act_outside_their_stage_or_fields(self):
        # Doctor cannot act while patient is still at reception
        self.assertEqual(self.patch(self.doctor, {"diagnosis": "x"}).status_code, status.HTTP_403_FORBIDDEN)

        self.patch(self.reception, {"assigned_doctor": self.doctor.id, "current_stage": "doctor_review"})

        # Reception cannot edit once patient left reception
        self.assertEqual(self.patch(self.reception, {"priority": "urgent"}).status_code, status.HTTP_403_FORBIDDEN)
        # Doctor cannot write nurse fields
        self.assertEqual(self.patch(self.doctor, {"temperature": "99"}).status_code, status.HTTP_403_FORBIDDEN)
        # Doctor cannot skip to super doctor without assigning one
        self.assertEqual(
            self.patch(self.doctor, {"current_stage": "admitting_provider"}).status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        # Doctor can discharge directly when not serious
        self.assertEqual(self.patch(self.doctor, {"current_stage": "completed"}).status_code, status.HTTP_200_OK)

    def test_doctor_only_sees_assigned_patients(self):
        self.patch(self.reception, {"assigned_doctor": self.doctor.id, "current_stage": "doctor_review"})

        self.client.force_authenticate(user=self.other_doctor)
        self.assertEqual(self.client.get("/api/v1/patients/").data["count"], 0)
        self.assertEqual(self.patch(self.other_doctor, {"diagnosis": "x"}).status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(user=self.doctor)
        self.assertEqual(self.client.get("/api/v1/patients/").data["count"], 1)

    def test_only_superdoctor_can_invite_staff_and_invite_activates(self):
        payload = {"first_name": "New", "email": "newnurse@h.com", "role": "nurse"}

        self.client.force_authenticate(user=self.doctor)
        self.assertEqual(self.client.post("/api/v1/staff/invite/", payload).status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(user=self.superdoctor)
        res = self.client.post("/api/v1/staff/invite/", payload)
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        # Superdoctor role cannot be granted through invite
        bad = self.client.post("/api/v1/staff/invite/", {**payload, "email": "x@h.com", "role": "superdoctor"})
        self.assertEqual(bad.status_code, status.HTTP_400_BAD_REQUEST)

        token = res.data["setup_url"].split("token=")[1]
        self.client.force_authenticate(user=None)
        set_res = self.client.post(
            "/api/v1/auth/set-password/",
            {"token": token, "password": "Strong@Pass123", "confirm_password": "Strong@Pass123"},
            format="json",
        )
        self.assertEqual(set_res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(set_res.data["role"], "nurse")
        self.assertTrue(User.objects.get(email="newnurse@h.com").check_password("Strong@Pass123"))
