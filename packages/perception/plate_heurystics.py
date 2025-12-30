import re
from typing import List
from dataclasses import dataclass

_PLATE_ALNUM_RE = re.compile(r"^[A-Z0-9]+$")

@dataclass
class PlateCandidate:
    """A grouped plate candidate with combined text and average confidence."""
    text: str           # Combined plate text (uppercase)
    confidence: float   # Average confidence from constituent tokens
    token_count: int    # Number of tokens that were grouped

def is_plate_component(token: str, *, min_len: int = 2, max_len: int = 4) -> bool:
    if not token:
        return False

    s = token.strip().upper()
    if len(s) < min_len or len(s) > max_len:
        return False

    if not _PLATE_ALNUM_RE.match(s):
        return False

    return True

def is_plate_candidate(
    token: str,
    *,
    min_len: int = 5,
    max_len: int = 8,
) -> bool:
    """
    Heuristic filter for license-plate-like OCR tokens.

    Rules (intentionally conservative):
    - Alphanumeric only
    - Length between 5 and 8
    - Contains at least one letter and one digit
    """
    if not token:
        return False

    s = token.strip().upper()

    if len(s) < min_len or len(s) > max_len:
        return False

    if not _PLATE_ALNUM_RE.match(s):
        return False

    has_alpha = any(c.isalpha() for c in s)
    has_digit = any(c.isdigit() for c in s)

    if not (has_alpha and has_digit):
        return False

    return True


def group_plate_tokens(tokens: List, *, max_horizontal_gap: float = 2.0, max_vertical_offset: float = 0.5) -> List[PlateCandidate]:
    """
    Group OCR tokens by spatial proximity to form complete license plates.
    
    Handles two cases:
    1. Complete plates read as single tokens (e.g., "ABC123")
    2. Fragmented plates that need grouping (e.g., "ABC" + "123")
    
    Args:
        tokens: List of OCRToken objects (must have .text, .confidence, .center, .height properties)
        max_horizontal_gap: Maximum horizontal distance as multiple of average height
        max_vertical_offset: Maximum vertical distance as multiple of average height
    
    Returns:
        List of PlateCandidate objects for tokens that form valid plates
    
    Algorithm:
        1. Check for complete plates (single tokens that already match)
        2. Filter to plate component tokens (2-4 chars)
        3. Sort left-to-right by horizontal position
        4. Group consecutive tokens that are spatially close
        5. Validate each group as a plate candidate
        6. Return all candidates with combined text and average confidence
    """
    if not tokens:
        return []
    
    candidates = []
    
    # First pass: Check for complete plates (single tokens)
    for tok in tokens:
        if is_plate_candidate(tok.text):
            candidates.append(PlateCandidate(
                text=tok.text.upper(),
                confidence=tok.confidence,
                token_count=1
            ))
    
    # Second pass: Group plate components for fragmented plates
    plate_components = [t for t in tokens if is_plate_component(t.text)]
    
    if not plate_components:
        return candidates  # Return only complete plates found in first pass
    
    # Sort tokens by horizontal position (left to right)
    plate_components.sort(key=lambda t: t.center[0])
    
    # Group tokens that are close together
    plate_groups = []
    current_group = [plate_components[0]]
    
    for i in range(1, len(plate_components)):
        prev_tok = plate_components[i - 1]
        curr_tok = plate_components[i]
        
        # Calculate horizontal and vertical distance between centers
        dx = abs(curr_tok.center[0] - prev_tok.center[0])
        dy = abs(curr_tok.center[1] - prev_tok.center[1])
        
        # Use average height as reference for proximity
        avg_height = (prev_tok.height + curr_tok.height) / 2
        
        # Tokens are "close" if:
        # - Horizontal gap < max_horizontal_gap * average height
        # - Vertical offset < max_vertical_offset * average height
        if dx < (avg_height * max_horizontal_gap) and dy < (avg_height * max_vertical_offset):
            current_group.append(curr_tok)
        else:
            # Start new group
            plate_groups.append(current_group)
            current_group = [curr_tok]
    
    # Don't forget the last group
    plate_groups.append(current_group)
    
    # Process each group: combine tokens and validate as plate candidates
    for group in plate_groups:
        combined_text = "".join(t.text.upper() for t in group)
        
        if is_plate_candidate(combined_text):
            avg_conf = sum(t.confidence for t in group) / len(group)
            candidates.append(PlateCandidate(
                text=combined_text,
                confidence=avg_conf,
                token_count=len(group)
            ))
    
    # Deduplicate: If we found both "ABC123" as a single token AND "ABC"+"123" grouped,
    # prefer the single token (usually more accurate)
    seen_texts = set()
    unique_candidates = []
    
    # Sort by token_count ascending (single tokens first)
    candidates.sort(key=lambda c: c.token_count)
    
    for candidate in candidates:
        if candidate.text not in seen_texts:
            seen_texts.add(candidate.text)
            unique_candidates.append(candidate)
    
    return unique_candidates


def select_best_plate(candidates: List[PlateCandidate]) -> PlateCandidate | None:
    """
    Select the most likely real plate from multiple candidates.
    
    Strategy:
    1. Prefer standard length plates (6-7 chars) over edge cases
    2. Prefer higher confidence
    3. Prefer fewer tokens (single read vs fragmented)
    
    Args:
        candidates: List of PlateCandidate objects
    
    Returns:
        The single best candidate, or None if empty list
    """
    if not candidates:
        return None
    
    if len(candidates) == 1:
        return candidates[0]
    
    # Score each candidate
    scored = []
    for candidate in candidates:
        score = 0.0
        
        # 1. Length score: Standard plates are usually 6-7 characters
        if 6 <= len(candidate.text) <= 7:
            score += 2.0  # Strong preference
        elif 5 <= len(candidate.text) <= 8:
            score += 1.0  # Acceptable
        else:
            score += 0.0  # Edge case (custom plates, etc.)
        
        # 2. Confidence score (0.0 - 1.0)
        score += candidate.confidence
        
        # 3. Token count score: Prefer single-token reads (more likely correct)
        if candidate.token_count == 1:
            score += 1.0
        elif candidate.token_count == 2:
            score += 0.5
        else:
            score += 0.0
        
        scored.append((score, candidate))
    
    # Sort by score descending and return the best
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1]
