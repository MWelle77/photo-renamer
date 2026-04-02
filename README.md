# Media File Renamer

A simple desktop app that renames your photos and videos based on when they were taken, so your files sort in chronological order automatically — no matter which camera or device they came from.

**By [Michael C. Welle](https://mcwelle.com/) — released under [GPL-3.0](LICENSE)**

---

## What it does

Instead of cryptic names like `IMG_4823.JPG` or `GX010110.MP4`, every file gets a clean, sortable name:

```
20240315_143022_IPHONE15_PRO.jpg
20240315_143045_GOPRO.mp4
```

Format: `YYYYMMDDHHMMSS_DEVICE.ext`

- Works on photos **and** videos
- Processes all subfolders automatically
- Files without date metadata are left unchanged (never deleted)
- Duplicate timestamps get a `_2`, `_3` suffix automatically

---

## Supported formats

| Type   | Formats |
|--------|---------|
| Images | JPG, JPEG, PNG, HEIC, HEIF, TIFF, CR2, NEF, ARW, DNG, ORF, RW2, BMP, GIF, WebP |
| Videos | MP4, MOV, AVI, MKV, M4V, WMV, 3GP, MTS, M2TS, FLV, TS |

---

## Download

Download the latest Windows `.exe` from the [Releases](../../releases) page — no installation or Python required.

---

## Running from source

**Requirements:** Python 3.10+

```bash
git clone https://github.com/YOUR_USERNAME/photo-renamer.git
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

## Settings

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
