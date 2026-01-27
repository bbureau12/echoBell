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
- License plate is detected and tracked using plate_hmac as the vehicle's identity.
- No person is initially visible.
- After a short dwell period (≤3 seconds), a person exits the vehicle.
- The person is linked to the vehicle they arrived in.
- The vehicle later leaves the scene (not detected for 6+ seconds).

**Scene evidence emitted**
- `scene.vehicle_entered = 1` - Vehicle first appears
- `scene.vehicle_present = true` - Vehicle currently in frame
- `scene.vehicle_count = 1` - Number of vehicles present
- `scene.person_entered = 1` - Person exits vehicle
- `scene.person_present = true` - Person detected
- `scene.vehicle_exited = 1` - Vehicle leaves (after grace period)

**Database records created**
- `scene_tracks` table:
  - Track with `track_key=plate_hmac` for the vehicle (persistent ID)
  - Track with `track_key=visitor_id` for the person (if recognized)
  - Tracks include `first_seen_ts`, `last_seen_ts`, bounding box, color
- `visit_entity_links` table:
  - Links person to vehicle (only if person appeared within 3 seconds of vehicle)
  - Evidence: `person_linked.vehicle_plate` with plate_hmac

**Result**
- Events are created even when no visitor is initially present.
- Temporal evidence is attached to events and consumed by the classifier.
- Intent inference is informed by *change over time*, not a single frame.
- Person-to-vehicle association enables:
  - "Who arrived in which car?"
  - "This person came in a delivery truck" → boost delivery intent
  - "Known resident arrived in unknown vehicle" → boost visitor intent

**What this demonstrates**
- **Temporal tracking** - System maintains state across frames (6s grace period)
- **Entry/exit detection** - Knows when entities arrive and leave
- **Identity persistence** - Vehicles tracked by plate_hmac, not ephemeral IDs
- **Upgrade logic** - If plate detected after vehicle appears, temp track upgraded to plate_hmac
- **Contextual linking** - People associated with vehicles only on arrival (not passersby)
- **First-appearance window** - 3-second window prevents false associations
- **Scene queries** - External systems can query "what's currently present?" using `get_currently_present()`

**Temporal tracking details**
- **IoU matching** - Objects matched across frames using Intersection over Union (threshold: 0.30)
- **Strong key priority** - plate_hmac/visitor_id matched first, IoU fallback for unknowns
- **Grace period** - Tracks marked exited only after 6s without detection (prevents false exits)
- **Track upgrade** - Temp tracks upgraded to plate_hmac when plate detected on subsequent frames

**Privacy considerations**
- Plate stored as HMAC (plate_hmac), not raw text
- Vehicle tracking uses cryptographic hash, not identifying information
- Person-vehicle links use anonymized identifiers
- Bounding boxes stored for scene analysis, not full frames


---

## Scenario 6: Multi-vehicle scene with selective tracking

**What happens**
- Two vehicles present: one with readable plate, one without
- System creates two tracks:
  - Track 1: `key_kind=plate`, `track_key=<plate_hmac>` (stable, persistent)
  - Track 2: `key_kind=iou`, `track_key=temp:<uuid>` (ephemeral, IoU-based)
- Both vehicles are counted in scene evidence
- Only the plated vehicle generates plate history and visitor associations

**Evidence**
- `scene.vehicle_count = 2`
- `scene.vehicle_present = true`
- `ocr.plate_text = "ABC123"` (only for readable plate)
- `plate_history.intent = "delivery"` (if this plate has history)

**Result**
- System handles mixed scenarios gracefully
- Vehicles without plates still tracked for scene awareness
- Vehicles with plates get stable identity for history/policy decisions
- Scene count remains accurate regardless of plate detection

**What this demonstrates**
- Fallback tracking strategies (plate → IoU → temp key)
- Stable identity when available, tracking when not
- Scene awareness independent of identification
- Multi-entity handling within same frame


---

## Future Demo Extensions (Optional)
- Trusted plate labeling (e.g., "mail", "family")
- Vehicle role refinement (commercial vs. personal)
- Intent confidence boosting via multi-signal evidence
- Plate history influencing policy decisions (known delivery = auto-accept)
- Multiple plate candidate handling (select best, ignore noise)
- Scene-based policy triggers ("If vehicle present for >30s without person, alert")
- Vehicle dwell time analysis (suspicious loitering detection)
- Multi-camera scene fusion (track vehicles across camera views)

