import multiprocessing
import sys
import os

# MUST be the very first call after imports.
# When PyInstaller bundles as a onefile exe on Windows, multiprocessing uses
# the "spawn" start method: each worker re-executes the frozen exe from scratch.
# freeze_support() detects that the process is a worker child and exits
# immediately, preventing every spawned worker from opening a new GUI window.
multiprocessing.freeze_support()

# When running as a PyInstaller onefile bundle, add the extracted temp dir
# to sys.path so relative imports resolve correctly.
if getattr(sys, 'frozen', False):
    base = sys._MEIPASS  # type: ignore[attr-defined]
    if base not in sys.path:
        sys.path.insert(0, base)
    os.chdir(base)

if __name__ == '__main__':
    from app import App
    app = App()
    app.mainloop()
