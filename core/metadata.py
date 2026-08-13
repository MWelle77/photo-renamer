"""
Extract (datetime, device_string, gps_coords, tz_offset_hours) from image and video files.
Returns (None, 'UNKNOWN', None, None) when metadata is absent or unreadable.
"""

import re
import struct as _st
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

from utils.formats import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS
from utils.sanitize import sanitize_device_name

Coords = Optional[Tuple[float, float]]
MetadataResult = Tuple[Optional[datetime], str, Coords, Optional[int]]

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
            return None, 'UNKNOWN', None, None
    except Exception:
        result = (None, 'UNKNOWN', None, None)
    # Fallback: try to parse date from the filename itself (GPS stays None)
    if result[0] is None:
        dt, device = _from_filename(path)
        return dt, device, None, None
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
            tz_offset = _parse_tz_offset(
                str(tags.get('EXIF OffsetTimeOriginal', '') or
                    tags.get('EXIF OffsetTime', '') or '')
            )
            if dt:
                # exifread found the date but missed GPS (common for HEIC and
                # some JPEG encodings) — try Pillow specifically for GPS.
                if gps is None and _PILLOW_OK:
                    try:
                        img_exif = _PilImage.open(path).getexif()
                        gps = _pillow_gps(img_exif)
                        if tz_offset is None:
                            tz_offset = _parse_tz_offset(
                                str(img_exif.get(36881, '') or img_exif.get(36880, '') or '')
                            )
                    except Exception:
                        pass
                return dt, device, gps, tz_offset
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
            # Tag 36881 = OffsetTimeOriginal, 36880 = OffsetTime
            tz_offset = _parse_tz_offset(
                str(exif.get(36881, '') or exif.get(36880, '') or '')
            )
            return dt, device, gps, tz_offset
        except Exception:
            pass

    return None, 'UNKNOWN', None, None


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


def _parse_tz_offset(s: str) -> Optional[int]:
    """Parse '+10:00' or '-05:30' EXIF OffsetTime string into integer hours (rounded)."""
    if not s:
        return None
    m = re.match(r'^([+-])(\d{1,2}):(\d{2})$', s.strip())
    if m:
        sign = 1 if m.group(1) == '+' else -1
        total_minutes = sign * (int(m.group(2)) * 60 + int(m.group(3)))
        return round(total_minutes / 60)
    return None


# ── Video ──────────────────────────────────────────────────────────────────

# GPMF type codes → (bytes_per_value, struct_format_char)
_GPMF_NUM = {
    b'b': (1, 'b'), b'B': (1, 'B'),
    b's': (2, 'h'), b'S': (2, 'H'),
    b'l': (4, 'i'), b'L': (4, 'I'),
    b'f': (4, 'f'), b'd': (8, 'd'),
    b'j': (8, 'q'), b'J': (8, 'Q'),
}


def _gpmf_iter(data: bytes):
    """Yield (key, type_byte, payload) for each record in a GPMF byte stream."""
    pos = 0
    while pos + 8 <= len(data):
        key  = data[pos:pos+4]
        typ  = data[pos+4:pos+5]
        esz  = data[pos+5]
        rep  = _st.unpack_from('>H', data, pos+6)[0]
        pos += 8
        total = esz * rep
        if pos + total > len(data):
            break
        payload = data[pos:pos+total]
        pos += total + ((-total) & 3)          # pad to 4-byte boundary

        if typ == b'\x00':
            yield key, typ, payload            # container — payload is nested GPMF
        elif typ in _GPMF_NUM:
            base, fc = _GPMF_NUM[typ]
            n_total = total // base
            if n_total:
                vals = list(_st.unpack_from(f'>{n_total}{fc}', payload))
                n_per = esz // base            # values per element (5 for GPS5)
                if n_per > 1:
                    yield key, typ, [vals[i*n_per:(i+1)*n_per] for i in range(rep)]
                else:
                    yield key, typ, vals
            else:
                yield key, typ, []
        else:
            yield key, typ, payload            # unknown type — raw bytes


def _gpmf_gps(data: bytes) -> Coords:
    """
    Parse a GPMF binary blob and return the first GPS coordinate that has a
    valid fix.  Handles both GPS5 (older GoPros) and GPS9 (Hero 9+).

    GPS5: type 'l', 5 int32 per element, fix via separate GPSF stream.
    GPS9: composite type lllllllSS (7 int32 + 2 uint16 = 32 bytes), fix is
          the last uint16 (byte 30-31 of each element, value ≥ 2 = good fix).
    """
    for key, typ, content in _gpmf_iter(data):
        if key != b'DEVC' or typ != b'\x00':
            continue
        for skey, styp, scontent in _gpmf_iter(content):
            if skey != b'STRM' or styp != b'\x00':
                continue
            scal_list = []
            gpsf = 0
            gps5 = None
            gps9_raw = None

            for rkey, _rt, rvals in _gpmf_iter(scontent):
                if rkey == b'SCAL' and isinstance(rvals, list) and rvals:
                    scal_list = rvals
                elif rkey == b'GPSF' and isinstance(rvals, list) and rvals:
                    gpsf = rvals[0]
                elif rkey == b'GPS5' and isinstance(rvals, list) and rvals:
                    gps5 = rvals
                elif rkey == b'GPS9' and isinstance(rvals, bytes) and rvals:
                    gps9_raw = rvals

            # GPS5 path — per-channel SCAL (lat=SCAL[0], lon=SCAL[1]); fix via GPSF
            if gps5 and gpsf >= 2 and scal_list:
                lat_s = scal_list[0]
                lon_s = scal_list[1] if len(scal_list) >= 2 else scal_list[0]
                if lat_s and lon_s:
                    first = gps5[0]
                    if isinstance(first, list) and len(first) >= 2:
                        lat, lon = first[0] / lat_s, first[1] / lon_s
                        if -90 <= lat <= 90 and -180 <= lon <= 180:
                            return lat, lon

            # GPS9 path — TYPE=lllllllSS (7×int32 + 2×uint16 = 32 bytes/element)
            # fix is the last uint16 (offset 30); lat/lon scale from SCAL[0..1]
            if gps9_raw and len(scal_list) >= 2:
                lat_s, lon_s = scal_list[0], scal_list[1]
                if lat_s and lon_s:
                    for off in range(0, len(gps9_raw) - 31, 32):
                        elem = gps9_raw[off:off+32]
                        fix = _st.unpack_from('>H', elem, 30)[0]
                        if fix >= 2:
                            ints = _st.unpack_from('>2i', elem, 0)
                            lat, lon = ints[0] / lat_s, ints[1] / lon_s
                            if -90 <= lat <= 90 and -180 <= lon <= 180:
                                return lat, lon
    return None


def _mp4_boxes(fh, start: int, end: int):
    """Yield (type, payload_start, payload_end) for MP4 boxes in [start, end)."""
    pos = start
    while pos + 8 <= end:
        fh.seek(pos)
        hdr = fh.read(8)
        if len(hdr) < 8:
            return
        size = _st.unpack('>I', hdr[:4])[0]
        typ = hdr[4:8]
        hdr_len = 8
        if size == 1:                          # 64-bit largesize follows
            ext = fh.read(8)
            if len(ext) < 8:
                return
            size = _st.unpack('>Q', ext)[0]
            hdr_len = 16
        elif size == 0:                        # box extends to end of parent
            size = end - pos
        if size < hdr_len or pos + size > end:
            return
        yield typ, pos + hdr_len, pos + size
        pos += size


def _gpmd_sample_locations(fh, file_size: int):
    """
    Walk moov > trak > mdia > minf > stbl to find the GoPro 'gpmd' telemetry
    track.  Returns (chunk_offsets, read_size) or None if no such track.
    Only box headers and sample tables are read — never the media data.
    """
    moov = next(((s, e) for t, s, e in _mp4_boxes(fh, 0, file_size)
                 if t == b'moov'), None)
    if not moov:
        return None

    for typ, ts, te in _mp4_boxes(fh, *moov):
        if typ != b'trak':
            continue
        stbl = None
        for t2, s2, e2 in _mp4_boxes(fh, ts, te):
            if t2 != b'mdia':
                continue
            for t3, s3, e3 in _mp4_boxes(fh, s2, e2):
                if t3 != b'minf':
                    continue
                for t4, s4, e4 in _mp4_boxes(fh, s3, e3):
                    if t4 == b'stbl':
                        stbl = (s4, e4)
        if not stbl:
            continue

        stsd_head = stco = co64 = stsz_head = None
        for t5, s5, e5 in _mp4_boxes(fh, *stbl):
            fh.seek(s5)
            if t5 == b'stsd':
                stsd_head = fh.read(min(e5 - s5, 256))
            elif t5 == b'stco':
                stco = fh.read(e5 - s5)
            elif t5 == b'co64':
                co64 = fh.read(e5 - s5)
            elif t5 == b'stsz':
                stsz_head = fh.read(min(e5 - s5, 12))

        if not stsd_head or b'gpmd' not in stsd_head:
            continue

        offsets = []
        if stco and len(stco) >= 8:
            n = min(_st.unpack_from('>I', stco, 4)[0], (len(stco) - 8) // 4)
            offsets = list(_st.unpack_from(f'>{n}I', stco, 8))
        elif co64 and len(co64) >= 8:
            n = min(_st.unpack_from('>I', co64, 4)[0], (len(co64) - 8) // 8)
            offsets = list(_st.unpack_from(f'>{n}Q', co64, 8))

        # stsz constant sample size (0 = per-sample table; use 64 KB default,
        # generous for GPMF payloads which are typically a few KB per second)
        read_size = 1 << 16
        if stsz_head and len(stsz_head) >= 12:
            const_size = _st.unpack_from('>I', stsz_head, 4)[0]
            if const_size:
                read_size = min(max(const_size, 4096), 1 << 20)

        if offsets:
            return offsets, read_size
    return None


def _gps_from_gpmf_scan(fh) -> Coords:
    """
    Fallback brute-force scan for DEVC markers when the MP4 box tree could
    not be parsed.  Reads 128 KB chunks so large files are never fully loaded.
    """
    CHUNK  = 1 << 17   # 128 KB per read
    EXTRA  = 1 << 16   # 64 KB read-ahead after a DEVC marker
    WINDOW = 8          # small overlap so markers split across chunks are not missed
    fh.seek(0)
    tail = b''
    while True:
        raw = fh.read(CHUNK)
        if not raw:
            break
        buf = tail + raw
        off = 0
        while True:
            p = buf.find(b'DEVC\x00', off)
            if p < 0:
                break
            cur = fh.tell()
            extra = fh.read(EXTRA)
            fh.seek(cur)
            # A false-positive match in compressed video data must not
            # abort the scan — skip it and keep looking.
            try:
                gps = _gpmf_gps(buf[p:] + extra)
            except Exception:
                gps = None
            if gps is not None:
                return gps
            off = p + 1
        tail = buf[-WINDOW:]
    return None


def _gps_from_gpmf(path: Path) -> Coords:
    """
    Extract the first valid GPS fix from a GoPro MP4's GPMF telemetry.

    Primary path: locate the 'gpmd' track via the MP4 sample tables and read
    only its samples (a few KB per second of footage) — a video with no GPS
    lock costs seconds, not a full multi-GB file read.  Falls back to a
    brute-force DEVC scan if the box tree is unparsable.
    """
    try:
        with open(path, 'rb') as fh:
            try:
                found = _gpmd_sample_locations(fh, path.stat().st_size)
            except Exception:
                found = None
            if found:
                offsets, read_size = found
                for off in offsets:
                    try:
                        fh.seek(off)
                        gps = _gpmf_gps(fh.read(read_size))
                    except Exception:
                        continue
                    if gps is not None:
                        return gps
                return None
            return _gps_from_gpmf_scan(fh)
    except Exception:
        pass
    return None


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


def _track_gps(track, attrs) -> Coords:
    """Try a list of pymediainfo attribute names on one track, return first parseable GPS."""
    for attr in attrs:
        raw = str(getattr(track, attr, '') or '')
        if raw:
            gps = _parse_xyz(raw)
            if gps:
                return gps
    return None


def _from_video(path: Path) -> MetadataResult:
    if not _MEDIAINFO_OK:
        return None, 'UNKNOWN', None, None
    try:
        info = _MediaInfo.parse(str(path))
        general = next((t for t in info.tracks if t.track_type == 'General'), None)
        if not general:
            return None, 'UNKNOWN', None, None

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

        other_formats = str(getattr(general, 'other_format_list', '') or '')
        has_gpmd = 'gpmd' in other_formats.lower()

        if not make and not model and has_gpmd:
            make = 'GoPro'

        # GPS — try multiple attribute names (GoPro, Android, iPhone, generic).
        # iPhone MOVs store location as com.apple.quicktime.location.ISO6709.
        gps = _track_gps(general, (
            'xyz', 'location', 'comapplequicktimelocationiso6709',
            'comgpslocation', 'comgooglelocation', 'coordinates',
        ))

        # Also check non-General tracks — GoPro stores telemetry in an 'Other' track
        # that pymediainfo sometimes surfaces with its own xyz/location attribute
        if gps is None:
            for track in info.tracks:
                if track.track_type == 'General':
                    continue
                gps = _track_gps(track, ('xyz', 'location', 'comgpslocation'))
                if gps:
                    break

        # GoPro: pymediainfo cannot decode the binary GPMF telemetry track —
        # fall back to parsing the raw MP4 bytes directly.
        if gps is None and has_gpmd:
            gps = _gps_from_gpmf(path)

        return dt, sanitize_device_name(make, model), gps, None
    except Exception:
        return None, 'UNKNOWN', None, None


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
