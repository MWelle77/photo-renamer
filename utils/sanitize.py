import re

MAX_DEVICE_LEN = 40


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
        if make.lower() in model.lower():
            raw = model
        else:
            raw = f"{make} {model}"
    else:
        raw = make or model

    # Keep only alphanumeric and replace everything else with underscore
    cleaned = re.sub(r'[^\w]', '_', raw)
    cleaned = re.sub(r'_+', '_', cleaned).strip('_')
    cleaned = cleaned.upper()[:MAX_DEVICE_LEN]

    return cleaned or 'UNKNOWN'
