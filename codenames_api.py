"""
HTTP client for Codenames Daily (https://codenames.game/daily/en).

The web app talks to `https://daily-api.codenames.game/`. A browser is not
required to read the daily cases or to submit card picks: `POST /sync` returns
`today.cases` (clue word, count, 16 grid words) for all four rounds, and
`POST /update` returns a `timeline` that can include `showCorrectWords` after a
bad guess, listing the target words the puzzle author linked to the clue.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx

API_BASE = "https://daily-api.codenames.game"


@dataclass
class Case:
    index: int
    language: str
    clue: str
    number: int
    grid: list[str]
    perfect_rate: float | None = None
    target_words: list[str] = field(default_factory=list)

    @staticmethod
    def from_api_payload(idx: int, c: dict[str, Any]) -> Case:
        g = c.get("grid") or []
        words: list[str] = []
        for cell in g:
            if isinstance(cell, dict) and "word" in cell:
                words.append(str(cell["word"]).strip().upper())
        pr = c.get("perfectRate")
        return Case(
            index=idx,
            language=str(c.get("language", "")),
            clue=str(c.get("word", "")).strip().upper(),
            number=int(c.get("number", 0)),
            grid=words,
            perfect_rate=float(pr) if pr is not None else None,
        )


@dataclass
class SyncResult:
    date: str
    language: str
    user_token: str
    current_case_index: int
    cases: list[Case]
    raw: dict[str, Any]


def _parse_sync(body: dict[str, Any]) -> SyncResult:
    today = (body or {}).get("today") or {}
    date = str(today.get("date", ""))
    language = str(today.get("language", ""))
    u = (body or {}).get("user") or {}
    token = str(u.get("token", ""))
    cur = int(today.get("currentCaseIndex", 0))
    case_list: list[Case] = []
    for i, c in enumerate(today.get("cases") or []):
        if isinstance(c, dict):
            case_list.append(Case.from_api_payload(i, c))
    return SyncResult(
        date=date,
        language=language,
        user_token=token,
        current_case_index=cur,
        cases=case_list,
        raw=body,
    )


class DailyClient:
    def __init__(self, language: str = "en", token: str | None = None) -> None:
        self.language = language
        self.token = token
        self._http = httpx.Client(
            base_url=API_BASE,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            timeout=60.0,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> DailyClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def sync(self, use_saved_token: bool = True) -> SyncResult:
        """Register or resume session. Pass token=None in JSON for a new user."""
        t = self.token if use_saved_token else None
        r = self._http.post(
            "/sync",
            content=json.dumps({"token": t, "language": self.language}),
        )
        r.raise_for_status()
        data = r.json()
        res = _parse_sync(data)
        if res.user_token:
            self.token = res.user_token
        return res

    def update_turn_card(self, word: str) -> dict[str, Any]:
        if not self.token:
            raise ValueError("No token: call sync() first")
        r = self._http.post(
            "/update",
            content=json.dumps(
                {
                    "token": self.token,
                    "move": {
                        "type": "turnCard",
                        "word": word.strip().upper(),
                        "duration": 600,
                        "await": 200,
                    },
                    "language": self.language,
                }
            ),
        )
        r.raise_for_status()
        return r.json()


def extract_show_correct_words(update_body: dict[str, Any]) -> list[str] | None:
    move = (update_body or {}).get("move") or {}
    timeline = move.get("timeline") or []
    best: list[str] | None = None
    for step in timeline:
        if not isinstance(step, dict):
            continue
        if step.get("type") == "showCorrectWords":
            w = step.get("words")
            if isinstance(w, list):
                cand = [str(x).strip().upper() for x in w if x is not None]
                if not cand:
                    continue
                if best is None or len(cand) > len(best):
                    best = cand
    return best


def extract_grid_color_patches(update_body: dict[str, Any]) -> list[dict[str, Any]]:
    """Color hints from timeline patches (e.g. white = civ, gold may appear on good picks)."""
    out: list[dict[str, Any]] = []
    move = (update_body or {}).get("move") or {}
    for step in move.get("timeline") or []:
        if not isinstance(step, dict):
            continue
        for p in step.get("patch") or []:
            if isinstance(p, dict) and p.get("path", "").endswith("/color"):
                out.append(p)
    return out
