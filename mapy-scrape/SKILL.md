---
name: mapy-scrape
description: Search Mapy.com (formerly Mapy.cz) for a keyword such as "Hotels" in the internal Claude browser and export the found places to a CSV file. Use when the user wants Mapy.com / Czech map listings collected into a spreadsheet.
---

# Mapy.com → CSV

**Verified live** twice (Aug 2026): `Hotels in Prague` → 15/15 rows with name,
category, full address, **phone, and website**; `University in Kyiv` → **75 rows
across 5 pages**. Mapy paginates — see step 5, which is the single easiest thing
to get wrong here.

## Inputs

- **keyword** (required) — e.g. `Hotels in Prague`. Coverage is richest in Czechia
  and Slovakia.
- **output path** — default `./mapy-<slug>.csv`.
- **target count** — 15 per page, **paginated**. Page until the list comes back
  empty. Scrolling the panel loads nothing; only the pager advances.

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

4. **Extract.** Rows are `a.li-inner`. Do **not** filter on `source=firm`: business
   records from Firmy.cz use `?source=firm&id=…`, but OSM-derived POIs (most
   non-commercial results — universities, schools, institutes) use `?source=osm&id=…`.
   An earlier version of this skill filtered on `firm` and returned **zero rows** for
   a university search. Key the accumulator on `a.href`, which is unique either way:

   ```js
   (() => {
     const out = [];
     document.querySelectorAll('a.li-inner').forEach(a => {
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
   semantic across both verified runs. If the snippet returns `[]`, the cause is
   almost never a selector change — check, in order: (a) you read once and got a
   throttled stale result (step 5), (b) the panel is collapsed (step 2), (c) the
   cookie dialog is still up (step 3).

5. **Page through the results — this is where rows go missing.**

   Mapy shows 15 per page and has a `<button>` whose text is `next` at the bottom of
   the panel. Clicking it also updates the URL to `…&pg=N`, so the current page is
   readable from `new URL(location.href).searchParams.get('pg')`.

   **The trap:** the Browser pane runs the tab with `document.visibilityState ===
   "hidden"`, so Mapy's rendering is throttled. After each page change the *first*
   `javascript_tool` read routinely returns **0 rows while a screenshot clearly shows
   15**. That is not a selector change and not the end of the results — it is a
   stale read. Re-read before drawing any conclusion.

   Loop, accumulating in `sessionStorage` (it survives the SPA's URL updates), and
   read twice per page:

   ```js
   (() => {
     const KEY = '__mapyAcc';
     const acc = JSON.parse(sessionStorage.getItem(KEY) || '{}');
     document.querySelectorAll('a.li-inner').forEach(a => {
       const t = s => a.querySelector(s)?.textContent.trim() || '';
       const name = t('h3'); if (!name) return;
       const cat = t('.type-name');
       const ps = [...a.querySelectorAll('p')].map(p => p.textContent.trim()).filter(Boolean);
       acc[a.href] = { name, category: cat,
         address: ps.find(p => p !== cat && !/review|hodnocen/i.test(p)) || '',
         phone: t('.phone'), website: a.querySelector('a.www')?.href || '', url: a.href };
     });
     sessionStorage.setItem(KEY, JSON.stringify(acc));
     const b = [...document.querySelectorAll('button')]
       .find(x => x.innerText.trim().toLowerCase() === 'next' && !x.disabled);
     if (b) b.click();                       // advance only after harvesting
     return JSON.stringify({ pg: new URL(location.href).searchParams.get('pg'),
       onPage: document.querySelectorAll('a.li-inner').length,
       total: Object.keys(acc).length, clickedNext: !!b });
   })()
   ```

   Between pages: `computer { action: "wait", duration: 10 }` (max allowed is 10),
   then run the snippet. **If `onPage` is 0, run it again before deciding anything** —
   it usually returns 15 on the second call.

   Stop only when a re-read still shows `onPage: 0` **and** `h3` count is 0 **and**
   there is no enabled `next` button. All three together mean the last page is past
   the end. Verified: `University in Kyiv` ran pages 1–5 (75 rows) with page 6 empty.

   Finally, read the accumulator out:

   ```js
   JSON.stringify(Object.values(JSON.parse(sessionStorage.getItem('__mapyAcc')||'{}')))
   ```

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
phone and website on most. Measured on `University in Kyiv` (75 rows): name,
category, and address on every row, but **phone and website on none** — those come
from Firmy.cz business records, so OSM-sourced results carry neither. No ratings,
review counts, or coordinates in the list either way.

Phone numbers come in local Czech format (`222 500 177`, 9 digits) and pass the
validator's phone check. Do not add a country code that was not scraped.

## Notes

- Outside Czechia/Slovakia results thin out fast — if the user is searching a
  Western European or US city, say another provider will likely return more.
- Czech pages: `hodnocení` = rating count, `Otevřeno` = open now. Keep scraped
  values as-is; do not translate data written to the CSV.
