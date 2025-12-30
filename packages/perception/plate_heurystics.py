import re
from typing import List
from dataclasses import dataclass

_PLATE_ALNUM_RE = re.compile(r"^[A-Z0-9]+$")

@dataclass
class PlateCandidate:
    """A grouped plate candidate with combined text and average confidence."""
    text: str                    # Combined plate text (uppercase)
    confidence: float            # Average confidence from constituent tokens
    token_count: int             # Number of tokens that were grouped
    center: tuple = None         # (x, y) center position of plate
    vehicle_bbox: tuple = None   # (x1, y1, x2, y2) bounding box of parent vehicle
    tokens: list = None          # List of OCRToken objects that make up this candidate

@dataclass
class PlateModifiers:
    """Configuration for plate detection and confidence boosting."""
    
    # Pattern-based confidence boosting
    boost_standard_length: float = 0.35      # Boost for 6-7 char plates
    boost_acceptable_length: float = 0.20    # Boost for 5 or 8 char plates
    boost_good_balance: float = 0.35         # Boost for 2-4 alphas AND 2-4 digits
    boost_weak_balance: float = 0.20         # Boost for any alphas AND any digits
    boost_spatial_position: float = 0.15     # Boost for plates in expected location (center-bottom)
    boost_size_ratio: float = 0.10           # Boost for plates with appropriate size relative to vehicle
    
    # Confidence caps
    max_confidence: float = 0.95             # Cap to avoid overconfidence
    
    # Proximity grouping thresholds
    max_horizontal_gap: float = 2.0          # Max gap as multiple of avg height
    max_vertical_offset: float = 0.5         # Max vertical offset as multiple of avg height
    
    # Spatial position validation (relative to vehicle bbox)
    expected_horizontal_range: tuple = (0.2, 0.8)  # Plate should be in center 60% horizontally (0.2 to 0.8)
    expected_vertical_range: tuple = (0.5, 1.0)    # Plate should be in bottom 50% vertically (0.5 to 1.0)
    
    # Size validation (relative to vehicle bbox area)
    expected_size_ratio_range: tuple = (0.01, 0.05)  # Plate should be 1-5% of vehicle area
    
    # Validation thresholds
    min_component_len: int = 2               # Min length for plate fragment
    max_component_len: int = 4               # Max length for plate fragment
    min_candidate_len: int = 5               # Min length for complete plate
    max_candidate_len: int = 8               # Max length for complete plate

def is_plate_component(token: str, modifiers: PlateModifiers = None) -> bool:
    if not token:
        return False
    
    if modifiers is None:
        modifiers = PlateModifiers()

    s = token.strip().upper()
    if len(s) < modifiers.min_component_len or len(s) > modifiers.max_component_len:
        return False

    if not _PLATE_ALNUM_RE.match(s):
        return False

    return True

def is_plate_candidate(token: str, modifiers: PlateModifiers = None) -> bool:
    """
    Heuristic filter for license-plate-like OCR tokens.

    Rules (intentionally conservative):
    - Alphanumeric only
    - Length between min_candidate_len and max_candidate_len (default 5-8)
    - Contains at least one letter and one digit
    """
    if not token:
        return False
    
    if modifiers is None:
        modifiers = PlateModifiers()

    s = token.strip().upper()

    if len(s) < modifiers.min_candidate_len or len(s) > modifiers.max_candidate_len:
        return False

    if not _PLATE_ALNUM_RE.match(s):
        return False

    has_alpha = any(c.isalpha() for c in s)
    has_digit = any(c.isdigit() for c in s)

    if not (has_alpha and has_digit):
        return False

    return True


def group_plate_tokens(tokens: List, modifiers: PlateModifiers = None, vehicle_bbox: tuple = None) -> List[PlateCandidate]:
    """
    Group OCR tokens by spatial proximity to form complete license plates.
    
    Handles two cases:
    1. Complete plates read as single tokens (e.g., "ABC123")
    2. Fragmented plates that need grouping (e.g., "ABC" + "123")
    
    Args:
        tokens: List of OCRToken objects (must have .text, .confidence, .center, .height properties)
        modifiers: PlateModifiers configuration object
        vehicle_bbox: (x1, y1, x2, y2) bounding box of parent vehicle for spatial validation
    
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
    
    if modifiers is None:
        modifiers = PlateModifiers()
    
    candidates = []
    
    # First pass: Check for complete plates (single tokens)
    for tok in tokens:
        if is_plate_candidate(tok.text, modifiers):
            candidates.append(PlateCandidate(
                text=tok.text.upper(),
                confidence=tok.confidence,
                token_count=1,
                center=tok.center,
                vehicle_bbox=vehicle_bbox
            ))
    
    # Second pass: Group plate components for fragmented plates
    plate_components = [t for t in tokens if is_plate_component(t.text, modifiers)]
    
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
        if dx < (avg_height * modifiers.max_horizontal_gap) and dy < (avg_height * modifiers.max_vertical_offset):
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
        
        if is_plate_candidate(combined_text, modifiers):
            avg_conf = sum(t.confidence for t in group) / len(group)
            # Calculate center as average of all token centers
            avg_center = (
                sum(t.center[0] for t in group) / len(group),
                sum(t.center[1] for t in group) / len(group)
            )
            candidates.append(PlateCandidate(
                text=combined_text,
                confidence=avg_conf,
                token_count=len(group),
                center=avg_center,
                vehicle_bbox=vehicle_bbox,
                tokens=group  # Store the original tokens for size calculation
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


def select_best_plate(candidates: List[PlateCandidate], modifiers: PlateModifiers = None) -> PlateCandidate | None:
    """
    Select the most likely real plate from multiple candidates.
    
    Strategy:
    1. Prefer standard length plates (6-7 chars) over edge cases
    2. Prefer higher confidence
    3. Prefer fewer tokens (single read vs fragmented)
    4. Boost confidence for plates matching standard patterns
    
    Args:
        candidates: List of PlateCandidate objects
        modifiers: PlateModifiers configuration object
    
    Returns:
        The single best candidate (with potentially boosted confidence), or None if empty list
    """
    if not candidates:
        return None
    
    if modifiers is None:
        modifiers = PlateModifiers()
    
    if len(candidates) == 1:
        # Still apply confidence boost to single candidate
        c = candidates[0]
        boosted_conf = _boost_confidence_for_pattern(c, modifiers)
        return PlateCandidate(
            text=c.text, 
            confidence=boosted_conf, 
            token_count=c.token_count,
            center=c.center,
            vehicle_bbox=c.vehicle_bbox,
            tokens=c.tokens
        )
    
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
    
    # Sort by score descending and return the best with boosted confidence
    scored.sort(key=lambda x: x[0], reverse=True)
    best = scored[0][1]
    boosted_conf = _boost_confidence_for_pattern(best, modifiers)
    return PlateCandidate(
        text=best.text, 
        confidence=boosted_conf, 
        token_count=best.token_count,
        center=best.center,
        vehicle_bbox=best.vehicle_bbox,
        tokens=best.tokens
    )


def _boost_confidence_for_pattern(candidate: PlateCandidate, modifiers: PlateModifiers) -> float:
    """
    Boost confidence for plates that strongly match expected patterns.
    
    Pattern-based confidence boosting:
    - Standard length (6-7 chars)
    - Good alpha/digit balance  
    - Spatial position (center-bottom of vehicle)
    - Size ratio (1-5% of vehicle area)
    
    Args:
        candidate: PlateCandidate with text, confidence, and spatial info
        modifiers: PlateModifiers configuration object
    
    Returns:
        Boosted confidence (capped at max_confidence to avoid overconfidence)
    """
    text = candidate.text
    raw_conf = candidate.confidence
    
    # Count alphas and digits
    alpha_count = sum(1 for c in text if c.isalpha())
    digit_count = sum(1 for c in text if c.isdigit())
    total_len = len(text)
    
    boost = 0.0
    
    # Standard length (6-7 chars)
    if 6 <= total_len <= 7:
        boost += modifiers.boost_standard_length
    elif 5 <= total_len <= 8:
        boost += modifiers.boost_acceptable_length
    
    # Good alpha/digit balance (typical plates have 3-4 of each)
    if 2 <= alpha_count <= 4 and 2 <= digit_count <= 4:
        boost += modifiers.boost_good_balance
    elif alpha_count > 0 and digit_count > 0:
        boost += modifiers.boost_weak_balance
    
    # Spatial position boost: plate should be in center-bottom of vehicle
    if candidate.center and candidate.vehicle_bbox:
        x1, y1, x2, y2 = candidate.vehicle_bbox
        plate_x, plate_y = candidate.center
        
        # OCR coordinates are relative to the cropped vehicle bbox
        # Convert to absolute image coordinates first
        abs_plate_x = x1 + plate_x
        abs_plate_y = y1 + plate_y
        
        # Now normalize to 0-1 relative to vehicle bbox
        rel_x = (abs_plate_x - x1) / (x2 - x1) if (x2 - x1) > 0 else 0.5
        rel_y = (abs_plate_y - y1) / (y2 - y1) if (y2 - y1) > 0 else 0.5
        
        # Debug: log spatial position (can be removed later)
        print(f"[PLATE SPATIAL] plate={candidate.text}, "
              f"crop_center=({plate_x:.1f},{plate_y:.1f}), "
              f"abs_center=({abs_plate_x:.1f},{abs_plate_y:.1f}), "
              f"vehicle_bbox=({x1},{y1},{x2},{y2}), "
              f"rel_pos=({rel_x:.2f},{rel_y:.2f})")
        
        # Check if plate is in expected region
        h_min, h_max = modifiers.expected_horizontal_range
        v_min, v_max = modifiers.expected_vertical_range
        
        if h_min <= rel_x <= h_max and v_min <= rel_y <= v_max:
            boost += modifiers.boost_spatial_position
            print(f"[PLATE SPATIAL] ✓ Plate in expected region, adding {modifiers.boost_spatial_position} boost")
        else:
            print(f"[PLATE SPATIAL] ✗ Plate outside expected region "
                  f"(h: {h_min}-{h_max}, v: {v_min}-{v_max}), no spatial boost")
    
    # Size ratio boost: plate area should be 1-5% of vehicle area
    if candidate.tokens and candidate.vehicle_bbox:
        x1, y1, x2, y2 = candidate.vehicle_bbox
        vehicle_area = (x2 - x1) * (y2 - y1)
        
        # Calculate plate area from token bounding boxes
        # Use the convex hull approach: find min/max x and y from all token corners
        all_xs = []
        all_ys = []
        for token in candidate.tokens:
            for corner in token.bbox:
                all_xs.append(corner[0])
                all_ys.append(corner[1])
        
        if all_xs and all_ys:
            plate_width = max(all_xs) - min(all_xs)
            plate_height = max(all_ys) - min(all_ys)
            plate_area = plate_width * plate_height
            
            size_ratio = plate_area / vehicle_area if vehicle_area > 0 else 0
            
            # Check if size ratio is in expected range
            ratio_min, ratio_max = modifiers.expected_size_ratio_range
            
            print(f"[PLATE SIZE] plate={candidate.text}, "
                  f"plate_area={plate_area:.0f}, vehicle_area={vehicle_area:.0f}, "
                  f"ratio={size_ratio:.4f} (expected: {ratio_min}-{ratio_max})")
            
            if ratio_min <= size_ratio <= ratio_max:
                boost += modifiers.boost_size_ratio
                print(f"[PLATE SIZE] ✓ Plate size ratio in expected range, adding {modifiers.boost_size_ratio} boost")
            else:
                print(f"[PLATE SIZE] ✗ Plate size ratio outside expected range, no size boost")
    
    # Apply boost with diminishing returns for already-high confidence
    # Formula: new_conf = raw + boost * (1 - raw)
    # This way, low confidence gets bigger boost, high confidence gets smaller
    boosted = raw_conf + boost * (1.0 - raw_conf)
    
    # Cap at max_confidence to avoid overconfidence
    return min(modifiers.max_confidence, boosted)

