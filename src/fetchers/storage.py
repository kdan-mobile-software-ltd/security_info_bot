from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from src.models import IntelItem
from src.utils.logging import log

DATA_DIR = Path(__file__).parent.parent / "data"


def _ensure_data_dir() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR


def save_items(items: list[IntelItem], source: str, tag: str | None = None) -> Path:
    _ensure_data_dir()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if tag:
        filename = f"{source}_{tag}_{timestamp}.json"
    else:
        filename = f"{source}_{timestamp}.json"
    path = DATA_DIR / filename

    data = {
        "source": source,
        "fetched_at": datetime.now().isoformat(),
        "count": len(items),
        "items": [item.to_dict() for item in items],
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Saved %d items to %s", len(items), path)
    return path


def load_items(path: str | Path) -> list[IntelItem]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Data file not found: {path}")

    data = json.loads(path.read_text(encoding="utf-8"))
    items = [IntelItem.from_dict(d) for d in data["items"]]
    log.info("Loaded %d items from %s (fetched at %s)", len(items), path, data.get("fetched_at", "unknown"))
    return items


def list_saved_files(source: str | None = None) -> list[Path]:
    if not DATA_DIR.exists():
        return []
    files = sorted(DATA_DIR.glob("*.json"), reverse=True)
    if source:
        files = [f for f in files if f.name.startswith(source)]
    return files
