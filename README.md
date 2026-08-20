# maps-skills

Five Claude Code skills that search a map provider for a keyword in the internal
Claude browser and export the results to a CSV file.

| Skill | Provider | Strengths | Watch out for |
|---|---|---|---|
| `openstreetmap-scrape` | openstreetmap.org | **Most rows** (149 verified), lat/lon on every row, no blockers | No ratings; must loop "More results" |
| `mapy-scrape` | mapy.com | 75 rows verified, full addresses, best CZ/SK coverage | Cookie wall; paginated; throttled reads |
| `bing-maps-scrape` | bing.com/maps | Addresses + phones, no blockers | Hard cap ~18, no pagination at all |
| `google-maps-scrape` | google.com/maps | Ratings, reviews, coords, phones | Viewport-capped ~18; phrasing-sensitive |
| `apple-maps-scrape` | maps.apple.com | Full addresses + coords in the href | Category-limited — returns 0 for most keywords |

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

All five are verified against the live sites (Aug 2026), each on two different
queries — `Hotels in Kyiv` / `Hotels in Prague` and `University in Kyiv`. Running a
second query per provider is what caught most of the bugs: three of the five behaved
differently on the second one.

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

## Four things that decide whether this works

Learned the hard way from live runs. The first two cost the most rows:

1. **Exhaust the pagination.** Every provider stops early in a different way, and
   each looks like "no more results" if you take the first plateau at face value.
   A single `University in Kyiv` run went from **59 to 224 rows** once this was
   fixed. Per provider: OSM appends 10 per "More results" click — **loop it**
   (20 → 149); Mapy paginates with a `next` button, 15 per page (15 → 75); Google
   uses "Next page" only in its hotel UI; Bing genuinely has no pagination.
2. **A flat row count is not proof you are done.** Distinguish "end of list" (Google
   says so in the feed), "end of page" (a pager exists), "throttled stale read"
   (Mapy — re-read), and a real ceiling.
3. **Resize the browser to desktop before extracting.** These panels render only
   what fits. The same Google query gave **1 result** in a small pane and **19** at
   desktop width. Mapy collapses its panel entirely below ~800px.
4. **Phrasing changes the result set.** `University in Kyiv` → 6 Google rows;
   `Universities in Kyiv` → 18. Prefer the plural for category searches.

## Notes and limits

- **Selectors drift.** Every provider except OpenStreetMap ships generated class
  names that change without notice. The skills tell Claude to fall back to reading
  page text rather than guessing new selectors, and to report short results honestly
  instead of filling gaps.
- **Cross-provider coverage differs enormously.** For `University in Kyiv`:
  OSM 125, Mapy 75, Bing 18, Google 6, Apple 0 — 224 rows, 184 distinct names.
  Run several providers and merge with `--append` when completeness matters.
- **Volume.** OpenStreetMap gives the most rows; Apple the fewest. For bulk OSM data
  the OpenStreetMap skill points at the Overpass API — a public documented API, the
  right tool at that scale, and a useful cross-check (149 browser rows vs 148
  Overpass elements for the same city). It also returns phone/website tags the
  sidebar never shows.
- **CAPTCHAs are a stop condition.** No skill attempts to solve one — it saves what
  was collected and says so.
- **Phone and website** are usually absent from list cards on every provider.
  Filling them means opening each place page, one navigation per row; the skills
  offer that but do not do it unprompted.
- Check each provider's terms before collecting at scale; these skills automate a
  browser you are already allowed to use, which is not the same as a license to
  redistribute the data.
