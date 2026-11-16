# Buyer requests and public comparison evidence

Buyer requests accept any public HTTP(S) listing URL as metadata. LockX does not fetch that page or automatically message its seller. The buyer selects 1–6 listing photos, signs in to their credit wallet, reserves one credit, and shares the capture invitation. The reference photos are fixed for that request. The seller can record without an account or payment.

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
