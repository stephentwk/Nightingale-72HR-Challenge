import unittest

from app import CareNoteStore, PATIENT_ID


class HighlightProvenanceTests(unittest.TestCase):
    def test_ai_highlights_resolve_to_timeline_spans(self):
        store = CareNoteStore()
        actor = store.actor("clinician")
        highlights = store.generate_highlights(PATIENT_ID, actor)
        ai_highlights = [item for item in highlights if item["source_type"].startswith("ai_")]
        self.assertTrue(ai_highlights, "expected at least one AI-scribed highlight")
        for highlight in ai_highlights:
            resolved = store.resolve_provenance(highlight["provenance_pointer"], actor)
            self.assertTrue(resolved["resolved"])
            self.assertEqual(resolved["entry_id"], highlight["entry_id"])
            self.assertTrue(resolved["resolved_text"])

    def test_highlight_pointer_contains_source_identity_and_span(self):
        store = CareNoteStore()
        highlight = next(item for item in store.generate_highlights(PATIENT_ID, store.actor("clinician")) if item["entry_id"] == "ent-ai-patient-feb06")
        pointer = highlight["provenance_pointer"]
        self.assertEqual(pointer["source_id"], "ai-session-ps-2026-02-06-884")
        self.assertLess(pointer["start"], pointer["end"])


if __name__ == "__main__":
    unittest.main()
