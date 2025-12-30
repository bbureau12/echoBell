# ADR-0003: Treat license plates as evidence, not identity
Date: 2025-12-30
Status: Accepted

## Context
As vehicle detection and license plate OCR were added to EchoBell, an early design
question emerged: should a license plate represent a "visitor" in the same way
a human face does?

While plates can be used to detect repeat vehicles, equating a vehicle with a
visitor conflates ownership, operator, and intent. A vehicle may be shared,
borrowed, rented, or operated by different individuals over time.

Additionally, treating plates as identity would elevate PII sensitivity and
encourage over-attribution in intent classification.

## Decision
License plates are treated strictly as *evidence* associated with an event, not
as an identity.

- `visitor_events` may exist without a visitor_id
- Plates are linked to events via `visitor_event_plate_sightings`
- Plate repeat statistics are stored separately in `plate_visitors`
- Human identity (when present) remains the only source of `visitor_id`

Intent classification may consider plate history as supporting context, but plate
data never creates or replaces a visitor identity.

## Consequences
Pros:
- Prevents false attribution of identity to vehicles
- Keeps human identity modeling conceptually clean
- Supports privacy-first design and future policy changes
- Allows multiple people to legitimately share a vehicle

Cons:
- Some events require inference without a definitive actor
- Additional joins are needed when correlating vehicle history

Mitigations:
- Intent rules explicitly combine plate evidence with other signals (vehicle type,
  packages, dwell time)
- Trusted plates are labeled by role (e.g. "mail", "neighbor"), not by person
