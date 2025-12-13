from dataclasses import dataclass, field
from typing import List, Tuple, Optional


@dataclass
class Detection:
    # ------------------------------------------------------------------
    # cls
    # ------------------------------------------------------------------
    # The *semantic class* after mapping from YOLO raw class → EchoBell
    # category.
    #
    # Examples:
    #   - "person"
    #   - "vehicle"
    #   - "package"
    #   - "dog"
    #
    # These come from your POSITIVE_CLASSES or DB-driven class map.
    cls: str

    # ------------------------------------------------------------------
    # conf
    # ------------------------------------------------------------------
    # YOLO detection confidence (0–1).
    #
    # Typically:
    #   - ~0.25–0.40   weak/uncertain
    #   - ~0.50–0.75   decent
    #   - 0.80–0.95    strong
    #
    # Used to scale evidence weight later.
    conf: float

    # ------------------------------------------------------------------
    # box
    # ------------------------------------------------------------------
    # Bounding box (x1, y1, x2, y2) in pixel coordinates.
    #
    # Useful for:
    #   - cropping for OCR
    #   - feeding into Fashion classifier
    #   - tracking object identity over frames (future)
    box: Tuple[int, int, int, int]

    # ------------------------------------------------------------------
    # color
    # ------------------------------------------------------------------
    # The dominant color of the region, determined by k-means on the
    # cropped bounding box.
    #
    # Examples:
    #   - "black"
    #   - "tan"
    #   - "blue"
    #
    # This should *always* be understood as "color of this object," not
    # "color of the scene," preventing cross-category confusion.
    color: str


@dataclass
class Evidence:

    # ---------------------------------------------------------------------
    # SOURCE
    # ---------------------------------------------------------------------
    # The subsystem that produced this piece of evidence:
    #   - 'vision'   → YOLO detection, color estimation, flags
    #   - 'ocr'      → text extracted from regions
    #   - 'fashion'  → clothing/uniform classifier
    #   - 'vehicle'  → make/model recognizer
    #   - 'audio'    → future (doorbell mic), e.g. "dog barking"
    #
    # Used by rules to scope conditions ("this rule only applies to OCR")
    source: str

    # ---------------------------------------------------------------------
    # FEATURE
    # ---------------------------------------------------------------------
    # What KIND of information this is. Should be *specific* enough to
    # prevent cross-category misfires like "black person = black vehicle."
    #
    # Examples:
    #   - 'class'              (vision semantic class: person, vehicle…)
    #   - 'color'              (color estimate of the detection)
    #   - 'person_present'
    #   - 'vehicle_present'
    #   - 'token'              (OCR token)
    #   - 'age_group'          (child/teen/adult)
    #   - 'upper_body_color'
    #   - 'badge_detected'
    #   - 'plate_text'
    #
    # Rules match on (source, feature, operator, value).
    feature: str

    # ---------------------------------------------------------------------
    # VALUE
    # ---------------------------------------------------------------------
    # The observed value for the feature.
    #
    # Examples:
    #   - 'true'                       (boolean flags as strings)
    #   - 'vehicle'
    #   - 'package'
    #   - 'sheriff'
    #   - 'amazon'
    #   - 'black'
    #   - 'child'
    #   - 'hi_vis_vest'
    #   - 'ford_f150'
    #
    # IMPORTANT: Always store normalized lowercase text.
    value: str

    # ---------------------------------------------------------------------
    # CONFIDENCE
    # ---------------------------------------------------------------------
    # Float between 0–1 indicating how reliable this evidence is.
    #
    # Examples:
    #   - YOLO detections → 0.3 to 0.95
    #   - OCR tokens     → typically 0.7–0.95
    #   - Heuristic labels → e.g. 0.6 for color
    #
    # The rule engine uses this to scale weights:
    #    score += rule_weight * evidence_confidence
    conf: float

    # ---------------------------------------------------------------------
    # OBJECT_ID 
    # ---------------------------------------------------------------------
    # The ID of the specific object this evidence refers to.
    #
    # Used to delineate core objects such as people, cars, packages etc.

    object_id: int | None = None

@dataclass
class SceneObject:
    # ------------------------------------------------------------------
    # object_id
    # ------------------------------------------------------------------
    # A unique identifier **within this single snapshot**.
    #
    # YOLO detections are enumerated in order and assigned IDs:
    #    0 → first detected object
    #    1 → second detected object
    #    ...
    #
    # IMPORTANT:
    #   - These IDs do NOT persist across events.
    #   - They exist only to group evidence belonging to the
    #     same object within a single perception pass.
    #
    # Example:
    #   object_id = 0 → person
    #   object_id = 1 → vehicle
    object_id: int


    # ------------------------------------------------------------------
    # parent_id
    # ------------------------------------------------------------------
    # Points to the ID of another SceneObject that is this object's parent.
    #
    # IMPORTANT:
    #   - These IDs do NOT persist across events.
    #   - They exist only to group evidence belonging to the
    #     same object within a single perception pass.
    #
    # Example:
    #   object_id = 1 → self (license plate)
    #   parent_id = 1 → parent (vehicle)
    parent_id: int | None = None

    # ------------------------------------------------------------------
    # label
    # ------------------------------------------------------------------
    # Semantic label describing what kind of object this is.
    #
    # Typically derived from YOLO's class mapping (vision), but can
    # also come from other perception modules.
    #
    # Example labels:
    #   - "person"
    #   - "vehicle"
    #   - "dog"
    #   - "coat"
    #   - "tie"
    #   - "package"
    #
    # Used heavily by the rule engine to determine the behavior
    # of an object in context.
    label: str

    # ------------------------------------------------------------------
    # box
    # ------------------------------------------------------------------
    # Bounding box (x1, y1, x2, y2) in pixel coordinates.
    # Useful for:
    #   - cropping for OCR
        #   - feeding into Fashion classifier
    box: Tuple[int, int, int, int] | None = None


    # ------------------------------------------------------------------
    # parent_id
    # ------------------------------------------------------------------
    # Optional link to another SceneObject, forming a hierarchy,
    # also known as a *scene graph*.
    #
    # Useful for representing nested or attached objects:
    #   person (object_id=0)
    #     └─ coat (object_id=1)
    #          └─ tie (object_id=2)
    #
    # If None:
    #   - The object is a top-level item in the scene.
    parent_id: int | None = None

    # ------------------------------------------------------------------
    # props
    # ------------------------------------------------------------------
    # A dictionary of **canonical flat properties** describing this object.
    #
    # These differ from raw Evidence:
    #   - props represent *aggregated or interpreted facts*
    #   - evidence represents *individual observed signals*
    #
    # Examples of props:
    #   {
    #       "color": "tan",
    #       "age_group": "adult",
    #       "vehicle_make": "ford",
    #       "upper_body_color": "brown",
    #       "has_badge": True
    #   }
    #
    # Props are ideal for downstream rule evaluation or summary generation.
    props: dict = field(default_factory=dict)

    # ------------------------------------------------------------------
    # evidence
    # ------------------------------------------------------------------
    # Raw, unprocessed perception signals associated with THIS object.
    #
    # Each Evidence item captures:
    #   - which module produced it  (vision / ocr / fashion / vehicle)
    #   - what feature was observed (class / color / token / patch)
    #   - the observed value        ("vehicle", "black", "sheriff")
    #   - confidence score          (0.0 — 1.0)
    #
    # Examples:
    #   Evidence(source="vision", feature="class", value="person", conf=0.93)
    #   Evidence(source="vision", feature="color", value="black", conf=0.60)
    #   Evidence(source="ocr",    feature="token", value="sheriff", conf=0.88)
    #
    # The rule engine may operate directly on evidence or may use
    # evidence to populate props.
    evidence: list[Evidence] = field(default_factory=list)


@dataclass
class VisionResult:
    # ------------------------------------------------------------------
    # snapshot_path
    # ------------------------------------------------------------------
    # The path to the actual image used for this inference.
    #
    # Useful for:
    #   - debugging
    #   - showing images in a UI
    #   - logging
    snapshot_path: str

    # ------------------------------------------------------------------
    # detections
    # ------------------------------------------------------------------
    # A list of Detection objects — each representing one bounding box
    # YOLO produced after class mapping.
    #
    # Example:
    # [
    #   Detection(cls="person", color="brown", conf=0.88),
    #   Detection(cls="vehicle", color="black", conf=0.81)
    # ]
    #
    # These are the building blocks for evidence.
    detections: List[Detection]

    # ------------------------------------------------------------------
    # Boolean scene flags
    # ------------------------------------------------------------------
    # Derived from the semantic detections — coarse scene context:
    #   person_present    → any detection with cls == 'person'?
    #   package_box       → seen a package-likething?
    #   vehicle_present   → car/truck/motorbike visible?
    #   dog_present       → dog appears?
    #
    # These exist for convenience but should mainly feed into Evidence.
    person_present: bool
    package_box: bool
    vehicle_present: bool
    dog_present: bool

    # ------------------------------------------------------------------
    # uniform
    # ------------------------------------------------------------------
    # Placeholder for future "uniform detection".
    #
    # Example values:
    #   - "police"
    #   - "fire"
    #   - "unknown"
    #
    # You can keep this unused for now or remove it later.
    uniform: Optional[str] = None

    # ------------------------------------------------------------------
    # OCR info
    # ------------------------------------------------------------------
    # ocr_tokens → normalized individual tokens
    # ocr_raw    → concatenated raw text
    #
    # These assist in rules like:
    #   token contains 'amazon'  → delivery
    #   token equals 'sheriff'   → authority_urgent
    ocr_tokens: Optional[List[str]] = None
    ocr_raw: Optional[str] = None

    # ------------------------------------------------------------------
    # EVIDENCE
    # ------------------------------------------------------------------
    # The unified list of Evidence instances collected from:
    #   - Vision (class, color, flags)
    #   - OCR (tokens)
    #   - Fashion (future)
    #   - Vehicle type classifier (future)
    #   - Audio module (future)
    #
    # The rule engine uses this list to compute intent.
    #
    # Example:
    # [
    #   Evidence("vision", "person_present", "true", 0.9),
    #   Evidence("ocr", "token", "sheriff", 0.9),
    #   Evidence("vision", "color", "tan", 0.6),
    # ]
    #
    # As perception grows, this becomes richer but stays clean.
    evidence: List[Evidence] = field(default_factory=list)

    # ------------------------------------------------------------------
    # objects
    # ------------------------------------------------------------------
    # A list of SceneObject instances representing individual entities
    #
    # Example: 
    # [
    #  SceneObject( object_id=0, label="person", props={"color": "brown"}, evidence=[...]),
    #  SceneObject( object_id=1, label="vehicle", props={"color": "black"}, evidence=[...]),
    # ]   
    objects: List[SceneObject] = field(default_factory=list)