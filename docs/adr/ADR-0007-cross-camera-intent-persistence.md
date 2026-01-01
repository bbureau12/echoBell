# ADR-0007: Cross-camera intent persistence via visitor history

Date: 2026-01-01  
Status: Accepted

## Context

EchoBell uses ReID (Re-identification) to track the same person across multiple
cameras via facial embeddings. A person detected at camera 1 (driveway) receives
a `visitor_id`, and when they appear at camera 2 (front door), the same
`visitor_id` is matched via embedding similarity.

However, intent classification happens independently per camera frame. This
creates a consistency problem:

**Scenario**: A firefighter exits a fire truck at camera 1 (driveway):
- Person + fire truck detected together (same frame)
- Person-vehicle linkage created (proximity-based, ADR-0006)
- Intent classified: `authority_urgent` (person linked to authority vehicle)
- `visitor_id` assigned: `vis_abc123`

20 seconds later, same person walks to camera 2 (front door):
- Person detected alone (no fire truck visible)
- ReID matches face → same `visitor_id = vis_abc123`
- **Problem**: No vehicle context available at camera 2
- **Without intent persistence**: Might classify as `unknown` or `neighbor`
- **Expected**: Should maintain `authority_urgent` classification

The fire truck context is crucial for intent classification, but it's no longer
visible at camera 2. The person-vehicle link exists in the database
(`visit_entity_links`) but isn't queried during classification at camera 2.

## Decision

EchoBell adds **cross-camera intent persistence** via visitor history enrichment.

During evidence enrichment (PHASE 1 of `classify_and_log`), before classification
occurs, the system queries the most recent intent for any detected `visitor_id`:

```python
# PHASE 1d: Add visitor intent history
_add_visitor_intent_history(
    conn,
    vision=vision,
    now_ts=now_ts,
    intent_persistence_window_s=retention.intent_persistence_window_s,
)
```

**How it works**:
1. For each person detected, check if they have a `visitor_id` (from ReID)
2. Query `visitor_events` for the most recent intent for this `visitor_id`
3. If found within the persistence window (default: 1 hour), add as evidence:
   ```python
   Evidence(
       source="visitor_history",
       key="recent_intent",
       value="authority_urgent",  # From camera 1
       confidence=0.72,  # Slightly reduced (original × 0.8)
       metadata={
           "age_seconds": 20,
           "urgency": 90
       }
   )
   ```
4. Classifier sees this historical intent as additional context
5. Classification at camera 2 maintains consistency with camera 1

**Configuration**:
```python
# packages/common/config_models.py
@dataclass
class RetentionSettings:
    intent_persistence_window_s: int = 3600  # 1 hour default
```

**Time window reasoning**:
- **Too short** (60s): Person walking slowly between cameras loses context
- **Too long** (24 hours): Off-duty return gets stale intent (fire fighter
  returns home in civilian clothes shouldn't be flagged as authority)
- **1 hour**: Reasonable window for "same visit" across multiple cameras

## Consequences

### Pros
- **Consistent classification** across cameras for the same visitor
- **Preserves context** from initial detection (vehicle linkage, uniform, etc.)
- **Simple implementation**: Single query per visitor_id, minimal overhead
- **Configurable**: User can adjust persistence window for their use case
- **Audit trail preserved**: All evidence remains in database
  - Camera 1 event shows person-vehicle link
  - Camera 2 event shows visitor_history evidence
  - Full chain traceable via SQL queries

### Cons
- **May carry forward incorrect intent** if initial classification was wrong
- **Adds database query** per detected person during enrichment
- **Window duration is judgment call** - no perfect value for all scenarios

### Mitigations
- **Confidence reduction**: Historical intent confidence reduced (×0.8) to give
  fresh evidence more weight
- **Evidence-based**: Intent history is just one evidence signal among many;
  classifier can override if strong contradictory evidence exists
- **Configurable window**: Users can tune `intent_persistence_window_s` based on
  their camera layout and typical visitor patterns
- **Audit transparency**: Database preserves complete evidence chain showing
  why each classification was made

## Relationship to Other ADRs

**ADR-0005 (Scene awareness temporal tracking)**:
- ADR-0005 tracks objects across frames *within a camera*
- ADR-0007 tracks visitor intent across *cameras*
- Complementary: Scene tracking provides vehicle enter/exit signals; visitor
  history provides cross-camera context

**ADR-0006 (Entity association)**:
- ADR-0006 creates person-vehicle links *within a visit*
- ADR-0007 enables those links to influence classification at *other cameras*
- Flow: Camera 1 creates link → Intent classified → Camera 2 queries history →
  Maintains classification consistency

## Implementation Notes

**PHASE ordering is critical**:
```python
classify_and_log()
├─> PHASE 1: Evidence Enrichment
│   ├─> _link_plates_to_event()
│   ├─> _update_scene_tracking()
│   ├─> _link_people_to_vehicles()
│   └─> _add_visitor_intent_history()  ← NEW
├─> PHASE 2: Classification (sees enriched evidence)
└─> PHASE 3: Persistence
```

Intent history enrichment happens in PHASE 1 (before classification) so the
classifier sees the complete evidence picture.

**Database query**:
```sql
SELECT intent_inferred, urgency, intent_confidence, detected_ts
FROM visitor_events
WHERE visitor_id = ?
  AND intent_inferred IS NOT NULL
ORDER BY detected_ts DESC
LIMIT 1
```

Only the most recent intent is used. If age > `intent_persistence_window_s`,
no evidence is added.

**Evidence metadata**:
- `age_seconds`: How long ago this intent was classified
- `urgency`: Urgency level from the historical event
- Confidence is reduced to prevent stale intents from dominating fresh evidence

## Alternative Approaches Considered

**Option 1: Query historical vehicle links** (NOT chosen):
- Query `visit_entity_links` for person's previous vehicle associations
- Add vehicle plate_hmac as evidence at camera 2
- **Rejected**: More complex, requires multi-table joins, loses intent context

**Option 2: No cross-camera persistence** (NOT chosen):
- Classify each camera independently
- **Rejected**: Creates inconsistent classification (authority at driveway,
  unknown at door), confusing for users and policies

**Option 3: Event merging** (NOT chosen):
- Merge events from cameras 1 and 2 into single event
- **Rejected**: Too complex, loses per-camera granularity, makes debugging harder

**Chosen approach (Option 4: Simple intent lookup)** balances simplicity,
effectiveness, and auditability.
