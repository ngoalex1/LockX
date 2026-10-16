# Continuous recovery watches

Owners enable monitoring from **Lost & Found → My reports → Set up six-hour monitoring**. A watch is due immediately and then every six hours after each completed attempt. It has no automatic expiry. Paused, archived, and recovered reports are excluded. Reference photos are required; external visual processing requires the owner's explicit consent.

## Deployment

The API now includes owner-scoped monitoring settings and `/api/v1/lost-found/recovery-alerts`. Deploy `main.py`, `recovery_monitor.py`, and the updated `lost-found.js` together. Keep the existing persistent volume. Set `LOCKX_RECOVERY_WORKER=1` on the API service to start its worker automatically with the service lifecycle. Alternatively run `python recovery_monitor.py --loop` as a persistent process sharing **the same SQLite volume**. A separate machine with its own disk will not see the watches. Keep the service running; an application process cannot run while its host is offline. There is no subscription billing or expiry logic in this implementation.

Set `OPENAI_API_KEY` and `LOCKX_VISION_MODEL` to enable actual photo-to-photo comparison. The worker sends two labeled image groups to the configured vision model: owner references and listing photographs. It asks for distinguishing wear, damage, engravings, and legible serials. Similarity is a model score, not a calibrated probability or proof of identity. A score at or above the owner's threshold (default .82), a distinctive identifying feature, and no clearly conflicting serial are all required to flag a candidate. Same model alone should not qualify. Evaluation against real labeled examples is still needed before treating thresholds as reliable production recall/precision.

In-app flags persist in the database. Optional email delivery uses `RESEND_API_KEY` and `LOCKX_ALERT_FROM` with a verified sending domain, plus the owner's notification email. Failed deliveries retry with backoff and a stable provider idempotency key. In-app flags remain available if email is unconfigured or fails. No live paid model calls or email messages were sent in development validation.

## Listing intake

An optional browser adapter in `marketplace_browser.py` reads normal public Craigslist and Facebook Marketplace search pages on each due run. Install its optional dependencies on the worker host:

```sh
pip install -r requirements-browser.txt
python -m playwright install chromium
```

Set `LOCKX_BROWSER_SEARCH=1`. Chromium runs with its sandbox enabled; the worker host must support that. This adapter uses no API keys, hidden endpoints, stealth plugins, proxies, login automation, or challenge bypass. It launches an isolated anonymous browser. If Facebook requires sign-in or either site blocks automation, that source reports an error and contributes no listings. Do not assume logged-in Facebook coverage from this public-page adapter. Its reliability is best-effort and requires operational monitoring; public UI access can change. Standard Playwright setup follows [the official library documentation](https://playwright.dev/python/docs/library).

Owner settings persist a ZIP and Craigslist radius plus an optional Facebook search URL. Facebook retains its own location filter; the runner does not claim ZIP/radius equivalence for Facebook. The adapter reads up to 100 search-page cards with two bounded scrolls, not every listing or every detail photo. Craigslist can append results outside the requested radius. Source status records this limited scope. The card extractor was verified against the open live pages (32 Craigslist cards, six with loaded images; 35 Facebook cards with images). The standalone Chromium runtime, scheduled live acquisition, and real-photo recognition still need deployment integration testing.

The worker also accepts existing official eBay connector credentials and optional normalized listing feeds. Sources remain `not_connected` if neither intake is configured. Missing sources produce `waiting_for_sources` or partial coverage instead of a successful full scan.

An operator's automated, authorized intake service can write normalized batches into `LOCKX_MARKETPLACE_FEED_DIR/craigslist.json` and `facebook_marketplace.json` using atomic file replacement. This is an integration boundary, not a recommendation that owners export listings by hand. An actual intake adapter is still required to refresh these files from its source. Example schema:

```json
{
  "fetched_at": 1792108800,
  "listings": [
    {
      "external_id": "source-stable-listing-id",
      "url": "https://marketplace.example/item/123",
      "title": "Rolex Submariner",
      "description": "Visible condition and identifying details",
      "image_urls": ["https://images.example/item123.jpg"],
      "price": "11985",
      "location": "San Jose, CA"
    }
  ]
}
```

`fetched_at` must reflect a successful source fetch in Unix seconds, within the last six hours; future timestamps beyond five minutes and stale feeds are rejected. Batches are capped at 500 listings and 5 MB, with up to four HTTPS photos per listing. Feed retrieval must apply the intended query/location filters: this feed boundary accepts a shared batch and compares candidates against each watch’s references. Do not claim local coverage from a broad feed. Browser queries use the stored ZIP/radius for Craigslist; Facebook filters remain separate.

## Reliability and limits

Jobs, leases, candidates, errors, source coverage, and alerts survive restarts. Expired claims can be recovered. A source failing does not discard the others. Changed listing content, reference photos, model, or threshold triggers comparison again. Unchanged candidates avoid repeat model calls; failed comparisons retry on the next due run. At most 100 comparisons run per watch per attempt; remaining candidates can be processed in subsequent runs. One durable alert per source/listing/report prevents repeat notifications. This policy does not send a fresh alert for each subsequent edit of an already flagged listing. Flags that no longer meet the threshold are omitted from the current inbox.

The scheduler checks due work every minute and uses elapsed six-hour intervals; long runs, a large queue, or downtime can delay execution. A crash can leave a lease for up to 30 minutes. Run on one persistent-volume host; use a managed shared database/queue before scaling to multiple machines. A larger deployment also needs bounded storage retention, calibrated matching evaluation, notification bounce handling, and operational monitoring. The standalone scheduled browser runtime and live provider delivery have not been validated.

## Tests

`python -m pytest -q test_recovery_monitor.py test_lost_found.py test_digital_vault.py test_marketplace_search.py`

Tests simulate new candidates a year later, unchanged duplicates, six-hour due times, crashed leases, paused/recovered reports, ownership boundaries, missing references/consent, conflicting serials, comparison retries, source failures, stale feeds, and email retry behavior. Live marketplace access and real-photo recognition quality require separate integration validation.

## Local configuration prepared on this Mac

Playwright 1.64.0 and its Chromium runtime are installed in `/Users/ngo/Documents/ChatGPT/LockX.ai/.venv`. A private, Git-ignored `.env.recovery` beside this document contains local worker settings and the selected `gpt-4.1` vision model. Add an OpenAI project API key to its `OPENAI_API_KEY` entry. The file is readable/writable only by its owner (mode 0600). Existing process environment variables take precedence over file values.

From this checkout:

```sh
/Users/ngo/Documents/ChatGPT/LockX.ai/.venv/bin/python recovery_monitor.py --env-file .env.recovery --preflight
/Users/ngo/Documents/ChatGPT/LockX.ai/.venv/bin/python recovery_monitor.py --env-file .env.recovery --check-vision
/Users/ngo/Documents/ChatGPT/LockX.ai/.venv/bin/python recovery_monitor.py --env-file .env.recovery --loop
```

Preflight checks package/browser installation and credential presence; it does not prove browser launch, source access, or API-key validity. `--check-vision` makes one small billable request with two synthetic images and validates the response schema. It does not evaluate real-item matching accuracy. The loop refuses to start when required configuration is missing. Local worker data must be shared with the local API; this settings file does not connect to production Railway storage. The isolated `dev_server.py` preview deliberately disables paid vision and background work.

## Visible work and activity receipts

The recovery dashboard now includes an animated workflow plus owner-scoped, persisted work totals: listing checks (including repeated checks on later runs), completed photo comparisons, unchanged candidates skipped, and unique close-match flags. The animation is explicitly an illustration; it is not evidence of live scanning. Readiness is backed by a worker heartbeat every 30 seconds. The displayed activity refreshes every minute while the owner is viewing Lost & Found. Reduced-motion preferences and a pause control are supported.

Every due run records its start, completion, outcome, source statuses, counts, and failures in `recovery_runs`. Totals include actual recorded work only, and source failures remain visible. Empty accounts show zero work; no simulated throughput is added. Scan receipts, next due time, and worker check-in are returned only to the authenticated report owner. These metrics do not establish complete marketplace coverage.
