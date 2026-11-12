# LockX verification credits

One item verification costs one credit, including up to six selected photos and one 10-second recording. The packs are $5/10 credits, $10/20 credits, and $20/40 credits. All packs cost 50 cents per verification. There is no subscription or automatic renewal. New $1/2-credit checkouts are retired; existing purchases and their refund records retain their original amounts and credits.

## Implementation

`credit_wallet.py` owns balances, purchases, refunds and inspection reservations. It uses the same SQLite database and persistent Railway volume as In-hand evidence. `credit-wallet.js` supplies the public pricing and passwordless email wallet. Supabase authenticates the owner; browser balances and return query parameters cannot grant credits.

The server prices checkouts and verifies actual PayPal payment, amount, currency, recipient and checkout reference. Payment IDs and ledger references deduplicate callbacks. Each completed comparison consumes one credit even if the outcome is mismatch or inconclusive. Failed processing restores the credit; a technical retry reserves it again. The existing server-approved one-time quality retry is included. Viewing results and exporting approved images are free.

PayPal Payment Links are reusable. Each link belongs to its creating LockX account; a distinct completed payment on that link adds the same pack to that owner. Do not share a checkout link as a general store link. Direct Apple Pay and Google Pay use PayPal Orders and owner-scoped server capture. Eligible signed-in customers see Apple Pay above the PayPal/card fallback, without visiting the hosted checkout's extra-options menu.

## Server configuration

Store credentials only in Railway service variables, never in this repository or frontend assets.

| Variable | Purpose |
| --- | --- |
| `LOCKX_CREDITS_ENABLED` | Master rollout flag; absent or `0` preserves existing free checks and hides the wallet |
| `PAYPAL_ENVIRONMENT` | `sandbox` or `live` |
| `PAYPAL_CLIENT_ID` | Corresponding PayPal REST app client ID |
| `PAYPAL_CLIENT_SECRET` | Corresponding app secret; server only |
| `PAYPAL_MERCHANT_ID` | Expected payment recipient |
| `PAYPAL_WEBHOOK_ID` | ID for the notification endpoint below |
| `LOCKX_PAYPAL_LINKS_VALIDATED` | Set `1` only after a real Sandbox link purchase proves the reference binding |
| `PAYPAL_APPLE_PAY_ENABLED` | Set `1` after live Apple Pay activation and registration of the website domain; device and merchant SDK eligibility also control button visibility |
| `PAYPAL_GOOGLE_PAY_MERCHANT_ID` | Approved production Google Pay merchant ID; absent keeps Google Pay hidden |
| `LOCKX_PUBLIC_APP_ORIGIN` | `https://lockx.ai` (or its existing www alias) |

Webhook: `https://lockx-production.up.railway.app/api/v1/credits/paypal/webhook`, subscribed only to `CHECKOUT.PAYMENT-RESOURCE.PAYMENT-COMPLETED`, `PAYMENT.CAPTURE.COMPLETED`, `PAYMENT.CAPTURE.REFUNDED` and `PAYMENT.CAPTURE.REVERSED`.

Hosted Payment Links use the native payment-resource completion event, verified by PayPal's signature API. Its `payment_resource_id` must match the exact stored link, its transaction must be completed, and its merchant, gross amount and currency must match the selected pack. The canonical `transaction_id` deduplicates fulfillment. Capture-completed events fulfill only stored Apple Pay or Google Pay Orders, preventing a hosted purchase from being credited by both event families. PayPal's simulator provides the native event schema but its mock events cannot establish real payment verification.

Apple Pay requires the official live association file at `/.well-known/apple-developer-merchantid-domain-association`, served directly with `Content-Type: application/octet-stream`. The file and Vercel header configuration are committed here. Register each actual payment domain with PayPal; `lockx.ai` was registered on November 12, 2026. The frontend loads payment SDKs only when opening an authenticated wallet, starts Apple's session synchronously from the customer's click, fixes the selected pack before authorization, and reports payment success only after server capture.

Optional verified IPN fallback: `https://lockx-production.up.railway.app/api/v1/credits/paypal/ipn`. IPN must carry the generated `LX-<checkout UUID>` item number, the expected merchant, USD amount and the correct live/Sandbox indicator.

Supabase passwordless email uses the existing auth project. Enable production SMTP with a verified sender, and allow these exact return URLs: `https://lockx.ai/?wallet=return` and `https://www.lockx.ai/?wallet=return`. Existing site URLs must remain. Test a new customer and an existing customer, including another browser/device. A successful send API response alone is not proof of delivery.

## Release checks

1. Actual Sandbox purchases of the original $1/$5/$10 packs passed signed completion and deduplication checks. Real Sandbox refunds reversed all purchased credits through the authenticated refund-recovery path. The isolated test service and resources were removed.
2. New purchases offer $5/$10/$20 for 10/20/40 credits. Automated tests verify all three server-owned checkout amounts, reject new $1 checkouts, and preserve historical payment/refund reconciliation. The new $20 pack has not been purchased with live funds.
3. Resend SMTP delivery and cross-device passwordless wallet access were verified. The paid rollout is enabled at the user's request and uses the existing persistent Railway volume.
4. A real hosted Apple Pay purchase completed and granted its credits. The new direct Apple Pay button has provider-mocked flow checks; complete a customer-authorized eligible-device purchase to verify its live payment sheet and capture end to end. Never use return URL values as payment proof.
5. Google Pay remains unavailable pending PayPal provisioning and Google production merchant/domain approval. Its code stays hidden until configured.

## Validation and rollback

67 targeted wallet/refund tests and 25 frontend Apple Pay flow tests pass. Frontend checks exercise the actual wallet script with mocked provider APIs, including cancellation, fixed totals, shared SDK loading, capture-before-success, independent wallet loading, SDK timeouts, retry recovery and wallet-intent prewarming. These checks do not replace a real direct Apple Pay purchase. The earlier wallet layout was visually checked at 390px and 320px; this update adds no animations or image downloads.

Wallet interactions start authentication and Apple Pay preparation together. Eligible provider configuration and downloaded SDKs are reused on subsequent wallet opens. Safari can request merchant configuration while the Apple button script loads; browsers without the native Apple Pay API wait for Apple's SDK first. Passive homepage visits do not download payment SDKs. Prewarming creates no order or Apple Pay session, and capture still requires the authenticated purchase flow.

`/apple-pay-check.html` is a noindex, read-only diagnostic for actual SDK loading, device capability, custom-element registration and PayPal merchant eligibility. It does not create orders, request payment approval or take payment. A backend readiness flag alone does not prove merchant eligibility or a visible button on a customer's device.

For emergency rollout rollback, set `LOCKX_CREDITS_ENABLED=0`. Keep the database, app credentials and notification endpoint: already paid purchases must still be fulfilled and refunds processed. Do not delete credit tables or recreate the volume. Disabling the flag returns new checks to the existing free flow; it does not erase balances or paid inspection records.

`dev_server.py` previews pricing locally but strips payment/analysis credentials and disables paid backend calls. It cannot send real sign-in emails or take payment.
