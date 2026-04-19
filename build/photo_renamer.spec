# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for MediaFileRenamer
# Run from the repo root:
#   pyinstaller build/photo_renamer.spec --clean --noconfirm
#
import os
import sys
from PyInstaller.utils.hooks import collect_all, collect_data_files

# ── pillow-heif: collect native binaries + data ──────────────────────────
try:
    heif_datas, heif_binaries, heif_hidden = collect_all('pillow_heif')
except Exception:
    heif_datas, heif_binaries, heif_hidden = [], [], []

# ── reverse_geocoder: collect data files (cities CSV) ────────────────────
try:
    rg_datas, rg_binaries, rg_hidden = collect_all('reverse_geocoder')
except Exception:
    rg_datas, rg_binaries, rg_hidden = [], [], []

# ── pymediainfo: bundle libmediainfo.dll (Windows) ───────────────────────
mediainfo_binaries = []
try:
    import pymediainfo
    dll_dir = os.path.dirname(pymediainfo.__file__)
    dll_path = os.path.join(dll_dir, 'libmediainfo.dll')
    if os.path.isfile(dll_path):
        mediainfo_binaries.append((dll_path, '.'))
except Exception:
    pass

block_cipher = None

a = Analysis(
    ['../main.py'],
    pathex=['..'],          # repo root so "from core.xxx" and "from utils.xxx" resolve
    binaries=mediainfo_binaries + heif_binaries + rg_binaries,
    datas=heif_datas + rg_datas + [('../assets/icon.ico', 'assets')],
    hiddenimports=[
        # exifread dynamically imports makernote submodules
        'exifread',
        'exifread.tags',
        'exifread.tags.makernote',
        'exifread.tags.makernote.canon',
        'exifread.tags.makernote.casio',
        'exifread.tags.makernote.fujifilm',
        'exifread.tags.makernote.nikon',
        'exifread.tags.makernote.olympus',
        'exifread.tags.makernote.apple',
        'exifread.tags.makernote.sony',
        # tkinter internals
        'tkinter',
        'tkinter.ttk',
        'tkinter.filedialog',
        'tkinter.messagebox',
        'tkinter.scrolledtext',
        # PIL
        'PIL._tkinter_finder',
        'PIL.ExifTags',
        'reverse_geocoder',
        'scipy',
        'scipy.spatial',
        'scipy.spatial.cKDTree',
    ] + heif_hidden + rg_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='MediaFileRenamer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # set True if UPX is installed and AV is not a concern
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,      # no black cmd window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='../assets/icon.ico',
    onefile=True,
)
