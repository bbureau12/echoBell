# packages/perception/types.py
from dataclasses import dataclass
from typing import Optional, List, Tuple

BBox = Tuple[int, int, int, int]  # x1,y1,x2,y2

@dataclass(slots=True)
class Detection:
    cls: str
    conf: float
    box: BBox
    color: str | None = None

@dataclass(slots=True)
class VisionResult:
    snapshot_path: str
    detections: List[Detection]
    # Derived features for orchestrator/classifier:
    person_present: bool
    package_box: bool
    vehicle_present: bool
    dog_present: bool
    uniform: Optional[str] = None  # "police"|"fire"|None
