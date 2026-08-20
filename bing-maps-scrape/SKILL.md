---
name: bing-maps-scrape
description: Search Bing Maps for a keyword (e.g. "Hotels", "pharmacies in Vienna") in the internal Claude browser and export the local-business results to a CSV file. Use when the user wants Bing Maps or Bing local listings collected into a spreadsheet.
---

# Bing Maps → CSV

**Verified live** (Aug 2026, `Hotels in Kyiv`): 17/17 rows with name, category,
rating, review count, and street address.

Drive the internal Claude browser (`mcp__Claude_Browser__*`) through a Bing Maps
search and save the result list into a CSV.

## Inputs

- **keyword** (required) — e.g. `Hotels in Vienna`.
- **output path** — default `./bing-maps-<slug>.csv`.
- **target count** — not adjustable. Bing returns **one fixed batch** (17 for the
  verified query) with no pagination and no lazy loading. Take what it gives.

## Workflow

1. **Open the search:**

   ```
   mcp__Claude_Browser__preview_start { url: "https://www.bing.com/maps?q=<url-encoded keyword>&setlang=en" }
   ```

2. **Resize to desktop** (`resize_window { preset: "desktop" }`) before extracting —
   these panels render only what fits.

3. **Wait ~5s.** Bing boots slowly. No cookie banner appeared on the verified run;
   if one does, choose the reject option rather than "Accept all".

4. **Extract.** The cards are `ol.b_split_cards_cont > li`. Anchor on the `b_`
   prefix — it is Bing's long-standing convention. The sibling class names
   (`listingItem_fPE1q`, `listingContent_fjvwG`) are hashed CSS-module names that
   rotate on deploy; **do not** select on those.

   ```js
   (() => {
     const out = [];
     document.querySelectorAll('ol.b_split_cards_cont > li').forEach(card => {
       const lines = card.innerText.split('\n').map(s => s.trim()).filter(Boolean);
       if (!lines.length) return;
       let rating = '', reviews = '', category = '';
       const rl = lines.find(l => /^\d+(\.\d+)?\/\d+/.test(l)) || '';
       if (rl) {
         const m = rl.match(/^([\d.]+)\/(\d+)\s*(?:\(([^)]+)\))?\s*(?:·\s*(.*))?$/);
         if (m) {
           const val = parseFloat(m[1]), scale = parseFloat(m[2]);
           // Bing mixes sources: TripAdvisor is /5, Booking.com is /10.
           // Normalise everything to a 5-point scale.
           rating = scale === 10 ? +(val / 2).toFixed(2) : val;
           reviews = m[3] || '';
           category = (m[4] || '').trim();
         }
       }
       const idx = rl ? lines.indexOf(rl) : 0;
       out.push({
         name: lines[0], category, rating, reviews,
         address: lines[idx + 1] || '',
         url: location.href, source: 'bing-maps', query: '<the keyword>',
       });
     });
     return JSON.stringify(out);
   })()
   ```

   If it returns `[]`, Bing restructured. Fall back to `get_page_text` and parse the
   plain-text list rather than guessing selectors.

5. **Two data traps, both confirmed live** — the snippet handles them; keep them:
   - **Mixed rating scales.** Rows come from different providers: `3.6/5 (1.3K)`
     next to `9.5/10 (953)`. Writing both raw would put incomparable numbers in one
     column *and* a 9.5 would be rejected by the 0–5 validator. Halve the /10 ones.
   - **Abbreviated review counts.** `(1.3K)` means 1300. Emit the raw `"1.3K"` —
     the validator expands K/M suffixes. Do not strip the letter yourself; digits
     only would read it as 13.

6. **Coordinates.** Not present in the card markup. Read them from the map URL
   (`?cp=<lat>~<lon>`) after clicking a result, or leave blank — blank is cheaper
   and fine. Only click through if the user asked for coordinates.

7. **Save.**

   ```bash
   uv run scripts/write_csv.py ./bing-maps-hotels.csv places.json
   ```

8. **Report** row count, output path, and that coordinates are absent by default.

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

Set `source: "bing-maps"` and `query` to the keyword on every object.

## What this actually returns

Measured on `Hotels in Kyiv`: name, rating, reviews, and a street address on every
row; category on roughly half (Booking.com-sourced rows omit it). No coordinates,
no phone, no website.

## Notes

- Rating normalisation is lossy in one direction: a `9.5/10` becomes `4.75`. If the
  user needs the original figure, say so rather than silently rescaling.
- Some regions redirect to a "not available" page. If so, say that plainly and
  suggest another provider skill.
