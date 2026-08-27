import unittest

from app import CareNoteStore, PATIENT_ID


class SelfLearningImportanceTests(unittest.TestCase):
    def test_accepted_signal_increases_priority_for_similar_content(self):
        store = CareNoteStore()
        store.learning_signals.clear()
        clinician = store.actor("clinician")
        store._add_entry({
            "id": "ent-learning-test",
            "patient_id": PATIENT_ID,
            "created_at": "2026-08-27T09:00:00+08:00",
            "author_role": "system",
            "author_id": "ai-scribe",
            "type": "ai_nurse_consult_summary",
            "title": "AI nurse summary · adherence",
            "content": "Maya missed one evening dose and will bring the log.",
            "sections": {"summary": "Maya missed one evening dose."},
            "tags": ["medication adherence"],
            "source_id": "learning-source",
            "source_label": "Synthetic nurse summary",
            "provenance_kind": "transcript",
            "risk_level": "medium",
            "patient_visible": False,
        })
        before = next(item for item in store.generate_highlights(PATIENT_ID, clinician) if item["entry_id"] == "ent-learning-test")
        store.decide_highlight(before["id"], clinician, "accepted")
        after = next(item for item in store.generate_highlights(PATIENT_ID, clinician) if item["entry_id"] == "ent-learning-test")
        self.assertGreater(after["importance_score"], before["importance_score"])
        self.assertEqual(after["status"], "accepted")


if __name__ == "__main__":
    unittest.main()
