# LockX Lost & Found

The feature extends the existing LockX frontend and FastAPI service. Existing
Supabase sign-in remains the account authority. Lost & Found records use a new
SQLite database and do not change the existing watch-case schema.

## Local preview

Use Python 3.11 or newer:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python dev_server.py --demo
```

Open `http://127.0.0.1:8080/#lost-found`. The preview binds only to loopback,
substitutes a local preview identity, disables live MMS and image analysis, and
stores sample reports in `.lockx-data/preview`. Never deploy `dev_server.py`.
Omit `--demo` to skip inserting sample records; an existing preview database is
retained between runs. The ordinary production entrypoint remains `main:app`.

## Included workflows

- Missing-item reports across watches, jewelry, electronics, cameras, bikes,
  bags, and other items. Serial numbers, private identifying evidence, and police
  references are excluded from public API responses.
- Owner-controlled publication, searchable listings, category filters, reference
  photos, and shareable report links (`?item=REPORT_ID#lost-found`).
- Owners can edit details and reward pledges, archive a report, and restore an
  archived report. Revision checks prevent overwriting another window's edits.
  Returned reports are preserved. Changed identifying evidence resets prior
  ownership attestations; invalidated matches lose access to finder photos/contact.
- A finder responding to a specific public listing can send a photo-only lead
  directly to that listing's owner. The lead is explicitly unverified and scores
  only 20 without corroborating identifiers. Private/archived listings cannot be
  targeted. Shared report links fetch the selected report even beyond list limits.
- An owner-only activity log records report changes and match review transitions.
  A downloadable JSON evidence packet includes private owner details, current
  leads, activity, and sanitized reference-photo hashes. Unverified finder contact
  details and provider media URLs are excluded. Image files are not embedded.
- Adjustable reward percentage, defaulting to 30%, calculated in USD cents.
  Rewards are pledges only; there is no funding, escrow, or payout integration.
- Anonymous finder photo submission at `#found`: 1–4 JPEG, PNG, or WebP images,
  up to 5 MB each. Images are decoded, resized, and re-encoded without EXIF
  metadata before storage. Public report photos are public by the owner's choice;
  finder photos remain accessible only to owners with a matching report.
- Explainable matching using exact normalized serials, category, brand, model,
  color, and description signals. Conflicting nonempty serials suppress matches.
  Scores rank evidence; they are not calibrated probabilities or proof of ownership.
- Finder reports submitted before a missing report are matched again when a new
  report is created. Match inbox refresh is manual in this release.
- Review, dismissal/reopening, recorded ownership verification, and confirmed
  return. Returns remove the report from public discovery. Verification is
  owner-attested, not a LockX independent certification.

## Production configuration

Copy the relevant names from `.env.example` into the service host's secret/env
configuration. Keep secrets server-side. Run:

```sh
uvicorn main:app --host 0.0.0.0 --port 8000
```

Deploy the frontend files alongside the updated `app.js`, `index.html`, and CSS.
The frontend retains the current Railway API origin by default; a hosting page
can set `window.LOCKX_API_BASE` before loading `app.js` to use a different origin.
Configure CORS origins in `main.py` if changing frontend hosting.

Attach a Railway persistent volume at `/data`. The service automatically uses
`RAILWAY_VOLUME_MOUNT_PATH/lockx`. Alternatively, set `LOCKX_DATA_DIR` to a
**persistent volume**, such as `/data/lockx`. On Railway, storage requests fail
closed with HTTP 503 if neither location is configured. Back it up
with normal access-controlled database backups. The database contains private
evidence and contact details; use host disk encryption and restrict volume access.
One service instance can use this database; migrate to a shared database/object
store and queue before scaling across machines. Configure request-size limits,
trusted proxy handling, abuse controls, retention/deletion, and operational
monitoring at the hosting layer before a public launch. Anonymous intake currently
has SQLite-backed hourly peer-IP limits; an additional edge limit is recommended.

### Photo identification

Set both `OPENAI_API_KEY` and `LOCKX_VISION_MODEL` to enable the Responses API
adapter. Select a vision-capable model available to the account that supports JSON
output. Only sanitized finder photos are sent; `store` is false. Owner private
evidence, receipts, account identity, and contact details are not sent to the model.

The model extracts visible item attributes; matching compares those attributes
against submitted records. This release does not implement visual embeddings or
direct comparison of owner/finder photographs. Human review is always required.
Without credentials, photos are saved and submitted serial/text details can still
produce matches. The UI labels these as manual review. Analysis failures preserve
the submission and mark it for review/retry.

Implementation references: [OpenAI image input](https://developers.openai.com/api/docs/guides/images-vision)
and [JSON output](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses).

### Text-a-photo intake

Configure an MMS-capable Twilio number and set:

- `TWILIO_ACCOUNT_SID`
- `TWILIO_AUTH_TOKEN`
- `LOCKX_MMS_NUMBER` (E.164 format)
- `LOCKX_MMS_WEBHOOK_URL` (the exact externally visible HTTPS URL)

In Twilio, set the incoming messaging webhook to POST to:

`https://YOUR-API-HOST/api/v1/lost-found/webhooks/twilio`

The handler validates Twilio's signature using its SDK, checks the account and
receiving number, deduplicates message SIDs, acknowledges photos, and accepts
location/context replies for 24 hours. Configure Twilio opt-out handling for the
number. This release sends immediate TwiML replies only; automated owner alerts,
asynchronous finder updates, and two-way owner/finder messaging are future work.
MMS finder phone numbers are not stored; a keyed sender digest groups follow-ups.

Media is fetched with server credentials only from the configured account's
`api.twilio.com` media paths, with redirects disabled. If a media delivery requires
a redirect or an unsupported format, it is retained as `media_failed` for operator
review rather than fetching an untrusted destination. Test actual carrier delivery
before enabling the advertised number. Country/carrier coverage varies.

References: [Twilio signature validation](https://www.twilio.com/docs/usage/security)
and [media retrieval](https://www.twilio.com/docs/messaging/api/media-resource).

### Background-job recovery

The service acknowledges MMS before downloading/analyzing the attachments.
Web uploads are saved before analysis. Pending records survive restarts. Run this
with the same persistent volume and environment to drain pending work:

```sh
python lost_found_worker.py
```

For deliberate retries after resolving a provider issue:

```sh
python lost_found_worker.py --retry-failed
```

Stop active processing before resetting stuck jobs with `--retry-failed`. Retrying
may generate new paid vision requests. A durable external queue with leases,
scheduled retry/backoff, dead-letter review, and notifications should replace this
single-instance recovery helper for a larger deployment.

## API routes

All routes are under `/api/v1/lost-found`:

| Method | Path | Access |
| --- | --- | --- |
| GET | `/capabilities` | Public integration status; no credentials |
| GET | `/public` | Redacted active published reports |
| GET | `/public/photos/{id}` | Active published reference photos |
| GET | `/public/reports/{id}` | One redacted active published report |
| GET / POST | `/reports` | Authenticated owner |
| PATCH | `/reports/{id}` | Owner; full details and expected revision |
| PATCH | `/reports/{id}/status` | Owner; archive/restore with expected revision |
| GET | `/reports/{id}/activity` | Owner activity history |
| GET | `/reports/{id}/evidence` | Owner-only JSON evidence attachment |
| POST | `/sightings` | Anonymous multipart photo intake |
| GET | `/matches` | Only matches for the authenticated owner's reports |
| PATCH | `/matches/{id}` | Owner; transition and evidence checks |
| GET | `/photos/{id}` | Owner-scoped reference/finder photo |
| POST | `/webhooks/twilio` | Valid Twilio signature and configured account |

Multipart requests use a JSON `payload` field and repeated `photos` file fields.
Finder payloads optionally include `target_report_id`. Edit requests use JSON
`{"report": { /* ReportInput fields */ }, "expected_revision": 1}`. Existing
photos remain attached when editing. Status changes use JSON
`{"status": "archived", "expected_revision": 1}`.

Opening `index.html` directly as a `file://` URL displays instructions to start
the HTTP preview. It does not enable preview identity or send Lost & Found API
requests to production from that local file.

## Validation

```sh
.venv/bin/pip install pytest
.venv/bin/python -m pytest -q
```

Tests cover redaction, account/photo isolation, publication, reward arithmetic,
anonymous intake, serial conflicts, matching older finder reports, verification
transitions, malformed uploads, rate limiting, provider-status truthfulness,
signed/deduplicated MMS, untrusted media URLs, and mocked vision extraction.
External providers are mocked; no paid requests or real SMS are sent by tests.
