# ADR-0004: Infer vehicle role instead of vehicle identity
Date: 2025-12-30
Status: Accepted

## Context
EchoBell detects vehicles using object detection (e.g. car, truck, motorbike),
package presence, OCR text, and license plate repeat behavior.

A design decision arose around whether to identify vehicles by make/model or
assign them a persistent vehicle identity.

Vehicle identity is difficult to determine reliably from vision alone, varies
across regions, and increases privacy risk. Additionally, vehicle identity is
often less important than understanding the *role* the vehicle plays in a visit
(e.g. delivery, personal arrival, service).

## Decision
EchoBell infers *vehicle role* rather than vehicle identity.

Vehicle observations are classified into coarse roles such as:
- personal_likely
- commercial_likely
- courier_likely
- unknown

Role inference is based on:
- object detection class (car, truck, motorbike)
- presence of packages
- OCR tokens associated with vehicles
- repeat plate behavior (when available)

No attempt is made to identify vehicle make, model, or owner.

## Consequences
Pros:
- Improves intent inference without requiring fragile classifiers
- Avoids over-identification and privacy escalation
- Keeps reasoning explainable and auditable
- Works even with partial or noisy observations

Cons:
- Cannot distinguish between similar vehicles of the same class
- Some edge cases require additional context to disambiguate

Mitigations:
- Combine vehicle role with other evidence (time of day, dwell time, packages)
- Allow future refinement through optional, opt-in classifiers

## Implementation Notes
License plate OCR candidates are constrained using multiple conservative
heuristics to reduce false positives:

- Tokens must be associated with a detected vehicle
- Tokens must appear in the lower-middle region of the vehicle bounding box
- Tokens must occupy a plausible fraction of the vehicle area

These spatial and size-based constraints reduce false positives from logos,
decals, and background text while preserving robustness across camera
distances and mounting configurations.