---
name: openstreetmap-scrape
description: Search OpenStreetMap (openstreetmap.org / Nominatim) for a keyword such as "Hotels" in the internal Claude browser and export the found places, with coordinates, to a CSV file. Use when the user wants OSM search results or open map data collected into a spreadsheet.
---

# OpenStreetMap → CSV

**Verified live** (Aug 2026, `Hotels in Kyiv`): 10/10 rows, every field populated.

Drive the internal Claude browser (`mcp__Claude_Browser__*`) through an
openstreetmap.org search and save the results into a CSV. This is the one provider
that reliably gives you latitude and longitude for every row.

## Inputs

- **keyword** (required) — e.g. `Hotels in Kraków`. OSM's search is Nominatim, so it
  works best as `<thing> in <place>` or `<thing> near <place>`.
- **output path** — default `./openstreetmap-<slug>.csv`.
- **target count** — verified: **10 results per page**, with a "More results" link
  to load the next batch. (Not ~50 in one shot.)

## Workflow

1. **Open the search:**

   ```
   mcp__Claude_Browser__preview_start { url: "https://www.openstreetmap.org/search?query=<url-encoded keyword>" }
   ```

   No consent banner, no login, no CAPTCHA — go straight to extraction.

2. **Wait for results.** `computer { action: "wait", duration: 2 }`, then confirm the
   left sidebar has a results list.

3. **Extract the rows.** Verified live: **10/10 rows** with name, category,
   address, and coordinates. OSM's markup is stable and carries coordinates as
   `data-` attributes (`lat`, `lon`, `prefix`, `name`, `type`, `id`):

   ```js
   (() => {
     const out = [];
     document.querySelectorAll('.search_results_entry a.set_position, li.search_results_entry a')
       .forEach(a => {
         const full = (a.dataset.name || a.textContent || '').trim();
         if (!full) return;
         const parts = full.split(',').map(s => s.trim());
         out.push({
           name: parts[0],
           category: (a.dataset.prefix || a.previousElementSibling?.textContent || '').trim(),
           address: parts.slice(1).join(', '),
           latitude: a.dataset.lat || '',
           longitude: a.dataset.lon || '',
           url: a.href.startsWith('http') ? a.href : location.origin + a.getAttribute('href'),
         });
       });
     return out;
   })()
   ```

   Confirmed output shape: `data-prefix` is the category ("Hotel") and `data-name`
   is `"<name>, <street>, <district>, <city>, <postcode>, <country>"`, so splitting
   on the first comma gives name and address cleanly.

   A **"More results"** link sits at the bottom of the sidebar (confirmed present).
   Click it via `ref` and re-extract; repeat until it disappears or nothing new
   appears. Each click adds another 10.

4. **Enrich (optional).** Each result links to an OSM object page
   (`/node/<id>`, `/way/<id>`) whose tag table has `phone`, `website`,
   `addr:street`, `addr:housenumber`, `tourism`/`amenity`. Open those pages only if
   the user asked for phone/website — it is one navigation per row. Read the tags with:

   ```js
   Object.fromEntries([...document.querySelectorAll('.browse-tag-list tr')]
     .map(tr => [tr.children[0].innerText.trim(), tr.children[1].innerText.trim()]))
   ```

5. **Save.**

   ```bash
   uv run scripts/write_csv.py ./openstreetmap-hotels.csv places.json
   ```

6. **Report** row count and output path. OSM has no ratings or review counts — those
   columns are always empty; say so once rather than apologizing per row.

## Validation

`scripts/write_csv.py` validates every record with pydantic before writing. The
PEP 723 header means `uv run` fetches pydantic itself — no venv or install needed,
and the skill works standalone once copied into `~/.claude/skills`.

What it enforces, so you do not have to hand-check scraped values:

- `rating` 0–5, accepting `"4,5"` and `"4.7 stars"`; `reviews` digits only
  (`"(1,094)"` → `1094`); `latitude` ±90, `longitude` ±180.
- `phone` must look like a phone (≥9 digits) — this is what stops rating text such
  as `"4.4(137)"` from landing in the phone column.
- `website`/`url` must be `http(s)`; anything else is blanked.
- Leading interpuncts and non-breaking spaces are stripped from every string.

A field that fails is **blanked and reported on stderr**; the row still gets
written. Only a row with no usable name is dropped. Pass `--strict` to exit
non-zero when anything was blanked or skipped — use it when the user needs the CSV
to be trustworthy rather than complete, and report any warnings you see.

## CSV format

`name, category, rating, reviews, address, phone, website, latitude, longitude, url, source, query, scraped_at`

Set `source: "openstreetmap"` and `query: "<the keyword>"` on every object.
`rating` and `reviews` stay blank — OSM does not carry them.

## Notes

- **If the user wants many rows or a whole city**, the browser search caps out around
  50. Say so and offer the Overpass API instead — one HTTP request returns every
  tagged hotel in a bounding box:

  ```bash
  curl -s -G https://overpass-api.de/api/interpreter --data-urlencode \
    'data=[out:json][timeout:60];area[name="Kraków"]->.a;nwr["tourism"="hotel"](area.a);out center tags;'
  ```

  That is a documented public API, not a scrape, and it is the right tool at volume.
  Still pipe the result through `scripts/write_csv.py` after mapping the fields.
- Respect Nominatim's usage policy: no rapid-fire automated searches. One query per
  user request is fine; a loop over hundreds of keywords is not.
