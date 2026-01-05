# ADR-0011: Group-Only Signal Rules

**Status:** Accepted  
**Date:** 2026-01-04  
**Deciders:** System Architecture Team  
**Context:** Intent Classification System

## Context and Problem Statement

The intent classification system uses two scoring mechanisms:
1. **Standalone rules** - individual signals that contribute directly to intent scores
2. **Signal groups** - composite patterns that combine multiple rules with additional weighting

Prior to this ADR, all rules contributed to scores in both ways simultaneously, leading to:
- **Double-counting**: A rule would add points standalone AND again via its group
- **No way to create context-dependent rules**: Some signals only make sense in combination (e.g., "blue vehicle" alone doesn't indicate USPS, but "blue + white + specific shape" does)
- **Overfitting**: Individual weak signals were being amplified unintentionally

**Example of the problem:**
```
Rule: palette_color=blue → package_drop (weight=1.0)
Evidence: blue detected (conf=0.53)

Standalone scoring: +0.53 to package_drop
Group scoring: +1.265 to package_drop (base_weight + member contribution)
Total: 1.795 (double-counted!)
```

## Decision

Add a `contributes_standalone` column to the `signal_rule` table to control whether a rule scores independently or only through signal groups.

### Schema Change (Migration 008)

```sql
ALTER TABLE signal_rule 
ADD COLUMN contributes_standalone INTEGER DEFAULT 1 NOT NULL;
```

- **Default: 1 (true)** - Backward compatible, existing rules continue to work
- **Set to 0 (false)** - Rule only contributes via signal groups

### Scoring Behavior

**`contributes_standalone = 1` (default):**
```python
delta = weight × evidence.conf
scores[intent] += delta  # Adds to standalone score
# Also available for groups
```

**`contributes_standalone = 0` (group-only):**
```python
delta = weight × evidence.conf
# Does NOT add to standalone score
# Only contributes when signal group activates
```

### Trace Output Format

To make scoring transparent:

**Standalone rules:**
```
[signal_rule 11] package_drop +0.37 (w=0.80*conf=0.46, urg=10) 
because ev(src=ocr feat=token val=wwuspscomn obj=0) contains 'usps' scope=vehicle
```

**Group-only rules:**
```
[signal_rule 37] package_drop +0.00 (group-only, potential=0.60) 
(w=1.00*conf=0.60, urg=0) 
because ev(src=vision feat=color val=white obj=0) equals 'white' scope=vehicle
```

**Groups:**
```
[group usps_delivery_truck] package_drop +1.57 bind=0 scope=vehicle
```

The `potential=X` shows what the rule *could* contribute if its group activates.

## Implementation Details

### Code Changes

**packages/classify/intent.py:**
```python
# Load contributes_standalone from database
rows = conn.execute("""
    SELECT id, source, feature, operator, value, intent_name,
           weight, min_conf, urgency,
           COALESCE(scope_any_of,''),
           COALESCE(contributes_standalone, 1)
    FROM signal_rule WHERE enabled = 1
""").fetchall()

# Unpack with correct falsy handling (0 is valid!)
for (rule_id, source, feature, op, val, intent, weight, min_conf, urg, 
     scope_any_of, contrib_standalone) in rows:
    rules_by_key[(str(source), str(feature))].append(
        (int(rule_id), str(op), str(val), str(intent),
         float(weight) if weight is not None else 1.0, 
         float(min_conf or 0.0), 
         int(urg or 10),
         str(scope_any_of or ""), 
         int(contrib_standalone) if contrib_standalone is not None else 1)
         # ^^^ IMPORTANT: Not "or 1" because 0 is falsy!
    )

# Conditional standalone scoring
if delta > 0.0 and contrib_standalone:
    scores[intent] += delta
    urgencies[intent].append(urg)
```

### Migration Strategy

**Migration 008** automatically converts existing rules:
```sql
-- Rules with weight=0 were likely intended to be group-only
UPDATE signal_rule 
SET contributes_standalone = 0 
WHERE weight = 0.0;

-- Fix their weight so they contribute properly in groups
UPDATE signal_rule 
SET weight = 1.0 
WHERE contributes_standalone = 0 AND weight = 0.0;
```

## Consequences

### Positive

✅ **No more double-counting**: Rules contribute once, either standalone or via group  
✅ **Context-aware signals**: Weak signals can require corroboration  
✅ **Better score calibration**: Intent scores more accurately reflect confidence  
✅ **Clear intent semantics**:
   - Standalone rules: "This signal alone is meaningful"
   - Group-only rules: "This signal only matters in context"

### Negative

⚠️ **Complexity**: Developers must understand two scoring paths  
⚠️ **Migration needed**: Existing rules may need `contributes_standalone` adjustment  
⚠️ **Potential confusion**: Trace shows "potential=X" which might be misread

### Neutral

- Backward compatible (default=1 preserves old behavior)
- Trace verbosity increased slightly

## Use Cases

### Example 1: USPS Delivery Detection

**Problem:** Blue vehicles aren't always USPS, but USPS trucks are always blue+white

**Solution:**
```sql
-- Group-only rules
INSERT INTO signal_rule (source, feature, operator, value, intent_name, 
                         weight, contributes_standalone) 
VALUES 
  ('vision', 'palette_color', 'equals', 'blue', 'package_drop', 1.0, 0),
  ('vision', 'palette_color', 'equals', 'white', 'package_drop', 1.0, 0);

-- Standalone strong signal
INSERT INTO signal_rule (source, feature, operator, value, intent_name, 
                         weight, contributes_standalone) 
VALUES 
  ('ocr', 'token', 'contains', 'usps', 'package_drop', 0.8, 1);

-- Group combines weak signals
INSERT INTO signal_group (name, intent_name, base_weight, bind_scope) 
VALUES ('usps_delivery_truck', 'package_drop', 1.0, 'vehicle');

INSERT INTO signal_group_member (group_id, rule_id, required, weight_mul) 
VALUES 
  (1, 1, 1, 0.5),  -- blue required
  (1, 2, 1, 0.5);  -- white required
```

**Behavior:**
- Blue alone: 0 points (group-only)
- White alone: 0 points (group-only)
- Blue + White: 1.0 (base) + 0.53×0.5 + 0.60×0.5 = 1.565 points
- USPS text: 0.37 points (standalone, additive with group)

### Example 2: Trusted Person Override

**Problem:** Seeing a familiar face should suppress alerts regardless of other signals

**Solution:**
```sql
-- Strong standalone rule
INSERT INTO signal_rule (source, feature, operator, value, intent_name, 
                         weight, contributes_standalone) 
VALUES 
  ('visitor', 'kind', 'equals', 'trusted', 'trusted_arrival', 5.0, 1);
```

No group needed - this signal is decisive on its own.

## Alternatives Considered

### 1. Automatic Group-Only (if in any group, don't score standalone)

**Pros:** No new column needed  
**Cons:** Can't mix - some rules should contribute both ways

**Rejected:** Too inflexible

### 2. Negative Weights for Group-Only

**Pros:** Uses existing column  
**Cons:** Confusing semantics, harder to understand scores

**Rejected:** Poor developer experience

### 3. Separate `group_rule` Table

**Pros:** Clear separation  
**Cons:** Duplicates rules, harder to maintain

**Rejected:** Over-engineering

## Related Decisions

- **ADR-0003**: Plates as events (uses standalone rules for plate matching)
- **ADR-0009**: Concurrent intents (signal groups enable multi-intent scenes)
- **ADR-0010**: Cross-camera tracking (visitor_id used in signal rules)

## References

- Migration: `infra/db/migrations/008_add_contributes_standalone.sql`
- Implementation: `packages/classify/intent.py` (_score_signal_rules function)
- Test: `tools/test_contributes_standalone.py`

## Notes

**Critical Bug Fixed During Implementation:**

```python
# WRONG: 0 is falsy, so "0 or 1" returns 1
int(contrib_standalone or 1)

# CORRECT: Explicitly check for None
int(contrib_standalone) if contrib_standalone is not None else 1
```

This is a common Python gotcha when dealing with boolean flags stored as integers in SQLite.
