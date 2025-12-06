# apps/doorbell-agent/models.py
from dataclasses import dataclass
from typing import Optional, Tuple

BBox = Tuple[int, int, int, int]

@dataclass
class SceneObject:
    type: str                 # "person" | "vehicle" | "dog" | "package" | ...
    color: Optional[str]      # "black", "white", "tan", etc.
    box: Optional[BBox] = None
    ocr: Optional[str] = None       # later: "UPS", "SHERIFF"
    uniform: Optional[str] = None   # later: "authority", "delivery"