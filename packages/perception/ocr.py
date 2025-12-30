import easyocr
import numpy as np
import re
from typing import Dict, List, Tuple
from dataclasses import dataclass
from packages.common.types import Detection

_reader = None

TOKEN_RE = re.compile(r"[a-zA-Z0-9]+")

@dataclass
class OCRToken:
    """OCR token with bounding box information."""
    text: str           # Normalized token text (lowercase)
    bbox: Tuple[Tuple[float, float], Tuple[float, float], Tuple[float, float], Tuple[float, float]]  # 4 corners
    confidence: float   # OCR confidence
    
    @property
    def center(self) -> Tuple[float, float]:
        """Calculate center point of bounding box."""
        xs = [p[0] for p in self.bbox]
        ys = [p[1] for p in self.bbox]
        return (sum(xs) / 4, sum(ys) / 4)
    
    @property
    def width(self) -> float:
        """Approximate width of bounding box."""
        xs = [p[0] for p in self.bbox]
        return max(xs) - min(xs)
    
    @property
    def height(self) -> float:
        """Approximate height of bounding box."""
        ys = [p[1] for p in self.bbox]
        return max(ys) - min(ys)

def _get_reader():
    global _reader
    if _reader is None:
        _reader = easyocr.Reader(['en'], gpu=False)
    return _reader


def _easyocr_tokens(crop_bgr: np.ndarray) -> List[OCRToken]:
    """
    Run EasyOCR on a BGR crop and return tokens with bounding boxes.
    Returns: List of OCRToken objects with text, bbox, and confidence.
    """
    reader = _get_reader()

    # EasyOCR expects RGB
    crop_rgb = crop_bgr[:, :, ::-1]

    try:
        # detail=1 returns (bbox, text, confidence)
        results = reader.readtext(crop_rgb, detail=1)
    except Exception:
        return []

    tokens = []
    for bbox, text, conf in results:
        if not text:
            continue
        
        # Extract alphanumeric tokens from the text
        raw_tokens = TOKEN_RE.findall(text)
        for tok in raw_tokens:
            tokens.append(OCRToken(
                text=tok.lower(),
                bbox=tuple(tuple(p) for p in bbox),  # Convert to tuple of tuples
                confidence=float(conf)
            ))
    
    return tokens


def extract_ocr_tokens_by_object(frame_bgr: np.ndarray, detections: List[Detection]) -> Dict[int, List[OCRToken]]:
    """
    Returns: { object_id: [OCRToken1, OCRToken2, ...] }
    object_id matches enumerate(detections).
    """
    out: Dict[int, List[OCRToken]] = {}
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
            out[obj_id] = toks

    return out


def extract_ocr_tokens(frame: np.ndarray, detections: List[Detection]) -> List[str]:
    """
    Convenience: Flatten tokens across objects into a de-duplicated sorted list.
    Returns just the text strings (for backward compatibility).
    """
    tok_map = extract_ocr_tokens_by_object(frame, detections)
    all_tokens = set()
    for toks in tok_map.values():
        all_tokens.update(t.text for t in toks)
    return sorted(all_tokens)