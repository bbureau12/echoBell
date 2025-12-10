from dataclasses import dataclass, field
from typing import List, Tuple, Optional


@dataclass
class Detection:
    cls: str
    conf: float
    box: Tuple[int, int, int, int]
    color: str


@dataclass
class Evidence:
    source: str        # 'vision', 'ocr', 'fashion', 'audio', ...
    feature: str       # 'person_present', 'token', 'upper_body', ...
    value: str         # 'true', 'sheriff', 'hi_vis_vest', ...
    conf: float        # 0.0–1.0


@dataclass
class VisionResult:
    snapshot_path: str
    detections: List[Detection]
    person_present: bool
    package_box: bool
    vehicle_present: bool
    dog_present: bool
    uniform: Optional[str] = None

    # OCR info
    ocr_tokens: Optional[List[str]] = None   # normalized tokens like ["amazon", "prime"]
    ocr_raw: Optional[str] = None            # raw concatenated string, if you want it

    # (legacy; you can drop these later if everything uses signal_rule)
    vision_intent: Optional[str] = None
    vision_conf: Optional[float] = None
    vision_urgency: Optional[int] = None

    # Evidence collected from all perception modules
    evidence: List[Evidence] = field(default_factory=list)
