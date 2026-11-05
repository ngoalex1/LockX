# In-hand confirmed

The third LockX service connects exact listing photos to a guided mobile camera capture. The seller opens a private link in their browser, grants camera access, and follows changing instructions. No account, login, or native app is needed to create an inspection, complete capture, read results, publish an approved set, or download marked photos. The browser remembers an anonymous private access key. Each inspection also gets a separate private management link that works on another device. Keep that link: it controls access to the recording, results, and publication. Clearing browser storage removes the local list; the saved management link still works. A capture link cannot manage results or publish photos.

## Run locally

```sh
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python dev_server.py --port 8080
```

Open `http://127.0.0.1:8080/#in-hand`. This preview uses an isolated local identity, stores data in `.lockx-data/preview`, and disables paid analysis and messaging. It is loopback-only: a link containing `127.0.0.1` will not work on a different phone. Never deploy `dev_server.py` or its authentication override.

For actual phones, serve the frontend over HTTPS and point `window.LOCKX_API_BASE` to the deployed `/api/v1` service. The normal backend is `main:app`. Existing vault/recovery routes retain Supabase authentication; In-hand verification uses anonymous browser access and per-inspection management links. Allow the frontend origin in CORS. `LOCKX_DATA_DIR` must be a persistent volume. Set `LOCKX_PUBLIC_APP_ORIGIN` to the canonical website origin before creating QR-marked photos.

## Seller and buyer flow

1. Without signing in, select 1–6 exact listing photos (four is the suggested set), add optional per-photo details and listing claims, and create a private link. Client-side resizing limits image upload and decode work on phones.
2. Save the separate private management link for results. Copy or use the phone's Share control to deliver the capture link. This implementation does not send SMS. The capture link expires after 24 hours. Both links keep their secrets in the browser URL fragment; API access uses headers for management keys, which are stored hashed on the server. A management key cannot access another inspection, even if both were created on the same browser.
3. The seller consents, opens the rear camera, and records one take. Actions vary between attempts. Only the current instruction is returned. Each stage requires at least four seconds. Small items can be turned; flat items tilted; large appliances stay stationary while the phone moves. Digital tickets have a limited evidence mode.
4. A camera frame is checked for lighting/focus before advancing. When vision is configured, reference-photo stages can request another view of the photographed details. These checks are advisory: they do not approve the final set. Continuing past a warning is recorded and prevents automatic confirmation.
5. The browser uploads a video-only recording (no microphone). Recording is limited to two minutes and 60 MB. Upload progress and retry preserve the recording while the page remains open. An interrupted camera session requires a new take. Server-side decoding extracts evidence frames for the final comparison.
6. The report separates supported photo matches, contradicted evidence, and claims that cannot be established. Confirmation requires all selected photos, at least two distinct individual details, supported claims, followed actions, and no flagged evidence problems. Same-model appearance alone is insufficient. Digital tickets cannot earn the physical-item marking.
7. After a confirmed result, the owner explicitly chooses to publish the exact approved photos and item title. LockX generates marked JPEG copies with a record ID and QR code, downloadable together as a ZIP. Originals are preserved privately. Publication never exposes the private recording, owner identity, capture token, or written private details.
8. The public record displays the marked photo set and capture time. Withdrawal disables the public photos and leaves a withdrawn record at the QR destination. A withdrawn set requires a fresh inspection to publish again.

## Vision configuration and scope

`OPENAI_API_KEY` and a vision model enable photo planning, live advisory prompts, and final structured comparison. `LOCKX_IN_HAND_VISION_MODEL` overrides the existing `LOCKX_VISION_MODEL`; the existing model is reused when no override is set. Use a model available to your account that supports image input and structured output. In that mode, selected photos, live check frames, extracted video frames, and listing text are sent to OpenAI with `store: false`. No API key reaches the browser. Without configuration or when comparison fails, the result stays inconclusive and cannot be published or marked.

The implementation compares sampled frames; it does not run video-wide forensic analysis or establish a tamper-proof camera origin. Browser timing, randomized actions, media hashes, and rejecting an identical reused recording are useful evidence checks, not protection against every injected stream, edited or re-encoded replay, or synthetic video. There is no LiDAR capture or depth claim.

“LockX In-hand verified” refers to visual correspondence at the recorded time. It is not a certificate of product authenticity, legal ownership, current possession, internal working condition, ticket validity, transfer rights, or shipment. The public record and photo marking must preserve that scope.

## Deployment and validation remaining

This is an initial implementation, not a validated fraud-detection system. Before a public launch:

- Validate genuine and adversarial captures on physical iPhones and Android phones, including Safari/Chrome permissions, supported recording codecs, weak networks, and interrupted uploads. Camera capability is detected in the browser; a fallback explains unsupported browsers.
- Evaluate the configured vision model on known matches, visually identical units, altered listings, unreadable identifiers, replays, and synthetic inputs. The automated tests mock model outputs and do not establish model accuracy. Consider human review for ambiguous or high-value items.
- Move video storage and analysis to an object store and durable job queue for scale. Current SQLite/BLOB storage is intended for one persistent-volume instance; FastAPI background tasks can be interrupted on process exit. Failed/unavailable comparisons can be retried by the owner, but interrupted pending jobs need recovery.
- Set body-size and concurrency limits at the ingress, redact private capture-token paths from access logs, define retention/deletion and abuse controls, and align the privacy notice with external image processing and optional public publication.
- Add payment/billing and automatic message delivery separately if required. Neither is included here.

## Checks

```sh
.venv/bin/python -m pytest -q
node --check in-hand.js
```

The In-hand tests exercise account and anonymous access boundaries, per-inspection management-key isolation, immutable reference access, stage ordering/time limits, session restart, quality warnings, interactive follow-up, real video decoding, replay rejection, conservative result rules, publication consent, actual QR decoding, ZIP downloads, and withdrawal. Browser QA covers photo selection, link creation, seller preflight, and responsive layout. Physical camera recording and a paid live-model comparison have not been performed by these tests.
