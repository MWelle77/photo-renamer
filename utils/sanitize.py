import re
from functools import lru_cache

MAX_DEVICE_LEN = 40

_RE_NON_WORD = re.compile(r'[^\w]')
_RE_MULTI_UNDERSCORE = re.compile(r'_+')


@lru_cache(maxsize=256)
def sanitize_device_name(make: str, model: str) -> str:
    """
    Combine make + model into a filesystem-safe uppercase device string.
    Returns 'UNKNOWN' if both are empty.
    """
    make = (make or '').strip()
    model = (model or '').strip()

    if not make and not model:
        return 'UNKNOWN'

    # Avoid "AppleApple iPhone 14" when make is already in model
    if make and model:
        raw = model if make.lower() in model.lower() else f"{make} {model}"
    else:
        raw = make or model

    cleaned = _RE_NON_WORD.sub('_', raw)
    cleaned = _RE_MULTI_UNDERSCORE.sub('_', cleaned).strip('_')
    cleaned = cleaned.upper()[:MAX_DEVICE_LEN]

    return cleaned or 'UNKNOWN'
