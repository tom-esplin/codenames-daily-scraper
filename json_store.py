from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_history(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def save_history(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def merge_day(
    path: Path,
    date_key: str,
    day_record: dict[str, Any],
) -> None:
    cur = load_history(path)
    order = list(cur.get("_order", [])) if isinstance(cur.get("_order"), list) else []
    if date_key not in order:
        order.append(date_key)
    cur["_order"] = order
    cur[date_key] = day_record
    save_history(path, cur)
