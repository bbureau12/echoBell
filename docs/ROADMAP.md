# EchoBell Architecture Roadmap

This document describes EchoBell’s system architecture as a layered roadmap.
Each layer builds on the previous one and produces concrete, inspectable outputs
(evidence, state, or actions). The goal is to preserve explainability while
enabling increasingly sophisticated behavior.

EchoBell’s core design principle:

> **Perception produces evidence.  
> Reasoning interprets evidence.  
> Policy decides actions.  
> Language assists, but never overrides policy.**

---

## Layer 1: Perception (Sensors → Evidence)

**Status:** Largely implemented  
**Purpose:** Convert raw sensor input into structured, explainable facts.

### Responsibilities
- Capture frames from cameras
- Perform object detection (people, vehicles, packages, animals)
- Extract visual attributes:
  - bounding boxes
  - dominant color
  - confidence
- Run OCR on relevant objects (vehicles, packages)
- Estimate age group (young / adult / unknown)
- Perform visitor recognition (known / trusted / new)
- Perform license plate normalization and hashing

### Outputs
- `VisionResult`
- `SceneObject` list with object-level evidence
- Object-level evidence such as:
  - `vision.class=person`
  - `vision.color=tan`
  - `ocr.plate_text=ABC123`
  - `visitor.known=true`
  - `age.age_group=adult`

### Design Notes
- Perception **does not** infer intent or threat
- All outputs are atomic, confidence-scored evidence

---

## Layer 2: Scene Memory (Evidence → Context)

**Status:** In progress  
**Purpose:** Add *time* and *relationships* to perception data.

### 2a. Temporal Scene Tracking (ADR-0005)

Tracks objects across frames per camera.

#### Responsibilities
- Detect object entry, exit, and persistence
- Maintain short-lived per-camera state
- Tolerate detection flicker with grace periods

#### Emits Evidence
- `scene.person_entered`
- `scene.vehicle_exited`
- `scene.person_present`

---

### 2b. Visit-scoped Entity Associations (ADR-0006)

Infers relationships between entities *within a single visit*.

#### Responsibilities
- Associate people with nearby vehicles or packages
- Use proximity, overlap, and detector confidence
- Store visit-local relationships only

#### Stores
- `visit_entity_links`

#### Emits Evidence
- `scene.link.arrived_with_vehicle`
- `scene.link.carrying_package`

#### Design Notes
- Associations are **soft evidence**, not identity claims
- No ownership or long-term binding implied

---

## Layer 3: Intent Inference (Context → Meaning)

**Status:** Planned  
**Purpose:** Interpret evidence into a probable intent.

### Responsibilities
- Consume all accumulated evidence:
  - perception
  - temporal signals
  - visit entity links
  - historical visitor / plate context
- Infer intent per person or visit:
  - delivery
  - guest
  - salesman
  - charity
  - authority
  - suspicious / unknown

### Output
- `intent`
- `confidence`
- rationale (which evidence contributed)

### Design Notes
- Implemented initially via rules / scoring
- LLM consulted only for ambiguous or borderline cases
- Intent is probabilistic, never binary truth

---

## Layer 4: Policy & Orchestration (Meaning → Decisions)

**Status:** Planned  
**Purpose:** Decide *what EchoBell should do*.

### Responsibilities
- Apply household policy to inferred intent
- Incorporate context:
  - time of day
  - homeowner availability
  - prior warnings
  - escalation history
- Rate-limit and sequence actions

### Examples
- Delivery → notify only if package left
- Salesman → polite decline via speaker
- Child collecting for charity → notify human if available
- Authority → notify human immediately
- Suspicious lingering → announce recording, save media, alert

### Design Notes
- Deterministic and auditable
- LLM may assist with phrasing or edge reasoning, never final authority

---

## Layer 5: Communication & Actuation (Decisions → Actions)

**Status:** Planned  
**Purpose:** Execute decisions reliably.

### Responsibilities
- Speak to visitors (TTS)
- Send notifications (Telegram, push)
- Save screenshots / clips
- Trigger physical indicators (lights, future expansions)

### Design Notes
- Stateless and robust
- No reasoning or policy logic

---

## LLM Role (Advisory, Not Core)

**Purpose:** Assist higher-level reasoning and communication.

### Appropriate Uses
- Generate polite, context-aware responses
- Summarize incidents for humans
- Resolve ambiguous intent cases on request

### Explicit Non-Uses
- Directly triggering alerts
- Overriding policy
- Acting without evidence

---

## Architectural Summary

| Layer | Input | Output |
|-----|------|--------|
| Perception | Sensors | Evidence |
| Scene Memory | Evidence | Contextual Evidence |
| Intent Inference | Context | Intent + Confidence |
| Policy | Intent | Actions |
| Communication | Actions | Real-world Effects |

EchoBell remains explainable, auditable, and conservative by design.

---

## Guiding Principles

- Evidence is never discarded
- Intent is always probabilistic
- Policy decisions are deterministic
- LLMs assist, but never decide alone
- Prefer false negatives to false positives
- Humans remain in control

