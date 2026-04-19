import json
import os
from dataclasses import dataclass, asdict
from pathlib import Path

VIDEO_TZ_MODES = {
    'utc':         'Keep as UTC (no conversion)',
    'infer_image': 'Infer from closest photo in same folder',
    'ask_folder':  'Ask me for each folder that contains videos',
}

LOCATION_MODES = {
    'off':        'Off (no location in filename)',
    'country':    'Country only  (e.g. _ITALY)',
    'city':       'Country + City  (e.g. _ITALY_ROME)',
    'ask_folder': 'Ask me per folder  (manual fallback when no GPS)',
}


def _settings_dir() -> Path:
    appdata = os.environ.get('APPDATA')
    if appdata:
        return Path(appdata) / 'Media File Renamer'
    return Path.home() / '.media_file_renamer'


SETTINGS_FILE = _settings_dir() / 'settings.json'


@dataclass
class Settings:
    video_tz_mode: str = 'utc'
    location_mode: str = 'off'
    location_infer: bool = False


def load_settings() -> Settings:
    try:
        raw = json.loads(SETTINGS_FILE.read_text(encoding='utf-8'))
        valid = {k: v for k, v in raw.items() if k in Settings.__dataclass_fields__}
        return Settings(**valid)
    except Exception:
        return Settings()


def save_settings(s: Settings) -> None:
    try:
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(asdict(s), indent=2), encoding='utf-8')
    except Exception:
        pass
