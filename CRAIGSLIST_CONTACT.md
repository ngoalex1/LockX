# Automatic Craigslist seller contact

LockX opens the public listing's Reply → email controls in an anonymous browser, reads the visible `sale.craigslist.org` relay, and prefills the seller verification email. Discovery never sends an invitation. The buyer reviews the recipient/message and clicks Send.

## Runtime

The Railway API cannot create Chromium's required Linux sandbox namespaces. The optional remote mode therefore uses the existing Vercel project to orchestrate a fresh, nonpersistent Sandbox VM per lookup. Vercel OIDC stays in the orchestrator. The browser VM receives only trusted lookup code and the exact public listing URL; it receives no buyer account, payment, mail, photo, video, management-key, or API credentials.

The original `craigslist_contact.py` browser and pinned public-IP transport remain in use. Browser raw networking is denied, destinations are limited to Craigslist, TLS verification stays enabled, and all existing byte/request/time budgets apply. The VM adds an external Craigslist-only firewall. A clean dependency snapshot is accepted only after a nonroot user-namespace and sandboxed Chromium launch probe passes with network access denied. Each lookup VM is stopped/deleted before returning a valid result.

## Authorization and limits

Only server code can mint a 256-bit one-use lookup ticket. The API stores its hash and atomically consumes it at the fixed claim endpoint. Its binding includes the canonical URL, independent nonce, purpose, and 60-second expiry. Neither the public function nor the claim endpoint accepts a caller-selected URL or browser options. The API validates the entire bound result and requires a single valid Craigslist relay.

One lookup can be in flight. Initial admission is limited to 30 fresh attempts per hour. Errors or uncertain termination retain the lease until expiry. A normal contact failure preserves imported photos and does not use a verification credit.

Existing pending buyer requests can also refresh a missing contact while loading their private email draft. This requires remote mode, a pending/sendable draft, no existing contact, and no previous email attempt. Database access is closed before network work and the current recipient/state is rechecked afterward. A bounded short cache consolidates repeated reads. Refresh affects only the draft response: original photo provenance and imported timestamps remain unchanged.

## Setup and maintenance

1. Deploy the API ticket router and Vercel function. Remote mode stays off by default.
2. From trusted service setup code, mint `craigslist_remote.issue_ticket(public_listing_url, purpose='bootstrap')` and post its `ticket` to `https://lockx.ai/api/craigslist-contact` once. This prepares dependencies and performs the secure launch probe; it does not visit the listing.
3. Configure the returned clean snapshot ID using `LOCKX_CONTACT_SNAPSHOT_ID` on the Vercel function or its reviewed default constant. No credential is embedded in that ID.
4. Verify a direct remote lookup on the provided public listing, then set `LOCKX_CRAIGSLIST_CONTACT_MODE=remote` on Railway. Verify a free listing import retrieves four photos and the relay before calling the feature live.

Re-bootstrap when updating browser dependencies. The snapshot expires after 30 days without use. If Craigslist requires a login, CAPTCHA, or blocks contact access, the lookup stops; it does not solve or bypass the challenge.

Tests cover ticket replay/binding, bounded transport, auth before VM allocation, no secret propagation, secure launch requirements, VM cleanup, unchanged credit/send behavior, and old-draft recipient/cancellation races. Primary platform references: [Vercel Sandbox authentication](https://vercel.com/docs/sandbox/concepts/authentication), [firewall](https://vercel.com/docs/sandbox/concepts/firewall), [pricing and quotas](https://vercel.com/docs/sandbox/pricing).
