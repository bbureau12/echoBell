# EchoBell Demo Walkthrough

This document outlines a short, repeatable demo showcasing EchoBell’s core
capabilities. The demo is designed to be completed in approximately 5 minutes.

---

## Setup
1. Start the EchoBell service with vision enabled.
2. Ensure database schema is initialized.
3. Optional: preload one trusted face and one trusted plate.

---

## Scenario 1: Known visitor arrival (human identity)

**What happens**
- A known person approaches the door.
- Face detection produces an embedding.
- Visitor is matched against trusted embeddings (via InsightFace buffalo_l).
- Match requires similarity >= threshold (e.g., 0.67).

**Evidence**
- vision.person_present = true
- visitor_kind = trusted
- visitor_similarity = 0.80 (example high match)
- visitor.prior_intent (if visitor has event history)

**Result**
- visitor_event created with visitor_id
- intent inferred (e.g., "neighbor_help") potentially boosted by prior history
- snapshot saved (subject to retention policy)
- Face embedding stored in trusted_person_embedding (privacy: hashed, not raw image)

**What this demonstrates**
- Human identity is modeled explicitly when confidence is sufficient
- Facial recognition uses privacy-safe embeddings, not images
- Identity used for intent classification (prior history provides context)
- Similarity threshold prevents false positives

---

## Scenario 2: Vehicle-only delivery (no visible person)

**What happens**
- A delivery truck pulls up.
- No person is visible initially (or too far away for face detection).
- OCR detects license plate text (possibly split across tokens).
- Plate tokens are merged using proximity heuristics.
- Plate is hashed and stored in plate_visitors.
- Plate is linked to visitor_event via visitor_event_plate_sightings.

**Evidence**
- vehicle_present = true
- vehicle_raw_class = truck (or car)
- ocr.plate_text = "ABC123" (after grouping and selection)
- visitor_id = NULL (no person detected/matched)

**Result**
- visitor_event created without visitor_id (event exists independently)
- plate visit recorded in plate_visitors (first_seen_ts, last_seen_ts, visit_count)
- plate linked to event in visitor_event_plate_sightings
- intent inferred as "unknown" or boosted to "package_drop" if plate has history

**What this demonstrates**
- Events can exist without a human visitor (vehicle-only scenarios)
- Plates are treated as evidence, not identity
- Privacy-safe repeat detection (HMAC, no raw text storage)
- Plate history can influence intent classification

---

## Scenario 3: OCR split plate tokens

**What happens**
- OCR produces multiple short tokens (e.g. "NAS" + "997").
- Tokens are spatially close and associated with the same vehicle.
- Tokens are merged into a valid plate candidate using proximity heuristics.
- Confidence is boosted based on pattern matching (length, alpha/digit balance).

**Evidence**
- ocr.token entries preserved (individual fragments)
- ocr.plate_text emitted once (best candidate only)
- Confidence boosted from raw OCR (e.g., 0.12 → 0.74) for well-formed plates

**Result**
- Plate hashed consistently (HMAC-SHA256)
- No raw plate text stored in plate_visitors (privacy)
- Plate linked to event via visitor_event_plate_sightings
- Passes confidence threshold (default 0.65) after pattern boost

**What this demonstrates**
- Robust OCR handling with spatial grouping
- Pattern-based confidence boosting for standard plates
- Conservative heuristics (best plate selection prevents false positives)
- Deterministic privacy-safe hashing

---

## Scenario 4: Camera capability gating

**What happens**
- System has multiple cameras with different capability levels.
- Landscape camera (level 1): Basic motion detection only.
- Vehicle detail camera (level 2): Enables plate OCR.
- Facial detail camera (level 3): Enables face recognition.

**Evidence**
- Camera capabilities stored in camera_capability_level table
- allow_vehicle_detail flag controls plate OCR execution
- allow_facial_detail flag controls face recognition

**Result**
- Privacy controls built into detection pipeline
- Lower-resolution cameras don't attempt expensive/invasive operations
- Capability-appropriate evidence collection

**What this demonstrates**
- Granular privacy controls based on camera placement
- Resource optimization (don't run OCR where not needed)
- Configurable per-camera behavior

---

## Key Design Principles Highlighted
- Events represent *observations*, not assumptions
- Identity is optional and confidence-gated
- Vehicles and plates provide context, not attribution
- Privacy-first data handling throughout (HMAC hashing, embeddings not images)
- Camera capabilities control what operations are permitted
- Pattern-based confidence boosting improves low-confidence OCR
- Spatial proximity heuristics handle fragmented OCR reads
- Best plate selection prevents false positives (bumper stickers, misreads)
- Plate visit history can boost intent classification confidence

## Scenario 5: Scene awareness and temporal reasoning

**What happens**
- A vehicle enters the camera view and remains present for several seconds.
- No person is initially visible.
- After a short dwell period, a person exits the vehicle.
- The vehicle later leaves the scene.

**Scene evidence emitted**
- scene.vehicle_entered = true
- scene.vehicle_present = true
- scene.vehicle_dwell_s > threshold
- scene.person_entered = true
- scene.vehicle_exited = true

**Result**
- Events are created even when no visitor is initially present.
- Temporal evidence is attached to events and consumed by the classifier.
- Intent inference is informed by *change over time*, not a single frame.

**What this demonstrates**
- Vision is stateless and frame-based.
- Sc


---

## Future Demo Extensions (Optional)
- Trusted plate labeling (e.g., "mail", "family")
- Vehicle role refinement (commercial vs. personal)
- Intent confidence boosting via multi-signal evidence
- Plate history influencing policy decisions (known delivery = auto-accept)
- Multiple plate candidate handling (select best, ignore noise)
