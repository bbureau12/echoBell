# ADR-0012: Evidence Feature Naming Conventions

**Status:** Accepted  
**Date:** 2026-01-05  
**Deciders:** System Architecture Team  
**Context:** Evidence System, Intent Classification

## Context and Problem Statement

The evidence system collects observations from multiple sources (vision, OCR, visitor recognition, tracking, etc.) as `Evidence` objects with fields: `source`, `feature`, `value`, `conf`, `object_id`.

As the system grows, evidence features represent different types of measurements:
- Percentages (color coverage, confidence scores)
- Time durations (age, dwell time, tracking duration)
- Distances (proximity, movement range)
- Counts, temperatures, speeds, etc.

**The problem:** How should evidence values be displayed and interpreted?

### Options Considered

**Option 1: Add unit/format metadata to Evidence class**
```python
Evidence(source, feature, value, conf, object_id, unit="percent")
```
- ✅ Explicit
- ❌ Adds complexity to Evidence class
- ❌ Requires schema changes
- ❌ More fields to manage

**Option 2: Convention-based feature naming**
```python
Evidence("vision", "color_pct_blue", "6", 0.95, 0)
Evidence("visitor", "age_years", "5", 0.80, None)
```
- ✅ Self-documenting
- ✅ No schema changes needed
- ✅ Simple to extend
- ✅ Works across all evidence sources
- ❌ Requires consistent naming discipline

**Option 3: Store metadata in separate lookup table**
```sql
CREATE TABLE evidence_feature_metadata (
    source TEXT,
    feature TEXT,
    display_format TEXT
);
```
- ✅ Centralized configuration
- ❌ Extra table to maintain
- ❌ More complex queries
- ❌ Overkill for simple formatting

## Decision

**Adopt Option 2: Convention-based feature naming with a smart formatter function.**

Evidence features should follow naming conventions that encode their measurement type:

### Naming Conventions

| Convention | Example Feature | Display Format | Use Case |
|------------|----------------|----------------|----------|
| `*_pct_*` or `*_pct` | `color_pct_blue` | `6%` | Color coverage percentages |
| `pct_*` | `pct_confidence` | `87%` | Confidence percentages |
| `*_age` or `*_years` | `visitor_age` | `5 years` | Age measurements |
| `*_seconds` | `dwell_seconds` | `120s` | Duration in seconds |
| `*_meters` or `*_distance` | `approach_distance` | `2.5m` | Distance measurements |
| `*_celsius` | `temperature_celsius` | `22°C` | Temperature (future) |
| `*_mph` | `speed_mph` | `25 mph` | Speed (future) |
| No suffix | `class`, `color`, `camera_id` | Raw value | Plain values |

### Implementation

A single formatting function handles display logic:

```python
def _format_evidence_value(feature: str, value) -> str:
    """
    Smart formatting for evidence values based on naming conventions.
    """
    feature_lower = feature.lower()
    
    # Percentage-based features
    if '_pct_' in feature_lower or feature_lower.endswith('_pct') or feature_lower.startswith('pct_'):
        return f"{value}%"
    
    # Time-based features
    if feature_lower.endswith('_age') or feature_lower.endswith('_years'):
        return f"{value} years"
    if feature_lower.endswith('_seconds'):
        return f"{value}s"
    
    # Distance features
    if feature_lower.endswith('_meters') or feature_lower.endswith('_distance'):
        return f"{value}m"
    
    # Default: no formatting
    return str(value)
```

## Consequences

### Positive

1. **Self-documenting code**: Feature names like `color_pct_blue` immediately convey meaning
2. **No schema changes**: Evidence class remains simple
3. **Easy to extend**: Just add new patterns to the formatter
4. **Works everywhere**: Convention applies to all evidence sources (vision, OCR, tracking, etc.)
5. **Rule-friendly**: Rules can still match against raw values (`color_pct_blue >= 5`)
6. **Display-layer concern**: Formatting happens only at presentation, not in business logic

### Negative

1. **Requires discipline**: Developers must follow naming conventions
2. **No compile-time validation**: Typos in feature names won't be caught
3. **Convention must be documented**: New developers need to learn the patterns

### Mitigations

- Document conventions in this ADR and in code comments
- Code review should check for consistent naming
- Future: Could add linting to validate feature names match patterns

## Examples

### Color Percentage Evidence (Vision)
```python
# Generation (vision.py)
Evidence("vision", "color_pct_blue", "6", 0.95, object_id=0)

# Display (vision_harness.py)
"vision.color_pct_blue=6% conf=0.95 obj=0"

# Rule matching (signal_rule table)
source='vision', feature='color_pct_blue', operator='gte', value='5'
```

### Age Evidence (Visitor Recognition)
```python
# Generation (future)
Evidence("visitor", "last_seen_age", "5", 0.80, object_id=None)

# Display
"visitor.last_seen_age=5 years conf=0.80 obj=None"
```

### Dwell Time Evidence (Scene Tracking)
```python
# Generation (future)
Evidence("tracking", "dwell_seconds", "120", 1.00, object_id=0)

# Display
"tracking.dwell_seconds=120s conf=1.00 obj=0"
```

## Related Decisions

- **ADR-0011: Group-Only Signal Rules** - Established how rules interact with evidence
- **Color Palette Integration (Jan 2026)** - First use case requiring percentage display

## References

- `packages/perception/vision.py` - Color percentage evidence generation
- `tools/vision_harness.py` - Evidence display formatting
- `packages/classify/intent.py` - Rule matching against evidence values
- Migration 008 - Added numeric operators (gte, lte, gt, lt) for percentage comparisons

## Review

This ADR should be reviewed if:
- Evidence features require more complex formatting (e.g., units with conversions)
- Display needs vary significantly by context (admin UI vs. logs vs. API)
- Number of conventions grows beyond ~10 patterns
