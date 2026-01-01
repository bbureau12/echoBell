# ADR-0006: Visit-scoped entity association links (human ↔ vehicle / object)

Date: 2025-12-31  
Status: Accepted

## Context

EchoBell’s vision pipeline identifies entities such as people, vehicles, and
objects within a single snapshot or short visit window. While temporal scene
tracking (ADR-0005) captures *changes over time* (entering, exiting, persisting),
it does not express *relationships between entities* observed together in a
scene.

Examples of important but currently implicit relationships include:
- a person arriving with a vehicle
- a person carrying or standing with a package
- multiple people associated with the same vehicle during a visit

These relationships are valuable for intent inference (e.g. delivery vs guest)
even when strong identifiers (plates, faces) are unavailable. However, such
associations must remain explainable, confidence-scored, and non-binding, and
must not imply ownership or long-term identity.

## Decision

EchoBell introduces a **visit-scoped entity association layer** that infers and
records relationships between detected entities *within a single visit or
event*.

This layer:
- Computes relationship edges (e.g. `arrived_with_vehicle`,
  `carrying_package`) based on proximity, overlap, and detector confidence
- Stores these edges in a generic `visit_entity_links` table
- Associates entities by their scene-local `object_id`, with optional enrichment
  via stable keys (e.g. `visitor_id`, `plate_hmac`) when available
- Emits association evidence for downstream intent classification
- Does not assert identity, ownership, or persistence beyond the visit scope

Associations are treated as *soft evidence* and may be updated, decayed, or
discarded if contradicted by later signals.

## Consequences

### Pros
- Adds explicit relational context (“who is with what”) to scene understanding
- Improves intent inference without requiring plate OCR or facial recognition
- Preserves explainability via confidence-scored, inspectable edges
- Keeps relationship inference decoupled from both vision detection and
  classification logic

### Cons
- Introduces potential false associations in dense or ambiguous scenes
- Adds an additional processing and storage step to the pipeline

### Mitigations
- Prefer conservative thresholds and false negatives over false positives
- Scope all associations strictly to a single visit/event
- Treat associations as evidence, not ground truth
- Avoid promotion of visit-scoped links to long-term identity without explicit,
  higher-confidence confirmation

## Relationship to ADR-0005

ADR-0005 (Scene awareness via temporal tracking) focuses on *state over time*
(e.g. enter/exit/presence across frames).  
ADR-0006 focuses on *relational structure within a visit*.

The two layers are complementary:
- Temporal signals from ADR-0005 may strengthen or weaken associations in
  ADR-0006
- ADR-0006 provides relational evidence that ADR-0005 does not encode

They remain architecturally separate to preserve clarity of responsibility and
avoid overloading the definition of “scene awareness.”
