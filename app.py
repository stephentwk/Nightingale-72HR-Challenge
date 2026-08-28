"""Nightingale Care Note demo server.

This deliberately uses only Python's standard library so the challenge can be
run in a clean environment.  The in-memory store is seeded with synthetic
records on every process start; the policy and versioning code is real and is
also imported directly by the micro-tests.
"""

from __future__ import annotations

import difflib
import json
import math
import re
import threading
import time
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Iterable, Optional
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
HOST = "127.0.0.1"
PORT = 8000
CLINIC_ID = "clinic-harbour"
PATIENT_ID = "pat-maya-chen"

ROLES = {"patient", "staff", "clinician", "admin"}
ACTORS = {
    "patient": {"id": "pt-maya", "name": "Maya Chen", "clinic_id": CLINIC_ID},
    "staff": {"id": "st-lena", "name": "Lena Ortiz", "clinic_id": CLINIC_ID},
    "clinician": {"id": "cl-dr-patel", "name": "Dr. Arjun Patel", "clinic_id": CLINIC_ID},
    "admin": {"id": "ad-harbour", "name": "Harbour admin", "clinic_id": CLINIC_ID},
}


class PolicyError(Exception):
    """A server-side access decision that should be shown to the caller."""

    def __init__(self, message: str, status: int = 403):
        super().__init__(message)
        self.status = status


class ConflictError(PolicyError):
    def __init__(self, message: str, latest: Optional[dict] = None):
        super().__init__(message, 409)
        self.latest = latest


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def iso_date(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def snapshot(entry: dict) -> dict:
    return {
        "title": entry.get("title", ""),
        "content": entry.get("content", ""),
        "sections": deepcopy(entry.get("sections", {})),
        "patient_summary": entry.get("patient_summary", ""),
        "patient_instructions": deepcopy(entry.get("patient_instructions", [])),
        "patient_approved": entry.get("patient_approved", False),
    }


def snapshot_text(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def make_diff(before: dict, after: dict) -> list[str]:
    return list(
        difflib.unified_diff(
            snapshot_text(before).splitlines(),
            snapshot_text(after).splitlines(),
            fromfile="before",
            tofile="after",
            lineterm="",
        )
    )


def source_pointer(entry: dict, quote: str, start: int = 0) -> dict:
    text = entry.get("content", "")
    if not quote:
        quote = text[:110]
    actual_start = text.lower().find(quote.lower())
    if actual_start < 0:
        actual_start = start
    return {
        "entry_id": entry["id"],
        "field": "content",
        "start": actual_start,
        "end": actual_start + len(quote),
        "quote": quote,
        "source_id": entry.get("source_id", entry["id"]),
    }


def parse_mentions(text: str) -> list[str]:
    return sorted(set(re.findall(r"@[A-Za-z][A-Za-z0-9_.-]*", text or "")))


def redact_phi(text: str) -> tuple[str, dict[str, int]]:
    """Deterministically redact demo PHI before any model boundary.

    A production deployment would use a layered recognizer (presidio-like
    entity detection, facility-specific ID patterns, and a human-review
    fallback). The prototype keeps this function deliberately inspectable.
    """
    counts = {"names": 0, "ids": 0, "phones": 0}
    redacted = text or ""
    name_patterns = [r"\bMaya\s+Chen\b", r"\bArjun\s+Patel\b", r"\bLena\s+Ortiz\b", r"(?i)(?<=name:\s)[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,2}"]
    for pattern in name_patterns:
        redacted, replaced = re.subn(pattern, "[REDACTED NAME]", redacted)
        counts["names"] += replaced
    redacted, replaced = re.subn(r"(?i)\b(?:ic|id|mrn|identity)(?:\s*(?:number|no\.?))?\s*[:#-]?\s*[A-Z0-9-]{5,}\b", "[REDACTED ID]", redacted)
    counts["ids"] += replaced
    redacted, replaced = re.subn(r"(?<!\d)(?:\+?\d[\d ()-]{7,}\d)(?!\d)", "[REDACTED PHONE]", redacted)
    counts["phones"] += replaced
    return redacted, counts


class CareNoteStore:
    """Seeded domain store with policy, audit, version and importance logic."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.patients = {PATIENT_ID: self._seed_patient()}
        self.entries: dict[str, dict] = {}
        self.comments: dict[str, dict] = {}
        self.tasks: dict[str, dict] = {}
        self.highlights: dict[str, dict] = {}
        self.audit_log: list[dict] = []
        self.learning_signals: list[dict] = []
        self._seed_content()

    @staticmethod
    def _seed_patient() -> dict:
        return {
            "id": PATIENT_ID,
            "clinic_id": CLINIC_ID,
            "name": "Maya Chen",
            "initials": "MC",
            "age": 54,
            "pronouns": "she/her",
            "mrn_masked": "NC-•••-4821",
            "conditions": ["Hypertension", "Asthma"],
            "allergies": ["Penicillin — verified"],
            "care_team": ["Dr. Arjun Patel", "Lena Ortiz, RN"],
            "next_appointment": "Tomorrow · 09:30",
            "patient_summary": "Your care team is reviewing a recent symptom change and your blood pressure trend.",
            "patient_instructions": [
                "Bring your home blood-pressure log to the next visit.",
                "If chest pain returns, seek urgent care rather than waiting for a message.",
            ],
        }

    def _add_entry(self, entry: dict) -> dict:
        entry = deepcopy(entry)
        entry.setdefault("id", f"ent-{uuid.uuid4().hex[:10]}")
        entry.setdefault("version", 1)
        entry.setdefault("sections", {})
        entry.setdefault("content", "")
        entry.setdefault("visibility", "internal")
        entry.setdefault("tags", [])
        entry.setdefault("risk_level", "low")
        entry.setdefault("confidence", None)
        entry.setdefault("patient_visible", False)
        entry.setdefault("patient_approved", bool(entry.get("patient_visible", False)))
        entry.setdefault("source_id", entry["id"])
        entry.setdefault("source_label", "Manual note")
        entry.setdefault("section_roles", {})
        entry.setdefault("section_versions", {key: 1 for key in entry["sections"]})
        entry["versions"] = [
            {
                "version": 1,
                "created_at": entry["created_at"],
                "actor_id": entry.get("author_id", "system"),
                "actor_role": entry.get("author_role", "system"),
                "snapshot": snapshot(entry),
                "diff": [],
            }
        ]
        self.entries[entry["id"]] = entry
        return entry

    def _seed_content(self) -> None:
        self._add_entry(
            {
                "id": "ent-ai-doctor-apr15",
                "patient_id": PATIENT_ID,
                "created_at": "2025-04-15T09:40:00+08:00",
                "author_role": "system",
                "author_id": "ai-scribe",
                "type": "ai_doctor_consult_summary",
                "title": "Doctor consult · post-visit summary",
                "content": "Home readings remain above target (average 152/94). Maya reported intermittent chest pressure when climbing stairs, without fainting. Clinician plan: verify medication adherence, order ECG, and review urgently if symptoms recur.",
                "sections": {"assessment": "BP trend above target; exertional chest pressure needs review.", "plan": "Order ECG; verify adherence; same-day escalation if symptoms recur."},
                "risk_level": "high",
                "confidence": 0.84,
                "tags": ["blood pressure", "chest pressure", "medication adherence"],
                "source_id": "consult-doc-2025-04-15",
                "source_label": "Doctor consult transcript · 15 Apr 2025",
                "provenance_kind": "transcript",
                "patient_visible": False,
            }
        )
        self._add_entry(
            {
                "id": "ent-ai-patient-feb06",
                "patient_id": PATIENT_ID,
                "created_at": "2026-02-06T18:10:00+08:00",
                "author_role": "system",
                "author_id": "ai-scribe",
                "type": "ai_patient_session_summary",
                "title": "AI patient session · key questions",
                "content": "Maya asked whether occasional chest pressure could be related to her inhaler. She also shared that two evening blood-pressure doses were missed last week. The assistant advised contacting the care team and did not provide a diagnosis.",
                "sections": {"key_questions": "Could the inhaler relate to chest pressure?", "patient_context": "Two evening doses missed last week."},
                "risk_level": "high",
                "confidence": 0.79,
                "tags": ["chest pressure", "medication adherence", "patient question"],
                "source_id": "ai-session-ps-2026-02-06-884",
                "source_label": "AI patient session · 06 Feb 2026",
                "provenance_kind": "session",
                "patient_visible": False,
            }
        )
        self._add_entry(
            {
                "id": "ent-staff-feb06",
                "patient_id": PATIENT_ID,
                "created_at": "2026-02-06T18:35:00+08:00",
                "author_role": "staff",
                "author_id": "st-lena",
                "type": "staff_note",
                "title": "Follow-up coordination",
                "content": "Called Maya and confirmed tomorrow's review slot. She will bring her home BP log. @clinician please confirm whether ECG order should be placed before arrival.",
                "sections": {"follow_up": "Tomorrow review confirmed; bring BP log.", "handoff": "@clinician please confirm ECG order timing."},
                "risk_level": "medium",
                "tags": ["follow-up", "ECG", "blood pressure"],
                "source_id": "staff-call-2026-02-06-1835",
                "source_label": "Staff call log · 06 Feb 2026",
                "patient_visible": False,
                "owner_role": "staff",
                "section_roles": {"follow_up": "staff", "handoff": "staff"},
            }
        )
        self._add_entry(
            {
                "id": "ent-clinician-plan",
                "patient_id": PATIENT_ID,
                "created_at": "2026-02-06T19:02:00+08:00",
                "author_role": "clinician",
                "author_id": "cl-dr-patel",
                "type": "clinician_plan",
                "title": "Clinician plan · pending sign-off",
                "content": "Plan: ECG before review; reconcile antihypertensive doses against home log. Patient-facing instruction is awaiting clinician sign-off.",
                "sections": {"clinician_plan": "ECG before review; reconcile antihypertensive doses against home log.", "patient_instruction": "Bring the home BP log. Do not wait for a message if chest pain returns."},
                "risk_level": "high",
                "tags": ["ECG", "medication reconciliation", "patient instruction"],
                "source_id": "plan-2026-02-06-1902",
                "source_label": "Clinician workspace · 06 Feb 2026",
                "patient_visible": True,
                "patient_approved": True,
                "owner_role": "clinician",
                "section_roles": {"clinician_plan": "clinician", "patient_instruction": "clinician"},
                "patient_summary": "Your clinician would like an ECG before review and will check your medication doses against your home log.",
                "patient_instructions": ["Bring your home BP log.", "Do not wait for a message if chest pain returns."],
            }
        )
        self._add_entry(
            {
                "id": "ent-system-import",
                "patient_id": PATIENT_ID,
                "created_at": "2026-02-06T19:04:00+08:00",
                "author_role": "system",
                "author_id": "system",
                "type": "system_event",
                "title": "EHR snapshot linked",
                "content": "Latest structured snapshot linked: BP 149/92; allergy list unchanged; source timestamp 06 Feb 2026 17:55.",
                "sections": {},
                "risk_level": "low",
                "tags": ["EHR", "blood pressure", "allergy"],
                "source_id": "ehr-snapshot-2026-02-06-1755",
                "source_label": "EHR snapshot · 06 Feb 2026",
                "patient_visible": False,
            }
        )
        self._add_entry(
            {
                "id": "ent-patient-prep",
                "patient_id": PATIENT_ID,
                "created_at": "2026-02-07T08:00:00+08:00",
                "author_role": "patient",
                "author_id": "pt-maya",
                "type": "patient_insight",
                "title": "Patient insight · visit preparation",
                "content": "I wrote down my evening readings and the two doses I missed so we can review them together.",
                "sections": {"patient_context": "Evening readings and missed doses are ready for review."},
                "risk_level": "medium",
                "tags": ["home readings", "medication adherence"],
                "source_id": "patient-entry-2026-02-07-0800",
                "source_label": "Patient portal · 07 Feb 2026",
                "patient_visible": True,
                "owner_role": "patient",
                "patient_summary": "Your note is shared with the care team.",
            }
        )

        self.tasks.update(
            {
                "task-ecg": {
                    "id": "task-ecg",
                    "patient_id": PATIENT_ID,
                    "title": "Confirm ECG order before arrival",
                    "patient_title": "Complete the ECG before tomorrow’s review",
                    "owner_role": "clinician",
                    "owner_name": "Dr. Patel",
                    "status": "open",
                    "due": "Today",
                    "patient_visible": True,
                    "source_entry_id": "ent-staff-feb06",
                    "created_at": "2026-02-06T18:35:00+08:00",
                },
                "task-bp-log": {
                    "id": "task-bp-log",
                    "patient_id": PATIENT_ID,
                    "title": "Bring home BP log to review",
                    "owner_role": "patient",
                    "owner_name": "Maya",
                    "status": "open",
                    "due": "Tomorrow",
                    "patient_visible": True,
                    "source_entry_id": "ent-patient-prep",
                    "created_at": "2026-02-07T08:00:00+08:00",
                },
                "task-med-list": {
                    "id": "task-med-list",
                    "patient_id": PATIENT_ID,
                    "title": "Upload current medication list",
                    "owner_role": "patient",
                    "owner_name": "Maya",
                    "status": "done",
                    "due": "Completed today",
                    "patient_visible": True,
                    "source_entry_id": "ent-patient-prep",
                    "created_at": "2026-02-07T08:05:00+08:00",
                },
                "task-nurse-followup": {
                    "id": "task-nurse-followup",
                    "patient_id": PATIENT_ID,
                    "title": "Check in after ECG is booked",
                    "owner_role": "staff",
                    "owner_name": "Lena",
                    "status": "open",
                    "due": "Tomorrow",
                    "source_entry_id": "ent-clinician-plan",
                    "created_at": "2026-02-06T19:02:00+08:00",
                },
            }
        )

        # A resolved interaction demonstrates that importance is not simply a
        # fixed risk list; this signal is also used by the learning test.
        self.learning_signals.append(
            {
                "id": "learn-seed-1",
                "feature": "medication adherence",
                "action": "accepted",
                "actor_role": "clinician",
                "created_at": "2026-02-06T19:08:00+08:00",
            }
        )

    def actor(self, role: str = "clinician", user_id: Optional[str] = None) -> dict:
        if role not in ROLES:
            raise PolicyError("Unknown role", 401)
        actor = deepcopy(ACTORS[role])
        if user_id:
            actor["id"] = user_id
        actor["role"] = role
        return actor

    def _scope(self, actor: dict, patient_id: str) -> dict:
        patient = self.patients.get(patient_id)
        if not patient:
            raise PolicyError("Patient not found", 404)
        if actor.get("clinic_id") != patient["clinic_id"]:
            raise PolicyError("This role is outside the clinic scope", 403)
        if actor.get("role") == "patient" and actor.get("id") != "pt-maya":
            raise PolicyError("Patient identity does not match this record", 403)
        return patient

    def _visible_entry(self, entry: dict, actor: dict) -> Optional[dict]:
        role = actor["role"]
        if role == "patient":
            if not entry.get("patient_visible") or not entry.get("patient_approved"):
                return None
            return self._serialize_entry(entry, actor, patient_mode=True)
        if role == "staff":
            # Staff can coordinate against AI summaries and their own notes,
            # but clinician-only working sections remain hidden.
            if entry.get("type") == "clinician_plan":
                result = self._serialize_entry(entry, actor)
                result["sections"] = {
                    "patient_instruction": entry["sections"].get("patient_instruction", "")
                }
                result["content"] = entry.get("patient_summary", "")
                result["internal_sections_hidden"] = True
                return result
            return self._serialize_entry(entry, actor)
        return self._serialize_entry(entry, actor)

    def _serialize_entry(self, entry: dict, actor: dict, patient_mode: bool = False) -> dict:
        output = deepcopy(entry)
        output.pop("versions", None)
        if patient_mode:
            output["raw_content_hidden"] = True
            output["content"] = entry.get("patient_summary") or "Shared with your care team."
            output["sections"] = {}
            output["author_label"] = "Care team summary"
            output["type_label"] = "Patient-facing update"
            output["patient_instructions"] = deepcopy(entry.get("patient_instructions", []))
        else:
            output["author_label"] = {
                "system": "Nightingale AI",
                "staff": "Lena Ortiz, RN",
                "clinician": "Dr. Arjun Patel",
                "patient": "Maya Chen",
            }.get(entry.get("author_role"), entry.get("author_role"))
            output["type_label"] = entry.get("type", "entry").replace("_", " ").title()
            output["raw_content_hidden"] = False
        output["can_edit"] = self.can_edit_entry(entry, actor)
        output["can_approve_patient_copy"] = actor["role"] == "clinician" and entry.get("patient_visible") and not entry.get("patient_approved")
        output["can_comment"] = actor["role"] in {"staff", "clinician", "admin"}
        output["can_view_history"] = actor["role"] in {"clinician", "admin"} and entry.get("author_role") != "system"
        return output

    def can_edit_entry(self, entry: dict, actor: dict, section: Optional[str] = None) -> bool:
        role = actor["role"]
        if role == "admin":
            return False
        if entry.get("author_role") == "system":
            return False
        if role == "patient":
            return entry.get("author_role") == "patient" and entry.get("author_id") == actor["id"]
        if section:
            required = entry.get("section_roles", {}).get(section, entry.get("owner_role"))
            # Explicit section ownership permits a shared care-plan entry to
            # hold staff and clinician fields without either role overwriting
            # the other role's field.
            return required == role
        return entry.get("owner_role", entry.get("author_role")) == role

    def _require_entry(self, entry_id: str, actor: dict) -> dict:
        entry = self.entries.get(entry_id)
        if not entry:
            raise PolicyError("Entry not found", 404)
        self._scope(actor, entry["patient_id"])
        visible = self._visible_entry(entry, actor)
        if visible is None:
            raise PolicyError("This entry is not available in your role view", 403)
        return entry

    def timeline(self, patient_id: str, actor: dict) -> list[dict]:
        with self.lock:
            self._scope(actor, patient_id)
            visible = [
                item
                for entry in self.entries.values()
                if entry["patient_id"] == patient_id
                for item in [self._visible_entry(entry, actor)]
                if item is not None
            ]
            return sorted(visible, key=lambda item: item["created_at"], reverse=True)

    def tasks_for(self, patient_id: str, actor: dict) -> list[dict]:
        with self.lock:
            self._scope(actor, patient_id)
            results = []
            for task in self.tasks.values():
                if task["patient_id"] != patient_id:
                    continue
                if actor["role"] == "patient":
                    if not task.get("patient_visible"):
                        continue
                    task = deepcopy(task)
                    task["title"] = task.get("patient_title", task["title"])
                    task["owner_role"] = "patient" if task["owner_role"] == "patient" else "care_team"
                results.append(deepcopy(task))
            return sorted(results, key=lambda item: (item["status"] != "open", item["due"]))

    def resolve_provenance(self, pointer: dict, actor: dict) -> dict:
        entry = self._require_entry(pointer.get("entry_id", ""), actor)
        text = entry.get("content", "")
        start = int(pointer.get("start", 0))
        end = int(pointer.get("end", start))
        if start < 0 or end < start or end > len(text):
            raise PolicyError("Provenance span is invalid", 422)
        result = deepcopy(pointer)
        result["resolved"] = True
        result["resolved_text"] = text[start:end]
        result["entry_title"] = entry["title"]
        return result

    def _learning_weight(self, tags: Iterable[str], text: str = "") -> float:
        weights = {tag: 0.0 for tag in tags}
        for signal in self.learning_signals:
            if signal["action"] == "accepted":
                for tag in weights:
                    if tag.lower() == signal["feature"].lower() or signal["feature"].lower() in text.lower():
                        weights[tag] += 4.0
        return min(20.0, max(weights.values(), default=0.0))

    def generate_highlights(self, patient_id: str, actor: dict) -> list[dict]:
        with self.lock:
            self._scope(actor, patient_id)
            timeline = self.timeline(patient_id, actor)
            now = datetime.now(timezone.utc)
            candidates: list[dict] = []
            risk_terms = {
                "chest pressure": ("high", "Potential cardiac symptom; requires clinician review."),
                "chest pain": ("high", "Potential cardiac symptom; do not let an AI summary close the loop."),
                "shortness of breath": ("high", "Breathing symptom; review against asthma history."),
                "missed": ("medium", "Medication adherence may change the interpretation of the BP trend."),
                "allergy": ("high", "Allergy information is safety-critical and must be verified."),
            }
            for entry in timeline:
                content_lower = entry.get("content", "").lower()
                days_old = max(0.0, (now - iso_date(entry["created_at"])).total_seconds() / 86400)
                recency = max(0.0, 24.0 - min(days_old, 180.0) / 180.0 * 24.0)
                unresolved = sum(
                    1
                    for task in self.tasks.values()
                    if task["source_entry_id"] == entry["id"] and task["status"] == "open"
                )
                for phrase, (risk, reason) in risk_terms.items():
                    position = content_lower.find(phrase)
                    if position < 0:
                        continue
                    floor = 88.0 if risk == "high" else 60.0
                    tag_boost = 8.0 if phrase in [tag.lower() for tag in entry.get("tags", [])] else 0.0
                    learned = self._learning_weight(entry.get("tags", []), content_lower)
                    score = min(99.0, max(floor, floor + recency + unresolved * 10 + tag_boost + learned))
                    candidates.append(
                        {
                            "id": f"hl-{entry['id']}-{phrase.replace(' ', '-')}",
                            "entry_id": entry["id"],
                            "title": phrase.title(),
                            "importance_score": round(score, 1),
                            "risk_level": risk,
                            "risk_reason": reason,
                            "confidence_label": self.confidence_label(entry.get("confidence")),
                            "confidence_basis": "Evidence span + deterministic safety rule",
                            "status": self.highlights.get(f"hl-{entry['id']}-{phrase.replace(' ', '-')}", {}).get("status", "suggested"),
                            "feature": phrase,
                            "source_label": entry.get("source_label"),
                            "provenance_pointer": source_pointer(entry, phrase),
                            "entry_title": entry["title"],
                            "created_at": entry["created_at"],
                            "source_type": entry["type"],
                        }
                    )
            # Clinician-confirmed and unresolved items float together, then the
            # timeline order breaks ties. Critical floors cannot be learned away.
            return sorted(candidates, key=lambda item: (-item["importance_score"], item["created_at"]))[:8]

    @staticmethod
    def confidence_label(value: Optional[float]) -> str:
        if value is None:
            return "not applicable"
        if value >= 0.85:
            return "high · evidence matched"
        if value >= 0.70:
            return "medium · review suggested"
        return "low · abstain / verify"

    def care_note(self, patient_id: str, actor: dict) -> dict:
        started = time.perf_counter()
        with self.lock:
            patient = self._scope(actor, patient_id)
            result = {
                "patient": deepcopy(patient),
                "timeline": self.timeline(patient_id, actor),
                "tasks": self.tasks_for(patient_id, actor),
                "highlights": self.generate_highlights(patient_id, actor),
                "learning": {
                    "accepted_count": sum(1 for item in self.learning_signals if item["action"] == "accepted"),
                    "message": "Suggestions learn from confirmed patterns, but safety floors and human sign-off stay fixed.",
                },
                "role": actor["role"],
                "permissions": {
                    "can_add_staff_note": actor["role"] in {"staff", "clinician", "admin"},
                    "can_add_clinician_note": actor["role"] in {"clinician"},
                    "can_add_patient_insight": actor["role"] == "patient",
                    "can_view_audit": actor["role"] in {"clinician", "admin"},
                    "can_capture_voice": actor["role"] in {"patient", "staff", "clinician"},
                },
            }
            # Measured on the warm in-memory path; a real deployment would
            # record the same query at the API edge with a trace id.
            result["warm_path_ms"] = round((time.perf_counter() - started) * 1000, 2)
            return result

    def _audit(self, actor: dict, action: str, entity_type: str, entity_id: str, **metadata: Any) -> None:
        self.audit_log.append(
            {
                "id": f"aud-{uuid.uuid4().hex[:10]}",
                "timestamp": now_iso(),
                "actor_id": actor["id"],
                "actor_role": actor["role"],
                "action": action,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "metadata": metadata,
            }
        )

    def create_entry(self, patient_id: str, actor: dict, payload: dict) -> dict:
        with self.lock:
            self._scope(actor, patient_id)
            requested = payload.get("type", "")
            role_type = {
                "staff_note": "staff",
                "clinician_note": "clinician",
                "patient_insight": "patient",
            }.get(requested)
            if role_type != actor["role"]:
                raise PolicyError("This role cannot create that entry type", 403)
            content = str(payload.get("content", "")).strip()
            if not content:
                raise PolicyError("A note needs content", 422)
            entry = self._add_entry(
                {
                    "patient_id": patient_id,
                    "created_at": now_iso(),
                    "author_role": actor["role"],
                    "author_id": actor["id"],
                    "type": requested,
                    "title": str(payload.get("title") or {"staff_note": "Staff note", "clinician_note": "Clinician note", "patient_insight": "Patient insight"}[requested]),
                    "content": content,
                    "sections": {"note": content},
                    "risk_level": payload.get("risk_level", "low"),
                    "tags": payload.get("tags", []),
                    "source_id": f"manual-{uuid.uuid4().hex[:10]}",
                    "source_label": f"{actor['role'].title()} note · {datetime.now().strftime('%d %b %Y')}",
                    "patient_visible": actor["role"] == "patient",
                    "owner_role": actor["role"],
                    "section_roles": {"note": actor["role"]},
                    "patient_summary": content if actor["role"] == "patient" else "",
                }
            )
            self._audit(actor, "created", "entry", entry["id"], entry_type=requested, version=1)
            return self._serialize_entry(entry, actor)

    def update_entry(self, entry_id: str, actor: dict, payload: dict) -> dict:
        with self.lock:
            entry = self._require_entry(entry_id, actor)
            section = payload.get("section")
            if not self.can_edit_entry(entry, actor, section):
                raise PolicyError("Your role cannot edit this note or section", 403)
            base_version = int(payload.get("base_version", entry["version"]))
            current_version = entry["version"]
            if base_version > current_version:
                raise PolicyError("Client version is ahead of server", 422)
            if base_version != current_version:
                if not section or entry.get("section_versions", {}).get(section, 0) > base_version:
                    raise ConflictError(
                        "This section changed while you were editing. The latest server version remains authoritative; refresh to compare.",
                        self._serialize_entry(entry, actor),
                    )
            before = snapshot(entry)
            if section:
                if "sections" not in entry:
                    entry["sections"] = {}
                entry["sections"][section] = str(payload.get("content", "")).strip()
                entry.setdefault("section_versions", {})[section] = current_version + 1
                # Keep the main text useful for timeline search and provenance.
                entry["content"] = " ".join(str(value) for value in entry["sections"].values() if value)
                if section == "patient_instruction":
                    entry["patient_instructions"] = [entry["sections"][section]]
                    # Any change to patient-facing text must pass through the
                    # explicit clinician approval gate again.
                    entry["patient_approved"] = False
            else:
                entry["content"] = str(payload.get("content", "")).strip()
                if "restore_sections" in payload:
                    entry["sections"] = deepcopy(payload["restore_sections"])
                    entry["patient_summary"] = payload.get("restore_patient_summary", "")
                    entry["patient_instructions"] = deepcopy(payload.get("restore_patient_instructions", []))
                    entry["patient_approved"] = bool(payload.get("restore_patient_approved", False))
            if "title" in payload:
                entry["title"] = str(payload["title"]).strip()
            entry["version"] = current_version + 1
            after = snapshot(entry)
            entry["versions"].append(
                {
                    "version": entry["version"],
                    "created_at": now_iso(),
                    "actor_id": actor["id"],
                    "actor_role": actor["role"],
                    "snapshot": after,
                    "diff": make_diff(before, after),
                }
            )
            self._audit(
                actor,
                "updated",
                "entry",
                entry_id,
                before_version=current_version,
                after_version=entry["version"],
                section=section or "content",
                changed_fields=["content" if not section else f"sections.{section}"],
            )
            return self._serialize_entry(entry, actor)

    def revisions(self, entry_id: str, actor: dict) -> dict:
        with self.lock:
            entry = self._require_entry(entry_id, actor)
            if actor["role"] not in {"clinician", "admin"} or entry.get("author_role") == "system":
                raise PolicyError("Revision history is restricted to authorized clinical oversight", 403)
            return {
                "entry_id": entry_id,
                "current_version": entry["version"],
                "versions": deepcopy(entry["versions"]),
            }

    def revert(self, entry_id: str, actor: dict, target_version: int) -> dict:
        with self.lock:
            entry = self._require_entry(entry_id, actor)
            if not self.can_edit_entry(entry, actor):
                raise PolicyError("Your role cannot revert this note", 403)
            target = next((item for item in entry["versions"] if item["version"] == target_version), None)
            if not target:
                raise PolicyError("Version not found", 404)
            payload = {
                "base_version": entry["version"],
                "content": target["snapshot"]["content"],
                "restore_sections": deepcopy(target["snapshot"].get("sections", {})),
                "restore_patient_summary": target["snapshot"].get("patient_summary", ""),
                "restore_patient_instructions": deepcopy(target["snapshot"].get("patient_instructions", [])),
                "restore_patient_approved": target["snapshot"].get("patient_approved", False),
            }
            return self.update_entry(entry_id, actor, payload)

    def add_comment(self, entry_id: str, actor: dict, payload: dict) -> dict:
        with self.lock:
            entry = self._require_entry(entry_id, actor)
            if actor["role"] not in {"staff", "clinician"}:
                raise PolicyError("Comments are restricted to care-team roles", 403)
            body = str(payload.get("body", "")).strip()
            if not body:
                raise PolicyError("Comment cannot be empty", 422)
            comment = {
                "id": f"com-{uuid.uuid4().hex[:10]}",
                "entry_id": entry_id,
                "patient_id": entry["patient_id"],
                "body": body,
                "mentions": parse_mentions(body),
                "assigned_to": payload.get("assigned_to"),
                "status": "open",
                "created_at": now_iso(),
                "author_id": actor["id"],
                "author_role": actor["role"],
            }
            self.comments[comment["id"]] = comment
            self._audit(actor, "commented", "comment", comment["id"], entry_id=entry_id, mentions=comment["mentions"])
            return deepcopy(comment)

    def comments_for(self, entry_id: str, actor: dict) -> list[dict]:
        with self.lock:
            self._require_entry(entry_id, actor)
            if actor["role"] not in {"staff", "clinician", "admin"}:
                raise PolicyError("Comments are not part of the patient-facing view", 403)
            return sorted(
                [deepcopy(item) for item in self.comments.values() if item["entry_id"] == entry_id],
                key=lambda item: item["created_at"],
            )

    def toggle_comment(self, comment_id: str, actor: dict) -> dict:
        with self.lock:
            comment = self.comments.get(comment_id)
            if not comment:
                raise PolicyError("Comment not found", 404)
            self._scope(actor, comment["patient_id"])
            if actor["role"] not in {"staff", "clinician"}:
                raise PolicyError("Only care-team roles can resolve comments", 403)
            comment["status"] = "resolved" if comment["status"] == "open" else "open"
            comment["resolved_at"] = now_iso() if comment["status"] == "resolved" else None
            self._audit(actor, "comment_toggled", "comment", comment_id, status=comment["status"], entry_id=comment["entry_id"])
            return deepcopy(comment)

    def decide_highlight(self, highlight_id: str, actor: dict, decision: str) -> dict:
        with self.lock:
            if actor["role"] not in {"staff", "clinician"}:
                raise PolicyError("Only care-team users can confirm highlight suggestions", 403)
            highlights = self.generate_highlights(PATIENT_ID, actor)
            highlight = next((item for item in highlights if item["id"] == highlight_id), None)
            if not highlight:
                raise PolicyError("Highlight suggestion not found", 404)
            if decision not in {"accepted", "rejected"}:
                raise PolicyError("Decision must be accepted or rejected", 422)
            self.highlights[highlight_id] = {"status": decision, "decided_by": actor["id"], "decided_at": now_iso()}
            if decision == "accepted":
                self.learning_signals.append(
                    {
                        "id": f"learn-{uuid.uuid4().hex[:10]}",
                        "feature": highlight["feature"],
                        "action": "accepted",
                        "actor_role": actor["role"],
                        "created_at": now_iso(),
                    }
                )
            self._audit(actor, f"highlight_{decision}", "highlight", highlight_id, feature=highlight["feature"], entry_id=highlight["entry_id"])
            highlight["status"] = decision
            return highlight

    def resolve_task(self, task_id: str, actor: dict) -> dict:
        with self.lock:
            task = self.tasks.get(task_id)
            if not task:
                raise PolicyError("Task not found", 404)
            self._scope(actor, task["patient_id"])
            if actor["role"] not in {"staff", "clinician", "admin"}:
                raise PolicyError("Patient tasks are confirmed by the care team", 403)
            task["status"] = "done" if task["status"] == "open" else "open"
            task["resolved_at"] = now_iso() if task["status"] == "done" else None
            self._audit(actor, "task_toggled", "task", task_id, status=task["status"])
            return deepcopy(task)

    def approve_patient_copy(self, entry_id: str, actor: dict) -> dict:
        with self.lock:
            entry = self._require_entry(entry_id, actor)
            if actor["role"] != "clinician" or not entry.get("patient_visible"):
                raise PolicyError("Only a clinician can approve patient-facing copy", 403)
            entry["patient_approved"] = True
            self._audit(actor, "patient_copy_approved", "entry", entry_id, version=entry["version"])
            return self._serialize_entry(entry, actor)

    def create_voice_entry(self, patient_id: str, actor: dict, payload: dict) -> dict:
        with self.lock:
            self._scope(actor, patient_id)
            if actor["role"] not in {"patient", "staff", "clinician"}:
                raise PolicyError("This role cannot start a capture", 403)
            # The demo accepts only a redacted, synthetic transcript. Raw audio
            # is intentionally never persisted or sent to a model.
            supplied = str(payload.get("raw_transcript") or payload.get("redacted_transcript", "")).strip()
            redacted, redaction_counts = redact_phi(supplied)
            if not redacted or any(token in redacted.lower() for token in ["real name", "phone number", "ic number"]):
                raise PolicyError("Capture must be redacted before AI processing", 422)
            interaction = "patient" if actor["role"] == "patient" else ("doctor" if actor["role"] == "clinician" else "nurse")
            entry = self._add_entry(
                {
                    "patient_id": patient_id,
                    "created_at": now_iso(),
                    "author_role": "system",
                    "author_id": "ai-scribe",
                    "type": f"ai_{interaction}_consult_summary" if interaction != "patient" else "ai_patient_session_summary",
                    "title": f"AI {interaction} capture · redacted demo summary",
                    "content": redacted,
                    "sections": {"summary": redacted},
                    "risk_level": "medium",
                    "confidence": 0.72,
                    "tags": ["voice capture", "redacted before processing"],
                    "source_id": f"voice-session-{uuid.uuid4().hex[:10]}",
                    "source_label": f"{interaction.title()} voice capture · redaction preview",
                    "provenance_kind": "redacted_transcript",
                    "patient_visible": False,
                }
            )
            self._audit(actor, "voice_capture_summarized", "entry", entry["id"], redaction="passed", redaction_counts=redaction_counts, raw_audio_stored=False)
            return self._serialize_entry(entry, actor)

    def audit_for(self, patient_id: str, actor: dict) -> list[dict]:
        with self.lock:
            self._scope(actor, patient_id)
            if actor["role"] not in {"clinician", "admin"}:
                raise PolicyError("Audit view is restricted to clinical oversight", 403)
            ids = {entry_id for entry_id, entry in self.entries.items() if entry["patient_id"] == patient_id}
            return [deepcopy(item) for item in self.audit_log if item["entity_id"] in ids or item["metadata"].get("entry_id") in ids]


STORE = CareNoteStore()


def read_json(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0"))
    if length > 1_000_000:
        raise PolicyError("Payload too large", 413)
    raw = handler.rfile.read(length) if length else b"{}"
    try:
        return json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise PolicyError(f"Invalid JSON: {exc}", 400)


class CareNoteHandler(BaseHTTPRequestHandler):
    server_version = "NightingaleCareNote/0.1"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        # Keep the demo terminal quiet; the UI has its own connection status.
        return

    def actor(self) -> dict:
        role = self.headers.get("X-Demo-Role", "clinician").lower()
        user_id = self.headers.get("X-Demo-User")
        return STORE.actor(role, user_id)

    def send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, exc: Exception) -> None:
        status = exc.status if isinstance(exc, PolicyError) else 500
        payload = {"error": str(exc), "status": status}
        if isinstance(exc, ConflictError) and exc.latest:
            payload["latest"] = exc.latest
            payload["resolution"] = "reject_stale_same_section; latest server version remains authoritative"
        self.send_json(payload, status)

    def do_GET(self) -> None:  # noqa: N802
        try:
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            if path == "/api/health":
                self.send_json({"ok": True, "service": "care-note", "synthetic_data": True})
                return
            if path == "/api/care-note" or path == f"/api/patients/{PATIENT_ID}/care-note":
                self.send_json(STORE.care_note(PATIENT_ID, self.actor()))
                return
            if path == "/api/audit":
                self.send_json({"items": STORE.audit_for(PATIENT_ID, self.actor())})
                return
            match = re.fullmatch(r"/api/entries/([^/]+)/versions", path)
            if match:
                self.send_json(STORE.revisions(match.group(1), self.actor()))
                return
            match = re.fullmatch(r"/api/entries/([^/]+)/comments", path)
            if match:
                self.send_json({"items": STORE.comments_for(match.group(1), self.actor())})
                return
            if path.startswith("/api/"):
                raise PolicyError("API route not found", 404)
            self.serve_static(path)
        except Exception as exc:  # deliberate API boundary
            self.send_error_json(exc)

    def do_POST(self) -> None:  # noqa: N802
        try:
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/")
            body = read_json(self)
            actor = self.actor()
            if path == "/api/entries":
                self.send_json(STORE.create_entry(PATIENT_ID, actor, body), 201)
                return
            match = re.fullmatch(r"/api/entries/([^/]+)/comments", path)
            if match:
                self.send_json(STORE.add_comment(match.group(1), actor, body), 201)
                return
            match = re.fullmatch(r"/api/comments/([^/]+)/toggle", path)
            if match:
                self.send_json(STORE.toggle_comment(match.group(1), actor))
                return
            match = re.fullmatch(r"/api/entries/([^/]+)/revert", path)
            if match:
                self.send_json(STORE.revert(match.group(1), actor, int(body.get("target_version"))), 200)
                return
            match = re.fullmatch(r"/api/highlights/([^/]+)/decision", path)
            if match:
                self.send_json(STORE.decide_highlight(match.group(1), actor, str(body.get("decision"))))
                return
            match = re.fullmatch(r"/api/tasks/([^/]+)/toggle", path)
            if match:
                self.send_json(STORE.resolve_task(match.group(1), actor))
                return
            match = re.fullmatch(r"/api/entries/([^/]+)/approve-patient", path)
            if match:
                self.send_json(STORE.approve_patient_copy(match.group(1), actor))
                return
            if path == "/api/voice-sessions":
                self.send_json(STORE.create_voice_entry(PATIENT_ID, actor, body), 201)
                return
            raise PolicyError("API route not found", 404)
        except Exception as exc:
            self.send_error_json(exc)

    def do_PATCH(self) -> None:  # noqa: N802
        try:
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/")
            body = read_json(self)
            match = re.fullmatch(r"/api/entries/([^/]+)", path)
            if match:
                self.send_json(STORE.update_entry(match.group(1), self.actor(), body))
                return
            raise PolicyError("API route not found", 404)
        except Exception as exc:
            self.send_error_json(exc)

    def serve_static(self, path: str) -> None:
        relative = "index.html" if path == "/" else path.lstrip("/")
        target = (STATIC_DIR / relative).resolve()
        if STATIC_DIR.resolve() not in target.parents and target != STATIC_DIR.resolve():
            raise PolicyError("Invalid static path", 403)
        if not target.exists() or not target.is_file():
            raise PolicyError("Not found", 404)
        mime = {".html": "text/html", ".css": "text/css", ".js": "text/javascript", ".svg": "image/svg+xml"}.get(target.suffix, "application/octet-stream")
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", f"{mime}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)


def run() -> None:
    server = ThreadingHTTPServer((HOST, PORT), CareNoteHandler)
    print(f"Nightingale Care Note running at http://{HOST}:{PORT}")
    print("Synthetic demo data only · Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Care Note")
    finally:
        server.server_close()


if __name__ == "__main__":
    run()
