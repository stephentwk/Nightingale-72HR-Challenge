import unittest

from app import CareNoteStore, ConflictError, PATIENT_ID


class ConcurrentEditTests(unittest.TestCase):
    def setUp(self):
        self.store = CareNoteStore()
        self.store._add_entry({
            "id": "ent-shared-plan-test",
            "patient_id": PATIENT_ID,
            "created_at": "2026-02-07T08:15:00+08:00",
            "author_role": "clinician",
            "author_id": "cl-dr-patel",
            "type": "shared_care_plan",
            "title": "Shared plan",
            "content": "Plan and follow-up",
            "sections": {"clinician_plan": "Original plan", "staff_follow_up": "Original follow-up"},
            "section_roles": {"clinician_plan": "clinician", "staff_follow_up": "staff"},
            "owner_role": "clinician",
            "patient_visible": True,
            "patient_summary": "Shared plan",
        })

    def test_different_owned_sections_merge_from_same_base(self):
        clinician = self.store.actor("clinician")
        staff = self.store.actor("staff")
        first = self.store.update_entry("ent-shared-plan-test", clinician, {"section": "clinician_plan", "content": "Updated clinical plan", "base_version": 1})
        merged = self.store.update_entry("ent-shared-plan-test", staff, {"section": "staff_follow_up", "content": "Updated staff follow-up", "base_version": 1})
        self.assertEqual(first["version"], 2)
        self.assertEqual(merged["version"], 3)
        self.assertEqual(merged["sections"]["clinician_plan"], "Updated clinical plan")
        self.assertEqual(merged["sections"]["staff_follow_up"], "Updated staff follow-up")

    def test_same_section_conflict_is_deterministically_rejected(self):
        clinician = self.store.actor("clinician")
        self.store.update_entry("ent-shared-plan-test", clinician, {"section": "clinician_plan", "content": "Server wins", "base_version": 1})
        with self.assertRaises(ConflictError) as context:
            self.store.update_entry("ent-shared-plan-test", clinician, {"section": "clinician_plan", "content": "Stale client", "base_version": 1})
        self.assertIn("latest server version remains authoritative", str(context.exception))
        self.assertEqual(context.exception.latest["sections"]["clinician_plan"], "Server wins")


if __name__ == "__main__":
    unittest.main()
