"""
OmniSupply Platform Server Launcher
Runs both the FastAPI Backend API and Web Frontend Dashboard.
"""

import sys
import io
from pathlib import Path

# Force UTF-8 on Windows consoles to prevent charmap encoding errors
if sys.platform == "win32":
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, "buffer"):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Ensure workspace root is in python path
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import uvicorn

if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("OmniSupply AI Multi-Agent Platform is Starting...")
    print("Web Frontend Dashboard: http://127.0.0.1:8000")
    print("Backend REST API Docs:  http://127.0.0.1:8000/docs")
    print("=" * 70 + "\n")
    uvicorn.run("src.api.main:app", host="127.0.0.1", port=8000, reload=False)
