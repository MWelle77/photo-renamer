import json
from dataclasses import dataclass, asdict
from pathlib import Path

SETTINGS_FILE = Path.home() / '.photo_renamer_settings.json'

VIDEO_TZ_MODES = {
    'utc':         'Keep as UTC (no conversion)',
    'infer_image': 'Infer from closest photo in same folder',
    'ask_folder':  'Ask me for each folder that contains videos',
}


@dataclass
class Settings:
    video_tz_mode: str = 'utc'


def load_settings() -> Settings:
    try:
        raw = json.loads(SETTINGS_FILE.read_text(encoding='utf-8'))
        valid = {k: v for k, v in raw.items() if k in Settings.__dataclass_fields__}
        return Settings(**valid)
    except Exception:
        return Settings()


def save_settings(s: Settings) -> None:
    try:
        SETTINGS_FILE.write_text(json.dumps(asdict(s), indent=2), encoding='utf-8')
    except Exception:
        pass
