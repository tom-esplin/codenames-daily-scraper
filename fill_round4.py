"""
Unlock round 4 and fill `target_words` using only the HTTP API (no browser).

1. Read rounds 1–3 `target_words` from your merged JSON (from collect_daily).
2. `POST /sync` with a new anonymous session.
3. For each of cases 0–2, call `turnCard` only on those targets (a perfect run).
4. Re-sync; when `currentCaseIndex` is 3, reveal round-4 targets with one /update
   that triggers `showCorrectWords` (same approach as the loss-based scraper).
5. Merge the updated back into the JSON file.

The live `/sync` payload must match the stored puzzle (date, clues, grid words).
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path
from typing import Any

from codenames_api import Case, DailyClient, SyncResult, extract_show_correct_words
from collect_daily import _cases_to_dict, _collect_one_case
from json_store import load_history, merge_day
from validate_daily_log import validate_file


def _rounds_to_cases(sync: SyncResult, json_rounds: list[dict[str, Any]]) -> list[Case]:
    by_num = {int(r.get("round", 0)): r for r in json_rounds if isinstance(r, dict)}
    out: list[Case] = []
    for c in sync.cases:
        jr = by_num.get(c.index + 1) or {}
        targets = [str(x).strip().upper() for x in (jr.get("target_words") or []) if str(x).strip()]
        c2 = Case(
            index=c.index,
            language=c.language,
            clue=c.clue,
            number=c.number,
            grid=list(c.grid),
            perfect_rate=c.perfect_rate,
            target_words=targets,
        )
        out.append(c2)
    return out


def _validate_json_against_api(
    jrounds: list[dict[str, Any]], three_rounds: list[Case]
) -> None:
    for c in three_rounds:
        if c.index > 2:
            continue
        jr = jrounds[c.index] if c.index < len(jrounds) else None
        if not isinstance(jr, dict):
            raise ValueError(f"Missing JSON round {c.index + 1}")
        if str(jr.get("clue", "")).strip().upper() != c.clue:
            raise ValueError(
                f"Round {c.index + 1}: JSON clue {jr.get('clue')!r} does not match "
                f"the live API {c.clue!r}. Re-run collect_daily for {c.clue!r}."
            )
        jg = [str(x).strip().upper() for x in (jr.get("grid") or []) if str(x).strip()]
        if sorted(jg) != sorted(c.grid):
            raise ValueError(
                f"Round {c.index + 1}: JSON grid does not match the live /sync for today."
            )
        if len(c.target_words) != c.number:
            raise ValueError(
                f"Round {c.index + 1}: need {c.number} target_words in JSON, got {len(c.target_words)}"
            )
        grid = set(c.grid)
        for w in c.target_words:
            if w not in grid:
                raise ValueError(
                    f"Round {c.index + 1}: target {w!r} is not on the API grid for today"
                )


def _play_perfect_on_case(client: DailyClient, c: Case) -> dict[str, Any]:
    """Pick only the known targets; no wrong cards."""
    if len(c.target_words) != c.number:
        raise ValueError(f"case {c.index + 1}: must have {c.number} targets")
    body: dict[str, Any] = {}
    for w in c.target_words:
        body = client.update_turn_card(w)
        m = (body or {}).get("move") or {}
        if m.get("success") is False and extract_show_correct_words(body):
            raise RuntimeError(
                f"Round {c.index + 1} failed: {w!r} was not a target on the server. "
                "Re-run collect for today or check the JSON."
            )
    return body


def run_fill(
    path: Path,
    language: str,
    day_key: str | None,
    seed: int | None,
) -> dict[str, Any]:
    rng = random.Random(seed)
    hist = load_history(path)
    with DailyClient(language=language) as client:
        api = client.sync(use_saved_token=False)
        d = day_key or api.date
        if d != api.date:
            raise ValueError(
                f"Server date {api.date!r} != requested {d!r}. "
                "Omit --date to use today, or refresh your JSON for the current set."
            )
        day = hist.get(d) if isinstance(hist.get(d), dict) else None
        if not day:
            raise FileNotFoundError(
                f"No entry {d!r} in {path}. Run collect_daily first for that day."
            )
        jrounds: list[dict[str, Any]] = list(day.get("rounds") or [])
        if len(jrounds) < 4:
            raise ValueError("JSON must list four rounds (from a prior sync).")
        merged = _rounds_to_cases(api, jrounds)
        first_three = [c for c in merged if c.index < 3]
        _validate_json_against_api(jrounds, first_three)
        c4 = next((c for c in merged if c.index == 3), None)
        if not c4:
            raise RuntimeError("No fourth case in sync payload")
        for c in first_three:
            _play_perfect_on_case(client, c)
        r2 = client.sync(use_saved_token=True)
        idx = int((r2.raw.get("today") or {}).get("currentCaseIndex", 0))
        if idx != 3:
            raise RuntimeError(
                f"After three perfect rounds, expected currentCaseIndex 3, got {idx!r}. "
                "The API may have changed, or a step failed silently."
            )
        c4.target_words, _ = _collect_one_case(client, c4, rng)
        meta: dict[str, Any] = {
            "language": r2.language,
            "userToken": r2.user_token,
            "source": "https://daily-api.codenames.game",
            "round4Source": "API: three perfect games then turnCard + showCorrectWords",
        }
        if "noteBonusRound" in day:
            meta["noteBonusRound_replaced"] = day.get("noteBonusRound")
        record = _cases_to_dict(d, merged, meta)
        merge_day(path, d, record)
        errs = validate_file(
            path,
            date_key=d,
            require_target_words=True,
            require_targets_rounds=None,
        )
        if errs:
            for e in errs:
                print(e, file=sys.stderr)
            raise RuntimeError("validation failed after writing merged day record")
        return record


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Fill round 4 targets via API perfect play on rounds 1–3 (uses JSON + live sync).",
    )
    ap.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("data") / "codenames_daily.json",
    )
    ap.add_argument("--lang", default="en")
    ap.add_argument(
        "--date",
        default=None,
        help="Date key in the JSON (default: today's date from the server on sync).",
    )
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()
    run_fill(
        path=args.output,
        language=args.lang,
        day_key=args.date,
        seed=args.seed,
    )
    print(f"Updated round 4 in: {args.output.resolve()}")
    print("Log validation OK (four rounds with targets).")


if __name__ == "__main__":
    main()
