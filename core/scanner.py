import os
from pathlib import Path
from typing import Callable, Generator

from utils.formats import ALL_EXTENSIONS


def scan_folder(
    root: str,
    on_dir: Callable[[str], None] = None,
) -> Generator[Path, None, None]:
    """
    Walk root recursively and yield all media file paths.
    Calls on_dir(current_directory) before processing each directory.
    """
    for dirpath, _dirnames, filenames in os.walk(root):
        if on_dir:
            on_dir(dirpath)
        for name in filenames:
            if Path(name).suffix.lower() in ALL_EXTENSIONS:
                yield Path(dirpath) / name
