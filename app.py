"""
Main application window.
"""

from __future__ import annotations

import os
import queue
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from core.journal import reverse_renames
from core.worker import MsgDone, MsgProgress, MsgStatus, RenameWorker
from settings import VIDEO_TZ_MODES, Settings, load_settings, save_settings
from utils.formats import VIDEO_EXTENSIONS


POLL_MS = 100  # how often to drain the worker queue (milliseconds)
from version import VERSION


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"Media File Renamer v{VERSION}")
        self.resizable(True, True)
        self.minsize(580, 420)
        self._worker: RenameWorker | None = None
        self._queue: queue.Queue = queue.Queue()
        self._after_id = None
        self._log_lines: list[str] = []
        self._settings: Settings = load_settings()

        self._build_ui()
        self._set_running(False)

    # ── UI construction ────────────────────────────────────────────────────

    def _build_ui(self):
        pad = dict(padx=10, pady=5)

        # ── Folder row ──
        folder_frame = ttk.Frame(self)
        folder_frame.pack(fill='x', **pad)

        ttk.Label(folder_frame, text="Folder:").pack(side='left')
        self._folder_var = tk.StringVar()
        ttk.Entry(folder_frame, textvariable=self._folder_var, width=50).pack(
            side='left', fill='x', expand=True, padx=(5, 5)
        )
        ttk.Button(folder_frame, text="Browse…", command=self._browse).pack(side='left')

        # ── Action row ──
        action_frame = ttk.Frame(self)
        action_frame.pack(fill='x', **pad)

        self._start_btn = ttk.Button(
            action_frame, text="Start Renaming", command=self._start
        )
        self._start_btn.pack(side='left')

        self._cancel_btn = ttk.Button(
            action_frame, text="Cancel", command=self._cancel, state='disabled'
        )
        self._cancel_btn.pack(side='left', padx=(6, 0))

        ttk.Button(action_frame, text="About", command=self._show_about).pack(side='right')
        ttk.Button(action_frame, text="Settings", command=self._show_settings).pack(side='right', padx=(0, 4))
        ttk.Button(action_frame, text="Reverse Rename…", command=self._reverse_rename).pack(side='right', padx=(0, 4))

        # ── Progress ──
        progress_frame = ttk.LabelFrame(self, text="Progress")
        progress_frame.pack(fill='x', **pad)

        self._status_var = tk.StringVar(value="Ready.")
        ttk.Label(progress_frame, textvariable=self._status_var, anchor='w').pack(
            fill='x', padx=6, pady=(4, 0)
        )

        self._progress = ttk.Progressbar(
            progress_frame, mode='indeterminate', length=400
        )
        self._progress.pack(fill='x', padx=6, pady=(4, 6))

        self._file_var = tk.StringVar(value="")
        ttk.Label(
            progress_frame, textvariable=self._file_var,
            anchor='w', foreground='gray'
        ).pack(fill='x', padx=6, pady=(0, 4))

        # ── Log ──
        log_frame = ttk.LabelFrame(self, text="Log")
        log_frame.pack(fill='both', expand=True, **pad)

        self._log = scrolledtext.ScrolledText(
            log_frame, height=10, state='disabled',
            font=('Consolas', 9), wrap='none'
        )
        self._log.pack(fill='both', expand=True, padx=4, pady=4)

        # ── Summary ──
        self._summary_frame = ttk.LabelFrame(self, text="Summary")
        self._summary_var = tk.StringVar(value="")
        ttk.Label(
            self._summary_frame, textvariable=self._summary_var,
            justify='left', anchor='w'
        ).pack(fill='x', padx=8, pady=6)

    # ── Controls ──────────────────────────────────────────────────────────

    def _reverse_rename(self):
        current = self._folder_var.get().strip()
        initialdir = current if Path(current).is_dir() else str(Path.home())
        journal_path = filedialog.askopenfilename(
            title="Select a rename journal to reverse",
            initialdir=initialdir,
            filetypes=[("Rename journal", "*.json"), ("All files", "*.*")],
        )
        if not journal_path:
            return
        journal_path = Path(journal_path)
        try:
            from core.journal import load_journal
            data = load_journal(journal_path)
            count = len(data.get('entries', []))
            renamed_at = data.get('renamed_at', 'unknown time')
            root = data.get('root_folder', '')
        except Exception as e:
            messagebox.showerror("Invalid journal", f"Could not read journal file:\n{e}")
            return

        if count == 0:
            messagebox.showinfo("Nothing to reverse", "The journal contains no rename entries.")
            return

        confirmed = messagebox.askyesno(
            "Reverse renames",
            f"This will restore {count} file(s) to their original names.\n\n"
            f"Renamed at:  {renamed_at}\n"
            f"Folder:  {root}\n\n"
            "Continue?",
        )
        if not confirmed:
            return

        success, skipped, errors = reverse_renames(journal_path)

        self._clear_log()
        self._append_log(f"Reverse rename complete.")
        self._append_log(f"  Restored:  {success} file(s)")
        if skipped:
            self._append_log(f"  Skipped (file not found):  {skipped}")
        for err in errors:
            self._append_log(f"  ERR  {err}")

        messagebox.showinfo(
            "Reverse complete",
            f"Restored: {success}   Skipped: {skipped}   Errors: {len(errors)}"
        )

    def _show_settings(self):
        dlg = tk.Toplevel(self)
        dlg.title("Settings")
        dlg.resizable(False, False)
        dlg.transient(self)
        dlg.grab_set()

        ttk.Label(dlg, text="Video timestamp timezone", font=('', 10, 'bold')).pack(
            anchor='w', padx=16, pady=(14, 4)
        )
        ttk.Label(
            dlg,
            text="Video files (MP4, MOV…) often store timestamps in UTC.\n"
                 "Choose how to convert them to local time in the filename.",
            justify='left', foreground='gray',
        ).pack(anchor='w', padx=16, pady=(0, 8))

        mode_var = tk.StringVar(value=self._settings.video_tz_mode)
        for key, label in VIDEO_TZ_MODES.items():
            ttk.Radiobutton(dlg, text=label, variable=mode_var, value=key).pack(
                anchor='w', padx=24, pady=2
            )

        def _save():
            self._settings.video_tz_mode = mode_var.get()
            save_settings(self._settings)
            dlg.destroy()

        btn_frame = ttk.Frame(dlg)
        btn_frame.pack(fill='x', padx=16, pady=(12, 14))
        ttk.Button(btn_frame, text="Cancel", command=dlg.destroy).pack(side='right')
        ttk.Button(btn_frame, text="Save", command=_save).pack(side='right', padx=(0, 6))

    def _collect_folder_offsets(self, root: str) -> dict[str, int]:
        """For ask_folder mode: scan for video-containing folders and ask user for each."""
        video_folders = []
        for dirpath, _, filenames in os.walk(root):
            if any(Path(f).suffix.lower() in VIDEO_EXTENSIONS for f in filenames):
                video_folders.append(dirpath)

        offsets: dict[str, int] = {}
        for folder in sorted(video_folders):
            result = self._ask_tz_for_folder(folder)
            if result is not None:
                offsets[str(Path(folder))] = result  # normalize to match Path-based lookup
        return offsets

    def _ask_tz_for_folder(self, folder: str) -> int | None:
        """Show a dialog asking for UTC offset for a folder. Returns hours or None (keep UTC)."""
        dlg = tk.Toplevel(self)
        dlg.title("Video Timezone")
        dlg.resizable(False, False)
        dlg.transient(self)
        dlg.grab_set()
        result: list[int | None] = [None]

        name = Path(folder).name or folder
        ttk.Label(dlg, text=f"Videos found in:  {name}", font=('', 10, 'bold')).pack(
            padx=16, pady=(14, 4)
        )
        ttk.Label(
            dlg,
            text="These videos store time in UTC. What timezone were you in?\n"
                 "Examples:  +1 Rome/Paris,  +2 Helsinki,  -5 New York,  0 London",
            justify='center', foreground='gray',
        ).pack(padx=16, pady=(0, 10))

        spin_frame = ttk.Frame(dlg)
        spin_frame.pack(pady=(0, 10))
        ttk.Label(spin_frame, text="UTC offset (hours):").pack(side='left')
        offset_var = tk.IntVar(value=0)
        ttk.Spinbox(spin_frame, from_=-12, to=14, textvariable=offset_var, width=5).pack(
            side='left', padx=(8, 0)
        )

        def _apply():
            result[0] = offset_var.get()
            dlg.destroy()

        btn_frame = ttk.Frame(dlg)
        btn_frame.pack(pady=(0, 14))
        ttk.Button(btn_frame, text="Keep UTC", command=dlg.destroy).pack(side='left', padx=6)
        ttk.Button(btn_frame, text="Apply", command=_apply).pack(side='left', padx=6)

        dlg.wait_window(dlg)
        return result[0]

    def _show_about(self):
        messagebox.showinfo(
            "About Media File Renamer",
            f"Media File Renamer  v{VERSION}\n"
            "Copyright © 2026 Michael C. Welle\n"
            "https://mcwelle.com/\n"
            "Released under the GNU General Public License v3 (GPL-3.0)\n"
            "──────────────────────────────\n\n"
            "Renames your photos and videos so every file gets a name based\n"
            "on when it was taken — for example:\n\n"
            "    20240315_143022_IPHONE15.jpg\n\n"
            "Files sort in chronological order automatically in any folder,\n"
            "regardless of which camera or device they came from.\n\n"
            "How to use it:\n"
            "  1. Click Browse… and choose the folder with your media.\n"
            "  2. Click Start Renaming.\n"
            "  3. Done! All subfolders are processed automatically.\n\n"
            "Supported formats:\n"
            "  Images — JPG, PNG, HEIC, TIFF, CR2, NEF, ARW, DNG and more\n"
            "  Videos — MP4, MOV, AVI, MKV, MTS and more\n\n"
            "Date is read from file metadata (EXIF/video tags). If no metadata\n"
            "is found, the date is extracted from the filename itself —\n"
            "useful for WhatsApp photos, screenshots, and similar files.\n\n"
            "Files that cannot be dated are left completely unchanged.\n"
            "No files are ever deleted.\n\n"
            "Reverse Rename:\n"
            "After every run a journal is saved in the processed folder.\n"
            "Use Reverse Rename… to restore all files to their original names.\n\n"
            "Video Timezone (Settings):\n"
            "Videos often store time in UTC. You can choose to convert it\n"
            "to local time — either automatically using nearby photos as a\n"
            "reference, or by entering the UTC offset manually per folder.",
        )

    def _browse(self):
        folder = filedialog.askdirectory(title="Select folder with media files")
        if folder:
            self._folder_var.set(folder)

    def _start(self):
        folder = self._folder_var.get().strip()
        if not folder:
            messagebox.showwarning("No folder", "Please select a folder first.")
            return
        if not Path(folder).is_dir():
            messagebox.showerror("Invalid folder", f"Not a valid directory:\n{folder}")
            return

        self._log_lines.clear()
        self._clear_log()
        self._summary_frame.pack_forget()
        self._set_running(True)

        self._queue = queue.Queue()

        tz_mode = self._settings.video_tz_mode
        tz_offsets: dict[str, int] = {}
        if tz_mode == 'ask_folder':
            tz_offsets = self._collect_folder_offsets(folder)

        self._worker = RenameWorker(folder, self._queue, tz_mode=tz_mode, tz_offsets=tz_offsets)
        self._worker.start()
        self._after_id = self.after(POLL_MS, self._poll)

    def _cancel(self):
        if self._worker:
            self._worker.stop()
        self._set_running(False)
        self._status_var.set("Cancelled.")

    def _set_running(self, running: bool):
        state_start = 'disabled' if running else 'normal'
        state_cancel = 'normal' if running else 'disabled'
        self._start_btn.config(state=state_start)
        self._cancel_btn.config(state=state_cancel)
        if running:
            self._progress.config(mode='indeterminate')
            self._progress.start(12)
        else:
            self._progress.stop()
            self._progress.config(mode='determinate', value=0)

    # ── Queue polling ──────────────────────────────────────────────────────

    def _poll(self):
        try:
            while True:
                msg = self._queue.get_nowait()
                if isinstance(msg, MsgStatus):
                    self._status_var.set(msg.text)
                elif isinstance(msg, MsgProgress):
                    self._update_progress(msg)
                elif isinstance(msg, MsgDone):
                    self._on_done(msg)
                    return  # stop polling
        except queue.Empty:
            pass
        self._after_id = self.after(POLL_MS, self._poll)

    def _update_progress(self, msg: MsgProgress):
        if msg.total > 0:
            self._file_var.set(f"  {msg.current + 1} / {msg.total}  —  {msg.filename}")
            pct = int(100 * msg.current / msg.total)
            if self._progress['mode'] == 'indeterminate':
                self._progress.stop()
                self._progress.config(mode='determinate')
            self._progress['value'] = pct
        else:
            self._file_var.set(f"  {msg.filename}")

    def _on_done(self, msg: MsgDone):
        self._set_running(False)
        result = msg.result
        no_meta = msg.no_metadata

        # Build log
        for src, dest in result.renamed:
            self._append_log(f"OK   {src.name}  →  {dest.name}")
        for path in result.skipped_already_correct:
            self._append_log(f"SKIP {path.name}  (already correct)")
        for path in no_meta:
            self._append_log(f"NOMETA {path.name}")
        for path, err in result.errors:
            self._append_log(f"ERR  {path.name}  — {err}")
        for path, err in msg.extraction_errors:
            self._append_log(f"WARN {path.name}  — metadata error: {err}")

        # Summary
        n_renamed = len(result.renamed)
        n_correct = len(result.skipped_already_correct)
        n_no_meta = len(no_meta)
        n_errors = len(result.errors)

        summary = (
            f"Renamed:           {n_renamed} file(s)\n"
            f"Already correct:   {n_correct} file(s)\n"
            f"No metadata:       {n_no_meta} file(s)\n"
            f"Errors:            {n_errors} file(s)"
        )
        self._summary_var.set(summary)
        self._summary_frame.pack(fill='x', padx=10, pady=5)

        if msg.journal_path:
            self._append_log(f"Journal saved → {msg.journal_path}")

        self._status_var.set("Done.")
        self._file_var.set("")
        self._progress['value'] = 100

        # Show a compact popup too
        msg_text = (
            f"Renamed: {n_renamed}   |   "
            f"No metadata: {n_no_meta}   |   "
            f"Errors: {n_errors}"
        )
        messagebox.showinfo("Renaming complete", msg_text)

    # ── Log helpers ────────────────────────────────────────────────────────

    def _append_log(self, text: str):
        self._log_lines.append(text)
        self._log.config(state='normal')
        self._log.insert('end', text + '\n')
        self._log.see('end')
        self._log.config(state='disabled')

    def _clear_log(self):
        self._log.config(state='normal')
        self._log.delete('1.0', 'end')
        self._log.config(state='disabled')
