"""
Build and execute a rename plan for media files.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional, Tuple


@dataclass
class FileRecord:
    path: Path
    dt: Optional[datetime]
    device: str
    gps: Optional[Tuple[float, float]] = None
    location: str = ''


@dataclass
class RenameResult:
    renamed: List[Tuple[Path, Path]] = field(default_factory=list)
    renamed_sidecars: List[Tuple[Path, Path]] = field(default_factory=list)
    skipped_already_correct: List[Path] = field(default_factory=list)
    skipped_no_metadata: List[Path] = field(default_factory=list)
    errors: List[Tuple[Path, str]] = field(default_factory=list)


def build_target_stem(dt: datetime, device: str, location: str = '') -> str:
    stem = f"{dt.strftime('%Y%m%d%H%M%S')}_{device}"
    if location:
        stem += f"_{location}"
    return stem


def _find_free_name(directory: Path, stem: str, suffix: str,
                    reserved: set, source: Path = None) -> str:
    """Return the first available filename (stem+suffix or stem_N+suffix).
    source is excluded from collision checks so already-correct files are
    not bumped to _2 on reruns.
    """
    candidate = stem + suffix
    target = directory / candidate
    if candidate not in reserved and (not target.exists() or target == source):
        return candidate
    counter = 2
    while True:
        candidate = f"{stem}_{counter}{suffix}"
        target = directory / candidate
        if candidate not in reserved and (not target.exists() or target == source):
            return candidate
        counter += 1
        if counter > 9999:
            raise RuntimeError(f"Cannot find free name for {stem}{suffix}")


def plan_renames(records: List[FileRecord]) -> List[Tuple[Path, str]]:
    """
    Returns list of (source_path, new_filename) pairs.
    Files without a datetime are excluded (caller handles them separately).
    """
    by_dir: dict[Path, list[FileRecord]] = defaultdict(list)
    for rec in records:
        if rec.dt is not None:
            by_dir[rec.path.parent].append(rec)

    plan: List[Tuple[Path, str]] = []

    for directory, recs in by_dir.items():
        reserved: set[str] = set()
        recs_sorted = sorted(recs, key=lambda r: r.path.name)

        for rec in recs_sorted:
            stem = build_target_stem(rec.dt, rec.device, rec.location)
            suffix = rec.path.suffix.lower()
            new_name = _find_free_name(directory, stem, suffix, reserved, source=rec.path)
            reserved.add(new_name)
            plan.append((rec.path, new_name))

    return plan


_SIDECAR_SUFFIXES = ('.xmp', '.XMP')


def execute_renames(
    plan: List[Tuple[Path, str]],
    on_progress: Callable[[int, int, str], None] = None,
) -> RenameResult:
    """
    Execute the rename plan.
    on_progress(current_index, total, current_filename)
    """
    result = RenameResult()
    total = len(plan)

    for idx, (src, new_name) in enumerate(plan):
        if on_progress:
            on_progress(idx, total, src.name)

        # Already correctly named
        if src.name == new_name:
            result.skipped_already_correct.append(src)
            continue

        dest = src.parent / new_name

        if dest.exists() and dest != src:
            result.errors.append((src, f"Target already exists: {dest.name}"))
            continue

        try:
            src.rename(dest)
            result.renamed.append((src, dest))

            # Rename companion sidecar files (XMP etc.)
            for sidecar_suffix in _SIDECAR_SUFFIXES:
                sidecar_src = src.with_suffix(sidecar_suffix)
                if sidecar_src.exists():
                    sidecar_dest = dest.with_suffix(sidecar_suffix.lower())
                    if not sidecar_dest.exists():
                        sidecar_src.rename(sidecar_dest)
                        result.renamed_sidecars.append((sidecar_src, sidecar_dest))
                    break  # only rename one (avoid double-renaming .xmp and .XMP)

        except OSError as e:
            result.errors.append((src, str(e)))

    return result
