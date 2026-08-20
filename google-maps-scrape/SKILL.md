---
name: google-maps-scrape
description: Search Google Maps for a keyword (e.g. "Hotels", "coffee in Berlin") in the internal Claude browser, page through the results feed, and export the found places to a CSV file. Use when the user wants Google Maps listings, local business results, or place data collected into a spreadsheet.
---

# Google Maps → CSV

Drive the internal Claude browser (`mcp__Claude_Browser__*`) through a Google Maps
search and save every result row into a CSV.

Selectors below were verified live against Google Maps (Aug 2026, `hl=en`).

## Inputs

- **keyword** (required) — e.g. `Hotels in Prague`.
- **output path** — default `./google-maps-<slug>.csv`.
- **target count** — default: page until exhausted or ~120 rows.

## Critical setup — do these first

Two things dominate how many results you get. Both are easy to miss:

1. **Resize the viewport to desktop before extracting.**
   ```
   mcp__Claude_Browser__resize_window { preset: "desktop" }
   ```
   Google renders only what fits. In a small pane the feed yields **1 result**; at
   desktop width the same query yields **19**. This is the single biggest lever.

2. **Always put a location in the keyword.** A bare `Hotels` triggers Google's
   hotel/travel UI *and* often a "You're seeing a limited view of Google Maps"
   notice that caps the feed at one card. `Hotels in Kyiv` does not. If the user
   gives a bare keyword, ask for a city or infer it from context and say what you used.

## Workflow

1. **Open the search** with the query URL-encoded into the path:

   ```
   mcp__Claude_Browser__preview_start { url: "https://www.google.com/maps/search/Hotels+in+Kyiv?hl=en" }
   ```
   (Use `navigate` if the Browser pane is already open.) Then resize to desktop.

2. **Handle consent.** If a cookie dialog appears, pick the privacy-preserving
   option ("Reject all"), not "Accept all". Click it by `ref` from `read_page`.

3. **Wait and verify.** `computer { action: "wait", duration: 4 }`, then check state:

   ```js
   (() => { const f = document.querySelector('div[role="feed"]');
     return JSON.stringify({ feed: !!f,
       n: document.querySelectorAll('a[href*="/maps/place/"]').length,
       limited: /limited view/i.test(document.body.innerText) }); })()
   ```

   If `limited` is true, the query is too generic — add a location and reload.

4. **Fill the current page** by scrolling the feed element (not the window):

   ```js
   (async () => { const f = document.querySelector('div[role="feed"]'); const log = [];
     for (let i = 0; i < 6; i++) { f.scrollTop = f.scrollHeight;
       await new Promise(r => setTimeout(r, 2000));
       log.push(document.querySelectorAll('a[href*="/maps/place/"]').length); }
     return JSON.stringify(log); })()
   ```

   Stop when the count stops growing — it plateaus at ~19–20, which is one full page,
   **not** the end of the results.

5. **Extract** (verified: 19/19 rows, names, ratings, review counts, coordinates):

   ```js
   (() => {
     const phoneOf = (card) => {
       for (const line of card.innerText.split('\n').map(s => s.trim())) {
         if (!/^\+?[\d][\d\s\-()]{7,}$/.test(line)) continue;
         if ((line.match(/\d/g) || []).length < 9) continue;
         return line;
       }
       return '';
     };
     const looksAddress = (s) => /\d/.test(s) && /(St|Str|Ave|Rd|Blvd|Ln|вул|просп|,)/i.test(s);
     const out = [];
     document.querySelectorAll('div[role="feed"] > div > div[jsaction]').forEach(card => {
       const link = card.querySelector('a[href*="/maps/place/"]'); if (!link) return;
       const name = card.querySelector('.qBF1Pd')?.textContent
                    || link.getAttribute('aria-label') || '';
       if (!name.trim()) return;
       const meta = [...card.querySelectorAll('.W4Efsd > .W4Efsd > span')]
         .map(s => s.textContent.trim()).filter(Boolean);
       const rest = meta.slice(1).map(s => s.replace(/^[·\s]+/, '')).filter(Boolean);
       const m = link.href.match(/!3d(-?[\d.]+)!4d(-?[\d.]+)/)
                 || link.href.match(/@(-?[\d.]+),(-?[\d.]+)/);
       out.push({
         name,
         category: meta[0] || '',
         address: rest.filter(looksAddress).join(', '),
         rating: card.querySelector('.MW4etd')?.textContent || '',
         reviews: card.querySelector('.UY7F9')?.textContent || '',
         phone: phoneOf(card),
         website: [...card.querySelectorAll('a[href^="http"]')]
           .map(a => a.href).find(h => !h.includes('google.')) || '',
         latitude: m ? m[1] : '', longitude: m ? m[2] : '',
         url: link.href, source: 'google-maps', query: '<the keyword>',
       });
     });
     return JSON.stringify(out);
   })()
   ```

   Two traps this snippet already avoids — do not "simplify" them back:
   - A naive `innerText.match(/\+?[\d][\d\s\-().]{7,}\d/)` phone regex matches the
     **rating line**, producing garbage like `4.4(137)`. Hence `phoneOf`.
   - The second `.W4Efsd` span is often a *description* ("Upmarket hotel with dining
     & a bar"), not an address. Hence `looksAddress`; leaving `address` blank is
     correct and better than storing a description there.

   If it returns `[]`, Google changed its class names. Fall back to `get_page_text`
   and parse the block per listing rather than guessing new selectors.

6. **Next page.** The feed does **not** infinite-scroll past ~20. There is a
   `button[aria-label="Next page"]`. Click it, then **wait 5s and verify** the first
   card name changed before extracting again:

   ```js
   (() => { const b = document.querySelector('button[aria-label="Next page"]');
     if (!b || b.disabled) return 'no more pages';
     const before = document.querySelector('.qBF1Pd')?.textContent;
     b.click(); return JSON.stringify({ before }); })()
   ```

   A programmatic `.click()` does work here, but the swap can take **more than 3
   seconds** — do not conclude pagination failed from an early re-read. If the first
   name is unchanged after ~8s, click by `ref` via `computer` instead. Accumulate
   rows across pages and stop when the button is gone/disabled or the target is met.

7. **Save.** Write the accumulated JSON array to a scratch file, then:

   ```bash
   uv run scripts/write_csv.py ./google-maps-hotels.csv places.json
   ```

   Use `--append` to merge further pages or providers into an existing file; it
   de-duplicates against rows already there.

8. **Report** the row count, the output path, and which columns came back empty.

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

Set `source: "google-maps"` and `query` to the keyword on every object. Emit raw
scraped strings — the validator coerces and range-checks them; do not pre-clean by
hand.

## What this actually returns

Measured on `Hotels in Kyiv`: name, category, rating, reviews, latitude, longitude
populated on **every** row. `address` on a minority. `phone` and `website` on
essentially none — Google's hotel cards do not carry them. Filling those means
opening each place page (one navigation per row); offer it, but only do it on request.

## Notes

- Results are viewport-biased. Put the city in the keyword rather than panning the map.
- Non-Latin names come back correctly (`Мережі хостелів Likehostel`) — the CSV is
  UTF-8; do not transliterate.
- If Google serves a CAPTCHA, stop. Do not attempt to solve it — save the rows
  already collected and tell the user.
