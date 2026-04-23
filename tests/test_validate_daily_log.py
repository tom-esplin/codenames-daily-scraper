from __future__ import annotations

import json
from pathlib import Path

import pytest

from validate_daily_log import validate_after_pipeline, validate_day_record


def _base_round(
    n: int, clue: str, count: int, grid: list[str], targets: list[str]
) -> dict:
    return {
        "round": n,
        "language": "en",
        "clue": clue,
        "count": count,
        "grid": grid,
        "target_words": targets,
        "stats": {"perfectRate": 0.5},
    }


def _grid16(prefix: str = "W") -> list[str]:
    return [f"{prefix}{i}" for i in range(16)]


def test_valid_four_rounds() -> None:
    g = _grid16("A")
    g2 = _grid16("B")
    g3 = _grid16("C")
    g4 = _grid16("D")
    rec = {
        "date": "2026-01-01",
        "rounds": [
            _base_round(1, "C1", 4, g, g[:4]),
            _base_round(2, "C2", 3, g2, g2[:3]),
            _base_round(3, "C3", 5, g3, g3[:5]),
            _base_round(4, "C4", 3, g4, g4[:3]),
        ],
    }
    assert validate_day_record(rec) == []


def test_requires_three_rounds_without_round4_targets() -> None:
    g = _grid16("A")
    g2 = _grid16("B")
    g3 = _grid16("C")
    g4 = _grid16("D")
    rec = {
        "date": "2026-01-01",
        "rounds": [
            _base_round(1, "C1", 4, g, g[:4]),
            _base_round(2, "C2", 3, g2, g2[:3]),
            _base_round(3, "C3", 5, g3, g3[:5]),
            {**_base_round(4, "C4", 3, g4, []), "target_words": []},
        ],
    }
    assert any("4" in e and "target" in e.lower() for e in validate_day_record(rec))


def test_rounds_123_only_allows_empty_round4() -> None:
    g = _grid16("A")
    g2 = _grid16("B")
    g3 = _grid16("C")
    g4 = _grid16("D")
    rec = {
        "date": "2026-01-01",
        "rounds": [
            _base_round(1, "C1", 4, g, g[:4]),
            _base_round(2, "C2", 3, g2, g2[:3]),
            _base_round(3, "C3", 5, g3, g3[:5]),
            {**_base_round(4, "C4", 3, g4, []), "target_words": []},
        ],
    }
    assert (
        validate_day_record(rec, require_targets_rounds=frozenset({1, 2, 3})) == []
    )


def test_target_not_on_grid() -> None:
    g = _grid16("A")
    rec = {
        "date": "2026-01-01",
        "rounds": [
            _base_round(1, "C1", 4, g, ["NOTONBOARD", g[1], g[2], g[3]]),
            _base_round(2, "C2", 3, _grid16("B"), _grid16("B")[:3]),
            _base_round(3, "C3", 5, _grid16("C"), _grid16("C")[:5]),
            _base_round(4, "C4", 3, _grid16("D"), _grid16("D")[:3]),
        ],
    }
    errs = validate_day_record(rec)
    assert any("NOTONBOARD" in e or "not on the board" in e for e in errs)


def test_wrong_round_index() -> None:
    g = _grid16("A")
    r = _base_round(1, "C1", 4, g, g[:4])
    r["round"] = 2
    rec = {"date": "2026-01-01", "rounds": [r, r, r, r]}
    errs = validate_day_record(rec)
    assert any("'round' must be" in e for e in errs)


def test_duplicate_targets() -> None:
    g = _grid16("A")
    rec = {
        "date": "2026-01-01",
        "rounds": [
            _base_round(1, "C1", 4, g, [g[0], g[0], g[2], g[3]]),
            _base_round(2, "C2", 3, _grid16("B"), _grid16("B")[:3]),
            _base_round(3, "C3", 5, _grid16("C"), _grid16("C")[:5]),
            _base_round(4, "C4", 3, _grid16("D"), _grid16("D")[:3]),
        ],
    }
    assert any("duplicate" in e.lower() for e in validate_day_record(rec))


def test_validate_after_pipeline_clues_only(tmp_path: Path) -> None:
    p = tmp_path / "x.json"
    p.write_text(
        json.dumps(
            {
                "_order": ["2026-01-01"],
                "2026-01-01": {
                    "date": "2026-01-01",
                    "rounds": [
                        {
                            "round": 1,
                            "language": "en",
                            "clue": "X",
                            "count": 4,
                            "grid": _grid16("A"),
                            "target_words": [],
                            "stats": {},
                        },
                        {
                            "round": 2,
                            "language": "en",
                            "clue": "X",
                            "count": 3,
                            "grid": _grid16("B"),
                            "target_words": [],
                            "stats": {},
                        },
                        {
                            "round": 3,
                            "language": "en",
                            "clue": "X",
                            "count": 5,
                            "grid": _grid16("C"),
                            "target_words": [],
                            "stats": {},
                        },
                        {
                            "round": 4,
                            "language": "en",
                            "clue": "X",
                            "count": 3,
                            "grid": _grid16("D"),
                            "target_words": [],
                            "stats": {},
                        },
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    assert validate_after_pipeline(p, "2026-01-01", clues_only=True, fill_round4=False) == []


def test_frozen_repo_data_file_if_present() -> None:
    data = Path(__file__).resolve().parent.parent / "data" / "codenames_daily.json"
    if not data.is_file():
        pytest.skip("no data/codenames_daily.json in repo")
    text = data.read_text(encoding="utf-8")
    d = json.loads(text)
    order = d.get("_order")
    if not order:
        pytest.skip("no _order in data file")
    k = order[-1]
    rec = d[k]
    assert validate_day_record(rec) == []
