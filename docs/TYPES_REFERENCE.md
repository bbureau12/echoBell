# Types Reference

This document describes the core dataclasses and types used throughout echoBell, including their structure, usage patterns, and common pitfalls.

**Location:** `packages/common/types.py`

## Table of Contents

- [Evidence](#evidence)
- [SceneObject](#sceneobject)
- [VisionResult](#visionresult)
- [Detection](#detection)
- [Common Patterns](#common-patterns)

## Evidence

**Purpose:** Represents a single perception signal from any module (vision, OCR, fashion, etc.).

### Structure

```python
@dataclass
class Evidence:
    source: str        # Module that produced it (vision|ocr|fashion|scene)
    feature: str       # What was observed (class|color|token|linkage)
    value: str         # Observed value ("person", "blue", "amazon")
    conf: float        # Confidence (0.0 - 1.0)
    object_id: int | None = None  # Optional: which scene object
```

### Usage

```python
# Vision detected a person
evidence = Evidence(
    source="vision",
    feature="class",
    value="person",
    conf=0.95,
    object_id=0
)

# Vision detected color
color_evidence = Evidence(
    source="vision",
    feature="color",
    value="brown",
    conf=0.82,
    object_id=0
)

# OCR detected text
ocr_evidence = Evidence(
    source="ocr",
    feature="token",
    value="amazon",
    conf=0.88
    # No object_id for text
)

# Scene linkage
linkage_evidence = Evidence(
    source="scene",
    feature="person_vehicle_link",
    value="linked",
    conf=0.95,
    object_id=0  # person's object_id
)
```

### Source Types

| Source | Description | Common Features |
|--------|-------------|-----------------|
| `vision` | YOLO detections | class, color, vehicle_type |
| `ocr` | Text recognition | token, plate |
| `fashion` | Clothing analysis | upper_color, has_badge, company |
| `vehicle` | Vehicle attributes | make, model, type |
| `scene` | Scene understanding | person_vehicle_link, proximity |

### Feature Examples

**Vision:**
- `class` - YOLO class (person, vehicle, dog, package)
- `color` - Detected color (blue, black, brown)
- `vehicle_type` - Specific vehicle (car, bicycle, truck)
- `raw_class` - Original YOLO class before mapping

**OCR:**
- `token` - Individual word detected
- `plate` - License plate text

**Fashion:**
- `upper_color` - Shirt/jacket color
- `has_badge` - Boolean badge detection
- `company` - Company logo (ups, fedex, amazon)

**Scene:**
- `person_vehicle_link` - Person associated with vehicle
- `proximity` - Spatial relationship

### Common Patterns

```python
# Collect all evidence for an object
object_evidence = [
    ev for ev in all_evidence 
    if ev.object_id == obj.object_id
]

# Filter by source
vision_evidence = [
    ev for ev in all_evidence 
    if ev.source == "vision"
]

# High-confidence only
confident = [
    ev for ev in all_evidence 
    if ev.conf >= 0.8
]

# Check for specific feature
has_bicycle = any(
    ev.source == "vision" 
    and ev.feature == "vehicle_type" 
    and ev.value == "bicycle"
    for ev in all_evidence
)
```

## SceneObject

**Purpose:** Represents a detected object in a scene with its properties and evidence.

### Structure

```python
@dataclass
class SceneObject:
    object_id: int                          # Unique within snapshot (0-based)
    label: str                              # Semantic label (person|vehicle|dog)
    parent_id: int | None = None            # Parent object ID
    box: Tuple[int, int, int, int] | None = None  # Bounding box (x1,y1,x2,y2)
    props: dict = field(default_factory=dict)     # Dynamic properties
    evidence: list[Evidence] = field(default_factory=list)  # Raw signals
```

### Key Concepts

#### Object IDs

- **Scoped to single snapshot** - IDs reset with each event
- **0-based indexing** - First object is 0, second is 1, etc.
- **Not persistent** - Don't store object_id across events

#### Labels

Common semantic labels:
- `person` - Human detected
- `vehicle` - Any vehicle (car, truck, bicycle)
- `dog` - Dog/pet
- `package` - Package/box
- `tie` - Necktie (for uniform detection)
- `coat` - Jacket/coat

#### Props vs Evidence

**Props** - Interpreted facts (aggregated, canonical):
```python
obj.props = {
    "color": "brown",           # Consensus color
    "visitor_id": "vis_123",    # Identified person
    "plate_hmac": "abc...",     # Vehicle plate hash
    "raw_class": "bicycle",     # Original YOLO class
    "age_group": "adult"        # Derived attribute
}
```

**Evidence** - Raw signals (individual observations):
```python
obj.evidence = [
    Evidence(source="vision", feature="class", value="person", conf=0.95),
    Evidence(source="vision", feature="color", value="brown", conf=0.82),
    Evidence(source="fashion", feature="upper_color", value="brown", conf=0.78)
]
```

### Usage

#### Creating Objects

```python
# ✅ Correct
person = SceneObject(
    object_id=0,
    label="person",
    box=(100, 100, 200, 300)
)
person.props["color"] = "brown"
person.props["visitor_id"] = "vis_123"
person.evidence.append(
    Evidence(source="vision", feature="class", value="person", conf=0.95)
)

# ❌ Wrong - color is not a constructor parameter
person = SceneObject(
    object_id=0,
    label="person",
    color="brown"  # ERROR!
)
```

#### Object Hierarchies

Objects can have parent-child relationships:

```python
# Vehicle is parent
vehicle = SceneObject(
    object_id=0,
    label="vehicle",
    box=(200, 200, 500, 400)
)

# License plate is child of vehicle
plate = SceneObject(
    object_id=1,
    label="plate",
    parent_id=0,  # Points to vehicle
    box=(220, 350, 280, 380)
)

# Person linked to vehicle
person = SceneObject(
    object_id=2,
    label="person",
    parent_id=0,  # Also linked to vehicle
    box=(100, 100, 200, 300)
)
```

#### Accessing Properties

```python
# Get property with default
color = obj.props.get("color", "unknown")

# Check if property exists
if "visitor_id" in obj.props:
    visitor_id = obj.props["visitor_id"]

# Set property
obj.props["confidence"] = 0.95
```

### Common Patterns

```python
# Find all people
people = [obj for obj in objects if obj.label == "person"]

# Find children of object
children = [
    obj for obj in objects 
    if obj.parent_id == parent.object_id
]

# Get object by ID
obj = next(
    (o for o in objects if o.object_id == target_id),
    None
)

# Walk up to root
def get_root(obj, objects):
    while obj.parent_id is not None:
        obj = next(o for o in objects if o.object_id == obj.parent_id)
    return obj
```

### Common Pitfalls

❌ **Don't try to set attributes directly:**
```python
obj.color = "blue"  # ERROR - no such attribute
```

✅ **Use props dict:**
```python
obj.props["color"] = "blue"
```

❌ **Don't pass props as constructor kwargs:**
```python
SceneObject(object_id=1, label="person", visitor_id="123")  # ERROR
```

✅ **Create object first, then set props:**
```python
obj = SceneObject(object_id=1, label="person")
obj.props["visitor_id"] = "123"
```

## VisionResult

**Purpose:** Complete result from vision processing, including all detected objects and evidence.

### Structure

```python
@dataclass
class VisionResult:
    snapshot_path: str                    # Path to image
    detections: List[Detection]           # Raw YOLO detections
    person_present: bool                  # Any person detected?
    package_box: bool                     # Package detected?
    vehicle_present: bool                 # Vehicle detected?
    dog_present: bool                     # Dog detected?
    uniform: Optional[str] = None         # Uniform type (if any)
    ocr_tokens: Optional[List[str]] = None        # Text tokens
    ocr_raw: Optional[str] = None                 # Raw concatenated text
    objects: List[SceneObject] = field(default_factory=list)
    evidence: List[Evidence] = field(default_factory=list)
```

### Usage

```python
# Creating a VisionResult
vision = VisionResult(
    snapshot_path="/path/to/image.jpg",
    detections=[
        Detection(cls="person", conf=0.95, box=(100,100,200,300)),
        Detection(cls="vehicle", conf=0.88, box=(300,200,500,400))
    ],
    person_present=True,
    package_box=False,
    vehicle_present=True,
    dog_present=False,
    objects=[
        SceneObject(object_id=0, label="person", box=(100,100,200,300)),
        SceneObject(object_id=1, label="vehicle", box=(300,200,500,400))
    ],
    evidence=[
        Evidence(source="vision", feature="class", value="person", conf=0.95, object_id=0),
        Evidence(source="vision", feature="class", value="vehicle", conf=0.88, object_id=1)
    ]
)
```

### Required Fields

When creating VisionResult for tests or mocks:

**Always required:**
- `snapshot_path` - Path to image
- `detections` - List of Detection objects (can be empty)
- `person_present` - Boolean
- `package_box` - Boolean  
- `vehicle_present` - Boolean
- `dog_present` - Boolean

**Optional:**
- `uniform` - String (default: None)
- `ocr_tokens` - List of strings (default: None)
- `ocr_raw` - String (default: None)
- `objects` - List of SceneObject (default: [])
- `evidence` - List of Evidence (default: [])

### Common Patterns

```python
# Check scene contents
if vision.person_present and vision.vehicle_present:
    print("Person and vehicle detected")

# Access all evidence
for ev in vision.evidence:
    print(f"{ev.source}.{ev.feature} = {ev.value} ({ev.conf:.2f})")

# Filter evidence by object
person_evidence = [
    ev for ev in vision.evidence
    if ev.object_id == 0  # First object
]

# Get object by label
vehicle = next(
    (obj for obj in vision.objects if obj.label == "vehicle"),
    None
)
```

## Detection

**Purpose:** Raw YOLO detection before semantic mapping.

### Structure

```python
@dataclass
class Detection:
    cls: str                              # YOLO class name
    conf: float                           # Confidence (0.0-1.0)
    box: Tuple[int, int, int, int]       # Bounding box (x1,y1,x2,y2)
    color: Optional[str] = None          # Detected color
```

### Usage

```python
# YOLO detected a person
det = Detection(
    cls="person",
    conf=0.95,
    box=(100, 100, 200, 300),
    color="brown"
)
```

### Relationship to SceneObject

`Detection` → (semantic mapping) → `SceneObject`

```python
# Detection is raw YOLO output
detection = Detection(cls="bicycle", conf=0.88, box=(300,200,500,400))

# SceneObject is semantically mapped
obj = SceneObject(
    object_id=1,
    label="vehicle",  # Mapped from "bicycle"
    box=(300,200,500,400)
)
obj.props["raw_class"] = "bicycle"  # Preserve original
```

## Common Patterns

### Building Evidence Lists

```python
def build_evidence(objects: List[SceneObject]) -> List[Evidence]:
    """Build evidence list from scene objects."""
    all_evidence = []
    
    for obj in objects:
        # Add class evidence
        all_evidence.append(Evidence(
            source="vision",
            feature="class",
            value=obj.label,
            conf=0.95,
            object_id=obj.object_id
        ))
        
        # Add color if available
        if "color" in obj.props:
            all_evidence.append(Evidence(
                source="vision",
                feature="color",
                value=obj.props["color"],
                conf=0.85,
                object_id=obj.object_id
            ))
    
    return all_evidence
```

### Grouping Evidence by Object

```python
from collections import defaultdict

def group_evidence_by_object(evidence: List[Evidence]) -> dict:
    """Group evidence by object_id."""
    grouped = defaultdict(list)
    for ev in evidence:
        grouped[ev.object_id].append(ev)
    return dict(grouped)

# Usage
evidence_by_obj = group_evidence_by_object(vision.evidence)
person_evidence = evidence_by_obj.get(0, [])  # Evidence for object 0
```

### Creating Test Fixtures

```python
def make_vision_result(
    objects: List[SceneObject] = None,
    evidence: List[Evidence] = None
) -> VisionResult:
    """Create minimal VisionResult for testing."""
    return VisionResult(
        snapshot_path="test.jpg",
        detections=[],
        person_present=bool(objects and any(o.label == "person" for o in objects)),
        package_box=False,
        vehicle_present=bool(objects and any(o.label == "vehicle" for o in objects)),
        dog_present=False,
        objects=objects or [],
        evidence=evidence or []
    )
```

### Evidence Queries

```python
# Find specific evidence
def find_evidence(
    evidence_list: List[Evidence],
    source: str = None,
    feature: str = None,
    value: str = None,
    min_conf: float = 0.0
) -> List[Evidence]:
    """Filter evidence by criteria."""
    results = evidence_list
    
    if source:
        results = [e for e in results if e.source == source]
    if feature:
        results = [e for e in results if e.feature == feature]
    if value:
        results = [e for e in results if e.value == value]
    if min_conf > 0:
        results = [e for e in results if e.conf >= min_conf]
    
    return results

# Usage
bicycle_evidence = find_evidence(
    vision.evidence,
    source="vision",
    feature="vehicle_type",
    value="bicycle"
)
```

## Type Checking

The codebase uses type hints. For proper type checking:

```python
from typing import List, Optional, Tuple
from packages.common.types import Evidence, SceneObject, VisionResult

def process_vision(vision: VisionResult) -> List[Evidence]:
    """Type-checked function signature."""
    evidence: List[Evidence] = []
    
    for obj in vision.objects:
        obj_id: int = obj.object_id
        label: str = obj.label
        
        # Type checker knows this is Evidence
        ev = Evidence(
            source="vision",
            feature="class",
            value=label,
            conf=0.95,
            object_id=obj_id
        )
        evidence.append(ev)
    
    return evidence
```

## See Also

- [CONTRIBUTING.md](../CONTRIBUTING.md) - Code standards
- [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md) - Database structure
- [ARCHITECTURE.md](ARCHITECTURE.md) - System design
- [packages/common/types.py](../packages/common/types.py) - Source code
