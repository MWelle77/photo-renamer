import sys
import os

# When running as a PyInstaller onefile bundle, add the extracted temp dir
# to sys.path so relative imports resolve correctly.
if getattr(sys, 'frozen', False):
    base = sys._MEIPASS  # type: ignore[attr-defined]
    if base not in sys.path:
        sys.path.insert(0, base)
    os.chdir(base)

from app import App

if __name__ == '__main__':
    app = App()
    app.mainloop()
