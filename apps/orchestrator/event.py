# apps/doorbell-agent/events.py
from dataclasses import dataclass
from typing import Optional

@dataclass
class Event:
    source: str      # "driveway" | "doorbell"
    type: str        # "approach" | "ring" | "motion"
    kind: Optional[str] = None      # "person" | "vehicle" | ...
    snapshot: Optional[str] = None  # path to image
    payload: Optional[dict] = None  # anything else
