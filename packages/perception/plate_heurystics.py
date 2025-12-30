import re

_PLATE_ALNUM_RE = re.compile(r"^[A-Z0-9]+$")

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
