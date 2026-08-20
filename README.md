# maps-skills

Five Claude Code skills that search a map provider for a keyword in the internal
Claude browser and export the results to a CSV file.

| Skill | Provider | Strengths | Watch out for |
|---|---|---|---|
| `google-maps-scrape` | google.com/maps | Most results, ratings + reviews, coords | Needs a location in the keyword; paginates at ~20 |
| `bing-maps-scrape` | bing.com/maps | Clean pagination | Thin data, patchy by region |
| `apple-maps-scrape` | maps.apple.com | — | Canvas UI, few results, hardest to scrape |
| `openstreetmap-scrape` | openstreetmap.org | Lat/lon on every row, no blockers | No ratings; ~50 results per search |
| `mapy-scrape` | mapy.com | Best CZ/SK coverage | Cookie wall; sparse outside CZ/SK |

## Develop

This repo is a `uv` workspace. The canonical validator lives in
[`src/maps_csv/write_csv.py`](src/maps_csv/write_csv.py); each skill carries a copy
so it stays self-contained.

```bash
uv sync                              # create the venv
uv run pytest                        # 24 tests
uv run scripts/sync_skills.py        # push the canonical script into all 5 skills
uv run scripts/sync_skills.py --check # verify copies are current (CI)
```

Edit `src/maps_csv/write_csv.py`, never a skill's copy — `--check` will catch drift.

## Install

Copy the skill folders into your skills directory:

```bash
cp -r google-maps-scrape bing-maps-scrape apple-maps-scrape openstreetmap-scrape mapy-scrape ~/.claude/skills/
```

Per-project instead: copy them into `.claude/skills/` in the repo.

Only `google-maps-scrape` has been verified against the live site (Aug 2026); its
selectors and quirks are confirmed. The other four are written from the same
pattern but their selectors are unverified — expect to fall back to page text.

## Use

Just ask, naming the provider:

- "Scrape Google Maps for Hotels in Prague and save a CSV"
- "Get OpenStreetMap results for pharmacies in Kraków"
- "Hotels in Brno from Mapy.com → hotels.csv"

Each skill will open the search in the Claude browser, scroll/page through the
result list, extract the rows, and write the CSV to the path you give (or a
default like `./google-maps-hotels.csv`).

## Output

Every skill writes the same columns, so files from different providers concatenate:

```
name, category, rating, reviews, address, phone, website,
latitude, longitude, url, source, query, scraped_at
```

`source` identifies the provider, `query` is your keyword, `scraped_at` is UTC.
Columns a provider does not expose are left empty rather than guessed.

## scripts/write_csv.py

Each skill bundles the same helper. It takes a JSON array of place objects,
validates them with pydantic, and writes de-duplicated CSV:

```bash
uv run scripts/write_csv.py out.csv places.json
uv run scripts/write_csv.py out.csv places.json --append
uv run scripts/write_csv.py out.csv places.json --strict
```

A PEP 723 header declares the pydantic dependency, so `uv run` resolves it with no
venv or install — the copy inside `~/.claude/skills` just works.

**Validation.** `rating` 0–5 (accepts `"4,5"`, `"4.7 stars"`), `reviews` coerced to
int (`"(1,094)"` → `1094`), `latitude` ±90, `longitude` ±180, `website`/`url` must
be http(s), and `phone` must have ≥9 digits — the rule that keeps rating text like
`"4.4(137)"` out of the phone column. A bad field is **blanked and reported on
stderr, keeping the row**; only a nameless row is dropped. `--strict` exits
non-zero if anything was blanked or skipped.

**De-duplication** is on `(name, address)`, falling back to `url`. With `--append`
it also de-dupes against rows already in the file, so several searches or several
providers can accumulate into one CSV.

## Two things that decide whether this works

Learned from the live Google run, and they generalize to every provider:

1. **Resize the browser to desktop before extracting.** These panels render only
   what fits the viewport. The same Google query returned **1 result** in a small
   pane and **19** at desktop width.
2. **Put a location in the keyword.** A bare `Hotels` pushed Google into its
   hotel/travel UI with a "limited view of Google Maps" cap of one card;
   `Hotels in Kyiv` returned a full page.

## Notes and limits

- **Selectors drift.** Every provider except OpenStreetMap ships generated class
  names that change without notice. The skills tell Claude to fall back to reading
  page text rather than guessing new selectors, and to report short results honestly
  instead of filling gaps.
- **Pagination is not always scrolling.** Google's hotel feed plateaus at ~20 and
  needs its "Next page" button; Bing pages explicitly; OSM has "More results".
  A flat result count usually means "end of page", not "end of results".
- **Volume.** Google gives the most rows; Apple the fewest. For bulk OSM data the
  OpenStreetMap skill points at the Overpass API, which is a public API and the
  right tool at that scale.
- **CAPTCHAs are a stop condition.** No skill attempts to solve one — it saves what
  was collected and says so.
- **Phone and website** are usually absent from list cards on every provider.
  Filling them means opening each place page, one navigation per row; the skills
  offer that but do not do it unprompted.
- Check each provider's terms before collecting at scale; these skills automate a
  browser you are already allowed to use, which is not the same as a license to
  redistribute the data.
