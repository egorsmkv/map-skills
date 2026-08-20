import csv
import json
import subprocess
from pathlib import Path

import pytest

from maps_csv.write_csv import Place, main, salvage, scrub

SCRIPT = Path(__file__).resolve().parents[1] / "src" / "maps_csv" / "write_csv.py"


def run(tmp_path, records, *flags):
    src = tmp_path / "in.json"
    src.write_text(json.dumps(records), encoding="utf-8")
    out = tmp_path / "out.csv"
    code = main([str(out), str(src), *flags])
    rows = []
    if out.exists():
        with out.open(newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
    return code, rows


# --- field coercion -------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("(1,094)", 1094),
        ("1 094 reviews", 1094),
        ("23", 23),
        ("", None),
        (None, None),
    ],
)
def test_reviews_normalized_to_int(raw, expected):
    assert Place(name="x", reviews=raw).reviews == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("4.1", 4.1),
        ("4,5", 4.5),
        ("4.7 stars", 4.7),
        ("", None),
    ],
)
def test_rating_accepts_locale_and_suffix(raw, expected):
    assert Place(name="x", rating=raw).rating == expected


def test_scrub_strips_interpunct_and_nbsp():
    assert scrub("· Heroiv Dnipra St, 22А ") == "Heroiv Dnipra St, 22А"


# --- the bugs the live Google run exposed ---------------------------------


def test_rating_text_never_lands_in_phone_column():
    """Regression: the old innerText regex matched '4.4(137)' as a phone number."""
    assert Place(name="x", phone="4.4(137)").phone == ""
    assert Place(name="x", phone="+380 44 123 4567").phone == "+380 44 123 4567"


def test_short_number_is_not_a_phone():
    assert Place(name="x", phone="732 UAH").phone == ""


def test_non_http_website_is_dropped():
    assert Place(name="x", website="javascript:void(0)").website == ""
    assert Place(name="x", url="/maps/place/rel").url == ""


# --- salvage semantics ----------------------------------------------------


def test_out_of_range_field_is_dropped_but_row_survives():
    problems = []
    place = salvage({"name": "Hotel", "rating": "9.9", "latitude": "500"}, problems, 1)
    assert place is not None and place.name == "Hotel"
    assert place.rating is None and place.latitude is None
    assert len(problems) == 2


def test_row_without_name_is_skipped():
    problems = []
    assert salvage({"name": "", "rating": "4.1"}, problems, 1) is None
    assert "skipped" in problems[0]


def test_valid_coords_survive():
    p = Place(name="x", latitude="50.4366431", longitude="30.5053184")
    assert (p.latitude, p.longitude) == (50.4366431, 30.5053184)


# --- CSV behaviour --------------------------------------------------------


def test_writes_expected_columns_and_utf8(tmp_path):
    code, rows = run(
        tmp_path,
        [
            {
                "name": "Мережі хостелів Likehostel",
                "rating": "4.1",
                "reviews": "23",
                "source": "google-maps",
            }
        ],
    )
    assert code == 0 and len(rows) == 1
    assert rows[0]["name"] == "Мережі хостелів Likehostel"
    assert rows[0]["reviews"] == "23" and rows[0]["rating"] == "4.1"
    assert rows[0]["scraped_at"].endswith("Z")


def test_address_with_comma_round_trips(tmp_path):
    _, rows = run(tmp_path, [{"name": "A", "address": "Heroiv Dnipra St, 22А"}])
    assert rows[0]["address"] == "Heroiv Dnipra St, 22А"


def test_duplicates_collapse(tmp_path):
    _, rows = run(
        tmp_path,
        [
            {"name": "A", "address": "X"},
            {"name": "a", "address": "x"},
            {"name": "B", "url": "https://e/1"},
        ],
    )
    assert len(rows) == 2


def test_append_dedupes_against_existing_file(tmp_path):
    recs = [{"name": "A", "address": "X", "reviews": "5"}]
    run(tmp_path, recs)
    code, rows = run(tmp_path, recs, "--append")
    assert code == 0 and len(rows) == 1


def test_append_adds_only_new_rows(tmp_path):
    run(tmp_path, [{"name": "A", "address": "X"}])
    _, rows = run(
        tmp_path,
        [{"name": "A", "address": "X"}, {"name": "C", "address": "Z"}],
        "--append",
    )
    assert [r["name"] for r in rows] == ["A", "C"]


def test_strict_flags_validation_problems(tmp_path):
    code, rows = run(tmp_path, [{"name": "A", "rating": "9.9"}], "--strict")
    assert code == 1 and len(rows) == 1 and rows[0]["rating"] == ""


def test_bad_json_exits_cleanly(tmp_path):
    src = tmp_path / "bad.json"
    src.write_text("{not json", encoding="utf-8")
    with pytest.raises(SystemExit):
        main([str(tmp_path / "o.csv"), str(src)])


def test_runs_standalone_via_uv_script_header(tmp_path):
    """The copies inside each skill must work without the workspace installed."""
    src = tmp_path / "in.json"
    src.write_text(json.dumps([{"name": "A", "rating": "4.2"}]), encoding="utf-8")
    out = tmp_path / "o.csv"
    proc = subprocess.run(
        ["uv", "run", "--no-project", str(SCRIPT), str(out), str(src)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "wrote 1 row" in proc.stdout


# --- abbreviated counts, found live on Bing Maps --------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1.3K", 1300),
        ("1.1K", 1100),
        ("2.4M", 2400000),
        ("12K", 12000),
        ("953", 953),
        ("1 094", 1094),
        ("(1,094)", 1094),
    ],
)
def test_abbreviated_review_counts(raw, expected):
    """Regression: digits-only parsing read '1.3K' as 13 - a 100x undercount."""
    assert Place(name="x", reviews=raw).reviews == expected
