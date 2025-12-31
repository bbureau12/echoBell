# ADR-0005: Scene awareness via temporal tracking
Date: 2025-12-30
Status: Accepted

## Context
EchoBell’s vision pipeline produces per-frame detections of people, vehicles,
and objects. While this snapshot-level information is sufficient for basic
recognition, it does not capture *change over time*, such as:

- a vehicle arriving or leaving
- a person exiting the scene
- an object remaining present across multiple frames

Intent inference (e.g. delivery, departure, lingering presence) depends heavily
on understanding these temporal changes rather than static observations.

## Decision
EchoBell introduces a dedicated scene awareness layer responsible for tracking
objects across frames and emitting temporal evidence.

This layer:
- Tracks objects over time using a combination of strong keys (e.g. plate_hmac,
  visitor_id) and fallback IoU-based bounding box matching
- Maintains short-lived state per camera
- Emits scene-level evidence such as:
  - scene.vehicle_entered
  - scene.vehicle_exited
  - scene.vehicle_present
  - scene.person_exited
- Does not perform intent classification itself

Scene awareness runs after vision inference and before intent classification.
Classification consumes scene evidence in the same way as other evidence sources.

## Consequences
Pros:
- Enables intent inference based on change over time
- Decouples state tracking from both vision and classification
- Allows operation even when strong identifiers (plates, faces) are unavailable
- Improves explainability by making temporal reasoning explicit

Cons:
- Introduces persistent state that must be maintained and expired
- Adds complexity to the event processing pipeline

Mitigations:
- Use conservative grace periods to avoid false exits due to detection flicker
- Prefer false negatives over false positives for entry/exit detection
- Treat scene signals as evidence, not ground truth
