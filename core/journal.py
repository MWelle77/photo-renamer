"""
Rename journal: saves old→new mappings after each run so renames can be reversed.
The journal is stored as .photo_renamer_journal.json in the root folder processed.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

JOURNAL_FILENAME = '.photo_renamer_journal.json'


def save_journal(root_folder: str, renames: List[Tuple[Path, Path]]) -> Path:
    """Save a journal of completed renames. Overwrites any previous journal in the folder."""
    entries = [
        {'folder': str(src.parent), 'old': src.name, 'new': dst.name}
        for src, dst in renames
    ]
    data = {
        'renamed_at': datetime.now().isoformat(timespec='seconds'),
        'root_folder': root_folder,
        'entries': entries,
    }
    journal_path = Path(root_folder) / JOURNAL_FILENAME
    journal_path.write_text(json.dumps(data, indent=2), encoding='utf-8')
    return journal_path


def load_journal(journal_path: Path) -> dict:
    return json.loads(journal_path.read_text(encoding='utf-8'))


def reverse_renames(journal_path: Path) -> Tuple[int, int, List[str]]:
    """
    Reverse all renames recorded in the journal (new → old).
    Returns (success_count, skipped_count, error_messages).
    """
    data = load_journal(journal_path)
    entries = data.get('entries', [])

    success, skipped = 0, 0
    errors: List[str] = []

    for entry in entries:
        folder = Path(entry['folder'])
        current = folder / entry['new']   # the renamed file
        original = folder / entry['old']  # where it should go back

        if not current.exists():
            skipped += 1
            continue
        if original.exists():
            errors.append(f"Cannot restore {entry['old']} — a file with that name already exists")
            continue
        try:
            current.rename(original)
            success += 1
        except OSError as e:
            errors.append(f"{entry['new']}: {e}")

    return success, skipped, errors
