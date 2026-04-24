"""
Fetch Codenames Daily puzzles and append to a local JSON file.

By default this uses the public daily API (no browser). It learns target words
per round by making guesses until a `showCorrectWords` event appears, or the
round completes without a miss (rare; then targets are read from the timeline
if present).
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from codenames_api import (
    Case,
    DailyClient,
    SyncResult,
    extract_grid_color_patches,
    extract_show_correct_words,
)
from json_store import merge_day
from validate_daily_log import validate_after_pipeline


def _try_targets_from_timeline(body: dict[str, Any]) -> list[str] | None:
    move = (body or {}).get("move") or {}
    best: list[str] | None = None
    for step in move.get("timeline") or []:
        if not isinstance(step, dict):
            continue
        if step.get("type") == "showCorrectWords" and step.get("words"):
            w = step["words"]
            if isinstance(w, list):
                cand = [str(x).strip().upper() for x in w if x is not None]
                if not cand:
                    continue
                if best is None or len(cand) > len(best):
                    best = cand
    return best


def _collect_one_case(
    client: DailyClient, case: Case, rng: random.Random, max_attempts: int = 32
) -> tuple[list[str], list[dict[str, Any]]]:
    words = list(case.grid)
    rng.shuffle(words)
    colors_log: list[dict[str, Any]] = []
    for w in words[:max_attempts]:
        body = client.update_turn_card(w)
        colors_log.extend(extract_grid_color_patches(body))
        got = _try_targets_from_timeline(body)
        if got:
            return got, colors_log
        move = (body or {}).get("move") or {}
        for step in move.get("timeline") or []:
            if not isinstance(step, dict):
                continue
            if step.get("type") == "completeCase" and step.get("success") is True:
                sw = _try_targets_from_timeline(body)
                if sw:
                    return sw, colors_log
    return [], colors_log


def _cases_to_dict(
    d: str,
    cases: list[Case],
    meta: dict[str, Any],
) -> dict[str, Any]:
    return {
        "date": d,
        "fetchedAt": datetime.now(timezone.utc).isoformat(),
        **meta,
        "rounds": [
            {
                "round": c.index + 1,
                "language": c.language,
                "clue": c.clue,
                "count": c.number,
                "grid": c.grid,
                "target_words": c.target_words,
                "stats": {
                    "perfectRate": c.perfect_rate,
                },
            }
            for c in cases
        ],
    }


def run(
    out_path: Path,
    language: str,
    new_session: bool,
    token: str | None,
    seed: int | None,
    clues_only: bool = False,
    fill_round4: bool = False,
) -> SyncResult:
    """
    Rounds 1–3: targets via loss-based /update. Round 4 is only in reach after three
    perfect games; run `fill_round4.py` (or --fill-round-4 after this) with stored
    targets 1–3 to finish round 4 via the API.
    """
    rng = random.Random(seed)
    with DailyClient(language=language, token=token) as client:
        if new_session and token is None:
            r0 = client.sync(use_saved_token=False)
        else:
            r0 = client.sync(use_saved_token=bool(client.token))
        d = r0.date
        meta: dict[str, Any] = {
            "language": r0.language,
            "userToken": r0.user_token,
            "source": "https://daily-api.codenames.game",
        }
        if not clues_only:
            # Only the first three cases are reachable by loss-reveal; round 4 needs perfect 1–3.
            for c in (x for x in r0.cases if x.index < 3):
                c.target_words, _ = _collect_one_case(client, c, rng)
        merge_day(
            out_path,
            d,
            _cases_to_dict(d, r0.cases, meta),
        )
        if fill_round4 and not clues_only:
            from fill_round4 import run_fill
            run_fill(
                path=out_path,
                language=language,
                day_key=d,
                seed=seed,
            )
        return r0


def main() -> None:
    ap = argparse.ArgumentParser(description="Collect Codenames Daily into JSON")
    ap.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("data") / "codenames_daily.json",
        help="Path to the JSON file to merge into (default: data/codenames_daily.json)",
    )
    ap.add_argument("--lang", default="en", help="Language code (e.g. en)")
    ap.add_argument(
        "--new-session",
        action="store_true",
        help="Call sync with token null (new anonymous user) before collecting",
    )
    ap.add_argument("--token", default=None, help="Existing daily-api user token to resume")
    ap.add_argument("--seed", type=int, default=None, help="Random seed for guess order")
    ap.add_argument(
        "--clues-only",
        action="store_true",
        help="Only run /sync and write cases (clue, grid, count) — no /update, no target_words",
    )
    ap.add_argument(
        "--fill-round-4",
        action="store_true",
        dest="fill_round4",
        help="After saving, re-sync and play rounds 1–3 perfectly from this file, then fill round-4 targets (API only).",
    )
    args = ap.parse_args()
    try:
        r0 = run(
            out_path=args.output,
            language=args.lang,
            new_session=args.new_session,
            token=args.token,
            seed=args.seed,
            clues_only=args.clues_only,
            fill_round4=args.fill_round4,
        )
    except Exception as e:
        if type(e) is ValueError and "target_words in JSON" in str(e):
            run(
                out_path=args.output,
                language=args.lang,
                new_session=args.new_session,
                token=args.token,
                seed=args.seed + 1 if args.seed is not None else None,
                clues_only=True,
                fill_round4=args.fill_round4,
            )
    errs = validate_after_pipeline(
        args.output, r0.date, clues_only=args.clues_only, fill_round4=args.fill_round4
    )
    if errs:
        for e in errs:
            print(e, file=sys.stderr)
        sys.exit(1)
    print(f"Wrote/merged: {args.output.resolve()}")
    print("Log validation OK (four rounds).")


if __name__ == "__main__":
    main()
