# Nightingale Care Note

Nightingale is a runnable, offline-friendly prototype of a shared longitudinal patient note for Harbour Clinic. It treats the note as a communication and trust system rather than another scrolling document: the first screen answers “what needs attention now?”, then lets the care team jump to evidence, collaborate, and audit the change.

The demo uses synthetic data only. It is not a medical device, does not make diagnoses, and must not be connected to production patient data.

## Run it

Requirements: Python 3.10+ and a modern browser. There are no third-party Python packages.

```powershell
python app.py
```

Then open <http://127.0.0.1:8000>.

If `python` is not on your PATH in the challenge environment, use the bundled runtime path supplied by the Codex workspace or install Python 3.10+ locally.

Run the complete micro-test suite:

```powershell
python -m unittest discover -s tests -v
```

The seeded records reset when the server restarts. This is intentional for a deterministic demo and test run.

## What is implemented

- Shared patient Care Note with a top card, deduplicated priority list, open loops, role-colored Timeline, synchronized patient prep, and a text trust ledger at the bottom of clinical surfaces.
- Distinct `ai_doctor_consult_summary`, `ai_nurse_consult_summary`, and `ai_patient_session_summary` entries with `author_role=system`, `source_id`, source label, and exact-span provenance.
- Staff notes, clinician plan sections, patient insights, threaded comments, `@mentions`, role-owned editing, and deterministic stale-write conflict handling.
- Full snapshot revisions, unified diffs, revert-as-a-new-version, and metadata-only audit events.
- Server-side RBAC and clinic scoping. The role selector is only a demo authentication switch; every API request is checked again.
- Deterministic importance logic combining safety terms, explicit risk, recency, unresolved tasks, and tags. Signals are deduplicated by concept, ranked with a top-three progressive disclosure, and linked to the latest corroborating source. Human “Keep” / “Dismiss” interactions add a bounded pattern boost; decisions can be cleared and high-risk safety floors cannot be learned away.
- Patient-facing prep is editable by staff/nurse and clinician, synchronized into the patient’s next-step surface, and guarded by a server-side urgent-safety message.
- Voice-capture architecture demo: a redaction function handles names, ID-like values, and phones before a synthetic summary entry is created. Raw audio is never persisted.
- Warm-path timing in the API response. The in-memory demo measures the assembled Care Note query; the technical brief explains how to replace this with an API-edge P95 metric in production.

## Security and privacy notes

The backend does not trust UI visibility. It derives an actor from the request headers, checks the actor’s clinic scope, filters each timeline entry server-side, and authorizes every create, edit, comment, revert, highlight decision, and task update. Patients receive a reduced serialization; their request never contains raw AI content or internal comments.

`redact_phi()` is deliberately small and inspectable for the prototype. A real deployment should add layered entity detection, facility-specific identifier patterns, a fail-closed review queue, TLS, encrypted storage, key rotation, access logging, and a model gateway that refuses unredacted input.

## Project map

| Path | Purpose |
| --- | --- |
| `app.py` | Standard-library HTTP API, seeded domain store, RBAC, revisions, provenance, importance logic, redaction, and static-file serving |
| `static/index.html` | App shell and role switcher |
| `static/styles.css` | Responsive visual system and interaction states |
| `static/app.js` | Glance view, timeline, modal collaboration tools, role transitions, and source navigation |
| `tests/` | Required micro-tests plus redaction coverage |
| `ATTRIBUTION.txt` | External dependency and license disclosure |

## API surface used by the demo

`GET /api/care-note` · `POST /api/entries` · `PATCH /api/entries/{id}` · `PATCH /api/patient-prep` · `GET /api/entries/{id}/versions` · `POST /api/entries/{id}/revert` · `GET/POST /api/entries/{id}/comments` · `POST /api/highlights/{id}/decision` · `POST /api/tasks/{id}/toggle` · `POST /api/voice-sessions` · `GET /api/audit`.

Every mutation is audited with metadata, never note text. See the tests for direct examples of the policy decisions.
