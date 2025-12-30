# ADR-0001: Allow visitor events without a visitor_id
Date: 2025-12-30
Status: Accepted

## Context
EchoBell initially modeled all events as being associated with a human visitor.
As vehicle detection and license plate recognition were added, it became clear
that meaningful events can occur without a visible person (e.g. vehicle arrival,
package drop-off, or delivery truck stopping briefly).

The existing schema enforced NOT NULL on visitor_events.visitor_id, which caused
plate-only events to fail insertion.

## Decision
visitor_events.visitor_id was changed to allow NULL values.
An event now represents "something happened at the doorway", not necessarily
"a person was identified".

Human visitors are linked when present, but are no longer required for event creation.

## Consequences
Pros:
- Supports vehicle-only and plate-only events
- Enables earlier intent inference before a person is visible
- Simplifies future support for packages, animals, and non-human actors

Cons:
- Some downstream logic must tolerate visitor_id = NULL

Mitigations:
- Classifier rules explicitly check for visitor presence when required
- Plate and vehicle evidence is linked via event_id instead
