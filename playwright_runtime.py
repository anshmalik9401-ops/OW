import os
import sys
from pathlib import Path


def configure_browser_path():
    if getattr(sys, "frozen", False):
        base_dir = Path(sys.executable).resolve().parent
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(base_dir / "ms-playwright")
    else:
        base_dir = Path(__file__).resolve().parent
        browser_dir = base_dir / "ms-playwright"
        if browser_dir.is_dir():
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(browser_dir)
