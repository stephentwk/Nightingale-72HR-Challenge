import statistics
import time
import unittest

from app import CareNoteStore, PATIENT_ID


class GlanceLatencyTests(unittest.TestCase):
    def test_warm_in_memory_glance_path_has_300ms_p95_budget(self):
        store = CareNoteStore()
        actor = store.actor("clinician")
        samples = []
        for _ in range(50):
            start = time.perf_counter()
            store.care_note(PATIENT_ID, actor)
            samples.append((time.perf_counter() - start) * 1000)
        p95 = statistics.quantiles(samples, n=20, method="inclusive")[18]
        self.assertLessEqual(p95, 300, f"warm-path p95 was {p95:.2f}ms")


if __name__ == "__main__":
    unittest.main()
