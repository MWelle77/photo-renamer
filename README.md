# Media File Renamer

A simple desktop app that renames your photos and videos based on when they were taken, so your files sort in chronological order automatically — no matter which camera or device they came from.

**By [Michael C. Welle](https://mcwelle.com/) — released under [GPL-3.0](LICENSE)**

---

## What it does

Instead of cryptic names like `IMG_4823.JPG` or `GX010110.MP4`, every file gets a clean, sortable name:

```
20240315_143022_IPHONE15_PRO.jpg
20240315_143045_GOPRO.mp4
20240315_150010_SAMSUNG_GALAXY_ITALY_ROME.jpg
```

Format: `YYYYMMDDHHMMSS_DEVICE.ext` or `YYYYMMDDHHMMSS_DEVICE_LOCATION.ext`

- Works on photos **and** videos
- Processes all subfolders automatically
- Optionally appends GPS-based location to the filename (fully offline)
- Files without date metadata are left unchanged — nothing is ever deleted
- Duplicate timestamps get a `_2`, `_3` suffix automatically
- Every run saves a journal so renames can be fully reversed

---

## Supported formats

| Type   | Formats |
|--------|---------|
| Images | JPG, JPEG, PNG, HEIC, HEIF, TIFF, CR2, NEF, ARW, DNG, ORF, RW2, BMP, GIF, WebP |
| Videos | MP4, MOV, AVI, MKV, M4V, WMV, 3GP, MTS, M2TS, FLV, TS |

---

## Download

Download the latest Windows installer from the [Releases](../../releases) page — no Python required.

---

## Running from source

**Requirements:** Python 3.10+

```bash
git clone https://github.com/MWelle77/photo-renamer.git
cd photo-renamer
pip install -r requirements.txt
python main.py
```

---

## Building the exe

```bash
python -m PyInstaller build/photo_renamer.spec --clean --noconfirm
```

Output: `dist/MediaFileRenamer.exe`

---

## Features

### Date extraction

The date is read from file metadata (EXIF for images, container tags for videos). If no metadata is found, the date is parsed from the filename itself — useful for WhatsApp exports, screenshots, and similar files. Files that cannot be dated are left completely unchanged.

### Location in filename

When GPS coordinates are present, the location can be appended to the filename:

| Mode | Example |
|------|---------|
| Country only | `20240315_143022_IPHONE15_ITALY.jpg` |
| Country + City | `20240315_143022_IPHONE15_ITALY_ROME.jpg` |
| Ask per folder | You type a label for each folder — applied to files without GPS |

Location lookup works **fully offline** using a bundled database. Enable **Infer location** to extend the location to nearby files in the same folder that have no GPS data.

### Reverse Rename

After every run a journal file is saved alongside your photos. Use **Reverse Rename…** to restore all files to their original names at any time.

### Video timezone

Video files (MP4, MOV, etc.) often store timestamps in UTC rather than local time. In **Settings** you can choose how to handle this:

| Option | Description |
|--------|-------------|
| Keep as UTC | No conversion — use timestamp as-is (default) |
| Infer from closest photo | Compares nearby photos (which store local time) to compute the offset automatically |
| Ask per folder | Prompts you for a UTC offset for each folder that contains videos |

---

## License

Copyright © 2026 Michael C. Welle  
Licensed under the [GNU General Public License v3.0](LICENSE)
