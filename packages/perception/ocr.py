import easyocr
import numpy as np
import re
from typing import Dict, List
from packages.common.types import Detection

_reader = None

TOKEN_RE = re.compile(r"[a-zA-Z0-9]+")

def _get_reader():
    global _reader
    if _reader is None:
        _reader = easyocr.Reader(['en'], gpu=False)
    return _reader


def _easyocr_tokens(crop_bgr: np.ndarray) -> List[str]:
    """
    Run EasyOCR on a BGR crop and return normalized tokens.
    """
    reader = _get_reader()

    # EasyOCR expects RGB
    crop_rgb = crop_bgr[:, :, ::-1]

    try:
        results = reader.readtext(crop_rgb, detail=0)  # list[str]
    except Exception:
        return []

    text = " ".join(str(r) for r in results if r)
    tokens = [t.lower() for t in TOKEN_RE.findall(text)]
    return tokens


def extract_ocr_tokens_by_object(frame_bgr: np.ndarray, detections: List[Detection]) -> Dict[int, List[str]]:
    """
    Returns: { object_id: [token1, token2, ...] }
    object_id matches enumerate(detections).
    """
    out: Dict[int, List[str]] = {}
    h, w = frame_bgr.shape[:2]

    for obj_id, det in enumerate(detections):
        # Only OCR likely text-bearing objects
        if det.cls not in {"person", "vehicle", "package"}:
            continue

        x1, y1, x2, y2 = det.box

        # clamp
        x1 = max(0, min(int(x1), w - 1))
        x2 = max(0, min(int(x2), w))
        y1 = max(0, min(int(y1), h - 1))
        y2 = max(0, min(int(y2), h))
        if x2 <= x1 or y2 <= y1:
            continue

        crop = frame_bgr[y1:y2, x1:x2]
        if crop.size == 0:
            continue

        toks = _easyocr_tokens(crop)
        if toks:
            # de-dupe per object, preserve order
            seen = set()
            ordered = []
            for t in toks:
                if t not in seen:
                    seen.add(t)
                    ordered.append(t)
            out[obj_id] = ordered

    return out


def extract_ocr_tokens(frame: np.ndarray, detections: List[Detection]) -> List[str]:
    """
    Convenience: Flatten tokens across objects into a de-duplicated sorted list.
    """
    tok_map = extract_ocr_tokens_by_object(frame, detections)
    all_tokens = set()
    for toks in tok_map.values():
        all_tokens.update(toks)
    return sorted(all_tokens)