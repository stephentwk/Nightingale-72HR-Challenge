import unittest

from app import CareNoteStore, PATIENT_ID


class RevisionHistoryTests(unittest.TestCase):
    def setUp(self):
        self.store = CareNoteStore()
        self.clinician = self.store.actor("clinician")

    def test_edit_increments_version_and_revert_restores_prior_state(self):
        entry = self.store.create_entry(PATIENT_ID, self.clinician, {"type": "clinician_note", "content": "First plan"})
        updated = self.store.update_entry(entry["id"], self.clinician, {"base_version": 1, "content": "Safer revised plan"})
        self.assertEqual(updated["version"], 2)
        reverted = self.store.revert(entry["id"], self.clinician, 1)
        self.assertEqual(reverted["version"], 3)
        self.assertEqual(reverted["content"], "First plan")

    def test_audit_log_is_metadata_only_and_identifies_actor(self):
        entry = self.store.create_entry(PATIENT_ID, self.clinician, {"type": "clinician_note", "content": "Private clinical content"})
        self.store.update_entry(entry["id"], self.clinician, {"base_version": 1, "content": "Updated private content"})
        audit = self.store.audit_for(PATIENT_ID, self.clinician)
        update = next(item for item in audit if item["action"] == "updated")
        self.assertEqual(update["actor_id"], self.clinician["id"])
        self.assertEqual(update["metadata"]["before_version"], 1)
        self.assertEqual(update["metadata"]["after_version"], 2)
        self.assertNotIn("Private clinical content", str(update))


if __name__ == "__main__":
    unittest.main()
