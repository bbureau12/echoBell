# Architecture Decision Records (ADR)

This directory captures significant architectural and design decisions made
during the evolution of EchoBell.

Early prototyping occurred prior to formal ADR tracking.
Records begin at the point where persistence, privacy, and system boundaries
became stable enough to warrant documentation.

## Index

### Identity & Privacy
- **ADR-00001**: Event creation without visitor identity
- **ADR-00002**: Plate privacy via HMAC hashing
- **ADR-00003**: License plates as events, not identity anchors

### Scene Awareness & Tracking
- **ADR-0005**: Scene awareness temporal tracking (SceneTracker design)
- **ADR-00006**: Scene awareness entity association (person-vehicle linkage)
- **ADR-0010**: Cross-camera person tracking via visitor_id

### Intent Classification
- **ADR-0004**: Vehicle role inference from visual attributes
- **ADR-0007**: Cross-camera intent persistence via visitor history
- **ADR-0009**: Scene context for concurrent intent classification

### Policy & Access Control
- **ADR-0008**: Trusted entity allowlists (plates, faces)

### Voice & LLM Integration
- **ADR-0015**: LLM-controlled voice listening mode for multi-turn conversations

