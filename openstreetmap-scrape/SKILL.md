---
name: openstreetmap-scrape
description: Search OpenStreetMap (openstreetmap.org / Nominatim) for a keyword such as "Hotels" in the internal Claude browser and export the found places, with coordinates, to a CSV file. Use when the user wants OSM search results or open map data collected into a spreadsheet.
---

# OpenStreetMap → CSV

**Verified live** twice (Aug 2026): `Hotels in Kyiv` → 10/10 rows, every field
populated; `University in Kyiv` → **149 rows** after looping "More results" to
exhaustion. Clicking it once and stopping yields 20 and looks complete — it isn't.

Drive the internal Claude browser (`mcp__Claude_Browser__*`) through an
openstreetmap.org search and save the results into a CSV. This is the one provider
that reliably gives you latitude and longitude for every row.

## Inputs

- **keyword** (required) — e.g. `Hotels in Kraków`. OSM's search is Nominatim, so it
  works best as `<thing> in <place>` or `<thing> near <place>`.
- **output path** — default `./openstreetmap-<slug>.csv`.
- **target count** — **10 per click**, appended to the list. Keep clicking "More
  results" until the link disappears. Verified ceiling for `University in Kyiv`: 149.

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

   A **"More results"** link sits at the bottom of the sidebar. Each click **appends**
   another 10 to the existing list (it does not replace them), so extract once at the
   end rather than per click.

   **Loop it to exhaustion.** This is the difference between 20 rows and 149:

   ```js
   (async () => {
     const count = () => document.querySelectorAll('.search_results_entry a.set_position').length;
     const more  = () => [...document.querySelectorAll('#sidebar_content a')]
                          .find(e => /More results/i.test(e.innerText));
     const log = [count()];
     for (let i = 0; i < 4; i++) {                 // 4 per call: ~2.2s each fits the 30s JS budget
       const m = more(); if (!m) { log.push('END'); break; }
       m.click(); await new Promise(r => setTimeout(r, 2200)); log.push(count());
     }
     return JSON.stringify({ log, hasMore: !!more() });
   })()
   ```

   Re-run this call until it reports `hasMore: false` (or the count plateaus across
   two consecutive calls). Do not put more than ~4 clicks in one call — the tool
   aborts at 30s and you lose the result, though the clicks already landed.

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

- **If the user wants a whole city**, the browser loop works (149 rows verified) but
  costs one tool call per ~4 clicks. Offer the Overpass API instead — one HTTP
  request returns every tagged feature in an area, with richer tags:

  ```bash
  curl -s -G https://overpass-api.de/api/interpreter --data-urlencode \
    'data=[out:json][timeout:60];area[name="Kraków"]->.a;nwr["tourism"="hotel"](area.a);out center tags;'
  ```

  That is a documented public API, not a scrape, and it is the right tool at volume.
  It also returns tags the sidebar never shows — on the verified Kyiv run it gave
  **73 websites and 24 phone numbers** across 125 named rows, where the browser
  sidebar gives neither. Map `tags.name:en || tags.name`, `tags.phone`,
  `tags.website`, `addr:*`, and `lat/lon` (or `center`) into the schema, then pipe
  through `scripts/write_csv.py`.
- **Cross-check at volume.** The browser loop and Overpass agree closely: 149 rows
  from the sidebar vs 148 elements (124 named) from Overpass for the same city. If
  the two disagree by a lot, you stopped clicking too early.
- Respect Nominatim's usage policy: no rapid-fire automated searches. One query per
  user request is fine; a loop over hundreds of keywords is not.
