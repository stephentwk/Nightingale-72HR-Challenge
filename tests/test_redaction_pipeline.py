import unittest

from app import CareNoteStore, PATIENT_ID, redact_phi


class RedactionPipelineTests(unittest.TestCase):
    def test_names_ids_and_phones_are_redacted_deterministically(self):
        redacted, counts = redact_phi("Maya Chen called from +65 8123 4567. ID: NC-1234567.")
        self.assertNotIn("Maya Chen", redacted)
        self.assertNotIn("8123 4567", redacted)
        self.assertNotIn("NC-1234567", redacted)
        self.assertEqual(counts, {"names": 1, "ids": 1, "phones": 1})

    def test_voice_entry_stores_no_raw_audio(self):
        store = CareNoteStore()
        entry = store.create_voice_entry(PATIENT_ID, store.actor("clinician"), {"raw_transcript": "Maya Chen said the chest pressure returned."})
        self.assertEqual(entry["author_role"], "system")
        self.assertNotIn("Maya Chen", entry["content"])
        self.assertFalse(any("raw_audio" in key for key in entry))
        audit = store.audit_for(PATIENT_ID, store.actor("clinician"))
        self.assertFalse(audit[-1]["metadata"]["raw_audio_stored"])


if __name__ == "__main__":
    unittest.main()
