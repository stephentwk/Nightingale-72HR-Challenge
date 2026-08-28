import unittest
from pathlib import Path

from app import CareNoteStore, PATIENT_ID, PATIENT_SAFETY_MESSAGE, PolicyError


class NewRequirementTests(unittest.TestCase):
    def test_priority_signals_are_unique_and_return_more_than_the_top_three(self):
        store = CareNoteStore()
        highlights = store.generate_highlights(PATIENT_ID, store.actor("clinician"))
        features = [item["feature"] for item in highlights]

        self.assertGreater(len(highlights), 3)
        self.assertEqual(len(features), len(set(features)))
        self.assertEqual(features.count("chest pressure"), 1)
        self.assertEqual(highlights, sorted(highlights, key=lambda item: (-item["importance_score"], item["created_at"])))

    def test_highlight_decision_can_be_cleared_and_redecided(self):
        store = CareNoteStore()
        clinician = store.actor("clinician")
        highlight = next(item for item in store.generate_highlights(PATIENT_ID, clinician) if item["feature"] == "chest pressure")

        self.assertEqual(store.decide_highlight(highlight["id"], clinician, "accepted")["status"], "accepted")
        self.assertEqual(store.decide_highlight(highlight["id"], clinician, "undecided")["status"], "suggested")
        self.assertNotIn(highlight["id"], store.highlights)
        self.assertEqual(store.decide_highlight(highlight["id"], clinician, "rejected")["status"], "rejected")
        self.assertEqual(store.decide_highlight(highlight["id"], clinician, "undecided")["status"], "suggested")

    def test_patient_prep_is_shared_editable_and_keeps_safety_floor(self):
        store = CareNoteStore()
        staff = store.actor("staff")
        clinician = store.actor("clinician")
        patient = store.actor("patient")
        updated = store.update_patient_prep(PATIENT_ID, staff, {"instructions": "Bring your ECG report.\nWrite down new symptoms."})

        self.assertEqual(updated["version"], 2)
        self.assertIn(PATIENT_SAFETY_MESSAGE, updated["instructions"])
        self.assertEqual(store.care_note(PATIENT_ID, patient)["patient"]["patient_instructions"], updated["instructions"])
        self.assertTrue(any(item["entity_type"] == "patient_prep" for item in store.audit_for(PATIENT_ID, store.actor("admin"))))
        clinician_update = store.update_patient_prep(PATIENT_ID, clinician, {"instructions": ["Bring your medication list.", PATIENT_SAFETY_MESSAGE]})
        self.assertEqual(clinician_update["version"], 3)
        with self.assertRaises(PolicyError):
            store.update_patient_prep(PATIENT_ID, patient, {"instructions": "Not allowed"})
        with self.assertRaises(PolicyError):
            store.update_patient_prep(PATIENT_ID, store.actor("admin"), {"instructions": "Not allowed"})

    def test_voice_capture_interaction_types_follow_the_role_surface(self):
        store = CareNoteStore()
        transcript = "Speaker 1: The patient reports a stable symptom update."
        patient_entry = store.create_voice_entry(PATIENT_ID, store.actor("patient"), {"interaction": "Patient session", "redacted_transcript": transcript})
        nurse_entry = store.create_voice_entry(PATIENT_ID, store.actor("clinician"), {"interaction": "Nurse consult", "redacted_transcript": transcript})

        self.assertEqual(patient_entry["type"], "ai_patient_session_summary")
        self.assertEqual(nurse_entry["type"], "ai_nurse_consult_summary")
        with self.assertRaises(PolicyError):
            store.create_voice_entry(PATIENT_ID, store.actor("patient"), {"interaction": "Clinical consult", "redacted_transcript": transcript})
        with self.assertRaises(PolicyError):
            store.create_voice_entry(PATIENT_ID, store.actor("staff"), {"interaction": "Patient session", "redacted_transcript": transcript})

    def test_ui_contains_role_specific_surfaces(self):
        source = (Path(__file__).resolve().parents[1] / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("Voice Consult Capture", source)
        self.assertIn("Human-approved notes", source)
        self.assertIn("trust-ledger-text", source)
        self.assertIn("decision-pending", source)
        self.assertIn("data-action=\"toggle-signals\"", source)
        self.assertIn("data-action=\"edit-prep\"", source)


if __name__ == "__main__":
    unittest.main()
