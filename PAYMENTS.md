# LockX verification credits

One item verification costs one credit, including up to six selected photos and one 10-second recording. The packs are $5/10 credits, $10/20 credits, and $20/40 credits. All packs cost 50 cents per verification. There is no subscription or automatic renewal. New $1/2-credit checkouts are retired; existing purchases and their refund records retain their original amounts and credits.

## Implementation

`credit_wallet.py` owns balances, purchases, refunds and inspection reservations. It uses the same SQLite database and persistent Railway volume as In-hand evidence. `credit-wallet.js` supplies the public pricing and passwordless email wallet. Supabase authenticates the owner; browser balances and return query parameters cannot grant credits.

The server prices checkouts and verifies actual PayPal payment, amount, currency, recipient and checkout reference. Payment IDs and ledger references deduplicate callbacks. Each completed comparison consumes one credit even if the outcome is mismatch or inconclusive. Failed processing restores the credit; a technical retry reserves it again. The existing server-approved one-time quality retry is included. Viewing results and exporting approved images are free.

PayPal Payment Links are reusable. Each link belongs to its creating LockX account; a distinct completed payment on that link adds the same pack to that owner. Do not share a checkout link as a general store link. Google Pay uses PayPal Orders and server capture because the hosted Payment Links wallet list does not include Google Pay.

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
| `PAYPAL_GOOGLE_PAY_MERCHANT_ID` | Approved production Google Pay merchant ID; absent keeps Google Pay hidden |
| `LOCKX_PUBLIC_APP_ORIGIN` | `https://lockx.ai` (or its existing www alias) |

Webhook: `https://lockx-production.up.railway.app/api/v1/credits/paypal/webhook`, subscribed only to `CHECKOUT.PAYMENT-RESOURCE.PAYMENT-COMPLETED`, `PAYMENT.CAPTURE.COMPLETED`, `PAYMENT.CAPTURE.REFUNDED` and `PAYMENT.CAPTURE.REVERSED`.

Hosted Payment Links use the native payment-resource completion event, verified by PayPal's signature API. Its `payment_resource_id` must match the exact stored link, its transaction must be completed, and its merchant, gross amount and currency must match the selected pack. The canonical `transaction_id` deduplicates fulfillment. Capture-completed events fulfill only Google Pay Orders, preventing a hosted purchase from being credited by both event families. PayPal's simulator provides the native event schema but its mock events cannot establish real payment verification.

Optional verified IPN fallback: `https://lockx-production.up.railway.app/api/v1/credits/paypal/ipn`. IPN must carry the generated `LX-<checkout UUID>` item number, the expected merchant, USD amount and the correct live/Sandbox indicator.

Supabase passwordless email uses the existing auth project. Enable production SMTP with a verified sender, and allow these exact return URLs: `https://lockx.ai/?wallet=return` and `https://www.lockx.ai/?wallet=return`. Existing site URLs must remain. Test a new customer and an existing customer, including another browser/device. A successful send API response alone is not proof of delivery.

## Launch checks still required

1. Use the existing Sandbox app to buy each pack with Sandbox buyer funds. Verify the native payment-resource completion event identifies the exact created link and transaction, passes real signature verification, and is delivered to this app's callback. This provider behavior is intentionally gated and has not been demonstrated by unit tests or the webhook simulator. Also validate native transaction IDs against refund/reversal payment IDs before launch.
2. Prove one confirmed payment adds exactly 10, 20 or 40 credits, replays do not add more, and a refund removes the corresponding credits. Verify historical $1/2-credit payments and refunds still reconcile. Never use return URL values as proof.
3. Configure SMTP and verify email delivery, passwordless sign-in and balance recovery on another device.
4. Finish PayPal Google Pay account provisioning and Google production merchant/domain approval. Test eligible Google Pay and Apple Pay devices. The newly created live PayPal app currently reports that its Expanded Checkout account is not provisioned for either wallet; hosted Payment Links Apple Pay eligibility is a separate setting.
5. Confirm the Railway persistent volume remains mounted and back up `in-hand.sqlite3` before paid launch. Deploy server before activating frontend paid gating. Keep both rollout flags off until the above checks pass.

## Validation and rollback

168 billing and existing In-hand tests pass. JavaScript syntax checks pass. The wallet was visually checked at 390px and 320px, with no new animations or image downloads. Provider calls in automated tests are mocked; the real Sandbox checkout and production email checks above are still required.

For emergency rollout rollback, set `LOCKX_CREDITS_ENABLED=0`. Keep the database, app credentials and notification endpoint: already paid purchases must still be fulfilled and refunds processed. Do not delete credit tables or recreate the volume. Disabling the flag returns new checks to the existing free flow; it does not erase balances or paid inspection records.

`dev_server.py` previews pricing locally but strips payment/analysis credentials and disables paid backend calls. It cannot send real sign-in emails or take payment.
