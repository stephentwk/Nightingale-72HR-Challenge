# Nightingale Care Note — technical brief

## Why this shape

The core design question was not “how do we put notes in a prettier database?” It was “what can a care team safely trust in the first ten seconds, and how do we make the next click prove it?”

The first screen therefore has a strict attention budget: one top signal, three compact supporting signals, and the open loops that can make a visit fail. The timeline remains the source of truth. The glance view is a reversible index into it, not a replacement narrative. A clinician can move quickly without being asked to accept a model’s paraphrase as a fact.

This is why the UI visibly separates AI-generated content, human notes, patient-safe copy, and system events. It also puts a short risk reason and an evidence jump beside every highlight. “99/100” is not presented as clinical certainty; the trust ledger says what the number is allowed to do.

## Architecture

```text
Browser / PWA surface
  ├─ clinician glance + full timeline
  ├─ staff handoff + tasks
  └─ patient-approved snapshot + visit-prep booklet
              │  actor + clinic headers (demo auth)
              ▼
HTTP API / policy boundary
  ├─ scope check (role, user, clinic, patient)
  ├─ visibility serializer (patient != internal)
  ├─ mutation authorization (entry/section ownership)
  ├─ version + section conflict service
  ├─ provenance resolver + audit metadata
  └─ redaction gate → model adapter (synthetic adapter in demo)
              │
              ▼
Domain store (in-memory demo; relational production shape)
  patients ─┬─ entries ─── versions
            ├─ comments
            ├─ tasks
            ├─ highlights ── provenance pointers
            ├─ ai_scribed metadata
            └─ learning signals / audit events
```

The prototype uses Python’s standard library to keep it runnable with no package installation. In production I would keep the same boundaries behind a FastAPI service, PostgreSQL, object storage for redacted transcripts, a model gateway, and an append-only audit sink. TLS terminates at the edge; database and object storage encryption use managed keys.

## Data schema and link model

The demo uses dictionaries, but the fields are intentionally close to a relational schema.

```text
Patient(id, clinic_id, patient-facing summary, instructions)
  1 ─── * Entry(id, patient_id, author_role, author_id, type, created_at,
               risk_level, confidence, source_id, source_label, visibility,
               patient_visible, patient_approved, content, sections)
              1 ─── * Version(entry_id, version, full_snapshot, diff,
                               actor_id, actor_role, created_at)
              1 ─── * Comment(entry_id, author_id, mentions, status, body)
              1 ─── * Highlight(entry_id, feature, score, risk_reason,
                                status, provenance_pointer)
              1 ─── * AuditEvent(entity_id, actor, action, metadata)

Highlight.provenance_pointer →
  { entry_id, field, start, end, quote, source_id }

Entry.type ∈ {
  ai_doctor_consult_summary,
  ai_nurse_consult_summary,
  ai_patient_session_summary,
  staff_note, clinician_plan, clinician_note,
  patient_insight, system_event
}
```

An AI entry is not converted into a human-authored note. It remains `author_role=system`, carries the interaction-specific type, and points to its original transcript/session identifier. A highlight resolves back through `entry_id + field + start/end`; the resolver verifies the span before returning it. If a later edit changes the source text, a production implementation would keep immutable source versions and mark stale pointers for review rather than silently moving the quote.

## RBAC and conflict policy

The role switcher is deliberately not a UI permission demo. It changes the request actor, then the backend applies policy again:

- Patient: only entries marked `patient_visible`, serialized as approved/plain-language copy. No internal comments, raw AI content, audit history, or clinical working sections.
- Staff: staff-owned notes and coordination context, plus the AI summaries needed for handoff. Clinician-only working sections are not serialized.
- Clinician: clinic-scoped view of all timeline entries and the ability to edit clinician-owned sections, confirm highlights, resolve actions, and inspect history.
- Admin: clinic-scoped oversight and audit view; read-only in this prototype to reduce the chance that oversight becomes authorship.

Entry ownership prevents staff from overwriting clinician notes and clinicians from overwriting staff notes. A shared plan can still contain explicit section ownership (`clinician_plan → clinician`, `staff_follow_up → staff`). Updates merge against the current snapshot when a stale client touches an untouched section. Two writes to the same section produce a 409 with a deterministic rule: reject the stale write and keep the latest server version authoritative. That is intentionally boring; an unresolved clinical contradiction should be visible, not “merged” by a clever string algorithm.

## Importance logic: useful, bounded, explainable

The score is a ranking aid, not a diagnosis. Each candidate is created only when a source span exists. Its score combines:

1. Deterministic risk floor: chest symptoms, breathing symptoms, allergies, and explicit safety terms start at a high floor.
2. Recency: a bounded decay curve over 180 days.
3. Unresolved action: source-linked open tasks add attention.
4. Structured tags: known concepts such as medication adherence or patient question add a small boost.
5. Bounded learning signal: accepted highlight interactions add a small feature weight to similar future entries.

Dismissal does not lower the safety floor. The model never gets to publish patient-facing copy or suppress a critical class. The feedback loop is intentionally conservative about exposure bias: surfaced items can be confirmed, but critical categories remain surfaced even when people are tired. In a larger system I would add per-clinic calibration dashboards, false-negative sampling, and an explicit “why did I not see this?” review path.

The UI labels confidence as “evidence matched”, “review suggested”, or “abstain / verify”. These are thresholds over source alignment and extraction heuristics, not self-reported model confidence. A medium confidence label is deliberately not a reassurance.

## Redaction and ambient capture

The capture path has three visible steps: consent, deterministic redaction, then summary. `redact_phi()` handles the synthetic patient/team names, ID-like strings, and phone patterns before text reaches the synthetic model adapter. The server accepts `raw_transcript` only to redact it immediately and never persists that value; the UI sends a redacted preview by default. The audit metadata records redaction counts and `raw_audio_stored=false` without storing content.

For production: capture audio under an explicit consent record, encrypt the short-lived object, run on-device/VPC redaction and speaker diarization, reject low-confidence redaction, send only redacted text to the LLM, retain a redacted transcript with segment timestamps, and provide a human review gate before a patient-facing result. Noise, overlap, code-switching, and medical terminology should lower confidence rather than create confident-looking filler.

## Data decay policy (bonus)

The demo keeps all synthetic entries hot so the challenge is easy to inspect. The production policy would be hybrid:

- Hot (0–90 days): full entries, comments, versions, and source spans in the primary store.
- Warm (90 days–2 years): immutable source stays available, while the glance index uses compressed daily/episode summaries plus unresolved safety items and clinician-confirmed facts.
- Cold (>2 years): encrypted archive with retention/legal hold controls. The timeline shows a dated “compressed episode” card and a one-click retrieval request; it never silently implies that absence means “nothing happened.”

Never decay allergies, active medications, unresolved safety flags, clinician-confirmed contradictions, or provenance pointers needed to explain a decision. A nightly compactor should emit a new system event and preserve hashes so the summary itself is auditable.

## Measurement and trade-offs

The current `warm_path_ms` is measured around the in-memory Care Note assembly with `time.perf_counter()` and is visible in the right rail. `test_glance_latency.py` takes 50 warm samples and asserts its inclusive P95 is ≤300 ms. On this seeded dataset it is sub-millisecond, which is useful as a local regression signal but not a production latency claim. A production P95 should be measured at the API edge over at least 100 warm requests, separately reporting cache-hit and cache-miss paths, with a target ≤300 ms for the glance payload.

What I tried conceptually: a pure recency feed felt fast but buried safety; a pure model-generated “top summary” was concise but hard to cite and too easy to over-trust; a dense database view preserved evidence but recreated the scrolling problem. The final hybrid keeps a small deterministic safety spine, source-linked suggestions, and a human-controlled learning layer. I also chose not to implement real transcription or an LLM call in a synthetic offline prototype: spending the time on boundary behavior, UI states, and tests makes the safety claims demonstrable instead of decorative.
