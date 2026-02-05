# Visitor Intent Reclassification

> **Quick Reference**: Jump to [Quick Start](#quick-start) | [MCP Tools](#mcp-tools) | [Common Evidence Keys](#common-evidence-keys)

## Overview

The visitor intent reclassification system allows the LLM (or API users) to correct misclassified visitor intents by injecting additional evidence or directly overriding classifications. This maintains the integrity of the evidence-based classification system while providing flexibility for corrections.

---

## Quick Start

### TL;DR

LLM can correct visitor intent classifications by injecting evidence or overriding directly.

### Common Use Cases

**Voice Correction**:
```
User: "That was UPS"
LLM: get_visitor_event(most_recent)
LLM: reclassify_visitor_intent(
    event_id=event.id,
    additional_evidence=[{"key": "uniform_type", "value": "ups", "conf": 0.95}],
    reason="User voice confirmation"
)
```

**Cross-Camera Context**:
```
Camera 1: Person exits UPS truck
Camera 2: Same person at door (unknown intent)

LLM: reclassify_visitor_intent(
    event_id=camera2_event,
    additional_evidence=[{
        "key": "recent_intent",
        "value": "delivery_arriving",
        "conf": 0.80,
        "source": "cross_camera"
    }],
    reason="Same visitor from Camera 1 UPS truck"
)
```

**User Override**:
```
User: "That's my neighbor John"

LLM: reclassify_visitor_intent(
    event_id=event_id,
    override_intent="neighbor_visit",
    override_confidence=0.95,
    reason="User identified as neighbor John"
)
```

---

## Architecture

### Core Concept: LLM as "Super-Observer"

The LLM can act as a super-observer that sees things the vision system missed:
- User verbally confirms "That was UPS" → LLM adds uniform evidence
- Historical context suggests different intent → LLM injects cross-camera evidence
- OCR failed to read logo → LLM adds vehicle brand evidence

### Classification Flow

```
┌─────────────┐         ┌──────────────┐         ┌─────────────┐
│   Vision    │────────▶│ Classifier   │────────▶│  Database   │
│   System    │ Evidence│ (classify()) │ Intent  │visitor_events│
└─────────────┘         └──────────────┘         └─────────────┘
                               ▲                         │
                               │                         │
                               │ Inject Evidence         │
                        ┌──────┴──────┐                  │
                        │     LLM     │◄─────────────────┘
                        │ Reclassify  │   Get Event
                        └─────────────┘
```

### Two Approaches

#### 1. Evidence Injection (Recommended)

**How it works**:
1. Fetch original vision result from `visitor_events.evidence_json`
2. Add LLM-provided evidence to the evidence list
3. Re-run `classify()` function with enriched evidence
4. Classification rules determine new intent
5. Update database with new intent + audit trail

**Advantages**:
- Respects existing classification rules
- Maintains consistency across similar cases
- Fully auditable (shows which evidence changed result)
- If rules change, re-classification still valid

**Example**:
```python
# LLM observed uniform details vision system missed
additional_evidence = [
    {"key": "uniform_type", "value": "ups", "conf": 0.95},
    {"key": "uniform_logo_visible", "value": "true", "conf": 0.90}
]
```

#### 2. Direct Override

**How it works**:
1. LLM specifies intent and confidence directly
2. Database updated without re-running classification
3. Bypasses all classification rules

**Use cases**:
- Classification rules are fundamentally wrong
- User provides explicit verbal override
- No appropriate evidence exists in the evidence schema

**Example**:
```python
# User said "That was my neighbor" via voice
override_intent = "neighbor_visit"
override_confidence = 0.95
```

## Implementation

### Service Layer

**Function**: `services.reclassify_visitor_intent()`

```python
def reclassify_visitor_intent(
    conn: sqlite3.Connection,
    event_id: str,
    additional_evidence: Optional[List[Dict[str, Any]]] = None,
    override_intent: Optional[str] = None,
    override_confidence: Optional[float] = None,
    reason: Optional[str] = None,
    reclassified_by: str = "llm"
) -> Dict[str, Any]:
    """
    Reclassify with audit trail.
    
    Returns:
        {
            "success": bool,
            "original_intent": str,
            "new_intent": str,
            "original_confidence": float,
            "new_confidence": float,
            "method": "evidence_injection" | "direct_override",
            "trace": List[str],  # Classification reasoning
            "changed": bool
        }
    """
```

### MCP Tools

#### reclassify_visitor_intent

**Description**: Reclassify visitor intent with evidence or override

**Parameters**:
- `event_id` (required): Visitor event ID
- `additional_evidence` (optional): List of evidence items to inject
- `override_intent` (optional): Direct intent override
- `override_confidence` (optional): Confidence for override
- `reason` (optional): Human-readable explanation

**Example - Evidence Injection**:
```json
{
  "name": "reclassify_visitor_intent",
  "arguments": {
    "event_id": "event_abc123",
    "additional_evidence": [
      {
        "key": "uniform_type",
        "value": "fedex",
        "conf": 0.95
      },
      {
        "key": "vehicle_brand",
        "value": "fedex_truck",
        "conf": 0.90
      }
    ],
    "reason": "User confirmed FedEx delivery via voice command"
  }
}
```

**Example - Direct Override**:
```json
{
  "name": "reclassify_visitor_intent",
  "arguments": {
    "event_id": "event_abc123",
    "override_intent": "neighbor_visit",
    "override_confidence": 0.95,
    "reason": "User identified as neighbor John"
  }
}
```

#### get_visitor_event

**Description**: Get event details before reclassifying

**Parameters**:
- `event_id` (required): Visitor event ID

**Returns**:
```json
{
  "event_id": "event_abc123",
  "visitor_id": "visitor_xyz",
  "camera_id": 1,
  "detected_ts": "2026-02-03 14:30:22",
  "intent": "unknown",
  "intent_confidence": 0.45,
  "urgency": 10,
  "reclassification_count": 0,
  "evidence_json": "{...}"
}
```

### REST API Endpoints

#### GET /visitors/events/{event_id}

Get visitor event details.

**Response**:
```json
{
  "event_id": "event_abc123",
  "visitor_id": "visitor_xyz",
  "intent": "unknown",
  "intent_confidence": 0.45,
  "reclassification_count": 1,
  "reclassified_by": "llm",
  "reclassification_reason": "User confirmed UPS delivery"
}
```

#### POST /visitors/events/{event_id}/reclassify

Reclassify visitor intent.

**Request Body**:
```json
{
  "additional_evidence": [
    {
      "source": "llm",
      "key": "uniform_type",
      "value": "ups",
      "conf": 0.95
    }
  ],
  "reason": "User verbally confirmed UPS uniform"
}
```

**Response**:
```json
{
  "success": true,
  "original_intent": "unknown",
  "new_intent": "delivery_arriving",
  "original_confidence": 0.45,
  "new_confidence": 0.87,
  "method": "evidence_injection",
  "trace": [
    "Re-classified with 1 additional evidence items",
    "Added evidence: llm.uniform_type = ups (conf=0.95)",
    "Result: unknown (conf=0.45) → delivery_arriving (conf=0.87)"
  ],
  "changed": true
}
```

#### GET /visitors/events

List visitor events with filters.

**Query Parameters**:
- `camera_id`: Filter by camera
- `visitor_id`: Filter by visitor
- `intent`: Filter by intent
- `limit`: Max results (default 50)
- `offset`: Pagination offset

**Response**:
```json
{
  "count": 10,
  "limit": 50,
  "offset": 0,
  "events": [...]
}
```

## Database Schema

### Migration 016

Adds reclassification tracking columns to `visitor_events`:

```sql
ALTER TABLE visitor_events ADD COLUMN reclassification_count INTEGER DEFAULT 0;
ALTER TABLE visitor_events ADD COLUMN reclassified_by TEXT;
ALTER TABLE visitor_events ADD COLUMN reclassification_reason TEXT;
ALTER TABLE visitor_events ADD COLUMN reclassified_ts INTEGER;
```

### Audit Trail

Every reclassification increments `reclassification_count` and stores:
- `reclassified_by`: "llm", "api", "human"
- `reclassification_reason`: Human-readable explanation
- `reclassified_ts`: Unix timestamp of reclassification

### Future Enhancement: Full History Table

For complete audit trail, consider:

```sql
CREATE TABLE visitor_event_reclassifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL,
    previous_intent TEXT,
    new_intent TEXT,
    previous_confidence REAL,
    new_confidence REAL,
    method TEXT,  -- 'evidence_injection' or 'direct_override'
    evidence_json TEXT,  -- Evidence added
    reclassified_by TEXT,
    reason TEXT,
    reclassified_ts INTEGER,
    FOREIGN KEY (event_id) REFERENCES visitor_events(event_id)
);
```

## Use Cases

### 1. Voice Command Correction

**Scenario**: User says "That was UPS"

```
User: "Hey Echobell, that was UPS"
LLM: [Queries recent visitor events]
LLM: [Calls get_visitor_event for most recent]
LLM: [Sees intent: "unknown", confidence: 0.45]
LLM: [Calls reclassify_visitor_intent with evidence]
LLM: "I've updated the classification to UPS delivery"
```

**Evidence Injected**:
```python
{
    "key": "uniform_type",
    "value": "ups",
    "conf": 0.95,
    "source": "user_voice_confirmation"
}
```

### 2. Historical Context

**Scenario**: Visitor recognized from cross-camera history

```
LLM observes:
- Camera 1: Person exited UPS truck (intent: delivery_arriving)
- Camera 2: Same person at front door (intent: unknown, no vehicle visible)

LLM reclassifies Camera 2 event:
{
    "additional_evidence": [
        {
            "key": "recent_intent",
            "value": "delivery_arriving",
            "conf": 0.80,
            "source": "cross_camera_history"
        }
    ],
    "reason": "Same visitor seen exiting UPS truck at Camera 1 30s ago"
}
```

### 3. OCR Failure Recovery

**Scenario**: Plate/uniform text not detected

```
Vision system: No uniform text detected
LLM from conversation: User mentions "FedEx driver"

LLM reclassifies:
{
    "additional_evidence": [
        {
            "key": "uniform_brand",
            "value": "fedex",
            "conf": 0.90,
            "source": "llm_text_analysis"
        }
    ],
    "reason": "User mentioned FedEx in conversation"
}
```

### 4. User Explicit Override

**Scenario**: Classification fundamentally wrong

```
User: "That's my neighbor John, not a salesman"

LLM:
{
    "override_intent": "neighbor_visit",
    "override_confidence": 0.95,
    "reason": "User identified visitor as neighbor John"
}
```

## Security & Authorization

### Tool Permissions

From `mcp_tool_permissions` table:

| Tool                      | Voice Enabled | Min Confidence | Security Level |
|---------------------------|---------------|----------------|----------------|
| reclassify_visitor_intent | Yes           | 0.80           | normal         |
| get_visitor_event         | Yes           | 0.75           | low            |

### Authorization Flow

1. Voice command arrives with voiceprint
2. Confidence checked against `requires_confidence`
3. If >= 0.80, reclassification allowed
4. All changes logged with `reclassified_by` and `reason`

### Audit Queries

**Recent reclassifications**:
```sql
SELECT event_id, intent_inferred, intent_confidence,
       reclassified_by, reclassification_reason, reclassified_ts
FROM visitor_events
WHERE reclassification_count > 0
ORDER BY reclassified_ts DESC
LIMIT 20;
```

**Reclassification success rate**:
```sql
SELECT 
    reclassified_by,
    COUNT(*) as total_reclassifications,
    AVG(intent_confidence) as avg_new_confidence,
    COUNT(DISTINCT event_id) as unique_events
FROM visitor_events
WHERE reclassification_count > 0
GROUP BY reclassified_by;
```

## Testing

### Manual Testing

```bash
# 1. Get a visitor event
curl http://localhost:8002/visitors/events/event_abc123

# 2. Reclassify with evidence
curl -X POST http://localhost:8002/visitors/events/event_abc123/reclassify \
  -H "Content-Type: application/json" \
  -d '{
    "additional_evidence": [
      {"key": "uniform_type", "value": "ups", "conf": 0.95}
    ],
    "reason": "Test reclassification"
  }'

# 3. Check reclassification history
curl http://localhost:8002/visitors/events/event_abc123/reclassification_history
```

### Integration Testing

```python
# tests/test_visitor_reclassification.py
import pytest
from central.policy_server import services

def test_evidence_injection_reclassification(test_db):
    """Test reclassifying with additional evidence"""
    # Setup: Create visitor event with "unknown" intent
    conn = test_db
    event_id = "test_event_001"
    
    # Create event
    conn.execute("""
        INSERT INTO visitor_events (event_id, intent_inferred, intent_confidence)
        VALUES (?, 'unknown', 0.45)
    """, (event_id,))
    
    # Reclassify with UPS evidence
    result = services.reclassify_visitor_intent(
        conn=conn,
        event_id=event_id,
        additional_evidence=[
            {"key": "uniform_type", "value": "ups", "conf": 0.95}
        ],
        reason="Test evidence injection"
    )
    
    assert result["success"] == True
    assert result["new_intent"] == "delivery_arriving"
    assert result["method"] == "evidence_injection"
    assert result["changed"] == True
```

## Best Practices

### When to Use Evidence Injection

✅ **Do**:
- Vision system missed obvious details
- User provides verbal confirmation
- Cross-camera context suggests different intent
- Historical patterns indicate misclassification

❌ **Don't**:
- Add made-up evidence
- Override when classification is correct
- Use for experimental/test intents

### When to Use Direct Override

✅ **Do**:
- User explicitly identifies visitor
- Classification rules are fundamentally broken
- No appropriate evidence schema exists
- Emergency override needed

❌ **Don't**:
- Use as default approach
- Bypass evidence when evidence approach works
- Override without clear reason

### Reason Field Best Practices

**Good reasons**:
- "User confirmed UPS delivery via voice command"
- "Same visitor seen exiting delivery truck at Camera 1"
- "OCR failed to read uniform logo, user identified FedEx"
- "Historical pattern: visitor visits every Tuesday as mail carrier"

**Bad reasons**:
- "Test"
- "Unknown"
- null
- "Reclassifying"

## Troubleshooting

### Reclassification Doesn't Change Intent

**Symptom**: Evidence added but intent stays the same

**Checks**:
1. Verify evidence keys match `signal_rule` table
2. Check confidence thresholds in signal rules
3. Inspect trace to see what rules matched
4. Verify evidence format (key/value/conf)

**Fix**:
```sql
-- Check what signal rules exist
SELECT * FROM signal_rule 
WHERE feature LIKE '%uniform%' 
  AND enabled = 1;

-- Add signal rule if missing
INSERT INTO signal_rule (source, feature, operator, value, intent_name, weight, enabled)
VALUES ('llm', 'uniform_type', 'equals', 'ups', 'delivery_arriving', 0.7, 1);
```

### Migration Fails

**Symptom**: ALTER TABLE fails

**Cause**: Columns already exist from partial migration

**Fix**:
```sql
-- Check existing columns
PRAGMA table_info(visitor_events);

-- Drop migration 016 if needed
-- Then re-run migration
```

### Evidence Not Injected

**Symptom**: Trace doesn't show injected evidence

**Check**:
- Evidence format: `{"key": "...", "value": "...", "conf": 0.95}`
- Not: `{"feature": "...", ...}` (wrong key name)

## Future Enhancements

### Planned Features

1. **Full History Table**: Track all past reclassifications
2. **Bulk Reclassification**: Reclassify multiple events at once
3. **Pattern Learning**: Learn from reclassifications to improve rules
4. **Confidence Decay**: Reduce confidence over time if repeatedly reclassified
5. **Conflict Resolution**: Handle conflicting evidence from multiple sources

### Roadmap

- **Q1 2026**: Basic reclassification (current implementation)
- **Q2 2026**: Full history table, bulk operations
- **Q3 2026**: Pattern learning from reclassifications
- **Q4 2026**: Auto-suggest evidence based on patterns

## Related Documentation

- `ARCHITECTURE.md` - Classification pipeline overview
- `packages/classify/intent.py` - Core classification logic
- `docs/DATABASE_SCHEMA.md` - visitor_events table schema
- `MCP_SERVER.md` - MCP tool development guide
