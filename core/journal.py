"""
Rename journal: saves old→new mappings after each run so renames can be reversed.
Each run saves a timestamped file, e.g. .photo_renamer_journal_20260419_143022.json
in the root folder that was processed.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

JOURNAL_PREFIX = '.photo_renamer_journal_'
JOURNAL_GLOB   = '.photo_renamer_journal_*.json'


def _journal_path(root_folder: str) -> Path:
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    return Path(root_folder) / f"{JOURNAL_PREFIX}{timestamp}.json"


def save_journal(
    root_folder: str,
    renames: List[Tuple[Path, Path]],
    sidecars: List[Tuple[Path, Path]] = None,
) -> Path:
    """Save a timestamped journal of completed renames."""
    entries = [
        {'folder': str(src.parent), 'old': src.name, 'new': dst.name, 'type': 'main'}
        for src, dst in renames
    ]
    if sidecars:
        entries += [
            {'folder': str(src.parent), 'old': src.name, 'new': dst.name, 'type': 'sidecar'}
            for src, dst in sidecars
        ]
    data = {
        'renamed_at': datetime.now().isoformat(timespec='seconds'),
        'root_folder': root_folder,
        'entries': entries,
    }
    path = _journal_path(root_folder)
    path.write_text(json.dumps(data, indent=2), encoding='utf-8')
    return path


def load_journal(journal_path: Path) -> dict:
    return json.loads(journal_path.read_text(encoding='utf-8'))


def reverse_renames(journal_path: Path) -> Tuple[int, int, List[str]]:
    """
    Reverse all renames recorded in the journal (new → old).
    Both main files and sidecars are restored.
    Returns (success_count, skipped_count, error_messages).
    """
    data = load_journal(journal_path)
    entries = data.get('entries', [])

    success, skipped = 0, 0
    errors: List[str] = []

    for entry in entries:
        folder  = Path(entry['folder'])
        current  = folder / entry['new']
        original = folder / entry['old']

        if not current.exists():
            skipped += 1
            continue
        if original.exists():
            errors.append(f"Cannot restore {entry['old']} — file already exists")
            continue
        try:
            current.rename(original)
            success += 1
        except OSError as e:
            errors.append(f"{entry['new']}: {e}")

    return success, skipped, errors
