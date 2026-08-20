#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pydantic>=2.7"]
# ///
"""Validate scraped map places (JSON) with pydantic and write them to CSV.

Usage:
    uv run scripts/write_csv.py OUTPUT.csv < places.json
    uv run scripts/write_csv.py OUTPUT.csv places.json
    uv run scripts/write_csv.py OUTPUT.csv places.json --append
    uv run scripts/write_csv.py OUTPUT.csv places.json --strict

Input is a JSON array of place objects. Fields are coerced and range-checked:
a field that cannot be salvaged is dropped (left empty) and reported, rather than
discarding the whole row. A row with no usable name is skipped entirely.
`--strict` exits non-zero if anything was dropped or skipped.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

COLUMNS = [
    "name",
    "category",
    "rating",
    "reviews",
    "address",
    "phone",
    "website",
    "latitude",
    "longitude",
    "url",
    "source",
    "query",
    "scraped_at",
]

# Scraped card text is full of non-breaking spaces and leading interpuncts.
_JUNK_EDGES = " ·-–—,\t\r\n"
_RATING_JUNK = re.compile(r"[^\d.,]")
_PHONE_SHAPE = re.compile(r"^\+?[\d][\d\s\-()]{7,}$")
# Bing abbreviates review counts as "1.3K" / "2.4M"; digits-only parsing would
# read those as 13 and 24. A thousands space ("1 094") must NOT match here.
_COUNT_SUFFIX = re.compile(r"^\D*?(\d+(?:[.,]\d+)?)\s*([KkMm])\b")


def scrub(value: Any) -> str:
    """Collapse whitespace and strip separator noise off both ends."""
    if value is None or value is False:
        return ""
    text = str(value).replace(" ", " ").replace(" ", " ")
    return " ".join(text.split()).strip(_JUNK_EDGES)


def _utcnow() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class Place(BaseModel):
    """One row of scraped map data."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    name: str = Field(min_length=1)
    category: str = ""
    rating: float | None = Field(default=None, ge=0, le=5)
    reviews: int | None = Field(default=None, ge=0)
    address: str = ""
    phone: str = ""
    website: str = ""
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    url: str = ""
    source: str = ""
    query: str = ""
    scraped_at: str = ""

    @field_validator("*", mode="before")
    @classmethod
    def _scrub_strings(cls, v: Any) -> Any:
        return scrub(v) if isinstance(v, str) else v

    @field_validator(
        "name",
        "category",
        "address",
        "phone",
        "website",
        "url",
        "source",
        "query",
        "scraped_at",
        mode="before",
    )
    @classmethod
    def _blank_when_missing(cls, v: Any) -> Any:
        return "" if v is None else v

    @field_validator("rating", mode="before")
    @classmethod
    def _parse_rating(cls, v: Any) -> Any:
        if v in (None, ""):
            return None
        if isinstance(v, (int, float)):
            return v
        # "4,5" (cs/uk locales) and "4.7 stars" both appear in the wild.
        text = _RATING_JUNK.sub("", str(v)).replace(",", ".")
        return text or None

    @field_validator("reviews", mode="before")
    @classmethod
    def _parse_reviews(cls, v: Any) -> Any:
        if v in (None, ""):
            return None
        if isinstance(v, int):
            return v
        text = str(v)
        suffix = _COUNT_SUFFIX.match(text)
        if suffix:
            scale = 1_000 if suffix.group(2).upper() == "K" else 1_000_000
            return int(float(suffix.group(1).replace(",", ".")) * scale)
        # "(1,094)" / "1 094 reviews" / "23" -> 1094 / 1094 / 23
        digits = "".join(ch for ch in text if ch.isdigit())
        return int(digits) if digits else None

    @field_validator("latitude", "longitude", mode="before")
    @classmethod
    def _parse_coord(cls, v: Any) -> Any:
        if v in (None, ""):
            return None
        return v

    @field_validator("phone")
    @classmethod
    def _reject_non_phone(cls, v: str) -> str:
        """Guard against rating text ("4.4(137)") landing in the phone column."""
        if not v:
            return ""
        if not _PHONE_SHAPE.match(v) or sum(ch.isdigit() for ch in v) < 9:
            return ""
        return v

    @field_validator("website", "url")
    @classmethod
    def _only_http(cls, v: str) -> str:
        return v if v.startswith(("http://", "https://")) else ""

    def dedupe_key(self) -> tuple:
        if self.name and self.address:
            return ("na", self.name.casefold(), self.address.casefold())
        if self.url:
            return ("u", self.url)
        return ("n", self.name.casefold(), self.latitude, self.longitude)

    def to_row(self) -> dict[str, str]:
        def num(x: float | None) -> str:
            if x is None:
                return ""
            if isinstance(x, float) and x.is_integer() and abs(x) >= 1000:
                return str(int(x))
            return str(x)

        row = {c: getattr(self, c) for c in COLUMNS}
        for key in ("rating", "reviews", "latitude", "longitude"):
            row[key] = num(row[key])
        return {c: str(row[c]) for c in COLUMNS}


def salvage(raw: dict[str, Any], problems: list[str], index: int) -> Place | None:
    """Validate one record, blanking individually bad fields instead of dropping it."""
    # Omit absent keys so model defaults apply; keep "name" so a missing one
    # fails as an empty string rather than as a type error.
    data: dict[str, Any] = {k: raw[k] for k in COLUMNS if raw.get(k) is not None}
    data.setdefault("name", "")
    for _ in range(len(COLUMNS) + 1):
        try:
            return Place(**data)
        except ValidationError as exc:
            fatal = True
            for err in exc.errors():
                field = str(err["loc"][0]) if err["loc"] else ""
                if field and field != "name" and data.get(field) not in (None, ""):
                    problems.append(
                        f"row {index}: dropped {field}={data[field]!r} ({err['msg']})"
                    )
                    data.pop(field, None)  # fall back to the model default
                    fatal = False
            if fatal:
                reason = exc.errors()[0]["msg"] if exc.errors() else "invalid"
                problems.append(f"row {index}: skipped ({reason})")
                return None
    return None


def load(raw_text: str) -> list[Any]:
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        sys.exit(f"input is not valid JSON: {exc}")
    if isinstance(data, dict):
        data = data.get("results") or data.get("places") or [data]
    if not isinstance(data, list):
        sys.exit("input JSON must be an array of place objects")
    return data


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("output")
    ap.add_argument("input", nargs="?")
    ap.add_argument(
        "--append",
        action="store_true",
        help="merge into an existing CSV, de-duplicating against it",
    )
    ap.add_argument(
        "--strict",
        action="store_true",
        help="exit non-zero if any row or field failed validation",
    )
    args = ap.parse_args(argv)

    if args.input:
        with open(args.input, encoding="utf-8") as fh:
            text = fh.read()
    else:
        text = sys.stdin.read()
    records = load(text)

    stamp = _utcnow()
    problems: list[str] = []
    seen: set[tuple] = set()
    rows: list[dict[str, str]] = []

    resuming = (
        args.append and os.path.exists(args.output) and os.path.getsize(args.output) > 0
    )
    if resuming:
        with open(args.output, newline="", encoding="utf-8") as fh:
            for old in csv.DictReader(fh):
                prior = salvage(old, [], -1)
                if prior:
                    seen.add(prior.dedupe_key())

    duplicates = 0
    for i, item in enumerate(records, 1):
        if not isinstance(item, dict):
            problems.append(f"row {i}: skipped (not an object)")
            continue
        place = salvage(item, problems, i)
        if place is None:
            continue
        if not place.scraped_at:
            place.scraped_at = stamp
        key = place.dedupe_key()
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        rows.append(place.to_row())

    with open(
        args.output, "a" if resuming else "w", newline="", encoding="utf-8"
    ) as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        if not resuming:
            writer.writeheader()
        writer.writerows(rows)

    for line in problems:
        print(f"warning: {line}", file=sys.stderr)
    summary = f"wrote {len(rows)} row(s) to {args.output}"
    if duplicates:
        summary += f"; skipped {duplicates} duplicate(s)"
    if problems:
        summary += f"; {len(problems)} validation issue(s)"
    print(summary)

    return 1 if (args.strict and problems) else 0


if __name__ == "__main__":
    raise SystemExit(main())
