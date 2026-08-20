---
name: apple-maps-scrape
description: Search Apple Maps on the web (maps.apple.com) for a keyword such as "Hotels" in the internal Claude browser and export the place results to a CSV file. Use when the user wants Apple Maps listings collected into a spreadsheet.
---

# Apple Maps → CSV

**Verified live** (Aug 2026, `Hotels in Kyiv`): 8/8 rows with name, category, full
street address, and coordinates.

Drive the internal Claude browser (`mcp__Claude_Browser__*`) through an Apple Maps
web search and save the results into a CSV.

## Inputs

- **keyword** (required) — e.g. `Hotels in Zurich`.
- **output path** — default `./apple-maps-<slug>.csv`.
- **target count** — Apple returns a short list (8 on the verified run). That is
  the whole result set; there is no pagination.

## Workflow

1. **Open the search:**

   ```
   mcp__Claude_Browser__preview_start { url: "https://maps.apple.com/?q=<url-encoded keyword>" }
   ```

2. **Wait ~6s.** The map is WebGL and boots slowly. The **results list is ordinary
   DOM** with stable `mw-` prefixed class names — you do not need screenshots or
   `get_page_text` for it, despite the canvas map behind it.

3. **Extract.** Each row is `.mw-search-result-item`, with semantic child classes:

   ```js
   (() => {
     const out = [];
     document.querySelectorAll('.mw-search-result-item').forEach(card => {
       const t = (s) => card.querySelector(s)?.textContent.trim() || '';
       const name = t('.place-title'); if (!name) return;
       const a = card.querySelector('a[href]');
       const u = a ? new URL(a.getAttribute('href'), location.origin) : null;
       const coord = (u?.searchParams.get('coordinate') || '').split(',');
       const rt = t('.place-rating-text');           // e.g. "4.2 on Booking.com"
       out.push({
         name,
         category: t('.place-category'),
         // The href carries the full street address; .place-address is just the city.
         address: u?.searchParams.get('address') || t('.place-address') || '',
         rating: (rt.match(/^([\d.]+)/) || ['', ''])[1],
         latitude: coord[0] || '', longitude: coord[1] || '',
         url: u ? u.href : '',
         source: 'apple-maps', query: '<the keyword>',
       });
     });
     return JSON.stringify(out);
   })()
   ```

4. **Coordinates and address come free.** The result `href` is
   `/place?address=…&coordinate=<lat>,<lon>&name=…&place-id=…`. Parse it — there is
   **no need to click each result**, which is what an earlier version of this skill
   wrongly required.

5. **Ratings are third-party and sparse.** The `.place-rating-text` reads
   "4.2 on Booking.com" and is absent on most rows. It is already on a 5-point
   scale. Review counts are not exposed at all — leave `reviews` empty.

6. **Save.**

   ```bash
   uv run scripts/write_csv.py ./apple-maps-hotels.csv places.json
   ```

7. **Report** the row count and output path. If the list is empty, take a
   `screenshot` to confirm the app booted before concluding anything.

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

Set `source: "apple-maps"` and `query` to the keyword on every object.

## What this actually returns

Measured on `Hotels in Kyiv`: name, category, full address, and coordinates on
every row; rating on a minority; never reviews, phone, or website. Addresses come
back in the local script (`Тараса Шевченка бульвар, 30, Київ`) — keep them as-is,
the CSV is UTF-8.

## Notes

- Apple returns the fewest rows of the five providers. If the user needs volume,
  `google-maps-scrape` or `openstreetmap-scrape` returns considerably more.
- Do not sign in to an Apple account, and do not enter credentials.
