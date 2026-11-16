# Buyer requests and public comparison evidence

Buyer requests accept public HTTP(S) listing links and automatically try to retrieve the item title and up to four product photos. The buyer reviews the imported views, signs in to their credit wallet, reserves one credit, and shares the capture invitation. LockX does not automatically message the seller. The reference photos are fixed for that request. The seller can record without an account or payment.

A pending invitation can be cancelled by its owner or declined by its capturer, and expires after 24 hours. Each path releases the hold once. Submitted evidence continues through the existing durable queue. Completed comparisons consume the credit, including mismatch or inconclusive results; technical failures restore it. Creation retries reuse a request key bound to the same normalized payload and image bytes. Existing seller flows, credit packs, payment providers, and queue budget remain in place.

## Sharing and evidence boundaries

Recording permission and public evidence sharing are separate choices. The sharing checkbox starts unchecked for every new capture session. Buyer requests require the seller to agree to sharing before recording; the seller may decline the invitation. Existing private recordings never gain public sharing through this release.

A consented physical-item publication can expose the original assessed video, approved reference photos, and only frames actually cited by the assessment. Failed or unclear reference photos remain private. Original photo/frame indices and recorded timestamps survive subset publication. Evidence records bind to the active publication, exact finished capture session, source media hashes, and saved permission. Withdrawal disables the public manifest and media. The public payload excludes management keys, capture tokens, owner identity, and the private analysis object.

Optional paired regions are AI proposals filtered by actual image correspondence and bounded geometric checks. Unsupported, repetitive, invalid, or ambiguous regions are omitted. These checks do not establish that a region's semantic description is correct and cannot promote a verification result. The viewer displays a saved reason and cited frames even when no region passes. There are no invented confidence percentages or fallback matching dots.

The result establishes visual correspondence at capture time. It does not certify authenticity, ownership, working condition, ticket validity, shipment, or camera provenance. Displaying evidence enables inspection; it does not establish an independently measured reduction in fraud.

## Loading and operation

The comparison manifest is small. Images load separately; the video source is attached only after play or timestamp selection. The original recording supports bounded 64 KB streaming and HTTP byte ranges instead of loading the entire video into application memory. Navigation tears down the viewer and playback. Mobile layouts were checked at 320, 390, and 736 pixels; landing header clearance was also checked at 1280 pixels.

This release retains the existing single persistent-volume SQLite instance and supervised worker queue. It does not add horizontal database scaling or certify 10,000 verifications per hour. Optional regions use the existing comparison call rather than an additional paid inference request. The existing hourly processing cap remains unchanged.

## Validation, 2026-11-16

- 593 offline backend tests passed in the complete local regression set, including the legacy local payment-sandbox harness. The harness is not deployed. New tests cover request replay/races, hold conservation, scoped cancellation/decline, consent, immutable publication/media binding, withdrawal, range errors, and real image geometry.
- 16 Node test entries passed across buyer request, Apple Pay, wallet loading, campaign attribution, and durable queue browser regressions.
- An isolated Chromium browser exercised buyer creation, credit reservation, separate seller consent, a real 10-second synthetic MediaRecorder upload, unavailable-provider handling, and exact credit restoration. Actual source video playback, frame seeking, paired detail crops, stable playback on photo changes, and no eager video download passed without JavaScript exceptions.
- A warm loopback benchmark made 120 read-only requests at concurrency five with zero errors. P95 times were 5.71 ms for capabilities, 8.42 ms for the public record, 10.47 ms for the evidence manifest, and 13.09 ms for the first 64 KB video range. These are local measurements, excluding internet/mobile networks, production load, payment latency, and real AI processing.

No real customer credits, live payments, or paid AI calls were used by these checks. Physical iPhone/Android recording, real-device Safari behavior, adversarial model accuracy, and high-volume production throughput remain unmeasured by this validation.

## Automatic photo import and the four-photo cap

All new verification requests accept one to four photos. Existing five/six-photo inspections retain their original evidence, capture compatibility, assessment schema and public records; they are not truncated. A fresh quality retry cannot copy more than four photos into a new request; already-created legacy retries remain recoverable. The ten-second recording and existing conservative verification rules remain unchanged.

Pasting a listing URL starts a free import before account sign-in. The importer reads public JSON-LD Product images, Open Graph image metadata, or a restricted product-gallery fallback, and returns normalized JPEG previews. It never opens a seller account, executes listing scripts, bypasses a login, or messages a seller. Blocked or script-only pages show a screenshot/photo fallback. The buyer can select/remove views and mix imported photos with manually supplied images, within four total. Failed imports preserve the current selection; stale replies cannot overwrite a different URL, route, edits, or a frozen creation retry.

A signed twenty-minute import snapshot binds the exact source URL, import time and normalized selected-image hashes. The server validates source provenance before holding a credit and saves the selected originals immutably with the request. Manual photos are not represented as automatically imported. Signing tokens are excluded from stored/public listing data. An application restart invalidates unused previews and requires a free reimport; already-created requests and their idempotent retries remain valid.

Network connections are pinned to validated public DNS addresses with the original Host and TLS identity. Every redirect and image URL passes the same policy; mixed private/public DNS answers are rejected. Imports use no cookies, credentials, environment proxies or external scraping service. Each import has a fourteen-second total deadline, two simultaneous image downloads, four retained photos, a 2 MB HTML limit and 5 MB per-image limit. Compressed responses are rejected rather than unboundedly decoded. Separate bounded DNS and image-decoder worker pools retain admission until native work really finishes, even after cancellation. Imported evidence uses the existing raster size/pixel limits. Importing and previewing never reserve or consume a credit.

Import release validation: 710 offline backend tests and 78 Node browser/camera regression entries passed. This includes 82 independent importer security cases, 20 four-photo/historical-compatibility cases, and 15 signed-import/credit-flow cases. A real local browser round trip imported four fixture photos, selected two, created a signed-source request and restored its held credit on cancellation, with no JavaScript exceptions or overflow at 320/390/1280 px. A public demonstration product imported one photo in 0.69 seconds; a separate product site blocked access and returned the fallback. These checks do not establish universal marketplace coverage or paid-model latency.

A 31-pair local benchmark using detailed 1600×1200 JPEG references measured cleaning at 57.35 ms for six versus 38.25 ms for four (33.3% less), and cold reference feature preparation at 60.16 versus 40.74 ms (32.3% less). These stages can overlap capture. Real network and AI response time were not measured; no overall percentage speedup is certified.
