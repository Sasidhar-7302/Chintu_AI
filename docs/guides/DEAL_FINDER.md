# Deal Finder (Price Compare)

Chintu includes a dedicated `deal_finder` capability for comparing prices in a read-only way.

Why it exists:
- General browser automation (`browser_pilot`) can be impacted by shopping-site anti-bot flows.
- For price checks, deterministic extraction is faster, cheaper, and easier to verify.

## What It Does

- Searches trusted retailers for your query:
  - Amazon
  - Newegg
  - Best Buy
  - B&H Photo
  - Micro Center
  - Walmart
- Optional: trusted web expansion (`include_web_search=true`) using an allowlist + JSON-LD product parsing.
- Extracts top listings (title, price, shipping when available).
- Returns a Markdown table with links.
- Writes evidence artifacts into the current run (when a `run_id` exists).

Safety guarantees:
- Read-only browsing and parsing.
- Never proceeds to checkout.
- Never performs payments.

## Examples

- "I need a new 2TB NVMe SSD. Find the best price on Amazon and Newegg right now."
- "Find best deal for 2TB NVMe SSD from legit websites right now."
- "Deal finder: Logitech MX Master 3S"
- "Compare RTX 4060 vs RX 7600 and tell me which has the lowest current deal."

Structured invocation (schema):

```json
{
  "query": "2TB NVMe SSD",
  "vendors": ["amazon", "newegg", "bestbuy", "bhphoto", "microcenter", "walmart"],
  "include_web_search": true,
  "max_results_per_vendor": 6,
  "max_web_results": 8
}
```

## Price Tracking

Chintu can persist a recurring deal watch and alert on drops:

- `deal_watch_add` creates a watch and schedules recurring checks.
- `deal_watch_list` lists current watches.
- `deal_watch_remove` removes a watch and cancels its schedule.
- `deal_watch_run` runs one watch immediately (used internally by scheduler).

Natural-language examples:

- "Track price for 2TB NVMe SSD under $120 every 3 hours."
- "List price watches."
- "Remove price watch ab12cd34."

## Product Comparison Mode

If your query includes comparison language (`vs`, `versus`, `compare`, `which is better`),
Deal Finder automatically switches to multi-product mode:

- Runs independent deal scans for each product.
- Ranks products by current best total price.
- Returns a compact comparison table with links and listing coverage.

Example:

- "Compare iPhone 15 vs Pixel 8 vs Galaxy S24 for current best deal."

## Reliability Notes

- Deal Finder uses Requests first.
- Requests uses bounded retries for transient HTTP/network failures (e.g., 429/503 timeouts).
- If Requests is blocked (captcha/robot check), it can fall back to Playwright to fetch the same search page HTML and parse it.
- For Amazon/Newegg status-code failures (for example HTTP 503), Deal Finder now attempts Playwright fallback before returning `n/a`.
- `skill::price-compare` performs one bounded trusted-web retry automatically when requested vendors return no priced rows.
- Some shopping sites may still block automated traffic even in a real browser. In those cases, Chintu will report the block and provide direct links you can open manually.
- Web expansion is restricted to trusted domains to avoid low-quality/scam listings.

## Evidence

When running under the run manager, Deal Finder writes artifacts such as:

- `deal_finder_<timestamp>.json`
- `deal_finder_<timestamp>.md`

These are useful for debugging, audits, and later training.
