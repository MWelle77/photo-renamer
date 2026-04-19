"""
Extract (datetime, device_string, gps_coords) from image and video files.
Returns (None, 'UNKNOWN', None) when metadata is absent or unreadable.
"""

import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

from utils.formats import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS
from utils.sanitize import sanitize_device_name

Coords = Optional[Tuple[float, float]]
MetadataResult = Tuple[Optional[datetime], str, Coords]

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


def extract_metadata(path: Path) -> MetadataResult:
    """Public entry point. Dispatches to image or video extractor."""
    suffix = path.suffix.lower()
    try:
        if suffix in IMAGE_EXTENSIONS:
            result = _from_image(path)
        elif suffix in VIDEO_EXTENSIONS:
            result = _from_video(path)
        else:
            return None, 'UNKNOWN', None
    except Exception:
        result = (None, 'UNKNOWN', None)
    # Fallback: try to parse date from the filename itself (GPS stays None)
    if result[0] is None:
        dt, device = _from_filename(path)
        return dt, device, None
    return result


# ── Image ──────────────────────────────────────────────────────────────────

def _dms_to_decimal(tag, ref: str) -> Optional[float]:
    """Convert exifread DMS tag to decimal degrees."""
    if not tag:
        return None
    try:
        vals = tag.values
        d = float(vals[0].num) / float(vals[0].den)
        m = float(vals[1].num) / float(vals[1].den)
        s = float(vals[2].num) / float(vals[2].den)
        decimal = d + m / 60 + s / 3600
        if ref.strip().upper() in ('S', 'W'):
            decimal = -decimal
        return decimal
    except Exception:
        return None


def _ratio_to_float(val) -> float:
    if hasattr(val, 'numerator') and hasattr(val, 'denominator'):
        return val.numerator / val.denominator
    if isinstance(val, tuple) and len(val) == 2:
        return val[0] / val[1]
    return float(val)


def _pillow_gps(exif) -> Coords:
    """Extract GPS coords from a Pillow EXIF object."""
    try:
        gps_ifd = exif.get_ifd(34853)
        if not gps_ifd:
            return None
        lat_dms = gps_ifd.get(2)
        lat_ref = str(gps_ifd.get(1, ''))
        lon_dms = gps_ifd.get(4)
        lon_ref = str(gps_ifd.get(3, ''))
        if not lat_dms or not lon_dms:
            return None
        lat = sum(_ratio_to_float(x) / (60 ** i) for i, x in enumerate(lat_dms))
        lon = sum(_ratio_to_float(x) / (60 ** i) for i, x in enumerate(lon_dms))
        if lat_ref.upper() == 'S':
            lat = -lat
        if lon_ref.upper() == 'W':
            lon = -lon
        return lat, lon
    except Exception:
        return None


def _from_image(path: Path) -> MetadataResult:
    # exifread — remove stop_tag so GPS coords are available
    if _EXIFREAD_OK:
        try:
            with open(path, 'rb') as f:
                tags = _exifread.process_file(f, details=False)
            dt = _exifread_datetime(tags)
            make = str(tags.get('Image Make', '') or tags.get('EXIF LensMake', '')).strip()
            model = str(tags.get('Image Model', '')).strip()
            device = sanitize_device_name(make, model)
            lat = _dms_to_decimal(tags.get('GPS GPSLatitude'),
                                   str(tags.get('GPS GPSLatitudeRef', '')))
            lon = _dms_to_decimal(tags.get('GPS GPSLongitude'),
                                   str(tags.get('GPS GPSLongitudeRef', '')))
            gps = (lat, lon) if lat is not None and lon is not None else None
            if dt:
                # exifread found the date but missed GPS (common for HEIC and
                # some JPEG encodings) — try Pillow specifically for GPS.
                if gps is None and _PILLOW_OK:
                    try:
                        gps = _pillow_gps(_PilImage.open(path).getexif())
                    except Exception:
                        pass
                return dt, device, gps
        except Exception:
            pass

    # Fallback: Pillow (date + GPS)
    if _PILLOW_OK:
        try:
            img = _PilImage.open(path)
            exif = img.getexif()
            dt = _pillow_datetime(exif)
            make = str(exif.get(271, '')).strip()
            model = str(exif.get(272, '')).strip()
            device = sanitize_device_name(make, model)
            gps = _pillow_gps(exif)
            return dt, device, gps
        except Exception:
            pass

    return None, 'UNKNOWN', None


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

_XYZ_RE = re.compile(r'([+-]\d+\.?\d*)([+-]\d+\.?\d*)')


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
    try:
        dt = datetime.fromisoformat(s.replace('UTC ', '').replace('Z', '+00:00'))
        return dt.replace(tzinfo=None)
    except Exception:
        pass
    return None


def _parse_xyz(xyz: str) -> Coords:
    if not xyz:
        return None
    m = _XYZ_RE.search(xyz.strip())
    if m:
        try:
            return float(m.group(1)), float(m.group(2))
        except ValueError:
            pass
    return None


def _from_video(path: Path) -> MetadataResult:
    if not _MEDIAINFO_OK:
        return None, 'UNKNOWN', None
    try:
        info = _MediaInfo.parse(str(path))
        general = next((t for t in info.tracks if t.track_type == 'General'), None)
        if not general:
            return None, 'UNKNOWN', None

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
        if not make:
            make = str(getattr(general, 'comandroidmanufacturer', '') or '').strip()
        if not model:
            model = str(getattr(general, 'comandroidmodel', '') or '').strip()

        if not make and not model:
            for track in info.tracks:
                if track.track_type == 'General':
                    continue
                t_make = str(getattr(track, 'publisher', '') or '').strip()
                t_model = str(getattr(track, 'encoded_application', '') or '').strip()
                if t_make or t_model:
                    make, model = t_make, t_model
                    break

        if not make and not model:
            other_formats = str(getattr(general, 'other_format_list', '') or '')
            if 'gpmd' in other_formats.lower():
                make = 'GoPro'

        gps = _parse_xyz(str(getattr(general, 'xyz', '') or ''))

        return dt, sanitize_device_name(make, model), gps
    except Exception:
        return None, 'UNKNOWN', None


# ── Filename date parsing (last-resort fallback) ───────────────────────────

_FN_PATTERNS_WITH_TIME = [
    re.compile(r'(2\d{3})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])[_\-T]([01]\d|2[0-3])([0-5]\d)([0-5]\d)'),
    re.compile(r'(2\d{3})[-_.](0[1-9]|1[0-2])[-_.](\d{2})[_\- T\-]([01]\d|2[0-3])[-:.]([0-5]\d)[-:.]([0-5]\d)'),
    re.compile(r'(2\d{3})-(0[1-9]|1[0-2])-(\d{2}) at ([01]\d|2[0-3])\.([0-5]\d)\.([0-5]\d)'),
    re.compile(r'(?<!\d)(2\d{3})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])([01]\d|2[0-3])([0-5]\d)([0-5]\d)(?!\d)'),
]

_FN_PATTERNS_DATE_ONLY = [
    re.compile(r'(?<!\d)(2\d{3})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?!\d)'),
]


def _from_filename(path: Path) -> Tuple[Optional[datetime], str]:
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
