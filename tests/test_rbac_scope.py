import unittest

from app import CareNoteStore, PolicyError, PATIENT_ID


class RBACScopeTests(unittest.TestCase):
    def setUp(self):
        self.store = CareNoteStore()
        self.staff = self.store.actor("staff")
        self.clinician = self.store.actor("clinician")
        self.patient = self.store.actor("patient")

    def test_staff_and_clinician_cannot_write_as_each_other(self):
        staff_note = self.store.create_entry(PATIENT_ID, self.staff, {"type": "staff_note", "content": "Staff handoff"})
        clinician_note = self.store.create_entry(PATIENT_ID, self.clinician, {"type": "clinician_note", "content": "Clinical assessment"})
        with self.assertRaises(PolicyError):
            self.store.update_entry(staff_note["id"], self.clinician, {"base_version": 1, "content": "Clinician overwrite"})
        with self.assertRaises(PolicyError):
            self.store.update_entry(clinician_note["id"], self.staff, {"base_version": 1, "content": "Staff overwrite"})
        with self.assertRaises(PolicyError):
            self.store.create_entry(PATIENT_ID, self.staff, {"type": "clinician_note", "content": "Impersonated note"})

    def test_patient_cannot_access_internal_comments_or_raw_ai_notes(self):
        timeline = self.store.timeline(PATIENT_ID, self.patient)
        ids = {entry["id"] for entry in timeline}
        self.assertNotIn("ent-ai-doctor-apr15", ids)
        self.assertNotIn("ent-ai-patient-feb06", ids)
        staff_note = self.store.create_entry(PATIENT_ID, self.staff, {"type": "staff_note", "content": "Internal callback note"})
        self.store.add_comment(staff_note["id"], self.staff, {"body": "@clinician please review"})
        with self.assertRaises(PolicyError):
            self.store.comments_for(staff_note["id"], self.patient)

    def test_care_team_comment_can_resolve_and_unresolve(self):
        note = self.store.create_entry(PATIENT_ID, self.staff, {"type": "staff_note", "content": "Handoff"})
        comment = self.store.add_comment(note["id"], self.staff, {"body": "@clinician please review", "assigned_to": "cl-dr-patel"})
        resolved = self.store.toggle_comment(comment["id"], self.clinician)
        self.assertEqual(resolved["status"], "resolved")
        reopened = self.store.toggle_comment(comment["id"], self.clinician)
        self.assertEqual(reopened["status"], "open")

    def test_staff_is_clinic_scoped(self):
        out_of_scope = self.store.actor("staff")
        out_of_scope["clinic_id"] = "clinic-other"
        with self.assertRaises(PolicyError):
            self.store.timeline(PATIENT_ID, out_of_scope)

    def test_patient_copy_requires_reapproval_after_instruction_edit(self):
        entry_id = "ent-clinician-plan"
        self.store.update_entry(entry_id, self.clinician, {"section": "patient_instruction", "content": "Updated safe instruction", "base_version": 1})
        patient_ids = {entry["id"] for entry in self.store.timeline(PATIENT_ID, self.patient)}
        self.assertNotIn(entry_id, patient_ids)
        with self.assertRaises(PolicyError):
            self.store.approve_patient_copy(entry_id, self.staff)
        self.store.approve_patient_copy(entry_id, self.clinician)
        patient_ids = {entry["id"] for entry in self.store.timeline(PATIENT_ID, self.patient)}
        self.assertIn(entry_id, patient_ids)


if __name__ == "__main__":
    unittest.main()
