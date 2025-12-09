# packages/perception/ocr.py
import easyocr
import numpy as np
from typing import List
from .types import Detection

_reader = None

def _get_reader():
    global _reader
    if _reader is None:
        # GPU=False is safer for a small box / doorbell device
        _reader = easyocr.Reader(['en'], gpu=False)
    return _reader

def extract_ocr_tokens(frame: np.ndarray, detections: List[Detection]) -> list[str]:
    """
    Run OCR on relevant regions (vehicles, packages, uniforms, shirts).
    Returns a de-duplicated list of lowercase tokens.
    """
    reader = _get_reader()
    tokens: set[str] = set()

    # Simple first pass: run OCR on each detection crop that's likely to have text
    for det in detections:
        if det.cls not in {"person", "vehicle", "package"}:
            continue

        x1, y1, x2, y2 = det.box
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            continue

        # detail=0 → just text strings
        try:
            results = reader.readtext(crop, detail=0)
        except Exception as e:
            # don't kill vision if OCR chokes on a weird crop
            continue

        for text in results:
            for tok in str(text).split():
                tok = tok.strip().lower()
                if tok:
                    tokens.add(tok)

    return sorted(tokens)
