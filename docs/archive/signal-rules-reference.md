# Signal Rules Reference Guide

**Last Updated:** 2026-01-05  
**Related ADRs:** ADR-0011 (Group-Only Rules), ADR-0012 (Evidence Naming Conventions)

## Overview

Signal rules enable intent classification based on multimodal evidence from vision, OCR, visitor recognition, and tracking systems. This guide documents all available evidence features and operators for creating rules.

## Table of Contents

- [Evidence Sources](#evidence-sources)
  - [Vision Evidence](#vision-evidence)
  - [OCR Evidence](#ocr-evidence)
  - [Visitor Evidence](#visitor-evidence)
- [Operators](#operators)
- [Rule Structure](#rule-structure)
- [Common Patterns](#common-patterns)
- [Examples](#examples)

---

## Evidence Sources

### Vision Evidence

Evidence generated from YOLO object detection and color analysis.

#### Scene-Level Evidence (object_id=None)

| Feature | Type | Values | Description |
|---------|------|--------|-------------|
| `camera_id` | Integer | `1`, `2`, etc. | Which camera captured this frame |
| `person_present` | Boolean | `true`, `false` | Any person detected in scene |
| `vehicle_present` | Boolean | `true`, `false` | Any vehicle detected in scene |
| `package_box` | Boolean | `true`, `false` | Package/box detected in scene |
| `dog_present` | Boolean | `true`, `false` | Dog detected in scene |

**Example:**
```sql
INSERT INTO signal_rule (source, feature, operator, value, intent_name, weight, urgency)
VALUES ('vision', 'vehicle_present', 'equals', 'true', 'package_drop', 0.5, 5);
```

#### Object-Level Evidence (object_id=N)

| Feature | Type | Values | Description |
|---------|------|--------|-------------|
| `class` | String | `person`, `vehicle`, `package`, `dog` | Object classification from YOLO |
| `color` | String | `white`, `black`, `gray`, `red`, `blue`, `green`, `yellow`, `orange`, `brown`, `tan`, `purple` | Dominant color of object |
| `palette_color` | String | Same as `color` | Color present in object (≥5% coverage) |
| `color_pct_<color>` | Integer | `0`-`100` | Percentage of object covered by specific color |

**Color Palette Details:**
- Applied to `vehicle` and `person` classes only
- Minimum 5% coverage threshold to appear in palette
- Colors detected: white, black, gray, red, blue, green, yellow, orange, brown, tan, purple
- Both `palette_color` and `color_pct_<color>` generated for each color

**Example - Dominant Color:**
```sql
-- Match any brown vehicle
INSERT INTO signal_rule (source, feature, operator, value, intent_name, weight)
VALUES ('vision', 'color', 'equals', 'brown', 'package_drop', 1.0);
```

**Example - Color Percentage:**
```sql
-- Match vehicles with >40% brown coverage (UPS trucks)
INSERT INTO signal_rule (source, feature, operator, value, intent_name, weight, scope_any_of)
VALUES ('vision', 'color_pct_brown', 'gte', '40', 'package_drop', 2.0, 'vehicle');
```

---

### OCR Evidence

Evidence generated from text extraction (EasyOCR).

| Feature | Type | Values | Description |
|---------|------|--------|-------------|
| `token` | String | Any text | Individual word/text detected via OCR |
| `plate_text` | String | Alphanumeric | License plate (vehicles only) |

**Example - Token Matching:**
```sql
-- Match "USPS" text on vehicle
INSERT INTO signal_rule (source, feature, operator, value, intent_name, weight, scope_any_of)
VALUES ('ocr', 'token', 'contains', 'usps', 'package_drop', 3.0, 'vehicle');
```

**Example - Plate Matching:**
```sql
-- Match specific known plate
INSERT INTO signal_rule (source, feature, operator, value, intent_name, weight)
VALUES ('ocr', 'plate_text', 'equals', 'ABC1234', 'trusted_visitor', 5.0);
```

---

### Visitor Evidence

Evidence generated from face recognition system.

| Feature | Type | Values | Description |
|---------|------|--------|-------------|
| `prior_intent` | String | Intent name | Most recent intent for recognized person |
| `name` | String | Person name | Matched visitor identity (future) |
| `last_seen_age` | Integer | Days/years | Time since last visit (future) |

**Example:**
```sql
-- If person previously triggered "package_drop", likely delivery person
INSERT INTO signal_rule (source, feature, operator, value, intent_name, weight)
VALUES ('visitor', 'prior_intent', 'equals', 'package_drop', 'package_drop', 2.0);
```

---

## Operators

### String Operators

| Operator | SQL Name | Description | Example |
|----------|----------|-------------|---------|
| `equals` | `equals` | Exact match (case-insensitive) | `color = 'white'` |
| `contains` | `contains` | Substring match | `token contains 'fed'` → matches "FedEx" |

### Numeric Operators

| Operator | SQL Name | Aliases | Description | Example |
|----------|----------|---------|-------------|---------|
| `gte` | `gte` | `>=` | Greater than or equal | `color_pct_blue >= 5` |
| `lte` | `lte` | `<=` | Less than or equal | `color_pct_white <= 20` |
| `gt` | `gt` | `>` | Greater than | `color_pct_brown > 40` |
| `lt` | `lt` | `<` | Less than | `camera_id < 3` |

**Notes:**
- Numeric operators attempt `float()` conversion on both evidence value and rule value
- If conversion fails, match returns `False`
- Works with percentage features (`color_pct_*`), counts, IDs, etc.

---

## Rule Structure

### Signal Rule Table Schema

```sql
CREATE TABLE signal_rule (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,           -- 'vision', 'ocr', 'visitor', etc.
    feature TEXT NOT NULL,          -- Feature name (see tables above)
    operator TEXT NOT NULL,         -- 'equals', 'contains', 'gte', 'lte', 'gt', 'lt'
    value TEXT NOT NULL,            -- Match value (stored as string)
    intent_name TEXT NOT NULL,      -- Target intent
    weight REAL DEFAULT 1.0,        -- Contribution multiplier
    min_conf REAL DEFAULT 0.0,      -- Minimum evidence confidence to match
    urgency INTEGER DEFAULT 0,      -- Intent urgency override
    scope_any_of TEXT,              -- Object scope filter (see below)
    contributes_standalone INTEGER DEFAULT 1,  -- 1=yes, 0=group-only
    enabled INTEGER DEFAULT 1
);
```

### Scope Filtering (`scope_any_of`)

Controls which object types a rule can match against:

| Scope Value | Matches | Use Case |
|-------------|---------|----------|
| `NULL` or empty | Scene-level evidence only | Camera ID, presence flags |
| `'vehicle'` | Evidence from vehicle objects | Vehicle colors, plates |
| `'person'` | Evidence from person objects | Clothing colors, faces |
| `'vehicle,person'` | Either vehicle OR person | Flexible matching |

**Example:**
```sql
-- Only match blue color on vehicles (not persons)
INSERT INTO signal_rule (source, feature, operator, value, intent_name, weight, scope_any_of)
VALUES ('vision', 'color_pct_blue', 'gte', '5', 'package_drop', 1.5, 'vehicle');
```

### Contributes Standalone

Controls whether a rule scores independently or only via signal groups:

| Value | Behavior | Use Case |
|-------|----------|----------|
| `1` (default) | Scores standalone + in groups | Strong individual signals |
| `0` | Scores only in groups | Weak signals requiring context |

**See ADR-0011 for details.**

---

## Common Patterns

### Pattern 1: Delivery Vehicle Detection

Combine color percentages with signal groups to identify delivery trucks:

```sql
-- USPS: Blue + white colors (group-only rules)
INSERT INTO signal_rule (source, feature, operator, value, intent_name, weight, scope_any_of, contributes_standalone)
VALUES 
  ('vision', 'color_pct_blue', 'gte', '5', 'package_drop', 1.0, 'vehicle', 0),
  ('vision', 'color_pct_white', 'gte', '25', 'package_drop', 1.0, 'vehicle', 0);

-- Create signal group to activate both
INSERT INTO signal_group (name, intent_name, group_mode, bind_scope, base_weight, urgency)
VALUES ('usps_colors', 'package_drop', 'all', 'vehicle', 2.0, 5);

-- Link rules to group
INSERT INTO signal_group_member (group_id, rule_id, required, weight_mul)
VALUES 
  (1, 1, 1, 1.5),  -- Blue required
  (1, 2, 1, 1.0);  -- White required
```

### Pattern 2: Known Visitor Recognition

Use visitor prior intent as a signal:

```sql
-- If we've seen this person deliver packages before
INSERT INTO signal_rule (source, feature, operator, value, intent_name, weight, urgency)
VALUES ('visitor', 'prior_intent', 'equals', 'package_drop', 'package_drop', 2.0, 5);
```

### Pattern 3: OCR Text + Vehicle Color

Combine text detection with vehicle characteristics:

```sql
-- FedEx branding
INSERT INTO signal_rule (source, feature, operator, value, intent_name, weight, scope_any_of)
VALUES ('ocr', 'token', 'contains', 'fedex', 'package_drop', 3.0, 'vehicle');

-- Purple accent color (FedEx brand)
INSERT INTO signal_rule (source, feature, operator, value, intent_name, weight, scope_any_of)
VALUES ('vision', 'color_pct_purple', 'gte', '5', 'package_drop', 1.5, 'vehicle');
```

### Pattern 4: Camera-Specific Rules

Different thresholds for different camera angles:

```sql
-- Front door camera sees packages clearly
INSERT INTO signal_rule (source, feature, operator, value, intent_name, weight)
VALUES ('vision', 'camera_id', 'equals', '1', 'package_drop', 0.5);

-- Driveway camera triggers on vehicles
INSERT INTO signal_rule (source, feature, operator, value, intent_name, weight)
VALUES ('vision', 'camera_id', 'equals', '2', 'vehicle_arrival', 0.5);
```

---

## Examples

### Example 1: USPS Truck (Comprehensive)

```sql
-- Individual color rules (group-only to prevent double-counting)
INSERT INTO signal_rule (source, feature, operator, value, intent_name, weight, scope_any_of, contributes_standalone)
VALUES 
  ('vision', 'color_pct_blue', 'gte', '5', 'package_drop', 1.0, 'vehicle', 0),
  ('vision', 'color_pct_white', 'gte', '25', 'package_drop', 1.0, 'vehicle', 0);

-- OCR rule (standalone + group)
INSERT INTO signal_rule (source, feature, operator, value, intent_name, weight, scope_any_of, contributes_standalone)
VALUES ('ocr', 'token', 'contains', 'usps', 'package_drop', 3.0, 'vehicle', 1);

-- Signal group combining colors
INSERT INTO signal_group (name, intent_name, group_mode, bind_scope, base_weight, urgency)
VALUES ('usps_vehicle', 'package_drop', 'all', 'vehicle', 2.0, 5);

INSERT INTO signal_group_member (group_id, rule_id, required, weight_mul)
VALUES 
  (1, 1, 1, 1.5),  -- Blue required, 1.5x multiplier
  (1, 2, 1, 1.0),  -- White required, 1.0x multiplier
  (1, 3, 0, 2.0);  -- USPS text optional, 2.0x boost if present
```

**Scoring Example:**
- USPS truck detected: 6% blue, 34% white
- Color rules trigger: +0.0 standalone (group-only), potential for group
- Group activates: base_weight (2.0) + member contributions
- Final: ~4-5 points to package_drop

### Example 2: UPS Truck (Brown Dominant)

```sql
-- High brown percentage
INSERT INTO signal_rule (source, feature, operator, value, intent_name, weight, scope_any_of, urgency)
VALUES ('vision', 'color_pct_brown', 'gte', '40', 'package_drop', 2.5, 'vehicle', 5);

-- UPS text
INSERT INTO signal_rule (source, feature, operator, value, intent_name, weight, scope_any_of, urgency)
VALUES ('ocr', 'token', 'contains', 'ups', 'package_drop', 3.0, 'vehicle', 5);
```

### Example 3: FedEx Truck (White + Purple)

```sql
INSERT INTO signal_rule (source, feature, operator, value, intent_name, weight, scope_any_of, contributes_standalone)
VALUES 
  ('vision', 'color_pct_white', 'gte', '30', 'package_drop', 1.0, 'vehicle', 0),
  ('vision', 'color_pct_purple', 'gte', '5', 'package_drop', 2.0, 'vehicle', 0),
  ('ocr', 'token', 'contains', 'fedex', 'package_drop', 3.0, 'vehicle', 1);

INSERT INTO signal_group (name, intent_name, group_mode, bind_scope, base_weight, urgency)
VALUES ('fedex_vehicle', 'package_drop', 'all', 'vehicle', 2.0, 5);

INSERT INTO signal_group_member (group_id, rule_id, required, weight_mul)
VALUES 
  (2, 4, 1, 1.0),  -- White required
  (2, 5, 1, 2.0),  -- Purple required (signature color)
  (2, 6, 0, 2.0);  -- FedEx text optional
```

### Example 4: Trusted Person (Recurring Visitor)

```sql
-- Person we've seen before with friendly intent
INSERT INTO signal_rule (source, feature, operator, value, intent_name, weight, urgency)
VALUES ('visitor', 'prior_intent', 'equals', 'neighbor_visit', 'neighbor_visit', 3.0, 10);
```

---

## Best Practices

1. **Use `scope_any_of`** to prevent cross-object matching (e.g., person wearing blue vs. blue vehicle)

2. **Set `contributes_standalone=0`** for weak signals that only matter in combination

3. **Use numeric operators** (`gte`, `lte`) for percentage thresholds rather than exact matches

4. **Combine color + OCR** for robust delivery vehicle detection

5. **Test with real images** using `tools/vision_harness.py` to see evidence generation

6. **Use signal groups** for multi-condition patterns (see ADR-0011)

7. **Follow naming conventions** for evidence features (see ADR-0012):
   - `color_pct_<color>` for percentages
   - `*_age` for time-based features
   - `*_seconds` for durations

---

## Testing Rules

### Using Vision Harness

```powershell
# Test with specific image
$env:PYTHONPATH="d:\Projects\echoBell\echoBell"
.\.venv-vision\Scripts\python.exe tools\vision_harness.py

# Look for evidence in output
Evidence (first 15):
  - vision.color_pct_blue=6% conf=0.95 obj=0
  - vision.color_pct_white=34% conf=0.95 obj=0
```

### Viewing Classification Trace

Enable trace in `classify()` to see rule matching:

```
[signal_rule 38] package_drop +1.90 (w=2.00*conf=0.95, urg=5)
  because ev(src=vision feat=color_pct_blue val=6 obj=0) gte '5' scope=vehicle
```

### Running All Tests

```powershell
python tests/run_all_tests.py
```

---

## Future Evidence Sources

These sources are planned but not yet implemented:

| Source | Features | Description |
|--------|----------|-------------|
| `tracking` | `dwell_seconds`, `approach_distance` | Scene tracker temporal data |
| `audio` | `doorbell_pressed`, `knock_detected` | Audio event detection |
| `weather` | `temperature_celsius`, `precipitation` | Environmental context |

---

## Related Documentation

- **ADR-0011:** Group-Only Signal Rules - `contributes_standalone` flag
- **ADR-0012:** Evidence Naming Conventions - Feature naming patterns
- **Schema:** `infra/db/schema.sql` - Database structure
- **Code:** `packages/classify/intent.py` - Rule matching logic
- **Code:** `packages/perception/vision.py` - Evidence generation
