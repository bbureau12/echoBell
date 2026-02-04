# Visitor Intent Reclassification - Quick Reference

## TL;DR

LLM can now correct visitor intent classifications by injecting evidence or overriding directly.

## MCP Tools

### reclassify_visitor_intent

**Evidence Injection** (recommended):
```json
{
  "event_id": "evt_123",
  "additional_evidence": [
    {"key": "uniform_type", "value": "ups", "conf": 0.95}
  ],
  "reason": "User confirmed UPS delivery"
}
```

**Direct Override**:
```json
{
  "event_id": "evt_123",
  "override_intent": "neighbor_visit",
  "override_confidence": 0.95,
  "reason": "User identified as neighbor"
}
```

### get_visitor_event

```json
{
  "event_id": "evt_123"
}
```

## REST API

### Get Event
```bash
GET /visitors/events/{event_id}
```

### Reclassify
```bash
POST /visitors/events/{event_id}/reclassify
Content-Type: application/json

{
  "additional_evidence": [...],
  "reason": "..."
}
```

### List Events
```bash
GET /visitors/events?camera_id=1&intent=unknown&limit=20
```

## Common Evidence Keys

| Key | Values | Use Case |
|-----|--------|----------|
| uniform_type | ups, fedex, usps, amazon | Delivery identification |
| uniform_logo_visible | true, false | Logo detection |
| vehicle_brand | ups_truck, fedex_van | Vehicle identification |
| vehicle_color | brown, white, blue | Vehicle details |
| uniform_color | brown, purple, blue | Uniform color |
| recent_intent | delivery_arriving, etc. | Cross-camera history |
| visitor_frequency | daily, weekly, monthly | Pattern recognition |

## Database Queries

### Recent Reclassifications
```sql
SELECT event_id, intent_inferred, reclassified_by, 
       reclassification_reason, reclassified_ts
FROM visitor_events
WHERE reclassification_count > 0
ORDER BY reclassified_ts DESC
LIMIT 20;
```

### Reclassification Stats
```sql
SELECT 
    reclassified_by,
    COUNT(*) as total,
    AVG(intent_confidence) as avg_confidence
FROM visitor_events
WHERE reclassification_count > 0
GROUP BY reclassified_by;
```

## Use Cases

### Voice Correction
```
User: "That was UPS"
LLM: get_visitor_event(most_recent)
LLM: reclassify_visitor_intent(
    event_id=event.id,
    additional_evidence=[{"key": "uniform_type", "value": "ups"}],
    reason="User voice confirmation"
)
```

### Cross-Camera Context
```
Camera 1: Person exits UPS truck
Camera 2: Same person at door (unknown intent)

LLM: reclassify_visitor_intent(
    event_id=camera2_event,
    additional_evidence=[{
        "key": "recent_intent",
        "value": "delivery_arriving",
        "source": "cross_camera"
    }],
    reason="Same visitor from Camera 1 UPS truck"
)
```

### User Override
```
User: "That's my neighbor John"

LLM: reclassify_visitor_intent(
    event_id=event_id,
    override_intent="neighbor_visit",
    override_confidence=0.95,
    reason="User identified as neighbor John"
)
```

## Files

- Service: `central/policy-server/services.py::reclassify_visitor_intent()`
- MCP: `central/policy-server/mcp_server.py` (tools + handlers)
- API: `central/policy-server/api_visitors.py`
- Migration: `infra/db/migrations/016_add_visitor_reclassification.sql`
- Docs: `docs/VISITOR_RECLASSIFICATION.md`

## Permissions

| Tool | Voice | Confidence | Level |
|------|-------|------------|-------|
| reclassify_visitor_intent | Yes | 0.80 | normal |
| get_visitor_event | Yes | 0.75 | low |

## Troubleshooting

**Intent doesn't change?**
- Check evidence keys match signal_rule table
- Verify confidence thresholds
- Inspect trace output

**Migration fails?**
```sql
PRAGMA table_info(visitor_events);
-- Check if columns exist already
```

**Evidence format wrong?**
```json
// ✅ Correct
{"key": "uniform_type", "value": "ups", "conf": 0.95}

// ❌ Wrong
{"feature": "uniform_type", "value": "ups"}
```
