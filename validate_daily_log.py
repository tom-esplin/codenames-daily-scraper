"""
Validate that a merged daily record has four well-formed rounds.

Used after collect / fill to fail fast if the log is incomplete or inconsistent.
Can be run as a CLI or imported from tests.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _norm_word(w: str) -> str:
    return str(w).strip().upper()


def validate_day_record(
    rec: dict[str, Any],
    *,
    require_target_words: bool = True,
    require_targets_rounds: frozenset[int] | None = None,
) -> list[str]:
    """
    Return a list of error messages. Empty list means the record is valid.

    When `require_target_words` is True (default), each round in `require_targets_rounds`
    (default: {1,2,3,4}) must have `len(target_words) == count`, targets on grid, no
    dups. Rounds not in the set are still checked for structure (clue, count, 16 cards)
    but not for filled targets. Use ``frozenset({1, 2, 3})`` when round 4 is
    intentionally empty until `fill_round4` runs.

    When `require_target_words` is False, checks structure only (e.g. --clues-only).
    """
    if require_targets_rounds is None and require_target_words:
        req_rounds = frozenset({1, 2, 3, 4})
    elif not require_target_words:
        req_rounds: frozenset[int] = frozenset()
    else:
        req_rounds = require_targets_rounds
    errs: list[str] = []
    if not isinstance(rec, dict):
        return ["record must be a JSON object"]
    d = rec.get("date")
    if not d or not isinstance(d, str) or not d.strip():
        errs.append("'date' must be a non-empty string (YYYY-MM-DD)")

    rounds = rec.get("rounds")
    if not isinstance(rounds, list) or len(rounds) != 4:
        n = len(rounds) if isinstance(rounds, list) else 0
        errs.append(f"expected exactly 4 'rounds', found {n}")
        if not isinstance(rounds, list) or not rounds:
            return errs

    for i, r in enumerate(rounds):
        label = f"rounds[{i}] (1-based round {i + 1})"
        if not isinstance(r, dict):
            errs.append(f"{label} must be an object")
            continue
        rnum = r.get("round")
        if rnum != i + 1:
            errs.append(
                f"{label}: 'round' must be {i + 1}, got {rnum!r}"
            )
        clue = r.get("clue")
        if not isinstance(clue, str) or not clue.strip():
            errs.append(f"{label}: missing or empty 'clue'")
        count = r.get("count")
        if not isinstance(count, int) or count < 1:
            errs.append(
                f"{label}: 'count' must be a positive int, got {count!r}"
            )
        grid = r.get("grid")
        norm_grid: list[str] = []
        gset: set[str] = set()
        if not isinstance(grid, list) or len(grid) != 16:
            glen = len(grid) if isinstance(grid, list) else 0
            errs.append(f"{label}: 'grid' must be a list of 16 words, got length {glen}")
        else:
            norm_grid = [_norm_word(x) for x in grid if str(x).strip()]
            gset = set(norm_grid)
            if len(norm_grid) != 16 or len(gset) != 16:
                errs.append(
                    f"{label}: grid must have 16 distinct non-empty words"
                )
        targets = r.get("target_words")
        if not isinstance(targets, list):
            errs.append(f"{label}: 'target_words' must be a list")
            continue
        tnorm = [_norm_word(x) for x in targets if str(x).strip()]
        round_num = i + 1
        need_t = require_target_words and (round_num in req_rounds)
        if need_t:
            if isinstance(count, int) and count >= 1 and len(tnorm) != count:
                errs.append(
                    f"{label}: len(target_words) is {len(tnorm)}, expected {count} to match 'count'"
                )
            if len(tnorm) != len(set(tnorm)):
                errs.append(f"{label}: 'target_words' must not contain duplicates")
            if gset:
                for w in tnorm:
                    if w not in gset:
                        errs.append(
                            f"{label}: target {w!r} is not on the board grid"
                        )
        elif require_target_words and round_num not in req_rounds:
            if tnorm and isinstance(count, int) and count >= 1 and len(tnorm) != count:
                errs.append(
                    f"{label}: if target_words is non-empty, len must be {count}, got {len(tnorm)}"
                )
        else:
            if tnorm and isinstance(count, int) and count >= 1 and len(tnorm) != count:
                errs.append(
                    f"{label}: if target_words present, len must be {count}, got {len(tnorm)}"
                )

    return errs


def validate_after_pipeline(
    path: Path, date_key: str, *, clues_only: bool, fill_round4: bool
) -> list[str]:
    """Select rules after `collect_daily` (optionally with `--fill-round-4`)."""
    if clues_only:
        return validate_file(
            path, date_key=date_key, require_target_words=False, require_targets_rounds=None
        )
    if fill_round4:
        return validate_file(
            path, date_key=date_key, require_target_words=True, require_targets_rounds=None
        )
    return validate_file(
        path,
        date_key=date_key,
        require_target_words=True,
        require_targets_rounds=frozenset({1, 2, 3}),
    )


def load_day_from_file(path: Path, date_key: str | None) -> tuple[dict[str, Any] | None, str | None]:
    """Return (day_record, key_used) or (None, None) if not found."""
    p = path.expanduser()
    if not p.is_file():
        return None, None
    try:
        data: Any = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None, None
    if not isinstance(data, dict):
        return None, None
    if date_key:
        v = data.get(date_key)
        if isinstance(v, dict):
            return v, date_key
        return None, None
    order = data.get("_order")
    if isinstance(order, list) and order:
        for k in reversed(order):
            if isinstance(k, str) and isinstance(data.get(k), dict):
                return data[k], k
    for k, v in data.items():
        if k.startswith("_") or not isinstance(v, dict):
            continue
        if "rounds" in v:
            return v, k
    return None, None


def validate_file(
    path: Path,
    date_key: str | None = None,
    require_target_words: bool = True,
    require_targets_rounds: frozenset[int] | None = None,
) -> list[str]:
    rec, _ = load_day_from_file(path, date_key)
    if rec is None:
        if not path.is_file():
            return [f"file not found: {path}"]
        return [f"no day record in {path!r} (set --date or add _order)"]
    return validate_day_record(
        rec,
        require_target_words=require_target_words,
        require_targets_rounds=require_targets_rounds,
    )


def run_validation_or_exit(
    path: Path,
    date_key: str | None = None,
    require_target_words: bool = True,
    require_targets_rounds: frozenset[int] | None = None,
) -> None:
    errs = validate_file(
        path,
        date_key=date_key,
        require_target_words=require_target_words,
        require_targets_rounds=require_targets_rounds,
    )
    if errs:
        for e in errs:
            print(e, file=sys.stderr)
        sys.exit(1)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Validate a merged codenames daily JSON (four rounds, grids, targets).",
    )
    ap.add_argument(
        "file",
        type=Path,
        default=Path("data") / "codenames_daily.json",
        nargs="?",
    )
    ap.add_argument("--date", default=None, help="Validate this date key only (default: latest in _order).")
    ap.add_argument(
        "--allow-missing-targets",
        action="store_true",
        help="Do not require target_words to match each round's count (for clues-only runs).",
    )
    ap.add_argument(
        "--rounds-123-only",
        action="store_true",
        help="Only require full target_words for rounds 1–3 (round 4 may be empty).",
    )
    args = ap.parse_args()
    if args.allow_missing_targets:
        rt = False
        rtr: frozenset[int] | None = None
    elif args.rounds_123_only:
        rt = True
        rtr = frozenset({1, 2, 3})
    else:
        rt = True
        rtr = None
    errs = validate_file(
        args.file,
        date_key=args.date,
        require_target_words=rt,
        require_targets_rounds=rtr,
    )
    if errs:
        for e in errs:
            print(e, file=sys.stderr)
        sys.exit(1)
    key = load_day_from_file(args.file, args.date)[1] or "?"
    print(f"OK: {args.file.resolve()} day {key}")


if __name__ == "__main__":
    main()
