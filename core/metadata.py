"""
Extract (datetime, device_string) from image and video files.
Returns (None, 'UNKNOWN') when metadata is absent or unreadable.
"""

import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

from utils.formats import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS
from utils.sanitize import sanitize_device_name

DateDevice = Tuple[Optional[datetime], str]

# Register HEIF/HEIC support once at import time
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass

# Pre-import libraries once so per-file calls have no import overhead
try:
    import exifread as _exifread
    _EXIFREAD_OK = True
except ImportError:
    _EXIFREAD_OK = False

try:
    from PIL import Image as _PilImage
    _PILLOW_OK = True
except ImportError:
    _PILLOW_OK = False

try:
    from pymediainfo import MediaInfo as _MediaInfo
    _MEDIAINFO_OK = True
except ImportError:
    _MEDIAINFO_OK = False


def extract_metadata(path: Path) -> DateDevice:
    """Public entry point. Dispatches to image or video extractor."""
    suffix = path.suffix.lower()
    try:
        if suffix in IMAGE_EXTENSIONS:
            result = _from_image(path)
        elif suffix in VIDEO_EXTENSIONS:
            result = _from_video(path)
        else:
            return None, 'UNKNOWN'
    except Exception:
        result = (None, 'UNKNOWN')
    # Fallback: try to parse date from the filename itself
    if result[0] is None:
        return _from_filename(path)
    return result


# ── Image ──────────────────────────────────────────────────────────────────

def _from_image(path: Path) -> DateDevice:
    # exifread handles JPEG, TIFF, and major RAW formats
    if _EXIFREAD_OK:
        try:
            with open(path, 'rb') as f:
                tags = _exifread.process_file(f, details=False, stop_tag='GPS GPSDate')
            dt = _exifread_datetime(tags)
            make = str(tags.get('Image Make', '') or tags.get('EXIF LensMake', '')).strip()
            model = str(tags.get('Image Model', '')).strip()
            device = sanitize_device_name(make, model)
            if dt:
                return dt, device
        except Exception:
            pass

    # Fallback: Pillow (covers PNG eXIf chunks, WebP, BMP, GIF, HEIC via pillow-heif)
    if _PILLOW_OK:
        try:
            img = _PilImage.open(path)
            exif = img.getexif()
            dt = _pillow_datetime(exif)
            make = str(exif.get(271, '')).strip()   # 271 = Make
            model = str(exif.get(272, '')).strip()  # 272 = Model
            device = sanitize_device_name(make, model)
            return dt, device
        except Exception:
            pass

    return None, 'UNKNOWN'


def _exifread_datetime(tags: dict) -> Optional[datetime]:
    for key in ('EXIF DateTimeOriginal', 'EXIF DateTimeDigitized', 'Image DateTime'):
        val = tags.get(key)
        if val:
            try:
                return datetime.strptime(str(val), '%Y:%m:%d %H:%M:%S')
            except ValueError:
                pass
    return None


def _pillow_datetime(exif) -> Optional[datetime]:
    # Tag 36867 = DateTimeOriginal, 36868 = DateTimeDigitized, 306 = DateTime
    for tag_id in (36867, 36868, 306):
        val = exif.get(tag_id)
        if val:
            try:
                return datetime.strptime(str(val), '%Y:%m:%d %H:%M:%S')
            except ValueError:
                pass
    return None


# ── Video ──────────────────────────────────────────────────────────────────

_VIDEO_DATE_FORMATS = [
    'UTC %Y-%m-%dT%H:%M:%S',
    'UTC %Y:%m:%d %H:%M:%S',
    '%Y-%m-%dT%H:%M:%S%z',
    '%Y-%m-%dT%H:%M:%S',
    '%Y-%m-%d %H:%M:%S UTC',
    '%Y-%m-%d %H:%M:%S',
    '%Y:%m:%d %H:%M:%S',
]


def _parse_video_date(raw: str) -> Optional[datetime]:
    if not raw:
        return None
    s = raw.strip()
    for fmt in _VIDEO_DATE_FORMATS:
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=None)
        except ValueError:
            pass
    # Last resort: isoformat
    try:
        dt = datetime.fromisoformat(s.replace('UTC ', '').replace('Z', '+00:00'))
        return dt.replace(tzinfo=None)
    except Exception:
        pass
    return None


def _from_video(path: Path) -> DateDevice:
    if not _MEDIAINFO_OK:
        return None, 'UNKNOWN'
    try:
        info = _MediaInfo.parse(str(path))
        general = next((t for t in info.tracks if t.track_type == 'General'), None)
        if not general:
            return None, 'UNKNOWN'

        dt = None
        for attr in ('encoded_date', 'tagged_date', 'recorded_date', 'mastered_date'):
            raw = getattr(general, attr, None)
            if raw:
                dt = _parse_video_date(str(raw))
                if dt:
                    break

        make = str(getattr(general, 'publisher', '') or '').strip()
        model = str(getattr(general, 'encoded_application', '') or '').strip()
        if not model:
            model = str(getattr(general, 'comment', '') or '').strip()

        # Android custom atoms
        if not make:
            make = str(getattr(general, 'comandroidmanufacturer', '') or '').strip()
        if not model:
            model = str(getattr(general, 'comandroidmodel', '') or '').strip()

        # Check other tracks for make/model if still empty
        if not make and not model:
            for track in info.tracks:
                if track.track_type == 'General':
                    continue
                t_make = str(getattr(track, 'publisher', '') or '').strip()
                t_model = str(getattr(track, 'encoded_application', '') or '').strip()
                if t_make or t_model:
                    make, model = t_make, t_model
                    break

        # GoPro detection via gpmd track
        if not make and not model:
            other_formats = str(getattr(general, 'other_format_list', '') or '')
            if 'gpmd' in other_formats.lower():
                make = 'GoPro'

        return dt, sanitize_device_name(make, model)
    except Exception:
        return None, 'UNKNOWN'


# ── Filename date parsing (last-resort fallback) ───────────────────────────

# Patterns tried in order — most specific first
_FN_PATTERNS_WITH_TIME = [
    # YYYYMMDD[_-T]HHMMSS  e.g. IMG_20240315_143022, Screenshot_20240315-143022
    re.compile(r'(2\d{3})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])[_\-T]([01]\d|2[0-3])([0-5]\d)([0-5]\d)'),
    # YYYY-MM-DD[_ T]HH[-:.]MM[-:.]SS  e.g. 2024-03-15 14.30.22, 2024-03-15_14-30-22
    re.compile(r'(2\d{3})[-_.](0[1-9]|1[0-2])[-_.](\d{2})[_\- T]([01]\d|2[0-3])[-:.]([0-5]\d)[-:.]([0-5]\d)'),
    # 14 consecutive digits YYYYMMDDHHMMSS  e.g. 20240315143022
    re.compile(r'(?<!\d)(2\d{3})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])([01]\d|2[0-3])([0-5]\d)([0-5]\d)(?!\d)'),
]

_FN_PATTERNS_DATE_ONLY = [
    # YYYYMMDD  e.g. 20240315
    re.compile(r'(?<!\d)(2\d{3})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?!\d)'),
]


def _from_filename(path: Path) -> DateDevice:
    stem = path.stem
    for pattern in _FN_PATTERNS_WITH_TIME:
        m = pattern.search(stem)
        if m:
            try:
                y, mo, d, h, mi, s = (int(x) for x in m.groups())
                return datetime(y, mo, d, h, mi, s), 'UNKNOWN'
            except ValueError:
                continue
    for pattern in _FN_PATTERNS_DATE_ONLY:
        m = pattern.search(stem)
        if m:
            try:
                y, mo, d = (int(x) for x in m.groups())
                return datetime(y, mo, d, 0, 0, 0), 'UNKNOWN'
            except ValueError:
                continue
    return None, 'UNKNOWN'
