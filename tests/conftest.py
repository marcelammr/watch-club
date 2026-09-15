import os
from pathlib import Path

os.environ.setdefault("SECRET_KEY", "test-secret")
_db = Path(__file__).resolve().parent / "test.sqlite"
if _db.exists():
    _db.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{_db}"
