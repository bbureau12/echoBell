from dataclasses import dataclass
from typing import List, Tuple, Optional

@dataclass
class Detection:
    cls: str
    conf: float
    box: Tuple[int, int, int, int]
    color: str

@dataclass
class VisionResult:
    snapshot_path: str
    detections: List[Detection]
    person_present: bool
    package_box: bool
    vehicle_present: bool
    dog_present: bool
    uniform: Optional[str] = None

    # new, all optional
    vision_intent: Optional[str] = None
    vision_conf: Optional[float] = None
    vision_urgency: Optional[int] = None
