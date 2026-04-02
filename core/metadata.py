"""
Extract (datetime, device_string) from image and video files.
Returns (None, 'UNKNOWN') when metadata is absent or unreadable.
"""

import io
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
    _HEIF_SUPPORTED = True
except ImportError:
    _HEIF_SUPPORTED = False


def extract_metadata(path: Path) -> DateDevice:
    """Public entry point. Dispatches to image or video extractor."""
    suffix = path.suffix.lower()
    print(f"[DEBUG] extract_metadata: {path.name} (suffix={suffix!r})")
    try:
        if suffix in IMAGE_EXTENSIONS:
            result = _from_image(path)
            print(f"[DEBUG]   image result: dt={result[0]}, device={result[1]!r}")
            return result
        if suffix in VIDEO_EXTENSIONS:
            result = _from_video(path)
            print(f"[DEBUG]   video result: dt={result[0]}, device={result[1]!r}")
            return result
        print(f"[DEBUG]   suffix not in IMAGE_EXTENSIONS or VIDEO_EXTENSIONS — skipped")
    except Exception as e:
        print(f"[DEBUG]   top-level exception: {type(e).__name__}: {e}")
    return None, 'UNKNOWN'


# ── Image ──────────────────────────────────────────────────────────────────

def _from_image(path: Path) -> DateDevice:
    # exifread handles JPEG, TIFF, and major RAW formats
    try:
        import exifread
        with open(path, 'rb') as f:
            tags = exifread.process_file(f, details=False, stop_tag='GPS GPSDate')

        dt = _exifread_datetime(tags)
        make = str(tags.get('Image Make', '') or tags.get('EXIF LensMake', '')).strip()
        model = str(tags.get('Image Model', '')).strip()
        device = sanitize_device_name(make, model)
        if dt:
            return dt, device
    except Exception:
        pass

    # Fallback: Pillow (covers PNG eXIf chunks, WebP, BMP, GIF, HEIC via pillow-heif)
    try:
        from PIL import Image
        img = Image.open(path)
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
    # Strip timezone suffix like "+0000" after normalizing
    s = raw.strip()
    for fmt in _VIDEO_DATE_FORMATS:
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=None)  # normalize to naive local
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
    try:
        from pymediainfo import MediaInfo
        print(f"[DEBUG]   pymediainfo imported OK, parsing {path.name}")
        info = MediaInfo.parse(str(path))
        general = next((t for t in info.tracks if t.track_type == 'General'), None)
        if not general:
            print("[DEBUG]   no General track found")
            return None, 'UNKNOWN'

        print(f"[DEBUG]   All tracks — non-empty fields:")
        for track in info.tracks:
            print(f"[DEBUG]   [{track.track_type}]")
            for key, val in track.to_data().items():
                if val not in (None, '', 'None'):
                    print(f"[DEBUG]     {key} = {val!r}")
        print(f"[DEBUG]   Date fields:")
        dt = None
        for attr in ('encoded_date', 'tagged_date', 'recorded_date', 'mastered_date'):
            raw = getattr(general, attr, None)
            print(f"[DEBUG]     {attr} = {raw!r}")
            if raw and dt is None:
                dt = _parse_video_date(str(raw))
                print(f"[DEBUG]     -> parsed dt = {dt}")

        make = str(getattr(general, 'publisher', '') or '').strip()
        model = str(getattr(general, 'encoded_application', '') or '').strip()
        if not model:
            model = str(getattr(general, 'comment', '') or '').strip()

        # Android custom atoms: com.android.manufacturer / com.android.model
        if not make:
            make = str(getattr(general, 'comandroidmanufacturer', '') or '').strip()
        if not model:
            model = str(getattr(general, 'comandroidmodel', '') or '').strip()

        # Check other tracks (e.g. video track) for make/model if still empty
        if not make and not model:
            for track in info.tracks:
                if track.track_type == 'General':
                    continue
                t_make = str(getattr(track, 'publisher', '') or '').strip()
                t_model = str(getattr(track, 'encoded_application', '') or '').strip()
                if t_make or t_model:
                    make, model = t_make, t_model
                    print(f"[DEBUG]   found make/model in {track.track_type} track: {make!r} / {model!r}")
                    break

        # GoPro detection: gpmd is a GoPro-proprietary metadata track
        if not make and not model:
            other_formats = str(getattr(general, 'other_format_list', '') or '')
            if 'gpmd' in other_formats.lower():
                make = 'GoPro'
                print(f"[DEBUG]   detected GoPro via gpmd track")

        print(f"[DEBUG]   make={make!r}, model={model!r}")
        device = sanitize_device_name(make, model)
        return dt, device
    except Exception as e:
        import traceback
        print(f"[DEBUG]   _from_video exception: {type(e).__name__}: {e}")
        traceback.print_exc()
        return None, 'UNKNOWN'
