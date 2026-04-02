"""
Background thread that scans and renames files, posting progress to a Queue.
The tkinter main thread polls the queue with root.after().
"""

from __future__ import annotations

import queue
import threading
from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Optional

from core.metadata import extract_metadata
from core.renamer import FileRecord, RenameResult, execute_renames, plan_renames
from core.scanner import scan_folder
from utils.formats import VIDEO_EXTENSIONS


# ── Message types posted to the queue ─────────────────────────────────────

@dataclass
class MsgStatus:
    text: str

@dataclass
class MsgProgress:
    current: int
    total: int
    filename: str

@dataclass
class MsgDone:
    result: RenameResult
    no_metadata: list


def _apply_video_tz(records: list, mode: str, folder_offsets: dict) -> None:
    """Adjust datetime on video FileRecords according to the chosen timezone mode."""
    if mode == 'ask_folder':
        for rec in records:
            if rec.path.suffix.lower() not in VIDEO_EXTENSIONS:
                continue
            hours = folder_offsets.get(str(rec.path.parent))
            if hours and rec.dt is not None:
                rec.dt = rec.dt + timedelta(hours=hours)

    elif mode == 'infer_image':
        by_folder: dict = defaultdict(lambda: {'images': [], 'videos': []})
        for rec in records:
            key = 'videos' if rec.path.suffix.lower() in VIDEO_EXTENSIONS else 'images'
            by_folder[str(rec.path.parent)][key].append(rec)

        for groups in by_folder.values():
            imgs = [r for r in groups['images'] if r.dt is not None]
            vids = [r for r in groups['videos'] if r.dt is not None]
            if not imgs or not vids:
                continue
            for vid_rec in vids:
                closest = min(imgs, key=lambda r: abs((r.dt - vid_rec.dt).total_seconds()))
                offset_hours = round((closest.dt - vid_rec.dt).total_seconds() / 3600)
                if -14 <= offset_hours <= 14:  # sanity check
                    vid_rec.dt = vid_rec.dt + timedelta(hours=offset_hours)


class RenameWorker(threading.Thread):
    def __init__(self, folder: str, out_queue: queue.Queue,
                 tz_mode: str = 'utc', tz_offsets: dict = None):
        super().__init__(daemon=True)
        self.folder = folder
        self.q = out_queue
        self.tz_mode = tz_mode
        self.tz_offsets = tz_offsets or {}
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def run(self):
        try:
            self._run()
        except Exception as e:
            self.q.put(MsgStatus(f"Unexpected error: {e}"))
            self.q.put(MsgDone(result=RenameResult(), no_metadata=[]))

    def _run(self):
        q = self.q

        # ── Phase 1: scan ──────────────────────────────────────────────
        q.put(MsgStatus("Scanning for media files..."))
        files = []
        for path in scan_folder(
            self.folder,
            on_dir=lambda d: q.put(MsgStatus(f"Scanning: {d}")),
        ):
            if self._stop_event.is_set():
                return
            files.append(path)

        total = len(files)
        if total == 0:
            q.put(MsgStatus("No media files found."))
            q.put(MsgDone(result=RenameResult(), no_metadata=[]))
            return

        q.put(MsgStatus(f"Found {total} files. Reading metadata..."))

        # ── Phase 2: read metadata ─────────────────────────────────────
        records = []
        no_metadata = []

        for idx, path in enumerate(files):
            if self._stop_event.is_set():
                return
            q.put(MsgProgress(idx, total, path.name))
            dt, device = extract_metadata(path)
            if dt is None:
                no_metadata.append(path)
            else:
                records.append(FileRecord(path=path, dt=dt, device=device))

        # ── Phase 2.5: timezone adjustment for videos ─────────────────
        if self.tz_mode != 'utc':
            q.put(MsgStatus("Adjusting video timestamps for timezone..."))
            _apply_video_tz(records, self.tz_mode, self.tz_offsets)

        # ── Phase 3: build plan ────────────────────────────────────────
        q.put(MsgStatus("Building rename plan..."))
        plan = plan_renames(records)

        # ── Phase 4: execute renames ───────────────────────────────────
        q.put(MsgStatus(f"Renaming {len(plan)} files..."))

        def on_progress(idx: int, total_r: int, name: str):
            if self._stop_event.is_set():
                raise InterruptedError
            q.put(MsgProgress(idx, total_r, name))

        try:
            result = execute_renames(plan, on_progress=on_progress)
        except InterruptedError:
            return

        q.put(MsgDone(result=result, no_metadata=no_metadata))
