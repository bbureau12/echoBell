# ADR-0008: Trusted entity allowlists (plates and people)

Date: 2026-01-01  
Status: Accepted

## Context

EchoBell classifies visitor intent using multimodal evidence (vision, text,
plate history, scene tracking). For most visitors, intent must be inferred from
observable signals.

However, certain entities are known and trusted by the homeowner:
- **Trusted plates**: Mail truck, neighbor's car, family member's vehicle
- **Trusted people**: Family members, close neighbors, regular service providers

When these entities are detected, the system should:
1. **Enrich evidence** with trust information to improve classification
2. **Enable policies** to make trust-based decisions (e.g., unlock door for
   family, don't alert for neighbor)
3. **Preserve privacy** (use HMACs for plates, embeddings for faces)

Without an allowlist system, trusted entities are treated the same as unknown
visitors, leading to:
- False alerts for family members
- Missed optimization opportunities (e.g., automatic unlock)
- No way to distinguish regular service providers from unknown vehicles

## Decision

EchoBell adds **trusted entity allowlists** for both license plates and people.

### Trusted Plates

**Storage**:
```sql
CREATE TABLE trusted_plates (
    plate_hmac TEXT PRIMARY KEY,  -- Privacy-safe HMAC
    label TEXT NOT NULL,           -- Human-readable: "mail_truck", "neighbor_bob"
    created_ts INTEGER,
    updated_ts INTEGER,
    active INTEGER DEFAULT 1
);
```

**API**:
```python
# packages/perception/plate_service.py

def is_plate_trusted(conn, raw_plate_text: str) -> dict | None:
    """
    Check if plate is trusted, return label if found.
    Returns: {"label": "mail_truck", "plate_hmac": "..."} or None
    """

def add_trusted_plate(conn, raw_plate_text: str, label: str):
    """Add plate to trusted list (stores HMAC, not raw text)."""
```

**Evidence enrichment**:
When a trusted plate is detected during PHASE 1a of `classify_and_log`:
```python
Evidence(
    source="plate_trust",
    key="trusted_plate",
    value="mail_truck",  # The label
    confidence=1.0,
    object_id=vehicle_object_id
)
```

Also added to vehicle `SceneObject.props`:
```python
vehicle.props["trusted_plate_label"] = "mail_truck"
vehicle.props["is_trusted_plate"] = True
```

### Trusted People

**Storage**:
```sql
CREATE TABLE trusted_person (
    trusted_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    label TEXT,
    created_ts INTEGER,
    updated_ts INTEGER,
    active INTEGER DEFAULT 1
);

CREATE TABLE trusted_person_embedding (
    embedding_id INTEGER PRIMARY KEY,
    trusted_id INTEGER NOT NULL,
    embedding_type TEXT,      -- 'face', 'body'
    model_name TEXT,
    embedding_dim INTEGER,
    embedding_blob BLOB,      -- Binary embedding vector
    quality_score REAL,
    camera_id INTEGER,
    FOREIGN KEY (trusted_id) REFERENCES trusted_person(trusted_id)
);
```

**How it works**:
- Admin adds trusted person with name/label
- System stores facial embeddings (same as visitor ReID)
- During face matching, check both:
  1. General visitor database (for ReID across cameras)
  2. Trusted person database (for trust-based classification)
- If matched to trusted person, add evidence

## Consequences

### Pros
- **Better classification**: Trusted entities get appropriate intents
  (e.g., "family_arriving" vs "unknown_person")
- **Policy flexibility**: Policies can differentiate trusted vs unknown
  (e.g., unlock door only for family)
- **Privacy preserved**: Plates stored as HMACs, faces as embeddings
- **User control**: Homeowner decides who/what is trusted
- **Audit trail**: Evidence shows "trusted_plate=mail_truck" in classification
  trace

### Cons
- **Admin burden**: Someone must populate the allowlists
- **Maintenance overhead**: Trusted lists need updates (new car, moved away)
- **False trust risk**: If attacker learns trusted plate, could spoof
  (mitigated: plates are evidence, not authentication)

### Mitigations
- **Plates as evidence, not authentication** (ADR-0003): Trust doesn't grant
  access automatically, just influences classification. Policy layer makes
  final decisions.
- **Multiple evidence sources**: Classifier combines trust with other signals
  (e.g., trusted plate + person wearing uniform → delivery_regular vs
  trusted plate + no person → vehicle_parked)
- **Active flag**: Can disable trusted entries without deletion
- **Audit logging**: All trust-based decisions are traceable

## Implementation Notes

### Plate Trust Flow

```python
# PHASE 1a in classify_and_log.py
for plate_read in plate_reads:
    # 1. Upsert to plate_visitors (standard tracking)
    rr = plate_service.upsert_plate_visit(...)
    
    # 2. Check if trusted
    trusted_info = plate_service.is_plate_trusted(conn, plate_read.raw_text)
    
    # 3. Add evidence if trusted
    if trusted_info:
        vision.evidence.append(
            Evidence(source="plate_trust", key="trusted_plate", 
                    value=trusted_info["label"], confidence=1.0)
        )
        
        # Also add to SceneObject props
        vehicle_obj.props["trusted_plate_label"] = trusted_info["label"]
```

### Privacy Design

**Plates**:
- Raw plate text never stored
- `trusted_plates.plate_hmac` uses same HMAC function as `plate_visitors`
- Lookup: normalize input → HMAC → check against `trusted_plates`

**People**:
- No photos stored, only embeddings
- Same embedding model as visitor ReID (InsightFace buffalo_l)
- Multiple embeddings per person (different angles/lighting)

### Label Conventions

**Plates**:
- `mail_truck` - USPS/postal service
- `neighbor_bob` - Neighbor's personal vehicle
- `family_car_1` - Family member vehicle
- `service_hvac` - Regular HVAC technician

**People**:
- `alice` - Family member
- `bob_neighbor` - Trusted neighbor
- `mail_carrier_jane` - Regular mail carrier

Labels are freeform strings for flexibility.

## Relationship to Other ADRs

**ADR-0002 (Plate privacy HMAC)**:
- ADR-0008 builds on HMAC design for trusted plates
- Maintains privacy: no raw plates in `trusted_plates` table

**ADR-0003 (Plates as evidence, not identity)**:
- Trusted plates still don't create visitor_id
- Trust is evidence for classification, not authentication for access
- Policy layer decides what actions to take based on trust evidence

**ADR-0007 (Cross-camera intent persistence)**:
- Trusted plate detected at camera 1 → intent classified with trust evidence
- Intent persists to camera 2 via visitor history
- Combines: trust detection + cross-camera consistency

## Future Enhancements

**Potential additions**:
- Time-based trust (trusted only during specific hours)
- Camera-specific trust (trusted at front door, not back gate)
- Trust expiration (guest pass valid for 24 hours)
- Trust delegation (trusted person can vouch for +1 guest)

**Not implemented** (keeping initial version simple):
- Currently trust is binary (active=1 or active=0)
- No partial trust or trust levels
- No automatic trust learning (all trust is explicit)
