---
name: mapy-scrape
description: Search Mapy.com (formerly Mapy.cz) for a keyword such as "Hotels" in the internal Claude browser and export the found places to a CSV file. Use when the user wants Mapy.com / Czech map listings collected into a spreadsheet.
---

# Mapy.com → CSV

**Verified live** (Aug 2026, `Hotels in Prague`): 15/15 rows with name, category,
full address, **phone, and website** — the richest contact data of the five
providers.

## Inputs

- **keyword** (required) — e.g. `Hotels in Prague`. Coverage is richest in Czechia
  and Slovakia.
- **output path** — default `./mapy-<slug>.csv`.
- **target count** — 15 per page; scroll the panel for more.

## Workflow

1. **Open the search:**

   ```
   mcp__Claude_Browser__preview_start { url: "https://mapy.com/en/zakladni?q=<url-encoded keyword>" }
   ```

   Use `mapy.com/en/…`. **`en.mapy.com` does not resolve** — it fails navigation.

2. **Resize wide before extracting:** `resize_window { width: 1440, height: 900 }`.
   Below roughly 800px Mapy collapses the results panel into a bottom search bar.
   (The rows still exist in the DOM, but you cannot see or scroll them.)

3. **Handle the cookie dialog.** A Seznam CMP appears with **Refuse** / **Agree** /
   *Detailed settings*. Choose **Refuse**.

   It is **not in the accessibility tree** — `read_page` and `find` will not see it,
   so you cannot click it by `ref`. Take a `screenshot` and click the Refuse button
   by `coordinate`. Verify with a second screenshot that the dialog is gone.

   Note the map renders *behind* the dialog either way, so a visible map is not
   evidence the dialog was dismissed.

4. **Extract.** Rows are `ul > li > a.li-inner[href*="source=firm"]`:

   ```js
   (() => {
     const out = [];
     document.querySelectorAll('ul > li > a.li-inner[href*="source=firm"]').forEach(a => {
       const t = (s) => a.querySelector(s)?.textContent.trim() || '';
       const name = t('h3'); if (!name) return;
       const cat = t('.type-name');
       const ps = [...a.querySelectorAll('p')].map(p => p.textContent.trim()).filter(Boolean);
       let site = a.querySelector('a.www')?.href || '';
       try {                       // strip Mapy's utm_* tracking parameters
         const u = new URL(site);
         [...u.searchParams.keys()].filter(k => k.startsWith('utm_'))
           .forEach(k => u.searchParams.delete(k));
         site = u.href;
       } catch {}
       out.push({
         name, category: cat,
         address: ps.find(p => p !== cat) || '',
         phone: t('.phone'),
         website: site,
         url: a.href,
         source: 'mapy.com', query: '<the keyword>',
       });
     });
     return JSON.stringify(out);
   })()
   ```

   `.li-inner`, `.type-name`, `.phone`, and `a.www` are all confirmed stable and
   semantic. If the snippet returns `[]`, check step 2 first — a collapsed panel is
   the likeliest cause, not a selector change.

5. **More results.** Scroll the results panel (`computer { action: "scroll" }` with
   the pointer over the list), re-extract, and repeat until the count stops growing.

6. **Coordinates.** Not in the list markup. Selecting a result puts them in the URL
   as `?x=<lon>&y=<lat>&z=<zoom>` — note **x is longitude, y is latitude**. Only
   click through if the user wants coordinates; otherwise leave blank.

7. **Save.**

   ```bash
   uv run scripts/write_csv.py ./mapy-hotels.csv places.json
   ```

8. **Report** row count, output path, and that ratings/coordinates are absent.

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

Set `source: "mapy.com"` and `query` to the keyword on every object.

## What this actually returns

Measured on `Hotels in Prague`: name, category, and full address on every row;
phone and website on most. No ratings or review counts in the list (Mapy shows
ratings on the map pins only), and no coordinates.

Phone numbers come in local Czech format (`222 500 177`, 9 digits) and pass the
validator's phone check. Do not add a country code that was not scraped.

## Notes

- Outside Czechia/Slovakia results thin out fast — if the user is searching a
  Western European or US city, say another provider will likely return more.
- Czech pages: `hodnocení` = rating count, `Otevřeno` = open now. Keep scraped
  values as-is; do not translate data written to the CSV.
