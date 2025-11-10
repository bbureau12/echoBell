from dataclasses import dataclass
import os

@dataclass
class VisionHints:
    person: bool = False
    package_box: bool = False
    uniform: str = "none"  # police|fire|utility|none
    snapshot_path: str | None = None

def snapshot_and_detect(rtsp_url:str) -> VisionHints:
    # TODO: grab frame to temp file; run YOLO. For now, stub.
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    snapshot_path = os.path.join(project_root, "data", "snap.jpg")
    return VisionHints(person=True, package_box=False, uniform="none", snapshot_path=snapshot_path)
